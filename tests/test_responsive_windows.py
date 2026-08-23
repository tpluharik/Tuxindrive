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
        self.assertIn("_run_thread(self.controller.search_index.search, ready, query)", dialog)
        self.assertIn('Gtk.CheckButton(label="Enable preview")', dialog)
        self.assertIn("_run_thread(preview_path, ready, target)", dialog)
        self.assertIn("if self.preview_enabled.get_active()", dialog)
        self.assertIn("self._resolved_result(result)", dialog)
        self.assertIn("result.local_path.resolve(strict=True)", dialog)
        self.assertIn('"edit-find-symbolic"', source)


if __name__ == "__main__":
    unittest.main()
