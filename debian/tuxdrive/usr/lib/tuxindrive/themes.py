"""Application-owned visual themes for the GTK 3 desktop client.

The theme keys are persisted in the private TuxInDrive configuration.  Keeping
the palettes and shared component rules here makes theme changes independent
from synchronization, provider, and folder-layout behavior.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VisualTheme:
    key: str
    label: str
    description: str
    dark: bool = False


THEMES = (
    VisualTheme(
        "nordic_glass",
        "Nordic Glass",
        "Airy blue-white surfaces, soft shadows, and crisp GNOME controls.",
    ),
    VisualTheme(
        "bento_cloud",
        "Bento Cloud",
        "Friendly violet accents, pastel summary tiles, and rounded cards.",
    ),
    VisualTheme(
        "midnight_sync",
        "Midnight Sync",
        "A focused navy workspace with cyan status accents and high contrast.",
        dark=True,
    ),
)
THEME_KEYS = {theme.key for theme in THEMES}
DEFAULT_THEME = "nordic_glass"


def normalize_theme(value: object) -> str:
    return value if isinstance(value, str) and value in THEME_KEYS else DEFAULT_THEME


def theme_by_key(value: object) -> VisualTheme:
    key = normalize_theme(value)
    return next(theme for theme in THEMES if theme.key == key)


_SHARED_CSS = """
window.tuxindrive-surface { font-family: Sans; }
.tuxindrive-root button,
dialog.tuxindrive-dialog button {
  min-height: 28px;
  padding: 5px 12px;
  border-radius: 10px;
}
.tuxindrive-root button.suggested-action,
.tuxindrive-root button.primary-action,
dialog.tuxindrive-dialog button.suggested-action {
  color: #ffffff;
  font-weight: 600;
}
.tuxindrive-root .sidebar {
  border-right-width: 1px;
  border-right-style: solid;
}
.tuxindrive-root .sidebar list,
.tuxindrive-root .job-list,
.tuxindrive-root .activity-log,
.tuxindrive-root list row {
  background: transparent;
}
.tuxindrive-root row.account-card,
.tuxindrive-root row.group-card,
.tuxindrive-root row.job-card,
.tuxindrive-root .activity-panel,
.tuxindrive-root .summary-card {
  border-width: 1px;
  border-style: solid;
  border-radius: 14px;
  margin-bottom: 8px;
}
.tuxindrive-root row.account-card:selected,
.tuxindrive-root row.group-card:selected,
.tuxindrive-root row.job-card:selected { background: transparent; }
.tuxindrive-root row.group-card { font-weight: 600; }
.tuxindrive-root .drag-handle {
  border-radius: 8px;
  padding: 2px;
}
.tuxindrive-root .status-label { font-size: 0.92em; }
.tuxindrive-root .summary-card { padding: 12px 16px; }
.tuxindrive-root .summary-value { font-size: 1.55em; font-weight: 700; }
.tuxindrive-root .summary-label { font-weight: 600; }
.tuxindrive-root .network-meter {
  padding: 9px 14px;
  border-width: 1px;
  border-style: solid;
  border-radius: 12px;
}
.tuxindrive-root .network-title,
.tuxindrive-root .network-value { font-weight: 700; }
.tuxindrive-root .network-label { font-size: 0.90em; }
.tuxindrive-root switch#tuxindrive-job-switch {
  min-width: 42px;
  min-height: 22px;
  padding: 0;
  margin: 0;
  border-radius: 14px;
}
.tuxindrive-root switch#tuxindrive-job-switch slider {
  min-width: 18px;
  min-height: 18px;
  margin: 2px;
  padding: 0;
  border-radius: 10px;
}
dialog.tuxindrive-dialog .theme-description { font-size: 0.92em; }
"""


_NORDIC_GLASS_CSS = """
window.tuxindrive-surface,
dialog.tuxindrive-dialog { background-color: #edf3f8; color: #172033; }
headerbar.tuxindrive-header {
  background-image: linear-gradient(to bottom, #ffffff, #f4f8fc);
  color: #172033;
  border-bottom: 1px solid #d8e2ec;
  box-shadow: 0 2px 10px alpha(#17324d, 0.10);
}
.tuxindrive-root { background-color: #edf3f8; color: #172033; }
.tuxindrive-root .sidebar {
  background-image: linear-gradient(to bottom, #f9fbfd, #f2f7fb);
  border-right-color: #d8e2ec;
}
.tuxindrive-root .workspace { background-color: #edf3f8; }
.tuxindrive-root row.account-card,
.tuxindrive-root row.group-card,
.tuxindrive-root row.job-card,
.tuxindrive-root .activity-panel,
.tuxindrive-root .summary-card {
  background-color: #ffffff;
  border-color: #dce6ef;
  box-shadow: 0 3px 12px alpha(#16324f, 0.08);
}
.tuxindrive-root row.group-card { background-color: #f8fbfe; }
.tuxindrive-root row.account-card:hover,
.tuxindrive-root row.job-card:hover { border-color: #8eb9e8; }
.tuxindrive-root .drag-handle:hover { background-color: #e6f0fa; }
.tuxindrive-root button { background-image: none; background-color: #ffffff; border-color: #cddae6; color: #24364a; }
.tuxindrive-root button:hover { background-color: #eef6ff; border-color: #76a9df; }
.tuxindrive-root button.suggested-action,
.tuxindrive-root button.primary-action,
dialog.tuxindrive-dialog button.suggested-action { background-image: none; background-color: #2563eb; border-color: #1d4ed8; }
.tuxindrive-root switch:checked { background-color: #2563eb; border-color: #1d4ed8; }
.tuxindrive-root .activity-log { background-color: #f8fbfe; color: #31445a; }
.tuxindrive-root .network-meter { background-color: #ffffff; border-color: #dce6ef; }
.tuxindrive-root .network-value { color: #2563eb; }
.tuxindrive-root .dim-label,
dialog.tuxindrive-dialog .theme-description { color: #63758a; }
"""


_BENTO_CLOUD_CSS = """
window.tuxindrive-surface,
dialog.tuxindrive-dialog { background-color: #fbf9ff; color: #211a35; }
headerbar.tuxindrive-header {
  background-image: linear-gradient(to right, #ffffff, #f6f0ff);
  color: #211a35;
  border-bottom: 1px solid #e8def8;
  box-shadow: 0 3px 14px alpha(#6d4aff, 0.10);
}
.tuxindrive-root { background-color: #fbf9ff; color: #211a35; }
.tuxindrive-root .sidebar {
  background-image: linear-gradient(to bottom, #f1edff, #faf8ff);
  border-right-color: #e2d8f7;
}
.tuxindrive-root .workspace { background-color: #fbf9ff; }
.tuxindrive-root row.account-card,
.tuxindrive-root row.group-card,
.tuxindrive-root row.job-card,
.tuxindrive-root .activity-panel,
.tuxindrive-root .summary-card {
  background-color: #ffffff;
  border-color: #e6def1;
  box-shadow: 0 4px 14px alpha(#4d2b7a, 0.09);
}
.tuxindrive-root row.group-card { background-color: #faf7ff; }
.tuxindrive-root row.account-card:hover,
.tuxindrive-root row.job-card:hover { border-color: #a78bfa; }
.tuxindrive-root .drag-handle:hover { background-color: #eee8ff; }
.tuxindrive-root button { background-image: none; background-color: #ffffff; border-color: #ddd2ef; color: #3b2f55; }
.tuxindrive-root button:hover { background-color: #f1ebff; border-color: #9a7cf0; }
.tuxindrive-root button.suggested-action,
.tuxindrive-root button.primary-action,
dialog.tuxindrive-dialog button.suggested-action { background-image: linear-gradient(to right, #7655e8, #5b3fd2); border-color: #5b3fd2; }
.tuxindrive-root switch:checked { background-color: #6d4aff; border-color: #5b3fd2; }
.tuxindrive-root #summary-services { background-color: #f4efff; border-color: #d9cafd; }
.tuxindrive-root #summary-active { background-color: #eef7ff; border-color: #c9e5ff; }
.tuxindrive-root #summary-protected { background-color: #effbf2; border-color: #ccebd3; }
.tuxindrive-root .activity-log { background-color: #fffdfb; color: #4e4264; }
.tuxindrive-root .network-meter { background-color: #f4efff; border-color: #d9cafd; }
.tuxindrive-root .network-value { color: #5b3fd2; }
.tuxindrive-root .dim-label,
dialog.tuxindrive-dialog .theme-description { color: #76698b; }
"""


_MIDNIGHT_SYNC_CSS = """
window.tuxindrive-surface,
dialog.tuxindrive-dialog { background-color: #08111f; color: #d7e3f3; }
headerbar.tuxindrive-header {
  background-image: linear-gradient(to bottom, #101b2d, #0b1525);
  color: #e7eef9;
  border-bottom: 1px solid #263750;
  box-shadow: 0 3px 14px alpha(#000000, 0.35);
}
.tuxindrive-root { background-color: #08111f; color: #d7e3f3; }
.tuxindrive-root label { color: #d7e3f3; }
.tuxindrive-root .sidebar {
  background-image: linear-gradient(to bottom, #0d1829, #0a1423);
  border-right-color: #263750;
}
.tuxindrive-root .workspace { background-color: #08111f; }
.tuxindrive-root row.account-card,
.tuxindrive-root row.group-card,
.tuxindrive-root row.job-card,
.tuxindrive-root .activity-panel,
.tuxindrive-root .summary-card {
  background-color: #101c2e;
  border-color: #2a3b55;
  box-shadow: 0 4px 14px alpha(#000000, 0.28);
  color: #d7e3f3;
}
.tuxindrive-root row.group-card { background-color: #0e1a2b; }
.tuxindrive-root row.account-card:hover,
.tuxindrive-root row.job-card:hover { border-color: #22d3ee; }
.tuxindrive-root .drag-handle:hover { background-color: #1b2c45; }
.tuxindrive-root button { background-image: none; background-color: #142238; border-color: #344966; color: #d7e3f3; }
.tuxindrive-root button:hover { background-color: #1b3150; border-color: #31c6e8; color: #ffffff; }
.tuxindrive-root button.suggested-action,
.tuxindrive-root button.primary-action,
dialog.tuxindrive-dialog button.suggested-action { background-image: linear-gradient(to right, #5b5cf0, #7149e8); border-color: #7c6df2; }
.tuxindrive-root switch { background-color: #25364f; border-color: #3c526f; }
.tuxindrive-root switch:checked { background-color: #6657ed; border-color: #8b7cf6; }
.tuxindrive-root .activity-log { background-color: #0b1626; color: #b9c9dd; caret-color: #22d3ee; }
.tuxindrive-root .network-meter { background-color: #101c2e; border-color: #2a3b55; }
.tuxindrive-root .network-value { color: #22d3ee; }
.tuxindrive-root .dim-label,
dialog.tuxindrive-dialog .theme-description { color: #91a3bb; }
dialog.tuxindrive-dialog entry,
dialog.tuxindrive-dialog combobox button { background-color: #142238; color: #d7e3f3; border-color: #344966; }
"""


_THEME_CSS = {
    "nordic_glass": _NORDIC_GLASS_CSS,
    "bento_cloud": _BENTO_CLOUD_CSS,
    "midnight_sync": _MIDNIGHT_SYNC_CSS,
}


def css_for_theme(value: object) -> bytes:
    key = normalize_theme(value)
    return (_SHARED_CSS + _THEME_CSS[key]).encode("utf-8")
