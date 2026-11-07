from tests import signal_safety as _signal_safety  # noqa: F401

import ast
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from tuxindrive.engine import JobResult, SyncEngine
from tuxindrive.models import AppConfig, AppSettings, SyncJob, SyncMode
from tuxindrive.network_recovery import (
    RETRY_DELAYS, log_network_issue, plan_network_retry, retry_wait_seconds,
    transient_network_issue,
)
from tuxindrive.recovery_advisor import advice_for_error
from tuxindrive.scheduling import persisted_run_time


DNS_ERROR = "couldn't fetch token: lookup oauth2.googleapis.com on 127.0.0.53:53: server misbehaving"


class NetworkRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)
        self.job = SyncJob("cloud", "/data", initialized=True)

    def result(self, message=DNS_ERROR, **kwargs):
        return JobResult(self.job.id, False, message, Path("/tmp/unused.log"), **kwargs)

    def test_dns_during_token_refresh_is_not_authorization_failure(self):
        issue = transient_network_issue(DNS_ERROR)
        self.assertEqual(issue.code, "dns")
        self.assertIn("oauth2.googleapis.com", issue.summary)
        advice = advice_for_error("safety preview failed", DNS_ERROR)
        self.assertEqual(advice.code, "dns")
        self.assertNotIn("Reconnect", advice.title)

    def test_explicit_cross_platform_transport_failures(self):
        for message in (
            "lookup graph.microsoft.com on 127.0.0.53:53: no such host",
            "[Errno -3] Temporary failure in name resolution",
            "lookup graph.microsoft.com: no such host",
            "[Errno 11001] getaddrinfo failed",
            "curl: Could not resolve host: eapi.pcloud.com",
            "dial tcp 1.2.3.4:443: i/o timeout",
            "connection reset by peer", "TLS handshake timeout", "HTTP error 503",
        ):
            with self.subTest(message=message):
                self.assertIsNotNone(transient_network_issue(message))

    def test_hard_failures_override_a_transport_error_in_the_same_run(self):
        for message in (
            "invalid_grant", "invalid_client", "HTTP error 401", "403 Forbidden",
            "permission denied", "no space left on device", "hashes differ",
            "Integrity verification failed", "Protection paused synchronization",
            "cannot find prior Path1 or Path2 listings", "must run --resync",
            "certificate signed by unknown authority",
        ):
            with self.subTest(message=message):
                self.assertIsNone(transient_network_issue(DNS_ERROR + "\n" + message))
                result = self.result(DNS_ERROR + "\n" + message, transient_network_failure=True)
                self.assertFalse(plan_network_retry(self.job, result, self.now))

    def test_retryable_without_resync_is_not_a_baseline_failure(self):
        text = DNS_ERROR + "\nBisync aborted. Error is retryable without --resync due to --resilient mode."
        self.assertIsNotNone(transient_network_issue(text))

    def test_ordinary_numbers_and_configured_delete_limit_do_not_veto_dns(self):
        self.assertIsNotNone(transient_network_issue(DNS_ERROR + "\nTransferred: 403 B; --max-delete 100"))

    def test_unknown_scan_or_auth_errors_are_not_automatically_retried(self):
        for message in ("safety preview failed", "couldn't fetch token", "unknown failure", "disk scan timeout"):
            self.assertIsNone(transient_network_issue(message))

    def test_progressive_backoff_stays_enabled_and_is_capped(self):
        for delay in (*RETRY_DELAYS, 900, 900):
            self.job.record_failure(DNS_ERROR)
            self.assertTrue(plan_network_retry(self.job, self.result(), self.now))
            self.assertEqual(retry_wait_seconds(self.job, self.now), delay)
            self.assertTrue(self.job.enabled)
            self.assertTrue(self.job.initialized)
        self.assertGreaterEqual(self.job.consecutive_failures, 3)
        self.assertEqual(self.job.network_failures, 5)

    def test_pause_and_manual_only_are_never_automatically_resumed(self):
        self.job.enabled = False
        self.assertTrue(plan_network_retry(self.job, self.result(), self.now))
        self.assertFalse(self.job.enabled)
        self.assertEqual(self.job.network_retry_at, "")
        self.job.enabled = True
        self.job.ai_connector = "codex"
        self.job.manual_only = True
        self.assertTrue(plan_network_retry(self.job, self.result(), self.now))
        self.assertEqual(self.job.network_retry_at, "")

    def test_safety_flags_and_streaming_lifecycle_do_not_use_sync_backoff(self):
        for flag in ("cancelled", "requires_resync", "mass_change_blocked",
                     "integrity_blocked", "verification_blocked", "lease_blocked"):
            plan_network_retry(self.job, self.result(), self.now)
            self.assertFalse(plan_network_retry(self.job, self.result(**{flag: True}), self.now))
            self.assertEqual(self.job.network_retry_at, "")
        self.job.mode = SyncMode.VIRTUAL_DRIVE
        self.assertFalse(plan_network_retry(self.job, self.result(), self.now))

    def test_success_and_manual_retry_clear_wait_and_counters(self):
        plan_network_retry(self.job, self.result(), self.now)
        self.job.clear_failures()
        self.assertEqual((self.job.network_failures, self.job.network_retry_at), (0, ""))
        plan_network_retry(self.job, self.result(), self.now)
        result = JobResult(self.job.id, True, "done", Path("/tmp/unused.log"))
        self.assertFalse(plan_network_retry(self.job, result, self.now))
        self.assertEqual((self.job.network_failures, self.job.network_retry_at), (0, ""))

    def test_retry_survives_restart_without_changing_legacy_disabled_jobs(self):
        plan_network_retry(self.job, self.result(), self.now)
        restored = SyncJob.from_dict(asdict(self.job))
        self.assertEqual(retry_wait_seconds(restored, self.now + timedelta(seconds=10)), 50)
        legacy = SyncJob.from_dict({"account_remote": "cloud", "local_path": "/data",
                                    "enabled": False, "consecutive_failures": 3})
        self.assertFalse(legacy.enabled)
        self.assertEqual(legacy.network_retry_at, "")

    def test_invalid_and_future_clocks_cannot_block_recovery_forever(self):
        for value in ("bad", "2026-10-12T18:00:00", (self.now + timedelta(days=7)).isoformat(), ""):
            self.job.network_retry_at = value
            self.assertEqual(retry_wait_seconds(self.job, self.now), 0)

    def test_log_reader_is_bounded_and_ignores_previous_run_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "sync.log"
            previous = DNS_ERROR + "\n"
            log.write_text(previous + "ERROR: invalid_grant\n", encoding="utf-8")
            self.assertIsNone(log_network_issue(log, len(previous.encode())))
            log.write_text("ERROR: invalid_grant\n" + "INFO: idle\n" * 10000 + DNS_ERROR, encoding="utf-8")
            self.assertEqual(log_network_issue(log).code, "dns")
            self.assertIsNone(log_network_issue(log, log.stat().st_size))

    def test_incremental_callbacks_cannot_bypass_network_wait(self):
        engine = SyncEngine("rclone")
        self.job.network_retry_at = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
        with patch.object(engine, "_apply_incremental_unlocked") as apply:
            self.assertFalse(engine._apply_incremental(self.job, [], Mock()))
        apply.assert_not_called()


def application_methods():
    """Execute actual controller methods without GTK startup or real providers."""
    source = Path(__file__).parents[1] / "src/tuxindrive/app.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    controller = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                      and node.name == "TuxInDriveApplication")
    names = {"run_job", "_scheduler_tick", "_apply_job_result"}
    selected = [node for node in controller.body if isinstance(node, ast.FunctionDef) and node.name in names]
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, *selected], type_ignores=[]))
    scope = {"datetime": datetime, "timezone": timezone, "time": time,
             "plan_network_retry": plan_network_retry, "retry_wait_seconds": retry_wait_seconds,
             "SyncMode": SyncMode, "persisted_run_time": persisted_run_time,
             "LOGGER": logging.getLogger(__name__), "Provider": SimpleNamespace(PEER="peer"),
             "TransferPolicy": Mock(return_value=SimpleNamespace(evaluate=lambda: SimpleNamespace(allowed=True))),
             "GLib": Mock(), "Gtk": Mock()}
    exec(compile(module, str(source), "exec"), scope)
    return scope


class ControllerNetworkRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.methods = application_methods()

    def setUp(self):
        self.job = SyncJob("cloud", "/data", initialized=True, interval_minutes=60)
        engine = Mock()
        engine.running_jobs = set()
        engine.callback_healthy.return_value = True
        engine.finalize_traffic.return_value = (0, 0)
        self.controller = SimpleNamespace(
            config=AppConfig(jobs=[self.job], settings=AppSettings()), engine=engine,
            _last_full_completed={}, _last_started={}, _last_cache_maintenance=0,
            _cache_maintenance_running=False, _runtime_ready_monotonic=time.monotonic(),
            _nautilus_active_jobs=set(), _offline_verified_paths={}, _pending_offline_requests=[],
            _mount_failures={}, window=None, audit=Mock(), save=Mock(),
            _refresh_tray_from_jobs=Mock(), start_callbacks=Mock(), refresh_search_index=Mock(),
            _publish_nautilus_state=Mock(), _job_finished=Mock(), _refresh_job_progress=Mock(),
            run_job=Mock(), notify=Mock(), mail_indexer=Mock(),
        )

    def test_third_dns_failure_does_not_disable_but_third_auth_failure_does(self):
        for _ in range(3):
            result = JobResult(self.job.id, False, DNS_ERROR, Path("/tmp/unused.log"))
            self.methods["_apply_job_result"](self.controller, result)
        self.assertTrue(self.job.enabled)
        self.assertEqual(self.job.network_failures, 3)
        self.controller.notify.assert_called_once()
        for _ in range(3):
            result = JobResult(self.job.id, False, "invalid_grant", Path("/tmp/unused.log"))
            self.methods["_apply_job_result"](self.controller, result)
        self.assertFalse(self.job.enabled)
        self.assertEqual(self.job.network_retry_at, "")

    def test_scheduler_waits_then_retries_even_with_healthy_callback_and_long_interval(self):
        now = datetime.now(timezone.utc)
        self.job.last_run = now.isoformat()
        self.controller._last_full_completed[self.job.id] = now
        self.job.network_retry_at = (now + timedelta(minutes=2)).isoformat()
        self.methods["_scheduler_tick"](self.controller)
        self.controller.run_job.assert_not_called()
        self.job.network_retry_at = (now - timedelta(seconds=1)).isoformat()
        self.methods["_scheduler_tick"](self.controller)
        self.controller.run_job.assert_called_once()

    def test_automatic_callbacks_respect_wait_pause_and_manual_only(self):
        self.job.network_retry_at = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
        self.methods["run_job"](self.controller, self.job, quiet=True)
        self.job.network_retry_at = ""
        self.job.enabled = False
        self.methods["run_job"](self.controller, self.job, quiet=True)
        self.job.enabled = True
        self.job.ai_connector, self.job.manual_only = "codex", True
        self.methods["run_job"](self.controller, self.job, quiet=True)
        self.controller.engine.configure_jobs.assert_not_called()

    def test_manual_sync_bypasses_the_wait_and_clears_network_failures(self):
        self.job.network_retry_at = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
        self.job.network_failures = 4
        self.methods["run_job"](self.controller, self.job)
        self.controller.engine.run_async.assert_called_once()
        self.assertEqual((self.job.network_retry_at, self.job.network_failures), ("", 0))

