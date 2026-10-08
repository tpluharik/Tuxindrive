from tests import signal_safety as _signal_safety  # noqa: F401

import unittest

from tuxindrive.models import AppConfig, AppSettings
from tuxindrive.themes import (
    DEFAULT_THEME,
    THEMES,
    css_for_theme,
    normalize_theme,
    theme_by_key,
)


class VisualThemeTests(unittest.TestCase):
    def test_three_named_designs_are_available(self):
        self.assertEqual(
            [theme.key for theme in THEMES],
            ["nordic_glass", "bento_cloud", "midnight_sync"],
        )
        self.assertEqual(
            [theme.label for theme in THEMES],
            ["Nordic Glass", "Bento Cloud", "Midnight Sync"],
        )

    def test_unknown_or_non_string_theme_falls_back_safely(self):
        for value in ("", "future-theme", None, 7):
            self.assertEqual(normalize_theme(value), DEFAULT_THEME)
        self.assertEqual(theme_by_key("future-theme").key, DEFAULT_THEME)

    def test_every_theme_contains_shared_components_and_distinct_palette(self):
        rendered = {theme.key: css_for_theme(theme.key) for theme in THEMES}
        for source in rendered.values():
            self.assertIn(b".account-card", source)
            self.assertIn(b".job-card", source)
            self.assertIn(b".group-card", source)
            self.assertIn(b".activity-panel", source)
            self.assertIn(b".network-meter", source)
            self.assertIn(b"border-radius", source)
            self.assertIn(b"switch#tuxindrive-job-switch", source)
        self.assertEqual(len(set(rendered.values())), 3)
        self.assertIn(b"#edf3f8", rendered["nordic_glass"])
        self.assertIn(b"#6d4aff", rendered["bento_cloud"])
        self.assertIn(b"#08111f", rendered["midnight_sync"])

    def test_midnight_is_the_only_dark_preference(self):
        self.assertFalse(theme_by_key("nordic_glass").dark)
        self.assertFalse(theme_by_key("bento_cloud").dark)
        self.assertTrue(theme_by_key("midnight_sync").dark)

    def test_midnight_overrides_nested_gtk_surface_images(self):
        rendered = css_for_theme("midnight_sync")
        self.assertIn(b".tuxindrive-root scrolledwindow", rendered)
        self.assertIn(b".tuxindrive-root viewport", rendered)
        self.assertIn(b"row.account-card:selected", rendered)
        self.assertIn(b"row.job-card:selected", rendered)
        self.assertIn(b"dialog.tuxindrive-dialog textview text", rendered)
        self.assertIn(b"background-image: none", rendered)
        self.assertIn(b"background-color: #08111f", rendered)

    def test_system_dark_palette_overrides_light_theme_surfaces(self):
        bento = css_for_theme("bento_cloud", prefer_dark=True)
        nordic = css_for_theme("nordic_glass", prefer_dark=True)
        for rendered in (bento, nordic):
            self.assertIn(b"background-color: #08111f", rendered)
            self.assertIn(b"background-color: #101c2e", rendered)
            self.assertGreater(
                rendered.rfind(b"#08111f"),
                rendered.find(b"#fbf9ff") if b"#fbf9ff" in rendered else rendered.find(b"#edf3f8"),
            )
            self.assertIn(b"#summary-services", rendered)
            self.assertIn(b"background-color: #171b36", rendered)
            self.assertIn(b"background-color: #10253a", rendered)
            self.assertIn(b"background-color: #13281f", rendered)

    def test_system_dark_palette_overrides_light_dialog_label_colors(self):
        light_rule = b"dialog.tuxindrive-dialog label { color: #211a35; }"
        dark_rule = b"dialog.tuxindrive-dialog label { color: #d7e3f3; }"
        for rendered in (
            css_for_theme("bento_cloud", prefer_dark=True),
            css_for_theme("nordic_glass", prefer_dark=True),
        ):
            self.assertIn(dark_rule, rendered)
            if light_rule in rendered:
                self.assertGreater(rendered.rfind(dark_rule), rendered.find(light_rule))
            self.assertIn(
                b"dialog.tuxindrive-dialog headerbar label { color: #e7eef9; }",
                rendered,
            )
            self.assertIn(
                b"dialog.tuxindrive-dialog label:disabled { color: #708199; }",
                rendered,
            )

    def test_light_palettes_pin_readable_label_colors(self):
        self.assertIn(
            b"dialog.tuxindrive-dialog label { color: #172033; }",
            css_for_theme("nordic_glass"),
        )
        self.assertIn(
            b"dialog.tuxindrive-dialog label { color: #211a35; }",
            css_for_theme("bento_cloud"),
        )

    def test_configuration_keeps_theme_and_legacy_config_gets_default(self):
        restored = AppConfig.from_dict({"settings": {"visual_theme": "bento_cloud"}})
        self.assertEqual(restored.settings.visual_theme, "bento_cloud")
        self.assertEqual(AppConfig.from_dict({}).settings.visual_theme, DEFAULT_THEME)
        self.assertEqual(
            AppConfig.from_dict({"settings": {"visual_theme": "unknown"}}).settings.visual_theme,
            DEFAULT_THEME,
        )
        self.assertEqual(AppSettings().visual_theme, DEFAULT_THEME)
        self.assertTrue(AppSettings().follow_system_dark_mode)


if __name__ == "__main__":
    unittest.main()
