"""App-owned, serial background mail indexing; no UI or browser dependency."""
from __future__ import annotations

from dataclasses import dataclass, replace
import logging
import threading
import time

from .mail_auth import MailCancelled, MailError, check_cancel
from .mail_connectors import MailClient
from .mail_index import MailRefreshState

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MailActivity:
    status: str
    detail: str
    messages: int = 0
    maximum: int = 0
    attachments: int = 0


def scan_summary(result) -> str:
    if result.skipped_messages:
        note = (f" Partial scan: {result.skipped_messages} unreadable message(s) skipped; "
                "older results retained. Index again to retry them.")
    else:
        note = " Complete scan." if result.complete else " Scan/index limit reached; older results retained."
    return (f"Indexed {result.indexed} attachments from {result.messages} messages; removed {result.removed} stale entries. "
            f"Text: {result.reused} reused, {result.downloaded} download attempts, {result.content_skipped} skipped." + note)


class MailIndexActivity:
    """One worker, bounded deduplicated requests, persisted schedule/backoff.

    Closing a dialog never stops this service. Only explicit cancellation or
    application shutdown does. All provider/credential and policy work is done
    in the worker, not the GTK thread. Existing indexes remain transactional.
    """

    def __init__(self, accounts, index, authorization, *, bandwidth=None,
                 provider_allowed=lambda _provider: True, content_allowed=lambda: True,
                 admission=lambda: "", changed=lambda: None, clock=time.time,
                 client_factory=MailClient, launch=None):
        self.accounts, self.index, self.authorization = accounts, index, authorization
        self.bandwidth = bandwidth
        self.provider_allowed, self.content_allowed = provider_allowed, content_allowed
        self.admission, self.changed, self.clock = admission, changed, clock
        self.client_factory = client_factory
        self.launch = launch or (lambda operation: threading.Thread(target=operation, daemon=True,
                                                                   name="Mail indexing").start())
        self.lock = threading.RLock()
        self.pending = {}
        self.activities = {}
        self.active_id = None
        self.stop_event = None
        self.worker_running = self.closed = False
        self._last_progress_notice = 0.0

    @property
    def running_ids(self):
        with self.lock:
            return frozenset(self.pending) | ({self.active_id} if self.active_id else set())

    def activity(self, identifier):
        with self.lock:
            current = self.activities.get(identifier)
        if current is not None:
            return current
        previous = self.index.activity(identifier)
        if previous is None:
            return None
        if previous.status == "running":
            return MailActivity("interrupted", "Indexing interrupted when the app closed; previous index retained.")
        return MailActivity(previous.status, previous.detail)

    def due_at(self, account, now=None):
        if not account.index_interval_minutes:
            return None
        now = self.clock() if now is None else now
        previous, scan = self.index.activity(account.id), self.index.last_scan(account.id)
        stamps = [value for value in (previous.started_at if previous else 0,
                                      scan.completed_at if scan else 0) if 0 < value <= now + 60]
        due = max(stamps) + account.index_interval_minutes * 60 if stamps else 0
        if previous and previous.failures and 0 < previous.retry_at <= now + 86400:
            due = max(due, previous.retry_at)
        return due

    def request(self, identifier, *, automatic=False):
        # Reject unknown accounts before queuing, without reading tokens.
        if not any(account.id == identifier for account in self.accounts.load()):
            raise MailError("This mailbox was disconnected; add it again from Add account.")
        with self.lock:
            if self.closed:
                raise MailError("Mail indexing is shutting down.")
            if identifier == self.active_id or identifier in self.pending:
                return False
            if len(self.pending) >= 100:
                raise MailError("The mail indexing queue is full; wait for an activity to finish.")
            self.pending[identifier] = automatic
            self.activities[identifier] = MailActivity("queued", "Queued for background mail indexing…")
            start = not self.worker_running
            self.worker_running = True
        self._changed()
        LOGGER.info("Mail indexing queued account_id=%s automatic=%s", identifier, automatic)
        if start:
            try:
                self.launch(self._worker)
            except Exception:
                with self.lock:
                    self.worker_running = False
                    for queued in self.pending:
                        self.activities[queued] = MailActivity("failed", "Could not start background mail indexing; retry manually.")
                    self.pending.clear()
                raise MailError("Could not start background mail indexing; retry manually.") from None
        return True

    def tick(self):
        with self.lock:
            if self.closed or self.worker_running:
                return
        try:
            now = self.clock()
            candidates = [(self.due_at(a, now), a.id) for a in self.accounts.load()
                          if a.index_interval_minutes and self.provider_allowed(a.provider)]
            due = [(when, identifier) for when, identifier in candidates if when <= now]
            if due:
                self.request(min(due)[1], automatic=True)
        except Exception:
            # Invalid settings/storage must never enable a scan or show a modal
            # dialog on every scheduler tick. Explicit manual actions show it.
            LOGGER.warning("Automatic mail indexing could not read its settings safely")

    def cancel(self, identifier):
        with self.lock:
            if identifier == self.active_id and self.stop_event is not None:
                self.stop_event.set()
                self.activities[identifier] = MailActivity("cancelling", "Stopping mail indexing… an in-flight request may finish first.")
            elif identifier in self.pending:
                self.pending.pop(identifier)
                self.activities[identifier] = MailActivity("cancelled", "Queued mail indexing cancelled.")
        self._changed()

    def shutdown(self):
        with self.lock:
            self.closed = True
            self.pending.clear()
            if self.stop_event is not None:
                self.stop_event.set()

    def _changed(self):
        if not self.closed:
            try:
                self.changed()
            except Exception:
                LOGGER.warning("Mail activity display notification failed safely")

    def _progress(self, messages, maximum, attachments):
        with self.lock:
            if self.active_id is None:
                return
            if self.stop_event is not None and self.stop_event.is_set():
                return
            self.activities[self.active_id] = MailActivity(
                "running", f"Scanned {messages} messages (limit {maximum}); found {attachments} attachments. "
                "Content extraction follows metadata scanning.", messages, maximum, attachments)
            stamp = time.monotonic()
            notify = stamp - self._last_progress_notice >= 1
            if notify:
                self._last_progress_notice = stamp
        if notify:
            self._changed()

    def _worker(self):
        while True:
            with self.lock:
                if self.closed or not self.pending:
                    self.worker_running = False
                    self.active_id = self.stop_event = None
                    return
                # A manual request has priority over an automatic one.
                identifier = min(self.pending, key=lambda key: self.pending[key])
                automatic = self.pending.pop(identifier)
                self.active_id, self.stop_event = identifier, threading.Event()
                stop = self.stop_event
                self.activities[identifier] = MailActivity("running", "Reading attachment metadata in the background…")
            self._changed()
            try:
                self._execute(identifier, automatic, stop)
            except Exception:
                # A storage failure must not leave a phantom busy worker or
                # strand the rest of the bounded queue. Never log mail content.
                with self.lock:
                    self.activities[identifier] = MailActivity("failed", "Mail indexing could not save its activity state; inspect the last completed scan.")
                LOGGER.warning("Mail indexing activity storage failed safely")
            with self.lock:
                self.active_id = self.stop_event = None
            self._changed()

    def _execute(self, identifier, automatic, stop):
        # Serialize account removal/reconnection/options with the entire scan.
        # Reload after admission so a queued disconnected account cannot return.
        with self.index.maintenance():
            account = next((a for a in self.accounts.load() if a.id == identifier), None)
            if account is None:
                with self.lock:
                    self.activities.pop(identifier, None)
                return
            previous = self.index.activity(identifier)
            started = self.clock()
            state = MailRefreshState(started, failures=previous.failures if previous else 0)
            self.index.record_activity(identifier, state)  # before touching the native credential store
            try:
                check_cancel(stop)
                if automatic and not account.index_interval_minutes:
                    raise MailCancelled("Automatic indexing is disabled for this mailbox.")
                if not self.provider_allowed(account.provider):
                    raise MailError("This mail provider is disabled by the managed desktop policy; the offline index is retained.")
                reason = self.admission()
                if reason:
                    state = replace(state, status="deferred", detail=reason)
                else:
                    client = self.client_factory(account, self.authorization, bandwidth=self.bandwidth, stop=stop)
                    result = self.index.refresh(account, client, stop_event=stop,
                                                include_content=account.include_content and self.content_allowed(),
                                                progress=self._progress)
                    state = replace(state, status="completed", detail=scan_summary(result), failures=0)
            except MailCancelled as error:
                state = replace(state, status="cancelled", detail=str(error))
            except Exception as error:
                failures = min(12, state.failures + 1)
                detail = str(error) if isinstance(error, MailError) else "Mail indexing failed; the previous index is retained."
                state = replace(state, status="failed", detail=detail, failures=failures,
                                retry_at=self.clock() + min(3600, 300 * 2 ** (failures - 1)))
            state = replace(state, finished_at=self.clock())
            self.index.record_activity(identifier, state)
            with self.lock:
                self.activities[identifier] = MailActivity(state.status, state.detail)
            LOGGER.info("Mail indexing activity %s account_id=%s", state.status, identifier)
