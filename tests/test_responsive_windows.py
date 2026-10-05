from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]


class ResponsiveWindowTests(unittest.TestCase):
    def test_client_dialogs_use_monitor_safe_maximum_without_forced_maximization(self) -> None:
        source = (REPOSITORY / "src/tuxindrive/app.py").read_text(encoding="utf-8")

        self.assertIn("self.set_resizable(True)", source)
        self.assertNotIn("self.maximize()", source)
        self.assertIn("max(1, int(workarea.width * 0.92))", source)
        self.assertIn("max(1, int(workarea.height * 0.92))", source)
        self.assertNotIn("min(target_width", source)

    def test_dialog_scroll_canvas_does_not_force_window_sized_minimum(self) -> None:
        source = (REPOSITORY / "src/tuxindrive/app.py").read_text(encoding="utf-8")

        responsive_dialog = source[source.index("class ResponsiveDialog"):source.index("class OAuthWizard")]
        self.assertNotIn("wrapper.set_size_request", responsive_dialog)
        self.assertIn("scroll.set_min_content_width(1)", responsive_dialog)
        self.assertIn("scroll.set_min_content_height(1)", responsive_dialog)
        self.assertIn("scroll.set_propagate_natural_width(False)", responsive_dialog)
        self.assertIn("scroll.set_propagate_natural_height(False)", responsive_dialog)

    def test_wide_job_controls_do_not_set_the_window_minimum_width(self) -> None:
        source = (REPOSITORY / "src/tuxindrive/app.py").read_text(encoding="utf-8")

        self.assertIn(
            "actions_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)",
            source,
        )
        self.assertGreaterEqual(source.count("set_propagate_natural_width(False)"), 3)
        self.assertIn(
            "scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)",
            source,
        )

    def test_server_window_starts_resizable_without_forced_maximization(self) -> None:
        source = (REPOSITORY / "src/tuxindrive/server_gui.py").read_text(encoding="utf-8")

        self.assertIn("self.set_resizable(True)", source)
        self.assertNotIn("self.maximize()", source)

    def test_synchronized_folder_search_uses_a_responsive_local_dialog(self) -> None:
        source = (REPOSITORY / "src/tuxindrive/app.py").read_text(encoding="utf-8")

        dialog = source[source.index("class FolderSearchDialog"):source.index("class MainWindow")]
        self.assertIn("class FolderSearchDialog(ResponsiveDialog)", dialog)
        self.assertIn("search(query, stop_event=cancel)", dialog)
        self.assertIn('Gtk.CheckButton(label="Enable preview")', dialog)
        self.assertIn("_run_thread(preview_path, ready, target)", dialog)
        self.assertIn("if self.preview_enabled.get_active()", dialog)
        self.assertIn("self._resolved_result(result)", dialog)
        self.assertIn("result.local_path.resolve(strict=True)", dialog)
        self.assertIn('Gtk.Button(label="Open local location")', dialog)
        self.assertIn('Gtk.Button(label="Open online location")', dialog)
        self.assertIn("location = target if result.is_directory else target.parent", dialog)
        self.assertIn("self.controller._open_online_path(str(target))", dialog)
        self.assertIn('"edit-find-symbolic"', source)

    def test_job_error_details_do_not_open_the_conflict_scanner(self) -> None:
        source = (REPOSITORY / "src/tuxindrive/app.py").read_text(encoding="utf-8")
        dialog = source[source.index("class ErrorDetailsDialog"):source.index("class RecoveryHistoryDialog")]
        self.assertIn("details_for_job(job", dialog)
        self.assertNotIn("IntegrityDialog", dialog)
        self.assertIn('Gtk.Button(label=tr("error_details"))', source)
        self.assertLess(source.index('Gtk.Button(label=tr("view_log"))'), source.index('Gtk.Button(label=tr("error_details"))'))

    def test_endpoint_change_forces_review_before_recovery_sync(self) -> None:
        source = (REPOSITORY / "src/tuxindrive/app.py").read_text(encoding="utf-8")
        edit_job = source[source.index("    def _edit_job("):source.index("    def _rename_job(")]

        self.assertIn("endpoint_changed = (job.local_path, job.remote_spec, job.mode)", edit_job)
        self.assertIn("updated.initialized = False", edit_job)
        self.assertIn("updated.enabled = False", edit_job)
        self.assertIn("Synchronization paused because an endpoint changed", edit_job)

    def test_browser_oauth_reconnect_uses_the_visible_authorization_wizard(self) -> None:
        source = (REPOSITORY / "src/tuxindrive/app.py").read_text(encoding="utf-8")
        reconnect = source[
            source.index("    def _reconnect("):
            source.index("    def _reconnect_done(")
        ]

        self.assertIn("if account.provider.browser_oauth:", reconnect)
        self.assertIn("OAuthWizard(", reconnect)
        self.assertIn("existing=account", reconnect)
        self.assertLess(
            reconnect.index("if account.provider.browser_oauth:"),
            reconnect.index("self.controller.rclone.reconnect"),
        )

    def test_pcloud_reconnect_requires_an_approved_oauth_application(self) -> None:
        source = (REPOSITORY / "src/tuxindrive/app.py").read_text(encoding="utf-8")
        wizard = source[
            source.index("class OAuthWizard"):
            source.index("class ProtonAuthDialog")
        ]

        self.assertIn("Provider.PCLOUD", wizard)
        self.assertIn("pCloud revoked rclone's shared OAuth application", wizard)
        self.assertIn("https://docs.pcloud.com/my_apps/", wizard)
        self.assertIn(
            "self.provider in {Provider.GOOGLE_DRIVE, Provider.PCLOUD}",
            wizard,
        )

    def test_persisted_live_log_setting_starts_refresh_lifecycle(self) -> None:
        source = (REPOSITORY / "src/tuxindrive/app.py").read_text(encoding="utf-8")
        window = source[source.index("class MainWindow"):]

        initialization = window[:window.index("    def _refresh_network_usage")]
        self.assertIn(
            "self.set_activity_log_enabled(\n"
            "            self.controller.config.settings.show_live_activity_log\n"
            "        )",
            initialization,
        )
        self.assertLess(
            initialization.index("self._activity_source = 0"),
            initialization.index("self.set_activity_log_enabled("),
        )
        self.assertIn(
            'self.connect("map", self._refresh_activity_log_on_map)',
            initialization,
        )

    def test_live_log_keeps_the_newest_records_visible_at_the_top(self) -> None:
        source = (REPOSITORY / "src/tuxindrive/app.py").read_text(encoding="utf-8")
        refresh = source[
            source.index("    def _refresh_activity_log("):
            source.index("    @staticmethod\n    def _tail_file")
        ]

        self.assertIn("newest_first_log(content)", refresh)
        self.assertIn("sections.sort(key=lambda section: section[0], reverse=True)", refresh)
        self.assertIn("buffer.get_start_iter()", refresh)
        self.assertNotIn("buffer.get_end_iter()", refresh)


if __name__ == "__main__":
    unittest.main()
