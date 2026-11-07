from tests import signal_safety as _signal_safety  # noqa: F401

from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from tuxindrive.mail_activity import MailIndexActivity
from tuxindrive.mail_auth import MailAccount, MailAccountStore, MailCancelled, MailError, check_cancel
from tuxindrive.mail_index import MailRefreshState, MailSearchIndex
from tests.test_mail_attachments import GMAIL, MICROSOFT, SyntheticClient


class MailActivityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.accounts = MailAccountStore(self.root / "accounts.json")
        self.accounts.save([GMAIL, MICROSOFT])
        self.index = MailSearchIndex(self.root / "index.sqlite3")
        self.now = [time.time()]
        self.operations = []
        self.factory = Mock(side_effect=lambda account, *_args, **_kwargs: SyntheticClient(account))
        self.changed = Mock()
        self.service = self.make_service()

    def make_service(self, **options):
        return MailIndexActivity(self.accounts, self.index, Mock(), clock=lambda: self.now[0],
                                 client_factory=self.factory, launch=self.operations.append,
                                 changed=self.changed, **options)

    def run_worker(self):
        self.operations.pop(0)()

    def scheduled(self, account=GMAIL, minutes=5):
        updated = replace(account, index_interval_minutes=minutes)
        self.accounts.upsert(updated)
        return updated

    def test_old_settings_stay_manual_and_new_interval_round_trips_privately(self):
        old = asdict(GMAIL)
        old.pop("index_interval_minutes")
        self.accounts.path.write_text(json.dumps([old]))
        self.assertEqual(self.accounts.load()[0].index_interval_minutes, 0)
        self.scheduled(minutes=90)
        self.assertEqual(self.accounts.load()[0].index_interval_minutes, 90)
        self.assertEqual(self.accounts.path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("access_token", self.accounts.path.read_text())

    def test_invalid_schedule_is_rejected_without_changing_original_settings(self):
        original = self.accounts.path.read_bytes()
        for value in (True, False, 1, 4, -1, 43201, "60", None, 5.0):
            with self.subTest(value=value), self.assertRaises(MailError):
                self.accounts.upsert(replace(GMAIL, index_interval_minutes=value))
            self.assertEqual(self.accounts.path.read_bytes(), original)

    def test_manual_accounts_never_schedule_network_or_credential_work(self):
        for _ in range(10):
            self.service.tick()
            self.now[0] += 86400
        self.assertEqual(self.operations, [])
        self.factory.assert_not_called()
        self.assertEqual(self.service.running_ids, frozenset())

    def test_manual_request_runs_without_a_window_and_persists_its_result(self):
        self.assertTrue(self.service.request(GMAIL.id))
        self.assertEqual(self.service.activity(GMAIL.id).status, "queued")
        self.assertEqual(self.index.count(), 0)
        self.run_worker()
        self.assertEqual(self.index.count(GMAIL.id), 1)
        self.assertEqual(self.service.activity(GMAIL.id).status, "completed")
        self.assertEqual(self.index.activity(GMAIL.id).status, "completed")
        self.assertEqual(self.service.running_ids, frozenset())

    def test_due_time_survives_restart_and_does_not_catch_up_in_a_burst(self):
        account = self.scheduled()
        self.service.tick()
        self.run_worker()
        due = self.service.due_at(account)
        self.assertGreaterEqual(due, self.now[0] + 300)
        restarted = self.make_service()
        restarted.tick()
        self.assertEqual(self.operations, [])
        self.now[0] = due + 86400
        for _ in range(10):
            restarted.tick()
        self.assertEqual(len(self.operations), 1)
        self.run_worker()
        restarted.tick()
        self.assertEqual(self.operations, [])

    def test_changing_or_disabling_interval_is_respected_immediately(self):
        account = self.scheduled(minutes=60)
        self.service.request(account.id)
        self.run_worker()
        self.now[0] = self.service.due_at(account) - 1
        self.service.tick()
        self.assertEqual(self.operations, [])
        self.scheduled(minutes=0)
        self.now[0] += 86400
        self.service.tick()
        self.assertEqual(self.operations, [])
        self.scheduled(minutes=5)
        self.service.tick()
        self.assertEqual(len(self.operations), 1)

    def test_provider_policy_prevents_automatic_work_and_manual_credential_reads(self):
        self.scheduled()
        blocked = self.make_service(provider_allowed=lambda _provider: False)
        blocked.tick()
        self.assertEqual(self.operations, [])
        blocked.request(GMAIL.id)
        self.run_worker()
        self.factory.assert_not_called()
        self.assertEqual(blocked.activity(GMAIL.id).status, "failed")

    def test_transfer_policy_defers_in_the_worker_without_touching_credentials(self):
        self.scheduled()
        decision = Mock(return_value="Paused on a metered network")
        service = self.make_service(admission=decision)
        service.tick()
        decision.assert_not_called()
        self.run_worker()
        decision.assert_called_once_with()
        self.factory.assert_not_called()
        self.assertEqual(service.activity(GMAIL.id).status, "deferred")
        service.tick()
        self.assertEqual(self.operations, [])

    def test_managed_policy_keeps_content_downloads_off(self):
        self.accounts.upsert(replace(GMAIL, include_content=True))
        service = self.make_service(content_allowed=lambda: False)
        service.request(GMAIL.id)
        self.run_worker()
        self.assertEqual(self.index.search("needle"), [])
        self.assertEqual(self.index.count(), 1)

    def test_requests_deduplicate_and_one_worker_serializes_accounts(self):
        self.service.request(GMAIL.id)
        self.assertFalse(self.service.request(GMAIL.id))
        self.service.request(MICROSOFT.id)
        self.assertEqual(len(self.operations), 1)
        self.run_worker()
        self.assertEqual([c.args[0].id for c in self.factory.call_args_list], [GMAIL.id, MICROSOFT.id])
        self.assertEqual(self.index.count(), 2)

    def test_manual_request_has_priority_and_queued_stop_prevents_a_scan(self):
        self.scheduled()
        self.service.request(GMAIL.id, automatic=True)
        self.service.request(MICROSOFT.id)
        self.run_worker()
        self.assertEqual([c.args[0].id for c in self.factory.call_args_list], [MICROSOFT.id, GMAIL.id])
        self.factory.reset_mock()
        self.service.request(GMAIL.id)
        self.service.cancel(GMAIL.id)
        self.run_worker()
        self.factory.assert_not_called()
        self.assertEqual(self.service.activity(GMAIL.id).status, "cancelled")

    def test_background_request_returns_before_io_and_explicit_stop_preserves_index(self):
        self.index.refresh(GMAIL, SyntheticClient())
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        stop_seen = []
        def factory(account, _authorization, **options):
            stop_seen.append(options["stop"])
            client = SyntheticClient(account, items=[])
            def scan(progress=None):
                started.set()
                release.wait(3)
                check_cancel(options["stop"])
                return client.original_scan(progress)
            client.original_scan, client.scan = client.scan, scan
            return client
        def launch(operation):
            def run():
                try:
                    operation()
                finally:
                    finished.set()
            thread = threading.Thread(target=run, daemon=True)
            thread.start()
        self.service.client_factory, self.service.launch = factory, launch
        try:
            self.assertTrue(self.service.request(GMAIL.id))
            self.assertTrue(started.wait(2))
            self.assertIn(GMAIL.id, self.service.running_ids)
            self.assertEqual(self.index.count(), 1)
            self.service.cancel(GMAIL.id)
            self.assertTrue(stop_seen[0].is_set())
        finally:
            release.set()
            self.assertTrue(finished.wait(3))
        self.assertEqual(self.index.count(), 1)
        self.assertEqual(self.service.activity(GMAIL.id).status, "cancelled")
        self.assertEqual(self.service.running_ids, frozenset())

    def test_failed_scans_preserve_index_and_backoff_survives_restart(self):
        account = self.scheduled()
        self.index.refresh(account, SyntheticClient(account))
        self.factory.side_effect = MailError("The mail service is temporarily unavailable.")
        for number in range(1, 5):
            self.service.request(account.id)
            self.run_worker()
            state = self.index.activity(account.id)
            self.assertEqual(state.failures, number)
            self.assertGreaterEqual(state.retry_at - self.now[0], min(3600, 300 * 2 ** (number - 1)))
            self.assertEqual(self.index.count(), 1)
            restarted = self.make_service()
            restarted.tick()
            self.assertEqual(self.operations, [])
            self.now[0] = self.service.due_at(account) + 1

    def test_recovered_scan_clears_failure_backoff(self):
        account = self.scheduled()
        self.index.record_activity(account.id, MailRefreshState(self.now[0], status="failed", failures=4,
                                                               retry_at=self.now[0] + 3600))
        self.service.request(account.id)
        self.run_worker()
        self.assertEqual(self.index.activity(account.id).failures, 0)
        self.assertEqual(self.index.activity(account.id).retry_at, 0)

    def test_unexpected_errors_are_redacted_and_never_clear_previous_rows(self):
        self.index.refresh(GMAIL, SyntheticClient())
        self.factory.side_effect = RuntimeError("private-token-and-subject")
        self.service.request(GMAIL.id)
        self.run_worker()
        self.assertNotIn("private-token", self.service.activity(GMAIL.id).detail)
        self.assertEqual(self.index.count(), 1)

    def test_interrupted_activity_is_visible_but_waits_for_its_next_cycle(self):
        account = self.scheduled()
        self.index.record_activity(account.id, MailRefreshState(self.now[0]))
        self.assertEqual(self.service.activity(account.id).status, "interrupted")
        self.service.tick()
        self.assertEqual(self.operations, [])

    def test_removing_a_queued_account_cannot_resurrect_its_index(self):
        self.service.request(GMAIL.id)
        self.accounts.save([MICROSOFT])
        self.index.remove_account(GMAIL.id)
        self.run_worker()
        self.factory.assert_not_called()
        self.assertEqual(self.index.count(), 0)
        self.assertIsNone(self.index.activity(GMAIL.id))

    def test_queue_reloads_current_account_options_before_starting(self):
        self.service.request(GMAIL.id)
        self.accounts.upsert(replace(GMAIL, days=14))
        self.run_worker()
        self.assertEqual(self.factory.call_args.args[0].days, 14)

    def test_shutdown_cancels_queue_and_disables_late_ui_callbacks(self):
        self.service.request(GMAIL.id)
        self.service.shutdown()
        self.changed.reset_mock()
        self.run_worker()
        self.factory.assert_not_called()
        self.changed.assert_not_called()
        self.service.tick()
        with self.assertRaises(MailError):
            self.service.request(GMAIL.id)

    def test_notification_or_storage_failure_does_not_strand_busy_state(self):
        self.changed.side_effect = RuntimeError("Synthetic destroyed view")
        self.service.request(GMAIL.id)
        with patch.object(self.index, "record_activity", side_effect=OSError("Synthetic storage failure")):
            self.run_worker()
        self.assertEqual(self.service.running_ids, frozenset())
        self.assertFalse(self.service.worker_running)
        self.factory.assert_not_called()
        self.assertEqual(self.service.activity(GMAIL.id).status, "failed")

    def test_future_timestamp_does_not_permanently_block_scheduling(self):
        account = self.scheduled()
        self.index.record_activity(account.id, MailRefreshState(self.now[0] + 86400 * 365))
        self.service.tick()
        self.assertEqual(len(self.operations), 1)

    def test_account_removal_deletes_its_persisted_activity(self):
        self.service.request(GMAIL.id)
        self.run_worker()
        self.index.remove_account(GMAIL.id)
        self.assertIsNone(self.index.activity(GMAIL.id))


if __name__ == "__main__":
    unittest.main()
