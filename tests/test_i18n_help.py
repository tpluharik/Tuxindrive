from tests import signal_safety as _signal_safety  # noqa: F401

import unittest

from tuxindrive.help_content import topics
from tuxindrive.i18n import LANGUAGES, get_language, is_rtl, set_language, tr


class LocalizationAndHelpTests(unittest.TestCase):
    def tearDown(self):
        set_language("en")

    def test_six_languages_have_matching_complete_help_topics(self):
        expected = [item.key for item in topics("en")]
        self.assertEqual(len(expected), 19)
        for language in LANGUAGES:
            localized = topics(language.code)
            self.assertEqual([item.key for item in localized], expected)
            self.assertTrue(all(len(item.title) > 3 and len(item.body) > 80 for item in localized))

    def test_translations_switch_and_unknown_language_falls_back(self):
        values = set()
        for code in ("en", "de", "fr", "es", "ar", "he"):
            set_language(code)
            values.add(tr("settings"))
        self.assertEqual(len(values), 6)
        self.assertTrue(is_rtl("ar"))
        self.assertTrue(is_rtl("he"))
        self.assertFalse(is_rtl("en"))
        self.assertEqual(set_language("unsupported"), "en")
        self.assertEqual(get_language(), "en")
        self.assertEqual(tr("missing-key"), "missing-key")

    def test_group_drag_and_collapse_controls_are_localized(self):
        for language in LANGUAGES:
            set_language(language.code)
            for key in (
                "expand_group", "minimize_group", "drag_folder_hint", "drop_group_hint",
                "visual_style", "theme_applies_after_save", "connected_services",
                "active_syncs", "protected_folders",
            ):
                self.assertNotEqual(tr(key), key)
                self.assertGreater(len(tr(key)), 5)


if __name__ == "__main__":
    unittest.main()
