from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import threading
import tempfile
import time
import uuid
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import __version__
from .diagnostics import (
    application_log_path,
    configure_logging,
    crash_log_path,
    install_crash_handlers,
    log_boot_failure,
    log_directory,
)
from .file_permissions import private_descriptor

LOGGER = configure_logging(__version__)
install_crash_handlers(LOGGER)

try:
    import gi

    # Pin GDK before importing it. Ubuntu 26.04 ships both GDK 3 and 4; without
    # this explicit requirement PyGObject may load GDK 4 before GTK 3.
    gi.require_version("Gdk", "3.0")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gdk, Gio, GLib
    from gi.repository import GdkPixbuf
except (ImportError, ValueError) as exc:  # pragma: no cover - depends on host desktop
    message = (
        "TuxInDrive could not load its desktop runtime. Reinstall with:\n\n"
        f"sudo apt install ./tuxindrive_{__version__}_all.deb\n\n"
        f"Technical detail: {exc}\nCrash log: {crash_log_path()}"
    )
    log_boot_failure(message)
    print(message, file=sys.stderr)
    if shutil.which("zenity"):
        subprocess.run(["zenity", "--error", "--title=TuxInDrive startup failure", f"--text={message}"], check=False)
    raise SystemExit(2) from exc

from .audit import AuditTimeline
from .capabilities import CAPABILITIES, capabilities_for
from .config import ConfigStore, cache_root
from .i18n import LANGUAGES, LANGUAGE_CODES, get_language, is_rtl, set_language, tr
from .engine import JobResult, SyncEngine
from .models import (
    Account, AppConfig, AuthorizedPeer, ConflictPolicy, FolderGroup, OneTimeDrop, PeerRole, PeerShare, PeerTransportPolicy, Provider, SyncJob, SyncMode,
    paths_overlap, safe_streaming_overlap,
)
from .github_sync import GitHubSyncError, parse_repository_url, repository_item_url, validate_branch
from .folder_layout import (
    cloud_selection_paths,
    initial_cloud_paths,
    job_drag_payload,
    job_id_from_drag_payload,
    move_job,
    toggle_cloud_selection,
)
from .peer import DiscoveredPeer, PeerError, PeerInvitation, PeerManager, key_fingerprint, local_network_address, normalize_public_key, validate_host, validate_port
from .recovery import AuditIssue, IntegrityAuditor, RecoveryEntry, SafetyError
from .rclone import ConfigQuestion, ConfigResult, DriveLocation, RcloneClient, RcloneError
from .proton import ProtonDriveClient, ProtonDriveError
from .updater import UpdateManager, UpdateRelease
from .policies import PolicyDecision, TransferPolicy
from .migration import MigrationError, ProfileManager
from .profile_qr import encode_profile_frames
from .platform_support import format_report, inspect_host
from .nautilus_support import (
    availability_route,
    command_line_path,
    lexical_relative_path,
    verified_rules_after,
)
from .themes import THEMES, css_for_theme, normalize_theme, theme_by_key
from .network_usage import NetworkUsageMeter, format_bytes
from .bandwidth import GlobalBandwidthController, normalize_bandwidth_limit
from .server_client import ServerClient, ServerClientError, normalize_server_url
from .server_credentials import store_server_token
from .search_index import FolderSearchIndex, IndexStats, SearchResult
from .file_preview import PreviewData, PreviewError, preview_path
from .error_details import details_for_job
from .recovery_advisor import advice_for_error
from .managed_policy import ManagedPolicy, load_managed_policy
from .scheduling import persisted_run_time

try:  # Ubuntu's AppIndicator extension provides Windows-like tray controls.
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3
except (ImportError, ValueError):  # pragma: no cover - optional desktop component
    AyatanaAppIndicator3 = None


APP_ID = "io.github.tuxindrive.TuxInDrive"
JOB_DND_TARGET = "UTF8_STRING"


def _brand_logo_path() -> Path | None:
    candidates: list[Path] = []
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / "branding" / "tuxindrive-logo.png")
    candidates.extend(
        (
            Path(__file__).resolve().parents[2] / "branding" / "tuxindrive-logo.png",
            Path("/usr/share/doc/tuxindrive/tuxindrive-logo.png"),
        )
    )
    return next((path for path in candidates if path.is_file()), None)


def _brand_pixbuf(icon_size: Gtk.IconSize):
    path = _brand_logo_path()
    if path is None:
        return None
    found, width, height = Gtk.icon_size_lookup(icon_size)
    pixels = max(width, height) if found else 32
    try:
        return GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), pixels, pixels, True)
    except GLib.Error:
        LOGGER.warning("Could not load application logo from %s", path)
        return None


def _brand_image(icon_size: Gtk.IconSize) -> Gtk.Image:
    pixbuf = _brand_pixbuf(icon_size)
    return Gtk.Image.new_from_pixbuf(pixbuf) if pixbuf else Gtk.Image.new_from_icon_name("tuxindrive", icon_size)


def _set_window_brand_icon(window: Gtk.Window) -> None:
    pixbuf = _brand_pixbuf(Gtk.IconSize.DIALOG)
    if pixbuf:
        window.set_icon(pixbuf)
    else:
        window.set_icon_name("tuxindrive")


def _desktop_open_command(target: str) -> list[str]:
    system = platform.system()
    if system == "Darwin":
        return ["open", target]
    if system == "Windows":
        return ["explorer.exe", target]
    return ["xdg-open", target]


def _run_thread(function: Callable, callback: Callable, *args) -> None:
    def worker() -> None:
        try:
            result = function(*args)
            GLib.idle_add(callback, result, None)
        except Exception as exc:  # UI boundary: display backend errors to the user.
            GLib.idle_add(callback, None, exc)

    threading.Thread(target=worker, daemon=True).start()


class ResponsiveDialog(Gtk.Dialog):
    """Dialog whose content remains reachable on small or resized screens."""

    def _prepare_responsive_content(self) -> None:
        if getattr(self, "_responsive_content_ready", False):
            return
        self._responsive_content_ready = True
        self.set_resizable(True)
        display = Gdk.Display.get_default()
        monitor = None
        if display is not None:
            parent = self.get_transient_for()
            parent_window = parent.get_window() if parent is not None else None
            if parent_window is not None:
                monitor = display.get_monitor_at_window(parent_window)
            if monitor is None:
                monitor = display.get_primary_monitor()
            if monitor is None and display.get_n_monitors() > 0:
                monitor = display.get_monitor(0)
        if monitor is not None:
            workarea = monitor.get_workarea()
            # Use nearly all of the active monitor's usable area without
            # requesting a true window-manager maximization. Workarea excludes
            # desktop panels, and the remaining margin accommodates window
            # decorations. Oversized content is handled by the scroll view.
            self.set_default_size(
                max(1, int(workarea.width * 0.92)),
                max(1, int(workarea.height * 0.92)),
            )

        area = self.get_content_area()
        children = list(area.get_children())
        if not children:
            return
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=area.get_spacing())
        wrapper.set_hexpand(True)
        wrapper.set_vexpand(True)
        packing: list[tuple[Gtk.Widget, bool, bool, int, Gtk.PackType]] = []
        for child in children:
            packing.append((
                child,
                bool(area.child_get_property(child, "expand")),
                bool(area.child_get_property(child, "fill")),
                int(area.child_get_property(child, "padding")),
                area.child_get_property(child, "pack-type"),
            ))
            area.remove(child)
        for child, expand, fill, padding, pack_type in packing:
            if pack_type == Gtk.PackType.END:
                wrapper.pack_end(child, expand, fill, padding)
            else:
                wrapper.pack_start(child, expand, fill, padding)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_width(1)
        scroll.set_min_content_height(1)
        scroll.set_propagate_natural_width(False)
        scroll.set_propagate_natural_height(False)
        scroll.add(wrapper)
        area.pack_start(scroll, True, True, 0)

    def show_all(self) -> None:
        self._prepare_responsive_content()
        super().show_all()

    def run(self) -> int:
        self._prepare_responsive_content()
        return super().run()


class OAuthWizard(ResponsiveDialog):
    def __init__(
        self,
        parent: Gtk.Window,
        client: RcloneClient,
        provider: Provider,
        complete_callback: Callable[[Account], None],
        existing: Account | None = None,
    ) -> None:
        super().__init__(title=f"Connect {provider.label}", transient_for=parent, modal=True)
        self.set_icon_name(provider.icon_name)
        self.set_default_size(580, 460)
        self.client = client
        self.provider = provider
        self.complete_callback = complete_callback
        self.existing = existing
        self.question: ConfigQuestion | None = None
        self.remote = ""
        self.session_id = uuid.uuid4().hex
        self._closed = False

        content = self.get_content_area()
        content.set_border_width(24)
        content.set_spacing(14)
        title = Gtk.Label()
        title.set_markup(f"<span size='x-large' weight='bold'>Connect {provider.label}</span>")
        title.set_xalign(0)
        content.pack_start(title, False, False, 0)
        description = Gtk.Label(label=(
            "Authorization opens in your default web browser. TuxInDrive never sees your password."
            if provider.browser_oauth else
            "Follow the connection questions below. Use an app password where your provider supports one; credentials remain in rclone's private configuration."
        ))
        description.set_xalign(0)
        description.set_line_wrap(True)
        content.pack_start(description, False, False, 0)

        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        self.name_entry = Gtk.Entry()
        self.name_entry.set_text(
            existing.remote if existing else
            provider.key_prefix + "-" + datetime.now().strftime("%H%M")
        )
        self.name_entry.set_sensitive(existing is None)
        self.display_entry = Gtk.Entry()
        self.display_entry.set_text(existing.display_name if existing else provider.label)
        self.client_id = Gtk.Entry()
        self.client_secret = Gtk.Entry()
        self.client_secret.set_visibility(False)
        grid.attach(Gtk.Label(label="Account key", xalign=0), 0, 0, 1, 1)
        grid.attach(self.name_entry, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Display name", xalign=0), 0, 1, 1, 1)
        grid.attach(self.display_entry, 1, 1, 1, 1)
        if provider.browser_oauth:
            grid.attach(Gtk.Label(label="OAuth client ID (optional)", xalign=0), 0, 2, 1, 1)
            grid.attach(self.client_id, 1, 2, 1, 1)
            grid.attach(Gtk.Label(label="OAuth client secret (optional)", xalign=0), 0, 3, 1, 1)
            grid.attach(self.client_secret, 1, 3, 1, 1)
        self.credential_entries: dict[str, Gtk.Entry] = {}
        for offset, (key, label, secret, _required) in enumerate(provider.credential_fields, start=2):
            entry = Gtk.Entry()
            entry.set_visibility(not secret)
            entry.set_text(provider.credential_defaults.get(key, ""))
            if secret:
                entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
            grid.attach(Gtk.Label(label=label, xalign=0), 0, offset, 1, 1)
            grid.attach(entry, 1, offset, 1, 1)
            self.credential_entries[key] = entry
        content.pack_start(grid, False, False, 0)

        self.question_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.help_label = Gtk.Label(xalign=0)
        self.help_label.set_line_wrap(True)
        self.help_label.set_selectable(True)
        self.question_box.pack_start(self.help_label, False, False, 0)
        self.answer_widget: Gtk.Widget | None = None
        content.pack_start(self.question_box, True, True, 0)

        self.spinner = Gtk.Spinner()
        self.status = Gtk.Label(label="Ready", xalign=0)
        status_row = Gtk.Box(spacing=10)
        status_row.pack_start(self.spinner, False, False, 0)
        status_row.pack_start(self.status, True, True, 0)
        content.pack_start(status_row, False, False, 0)

        self.cancel_button = self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.next_button = self.add_button(
            "Open browser and connect" if provider.browser_oauth else "Configure connection",
            Gtk.ResponseType.OK,
        )
        self.connect("response", self._on_response)
        self.connect("delete-event", self._on_delete)
        self.show_all()
        self.question_box.hide()

    def _on_response(self, _dialog: Gtk.Dialog, response: int) -> None:
        if response != Gtk.ResponseType.OK:
            self._cancel_authorization()
            self.destroy()
            return
        if self.question is None:
            remote = self.name_entry.get_text().strip()
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", remote):
                self._set_error("Account key may contain only letters, numbers, dot, dash, and underscore.")
                return
            self.remote = remote
            credentials = {
                key: entry.get_text().strip()
                for key, entry in self.credential_entries.items()
            }
            missing = [
                label for key, label, _secret, required in self.provider.credential_fields
                if required and not credentials.get(key)
            ]
            if missing:
                self._set_error("Required: " + ", ".join(missing))
                return
            self._busy("Preparing secure authorization…")
            _run_thread(
                self.client.begin_oauth,
                self._step_ready,
                remote,
                self.provider,
                self.client_id.get_text().strip(),
                self.client_secret.get_text().strip(),
                self.session_id,
                credentials,
            )
        else:
            answer = self._answer()
            if self.question.required and not answer:
                self._set_error("This value is required.")
                return
            state = self.question.state
            self._busy("Waiting for authorization… Check your web browser.")
            _run_thread(
                self.client.continue_oauth,
                self._step_ready,
                self.remote,
                state,
                answer,
                self.session_id,
            )

    def _on_delete(self, *_args) -> bool:
        self._cancel_authorization()
        return False

    def _cancel_authorization(self) -> None:
        if not self._closed:
            self._closed = True
            self.client.cancel_oauth(self.session_id)

    def _step_ready(self, result: ConfigResult | None, error: Exception | None) -> bool:
        if self._closed:
            return False
        self._not_busy()
        if error:
            self._set_error(str(error))
            return False
        if result is None:
            self._set_error("Authorization returned no result")
            return False
        if result.complete:
            self._busy("Verifying cloud access…")
            _run_thread(self.client.validate_remote, self._validation_ready, self.remote)
            return False
        self.question = result.question
        self._show_question(result.question)
        return False

    def _show_question(self, question: ConfigQuestion | None) -> None:
        if question is None:
            return
        self.name_entry.set_sensitive(False)
        self.display_entry.set_sensitive(False)
        self.client_id.set_sensitive(False)
        self.client_secret.set_sensitive(False)
        for entry in self.credential_entries.values():
            entry.set_sensitive(False)
        self.question_box.show()
        self.help_label.set_text((question.error + "\n\n" if question.error else "") + question.help)
        if self.answer_widget:
            self.question_box.remove(self.answer_widget)
        if question.examples:
            combo = Gtk.ComboBoxText()
            selected = 0
            for index, example in enumerate(question.examples):
                value = str(example.get("Value", ""))
                label = str(example.get("Help") or value)
                combo.append(value, label)
                if value == str(question.default):
                    selected = index
            combo.set_active(selected)
            self.answer_widget = combo
        else:
            entry = Gtk.Entry()
            entry.set_text("" if question.default is None else str(question.default))
            entry.set_visibility(not question.secret)
            self.answer_widget = entry
        self.question_box.pack_start(self.answer_widget, False, False, 0)
        self.answer_widget.show()
        self.next_button.set_label("Continue")
        self.status.set_text("Choose an option and continue")

    def _validation_ready(self, _result, error: Exception | None) -> bool:
        self._not_busy()
        if error:
            self._set_error(f"Connection validation failed: {error}")
            return False
        account = Account(
            remote=self.remote,
            provider=self.provider,
            display_name=self.display_entry.get_text().strip() or self.provider.label,
        )
        self.complete_callback(account)
        self.destroy()
        return False

    def _answer(self) -> str:
        if isinstance(self.answer_widget, Gtk.ComboBoxText):
            return self.answer_widget.get_active_id() or ""
        if isinstance(self.answer_widget, Gtk.Entry):
            return self.answer_widget.get_text()
        return ""

    def _busy(self, message: str) -> None:
        self.spinner.start()
        self.status.set_text(message)
        self.next_button.set_sensitive(False)
        self.cancel_button.set_sensitive(True)

    def _not_busy(self) -> None:
        self.spinner.stop()
        self.next_button.set_sensitive(True)
        self.cancel_button.set_sensitive(True)

    def _set_error(self, message: str) -> None:
        self.status.set_markup(f"<span foreground='#c01c28'>{GLib.markup_escape_text(message)}</span>")


class ProtonAuthDialog(ResponsiveDialog):
    """Browser-only authorization through Proton's official CLI."""

    def __init__(
        self,
        parent: Gtk.Window,
        client: ProtonDriveClient,
        complete_callback: Callable[[Account], None],
        accounts: list[Account],
        existing: Account | None = None,
    ) -> None:
        super().__init__(title="Connect Proton Drive", transient_for=parent, modal=True)
        self.set_icon_name(Provider.PROTON_DRIVE.icon_name)
        self.set_default_size(600, 420)
        self.client = client
        self.complete_callback = complete_callback
        self.accounts = accounts
        self.existing = existing
        self._closed = False
        area = self.get_content_area()
        area.set_border_width(24)
        area.set_spacing(14)
        title = Gtk.Label(xalign=0)
        title.set_markup("<span size='x-large' weight='bold'>Connect Proton Drive securely</span>")
        area.pack_start(title, False, False, 0)
        explanation = Gtk.Label(
            label=(
                "TuxInDrive starts Proton's official browser authorization. Your password and two-factor code "
                "are entered only on Proton's website. The resulting session is stored by the official CLI "
                "in Linux Secret Service; TuxInDrive never receives or exports it."
            ),
            xalign=0,
        )
        explanation.set_line_wrap(True)
        area.pack_start(explanation, False, False, 0)
        limitation = Gtk.Label(
            label=(
                "Scheduled folder synchronization is supported. Files-on-demand is disabled for Proton "
                "because the official CLI does not provide a mount interface."
            ),
            xalign=0,
        )
        limitation.set_line_wrap(True)
        limitation.get_style_context().add_class("dim-label")
        area.pack_start(limitation, False, False, 0)
        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        self.name_entry = Gtk.Entry()
        self.name_entry.set_text(existing.remote if existing else "proton-web")
        self.name_entry.set_sensitive(existing is None)
        self.display_entry = Gtk.Entry()
        self.display_entry.set_text(existing.display_name if existing else "Proton Drive")
        grid.attach(Gtk.Label(label="Account key", xalign=0), 0, 0, 1, 1)
        grid.attach(self.name_entry, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Display name", xalign=0), 0, 1, 1, 1)
        grid.attach(self.display_entry, 1, 1, 1, 1)
        area.pack_start(grid, False, False, 0)
        self.spinner = Gtk.Spinner()
        ready = client.available()
        self.status = Gtk.Label(
            label=(
                "Official Proton CLI detected; ready to open authorization."
                if ready
                else "The official CLI will be downloaded from Proton and checksum-verified before sign-in."
            ),
            xalign=0,
        )
        self.status.set_line_wrap(True)
        row = Gtk.Box(spacing=10)
        row.pack_start(self.spinner, False, False, 0)
        row.pack_start(self.status, True, True, 0)
        area.pack_start(row, False, False, 0)
        download = Gtk.Button(label="Proton CLI release information")
        download.connect(
            "clicked", lambda _button: webbrowser.open("https://proton.me/download/drive/cli/index.html")
        )
        area.pack_start(download, False, False, 0)
        self.cancel_button = self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.login_button = self.add_button(
            "Open browser and connect" if ready else "Install CLI and connect",
            Gtk.ResponseType.OK,
        )
        self.login_button.get_style_context().add_class("suggested-action")
        self.connect("response", self._response)
        self.connect("delete-event", self._delete)
        self.show_all()

    def _response(self, _dialog: Gtk.Dialog, response: int) -> None:
        if response != Gtk.ResponseType.OK:
            self._closed = True
            self.client.cancel_login()
            self.destroy()
            return
        remote = self.name_entry.get_text().strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", remote):
            self._error("Account key may contain only letters, numbers, dot, dash, and underscore.")
            return
        collision = next(
            (
                account for account in self.accounts
                if account.remote == remote
                and (not self.existing or account.remote != self.existing.remote)
            ),
            None,
        )
        if collision:
            self._error("That account key is already in use. Choose a different key.")
            return
        another = next(
            (
                account for account in self.accounts
                if account.provider is Provider.PROTON_DRIVE
                and account.backend == "proton_cli"
                and (not self.existing or account.remote != self.existing.remote)
            ),
            None,
        )
        if another:
            self._error(
                "The official Proton CLI maintains one active account session. Remove or reconnect the existing Proton account first."
            )
            return
        self.spinner.start()
        self.status.set_text(
            "Installing the verified Proton CLI, then opening browser authorization…"
            if not self.client.available()
            else "Complete sign-in and two-factor authentication in your browser…"
        )
        self.login_button.set_sensitive(False)
        _run_thread(self.client.install_and_login, self._ready)

    def _delete(self, *_args) -> bool:
        self._closed = True
        self.client.cancel_login()
        return False

    def _ready(self, _result, error: Exception | None) -> bool:
        self.spinner.stop()
        self.login_button.set_sensitive(True)
        if self._closed:
            return False
        if error:
            self._error(str(error))
            return False
        account = Account(
            remote=self.name_entry.get_text().strip(),
            provider=Provider.PROTON_DRIVE,
            display_name=self.display_entry.get_text().strip() or "Proton Drive",
            backend="proton_cli",
        )
        self.complete_callback(account)
        self.destroy()
        return False

    def _error(self, message: str) -> None:
        self.status.set_markup(
            f"<span foreground='#c01c28'>{GLib.markup_escape_text(message)}</span>"
        )


class CloudBrowserClient:
    """Route folder browsing without exposing provider sessions to callers."""

    def __init__(
        self,
        rclone: RcloneClient,
        proton: ProtonDriveClient,
        accounts: Callable[[], list[Account]],
    ) -> None:
        self.rclone = rclone
        self.proton = proton
        self.accounts = accounts

    def list_directories(self, remote: str, remote_path: str = "") -> list[str]:
        account = next((item for item in self.accounts() if item.remote == remote), None)
        if account and account.provider is Provider.PROTON_DRIVE and account.backend == "proton_cli":
            return self.proton.list_directories(remote, remote_path)
        return self.rclone.list_directories(remote, remote_path)

    def google_drive_locations(self, remote: str) -> list[DriveLocation]:
        return self.rclone.google_drive_locations(remote)


class CloudFolderTree(Gtk.Box):
    """Lazy-loading, multi-select cloud directory tree."""

    def __init__(self, client: RcloneClient | CloudBrowserClient, remote: str, selected: list[str] | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.client = client
        self.remote = remote
        self.selected_paths = cloud_selection_paths(selected)
        self.store = Gtk.TreeStore(bool, str, str, bool)
        self.view = Gtk.TreeView(model=self.store)
        self.view.set_headers_visible(False)
        toggle = Gtk.CellRendererToggle()
        toggle.connect("toggled", self._toggle)
        self.view.append_column(Gtk.TreeViewColumn("Sync", toggle, active=0))
        folder = Gtk.CellRendererPixbuf(icon_name="folder-symbolic")
        label = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Cloud folder")
        column.pack_start(folder, False)
        column.pack_start(label, True)
        column.add_attribute(label, "text", 1)
        self.view.append_column(column)
        self.view.connect("row-expanded", self._expanded)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(250)
        scroll.add(self.view)
        self.pack_start(scroll, True, True, 0)
        self.status = Gtk.Label(label="Expand folders to browse the cloud drive.", xalign=0)
        self.status.set_line_wrap(True)
        self.pack_start(self.status, False, False, 0)
        self.reset(remote, selected)

    def reset(self, remote: str, selected: list[str] | None = None) -> None:
        self.remote = remote
        self.selected_paths = cloud_selection_paths(selected)
        self.store.clear()
        root_selected = "" in self.selected_paths
        root = self.store.append(None, [root_selected, "Entire cloud drive", "", False])
        self.store.append(root, [False, "Loading…", "", True])
        self.view.expand_row(self.store.get_path(root), False)
        self._load(root)

    def selections(self) -> list[str]:
        # The cloud tree loads in worker threads. The user's choices must not
        # disappear merely because a selected row has not rendered yet.
        return sorted(self.selected_paths, key=lambda value: (value != "", value))

    def _toggle(self, _renderer, path: str) -> None:
        tree_iter = self.store.get_iter(path)
        selected = not self.store.get_value(tree_iter, 0)
        cloud_path = self.store.get_value(tree_iter, 2)
        self.selected_paths = toggle_cloud_selection(
            self.selected_paths, cloud_path, selected
        )
        self.store.set_value(tree_iter, 0, selected)
        if selected:
            parent = self.store.iter_parent(tree_iter)
            while parent:
                self.store.set_value(parent, 0, False)
                parent = self.store.iter_parent(parent)
            self._clear_descendants(tree_iter)
        self.status.set_text(
            f"{len(self.selections())} cloud location(s) selected"
            if self.selections()
            else "Select at least one cloud folder or the entire drive."
        )

    def _clear_descendants(self, tree_iter) -> None:
        child = self.store.iter_children(tree_iter)
        while child:
            self.store.set_value(child, 0, False)
            self._clear_descendants(child)
            child = self.store.iter_next(child)

    def _expanded(self, _view, tree_iter, _path) -> None:
        self._load(tree_iter)

    def _load(self, tree_iter) -> None:
        if self.store.get_value(tree_iter, 3):
            return
        self.store.set_value(tree_iter, 3, True)
        cloud_path = self.store.get_value(tree_iter, 2)
        self.status.set_text(f"Loading {cloud_path or 'cloud drive'}…")
        _run_thread(
            self.client.list_directories,
            lambda folders, error, remote=self.remote, path=cloud_path: self._loaded(
                remote, path, folders, error
            ),
            self.remote,
            cloud_path,
        )

    def _loaded(
        self,
        remote: str,
        cloud_path: str,
        folders: list[str] | None,
        error: Exception | None,
    ) -> bool:
        if remote != self.remote:
            return False
        target = self._find_path(self.store.get_iter_first(), cloud_path)
        if target is None:
            return False
        child = self.store.iter_children(target)
        while child:
            self.store.remove(child)
            child = self.store.iter_children(target)
        if error:
            self.store.set_value(target, 3, False)
            detail = str(error)
            if "username and password are required" in detail.lower():
                detail += (
                    "\nOpen the Proton Drive account menu and choose "
                    "Reconnect / refresh credentials."
                )
            self.status.set_markup(
                f"<span foreground='#c01c28'>{GLib.markup_escape_text(detail)}</span>"
            )
            return False
        parent_path = self.store.get_value(target, 2)
        for name in folders or []:
            full_path = f"{parent_path}/{name}".strip("/")
            row = self.store.append(target, [full_path in self.selected_paths, name, full_path, False])
            self.store.append(row, [False, "Loading…", full_path, True])
        self.status.set_text(f"{len(self.selections())} cloud location(s) selected")
        self._expand_pending(target)
        return False

    def _find_path(self, tree_iter, cloud_path: str):
        while tree_iter:
            if (
                self.store.get_value(tree_iter, 2) == cloud_path
                and self.store.get_value(tree_iter, 1) != "Loading…"
            ):
                return tree_iter
            nested = self._find_path(self.store.iter_children(tree_iter), cloud_path)
            if nested is not None:
                return nested
            tree_iter = self.store.iter_next(tree_iter)
        return None

    def _expand_pending(self, parent) -> None:
        parent_path = self.store.get_value(parent, 2)
        for wanted in self.selected_paths:
            if not wanted or not wanted.startswith(f"{parent_path}/" if parent_path else ""):
                continue
            child = self.store.iter_children(parent)
            while child:
                child_path = self.store.get_value(child, 2)
                if wanted == child_path:
                    self.store.set_value(child, 0, True)
                    break
                if wanted.startswith(child_path + "/"):
                    self.view.expand_row(self.store.get_path(child), False)
                    self._load(child)
                    break
                child = self.store.iter_next(child)


class ExceptionRulesEditor(Gtk.Box):
    def __init__(self, rules: list[str]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.rule_list = Gtk.ListBox()
        self.rule_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(110)
        scroll.add(self.rule_list)
        self.pack_start(scroll, True, True, 0)
        add_row = Gtk.Box(spacing=6)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Example: /folder/file.zip or *.tmp")
        self.entry.connect("activate", lambda _entry: self._add_clicked(None))
        add_button = Gtk.Button(label="Add exception")
        add_button.connect("clicked", self._add_clicked)
        add_row.pack_start(self.entry, True, True, 0)
        add_row.pack_start(add_button, False, False, 0)
        self.pack_start(add_row, False, False, 0)
        for rule in rules:
            self.add_rule(rule)

    def rules(self) -> list[str]:
        return [row.rule for row in self.rule_list.get_children()]

    def add_rule(self, rule: str) -> None:
        cleaned = rule.strip()
        if not cleaned or cleaned in self.rules():
            return
        row = Gtk.ListBoxRow()
        row.rule = cleaned
        box = Gtk.Box(spacing=8)
        box.set_border_width(4)
        label = Gtk.Label(label=cleaned, xalign=0)
        label.set_selectable(True)
        remove = Gtk.Button.new_from_icon_name("list-remove-symbolic", Gtk.IconSize.BUTTON)
        remove.set_tooltip_text("Remove this synchronization exception")
        remove.connect("clicked", lambda _button: self.rule_list.remove(row))
        box.pack_start(label, True, True, 0)
        box.pack_end(remove, False, False, 0)
        row.add(box)
        self.rule_list.add(row)
        row.show_all()

    def _add_clicked(self, _button) -> None:
        self.add_rule(self.entry.get_text())
        self.entry.set_text("")


class SyncJobDialog(ResponsiveDialog):
    def __init__(
        self,
        parent: Gtk.Window,
        client: RcloneClient | CloudBrowserClient,
        accounts: list[Account],
        existing: SyncJob | None = None,
    ) -> None:
        super().__init__(
            title="Edit synchronized folder" if existing else "Add synchronized folder",
            transient_for=parent,
            modal=True,
        )
        self.set_default_size(760, 760)
        self.client = client
        self.accounts = accounts
        self.existing = existing
        content = self.get_content_area()
        content.set_border_width(24)
        grid = Gtk.Grid(column_spacing=14, row_spacing=12)
        content.pack_start(grid, True, True, 0)
        self.name = Gtk.Entry()
        self.name.set_text(existing.name if existing else "Cloud files")
        self.account = Gtk.ComboBoxText()
        for item in accounts:
            self.account.append(item.remote, f"{item.display_name} · {item.provider.label}")
        self.account.set_active_id(existing.account_remote if existing else accounts[0].remote)
        self.local = Gtk.FileChooserButton(title="Choose local folder", action=Gtk.FileChooserAction.SELECT_FOLDER)
        default = Path.home() / ("TuxInDrive" if len(accounts) > 1 else accounts[0].provider.label.replace(" ", ""))
        self.local.set_filename(existing.local_path if existing else str(default))
        self.location = Gtk.ComboBoxText()
        self.location.set_sensitive(False)
        self.location.append("loading", "Loading cloud locations…")
        self.location.set_active_id("loading")
        self.locations: dict[str, DriveLocation] = {}
        self.folder_tree = CloudFolderTree(
            client,
            self.account.get_active_id(),
            [existing.remote_path] if existing else [""],
        )
        self.account.connect("changed", self._account_changed)
        self.location.connect("changed", self._location_changed)
        self._load_locations()
        self.mode = Gtk.ComboBoxText()
        for mode in SyncMode:
            self.mode.append(mode.value, mode.label)
        self.mode.set_active_id((existing.mode if existing else SyncMode.TWO_WAY).value)
        self.capability_note = Gtk.Label(xalign=0)
        self.capability_note.set_line_wrap(True)
        self.capability_note.get_style_context().add_class("dim-label")
        self._refresh_capabilities(existing.mode if existing else SyncMode.TWO_WAY)
        self.interval = Gtk.SpinButton.new_with_range(1, 1440, 1)
        self.interval.set_value(existing.interval_minutes if existing else 5)
        self.realtime_sync = Gtk.CheckButton(
            label="Sync saved file changes immediately (incremental)"
        )
        self.realtime_sync.set_active(existing.realtime_sync if existing else True)
        self.realtime_sync.set_tooltip_text(
            "Watches local saves and polls provider changes; transfers only changed paths."
        )
        self.block_delta = Gtk.CheckButton(label="Use block-level delta planning for changed files")
        self.block_delta.set_active(existing.block_delta_transfer if existing else True)
        self.block_delta.set_tooltip_text("Direct peer jobs exchange content-addressed changed blocks; cloud backends use their native transfer capabilities.")
        self._refresh_capabilities(existing.mode if existing else SyncMode.TWO_WAY)
        self.conflict = Gtk.ComboBoxText()
        for policy, label in (
            (ConflictPolicy.KEEP_BOTH, "Keep both copies"),
            (ConflictPolicy.NEWER_WINS, "Newer copy wins"),
            (ConflictPolicy.LOCAL_WINS, "Local copy wins"),
            (ConflictPolicy.CLOUD_WINS, "Cloud copy wins"),
        ):
            self.conflict.append(policy.value, label)
        self.conflict.set_active_id(
            (existing.conflict_policy if existing else ConflictPolicy.KEEP_BOTH).value
        )
        self.max_delete = Gtk.SpinButton.new_with_range(0, 100000, 10)
        self.max_delete.set_value(existing.max_delete if existing else 100)
        self.version_history = Gtk.CheckButton(label="Keep replaced and deleted files in local version history")
        self.version_history.set_active(existing.version_history if existing else True)
        self.retention = Gtk.SpinButton.new_with_range(1, 3650, 1)
        self.retention.set_value(existing.version_retention_days if existing else 30)
        self.ransomware = Gtk.CheckButton(label="Pause suspicious deletion, encryption, or mass-change bursts")
        self.ransomware.set_active(existing.ransomware_protection if existing else True)
        self.mass_limit = Gtk.SpinButton.new_with_range(10, 1000000, 10)
        self.mass_limit.set_value(existing.mass_change_limit if existing else 500)
        self.mass_percent = Gtk.SpinButton.new_with_range(1, 100, 1)
        self.mass_percent.set_value(existing.mass_change_percent if existing else 80)
        self.bandwidth = Gtk.Entry()
        self.bandwidth.set_placeholder_text("Optional, e.g. 10M")
        self.bandwidth.set_text(existing.bandwidth_limit if existing else "")
        self.acknowledge_abuse = Gtk.CheckButton(
            label="Allow downloading files Google flags as malware or spam (unsafe)"
        )
        self.acknowledge_abuse.set_active(
            existing.acknowledge_google_abuse if existing else False
        )
        self.acknowledge_abuse.set_tooltip_text(
            "Only enable this if you trust the flagged files. They may contain malware."
        )
        self.excludes = ExceptionRulesEditor(
            existing.exclude_patterns
            if existing
            else [".Trash-*/**", "*.part", "~$*"]
        )
        self.selective_extensions = Gtk.Entry()
        self.selective_extensions.set_placeholder_text("Optional allow-list, e.g. pdf, docx, jpg")
        self.selective_extensions.set_text(
            ", ".join(existing.selective_extensions) if existing else ""
        )
        self.selective_extensions.set_tooltip_text(
            "When set, only files with these extensions are transferred."
        )
        self.selective_max_size = Gtk.SpinButton.new_with_range(0, 1048576, 1)
        self.selective_max_size.set_value(existing.selective_max_size_mb if existing else 0)
        self.selective_max_size.set_tooltip_text("0 means no file-size limit")
        self.selective_max_age = Gtk.SpinButton.new_with_range(0, 36500, 1)
        self.selective_max_age.set_value(existing.selective_max_age_days if existing else 0)
        self.selective_max_age.set_tooltip_text("0 means files are not filtered by age")
        rows = [
            ("Name", self.name),
            ("Cloud account", self.account),
            ("Drive / cloud location", self.location),
            ("Local folder / mount point", self.local),
            ("Cloud folders to synchronize", self.folder_tree),
            ("Mode", self.mode),
            ("Provider capabilities", self.capability_note),
            ("Sync interval (minutes)", self.interval),
            ("Real-time callbacks", self.realtime_sync),
            ("Block-level delta transfer", self.block_delta),
            ("Conflict handling", self.conflict),
            ("Maximum deletions per run", self.max_delete),
            ("Local version history", self.version_history),
            ("Version retention (days)", self.retention),
            ("Ransomware protection", self.ransomware),
            ("Mass-change path limit", self.mass_limit),
            ("Mass-change percentage", self.mass_percent),
            ("Bandwidth limit", self.bandwidth),
            ("Google security warning", self.acknowledge_abuse),
            ("Synchronization exceptions", self.excludes),
            ("Only these extensions", self.selective_extensions),
            ("Maximum file size (MiB; 0 = unlimited)", self.selective_max_size),
            ("Maximum file age (days; 0 = any age)", self.selective_max_age),
        ]
        for row, (label, widget) in enumerate(rows):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Save" if existing else "Add folder", Gtk.ResponseType.OK)
        self.show_all()

    def job(self) -> SyncJob:
        return self.jobs()[0]

    def validation_error(self, message: str) -> None:
        self.folder_tree.status.set_markup(
            f"<span foreground='#c01c28'>{GLib.markup_escape_text(message)}</span>"
        )

    def jobs(self) -> list[SyncJob]:
        filename = self.local.get_filename() or str(Path.home() / "TuxInDrive")
        excluded = self.excludes.rules()
        selections = self.folder_tree.selections()
        values: list[SyncJob] = []
        base_name = self.name.get_text().strip() or "Cloud files"
        for remote_path in selections:
            leaf = Path(remote_path).name if remote_path else "Cloud files"
            multi = len(selections) > 1
            selected_account = next(item for item in self.accounts if item.remote == self.account.get_active_id())
            value = SyncJob(
                name=f"{base_name} · {leaf}" if multi else base_name,
                account_remote=self.account.get_active_id(),
                remote_scope=self._selected_scope(),
                cloud_location_name=self._selected_location_name(),
                local_path=str(Path(filename) / leaf) if multi else filename,
                remote_path=remote_path,
                mode=SyncMode(self.mode.get_active_id()),
                interval_minutes=self.interval.get_value_as_int(),
                realtime_sync=self.realtime_sync.get_active(),
                block_delta_transfer=self.block_delta.get_active(),
                peer_delta=selected_account.provider is Provider.PEER,
                conflict_policy=ConflictPolicy(self.conflict.get_active_id()),
                max_delete=self.max_delete.get_value_as_int(),
                version_history=self.version_history.get_active(),
                version_retention_days=self.retention.get_value_as_int(),
                ransomware_protection=self.ransomware.get_active(),
                mass_change_limit=self.mass_limit.get_value_as_int(),
                mass_change_percent=self.mass_percent.get_value_as_int(),
                bandwidth_limit=self.bandwidth.get_text().strip(),
                acknowledge_google_abuse=self.acknowledge_abuse.get_active(),
                exclude_patterns=excluded,
                selective_extensions=[
                    value.strip().lower().lstrip("*.")
                    for value in self.selective_extensions.get_text().split(",")
                    if value.strip()
                ],
                selective_max_size_mb=self.selective_max_size.get_value_as_int(),
                selective_max_age_days=self.selective_max_age.get_value_as_int(),
            )
            values.append(value)
        if self.existing and values:
            value = values[0]
            value.id = self.existing.id
            value.initialized = self.existing.initialized
            value.enabled = self.existing.enabled
            value.last_run = self.existing.last_run
            value.last_status = self.existing.last_status
            value.last_error = self.existing.last_error
            value.last_error_at = self.existing.last_error_at
            value.last_error_source = self.existing.last_error_source
            value.last_error_log = self.existing.last_error_log
            value.offline_paths = list(self.existing.offline_paths)
            value.online_only_paths = list(self.existing.online_only_paths)
            value.peer_role = self.existing.peer_role
            value.one_time_drop_id = self.existing.one_time_drop_id
            return [value]
        return values

    def _account_changed(self, combo: Gtk.ComboBoxText) -> None:
        remote = combo.get_active_id()
        if remote:
            self._load_locations()
            if hasattr(self, "mode"):
                self._refresh_capabilities()

    def _refresh_capabilities(self, preferred: SyncMode | None = None) -> None:
        remote = self.account.get_active_id()
        account = next((item for item in self.accounts if item.remote == remote), None)
        if not account:
            return
        capabilities = capabilities_for(account.provider)
        selected = preferred or SyncMode(self.mode.get_active_id() or SyncMode.TWO_WAY.value)
        self.mode.remove_all()
        for mode in SyncMode:
            if capabilities.supports_mode(mode):
                self.mode.append(mode.value, mode.label)
        if not capabilities.supports_mode(selected):
            selected = SyncMode.TWO_WAY
        self.mode.set_active_id(selected.value)
        features = [
            "streaming" if capabilities.streaming else "no streaming",
            "change polling" if capabilities.polling else "scheduled scans",
            "hash verification" if capabilities.hashes else "size/time verification",
            "share links" if capabilities.share_links else "no share links",
            "versions" if capabilities.versions else "no provider versions",
        ]
        self.capability_note.set_text(f"{account.provider.label}: {', '.join(features)}. {capabilities.notes}".strip())
        if hasattr(self, "realtime_sync") and account.provider is Provider.PROTON_DRIVE:
            self.realtime_sync.set_active(False)
            self.realtime_sync.set_sensitive(False)
            self.realtime_sync.set_tooltip_text(
                "The official Proton CLI currently supports scheduled reconciliation, not event callbacks."
            )
        elif hasattr(self, "realtime_sync"):
            self.realtime_sync.set_sensitive(True)
        if hasattr(self, "block_delta"):
            self.block_delta.set_sensitive(account.provider is Provider.PEER)

    def _load_locations(self) -> None:
        remote = self.account.get_active_id()
        if not remote:
            return
        account = next(item for item in self.accounts if item.remote == remote)
        self.location.remove_all()
        self.locations = {}
        if account.provider is not Provider.GOOGLE_DRIVE:
            value = DriveLocation("default", account.provider.label, remote)
            self.locations[value.key] = value
            self.location.append(value.key, value.name)
            self.location.set_active_id(value.key)
            self.location.set_sensitive(False)
            self.folder_tree.reset(remote, initial_cloud_paths(self.existing, remote))
            return
        self.location.append("loading", "Loading My Drive and Shared Drives…")
        self.location.set_active_id("loading")
        self.location.set_sensitive(False)
        self.folder_tree.status.set_text("Discovering Google Drive locations…")
        _run_thread(
            self.client.google_drive_locations,
            lambda locations, error, requested=remote: self._locations_loaded(
                requested, locations, error
            ),
            remote,
        )

    def _locations_loaded(
        self,
        requested_remote: str,
        locations: list[DriveLocation] | None,
        error: Exception | None,
    ) -> bool:
        remote = self.account.get_active_id()
        if not remote or remote != requested_remote:
            return False
        if error:
            fallback = DriveLocation("configured", "Configured Google Drive root", remote)
            locations = [fallback]
            self.folder_tree.status.set_markup(
                f"<span foreground='#c01c28'>{GLib.markup_escape_text(str(error))}</span>"
            )
        self.location.remove_all()
        self.locations = {item.key: item for item in locations or []}
        for item in locations or []:
            self.location.append(item.key, item.name)
        preferred = None
        if self.existing:
            if self.existing.remote_scope:
                preferred = next(
                    (
                        item.key
                        for item in locations or []
                        if item.scoped_remote == self.existing.remote_scope
                    ),
                    None,
                )
            else:
                preferred = "configured"
        selected = preferred or (locations[0].key if locations else None)
        if selected:
            self.location.set_active_id(selected)
            self.location.set_sensitive(len(locations or []) > 1)
            location = self.locations[selected]
            initial = initial_cloud_paths(self.existing, remote)
            self.folder_tree.reset(location.scoped_remote, initial)
        return False

    def _location_changed(self, combo: Gtk.ComboBoxText) -> None:
        key = combo.get_active_id()
        location = self.locations.get(key)
        if location:
            self.folder_tree.reset(location.scoped_remote, [""])

    def _selected_scope(self) -> str:
        location = self.locations.get(self.location.get_active_id())
        return location.scoped_remote if location else self.account.get_active_id()

    def _selected_location_name(self) -> str:
        location = self.locations.get(self.location.get_active_id())
        return location.name if location else "Cloud drive"


class GitHubSyncDialog(ResponsiveDialog):
    """Configure a repository job while leaving authentication to system Git."""

    def __init__(
        self,
        parent: Gtk.Window,
        groups: list[FolderGroup],
        account: Account | None = None,
        job: SyncJob | None = None,
    ) -> None:
        super().__init__(
            title="Edit GitHub synchronization" if job else "Synchronize with GitHub",
            transient_for=parent,
            modal=True,
        )
        self.set_default_size(680, 560)
        self.groups = groups
        self.account = account
        self.existing_job = job
        area = self.get_content_area()
        area.set_border_width(24)
        area.set_spacing(12)
        explanation = Gtk.Label(
            label=(
                "TuxInDrive clones, commits, rebases and pushes through system Git. "
                "For private or writable repositories, configure an SSH key or Git credential helper first. "
                "Never place a token in the repository URL."
            ),
            xalign=0,
        )
        explanation.set_line_wrap(True)
        area.pack_start(explanation, False, False, 0)
        grid = Gtk.Grid(column_spacing=14, row_spacing=12)
        area.pack_start(grid, True, True, 0)

        self.name = Gtk.Entry()
        self.name.set_text(job.name if job else "GitHub repository")
        self.repository = Gtk.Entry()
        self.repository.set_placeholder_text("https://github.com/owner/repository.git")
        self.repository.set_text((job.repository_url if job else "") or (account.repository_url if account else ""))
        self.branch = Gtk.Entry()
        self.branch.set_text((job.repository_branch if job else "") or (account.repository_branch if account else "main"))
        self.local = Gtk.FileChooserButton(
            title="Choose an empty folder or existing clone",
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        self.local.set_filename(job.local_path if job else str(Path.home() / "TuxInDrive" / "GitHub"))
        self.mode = Gtk.ComboBoxText()
        for mode in (SyncMode.TWO_WAY, SyncMode.DOWNLOAD_ONLY, SyncMode.UPLOAD_ONLY):
            self.mode.append(mode.value, mode.label)
        self.mode.set_active_id((job.mode if job else SyncMode.TWO_WAY).value)
        self.interval = Gtk.SpinButton.new_with_range(1, 1440, 1)
        self.interval.set_value(job.interval_minutes if job else 5)
        self.author_name = Gtk.Entry()
        self.author_name.set_text((job.git_author_name if job else "") or (account.git_author_name if account else "") or self._git_default("user.name"))
        self.author_email = Gtk.Entry()
        self.author_email.set_text((job.git_author_email if job else "") or (account.git_author_email if account else "") or self._git_default("user.email"))
        self.group = Gtk.ComboBoxText()
        self.group.append("", "Ungrouped")
        for item in groups:
            self.group.append(item.id, item.name)
        self.group.set_active_id(job.group_id if job and any(item.id == job.group_id for item in groups) else "")

        rows = (
            ("Displayed name", self.name),
            ("GitHub repository", self.repository),
            ("Branch", self.branch),
            ("Local folder", self.local),
            ("Mode", self.mode),
            ("Sync interval (minutes)", self.interval),
            ("Commit author name", self.author_name),
            ("Commit author email", self.author_email),
            ("Internal group", self.group),
        )
        for row, (label, widget) in enumerate(rows):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
        warning = Gtk.Label(
            label="Two-way mode automatically commits all changes in this local repository. Rebase conflicts stop safely and remain for manual review.",
            xalign=0,
        )
        warning.set_line_wrap(True)
        warning.get_style_context().add_class("dim-label")
        area.pack_start(warning, False, False, 0)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        save = self.add_button("Save" if job else "Connect and synchronize", Gtk.ResponseType.OK)
        save.get_style_context().add_class("suggested-action")
        self.show_all()

    @staticmethod
    def _git_default(key: str) -> str:
        git = shutil.which("git")
        if not git:
            return ""
        result = subprocess.run(
            [git, "config", "--global", "--get", key],
            capture_output=True, text=True, timeout=10, check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    def values(self) -> tuple[Account, SyncJob]:
        repository = parse_repository_url(self.repository.get_text())
        branch = validate_branch(self.branch.get_text())
        local = self.local.get_filename()
        if not local:
            raise GitHubSyncError("Choose a local folder")
        author_name = self.author_name.get_text().strip()
        author_email = self.author_email.get_text().strip()
        if self.mode.get_active_id() != SyncMode.DOWNLOAD_ONLY.value and (not author_name or "@" not in author_email):
            raise GitHubSyncError("Two-way and upload synchronization require a commit author name and email")
        remote = (
            self.account.remote
            if self.account else
            "github-" + hashlib.sha256(f"{repository.owner}/{repository.name}/{branch}".encode()).hexdigest()[:12]
        )
        account = Account(
            remote=remote,
            provider=Provider.GITHUB,
            display_name=self.name.get_text().strip() or repository.name,
            created_at=self.account.created_at if self.account else datetime.now(timezone.utc).isoformat(),
            repository_url=repository.clone_url,
            repository_branch=branch,
            git_author_name=author_name,
            git_author_email=author_email,
        )
        job = SyncJob(
            account_remote=remote,
            local_path=local,
            name=self.name.get_text().strip() or repository.name,
            cloud_location_name=f"GitHub · {repository.owner}/{repository.name}",
            mode=SyncMode(self.mode.get_active_id()),
            interval_minutes=self.interval.get_value_as_int(),
            realtime_sync=False,
            version_history=False,
            repository_url=repository.clone_url,
            repository_branch=branch,
            git_author_name=author_name,
            git_author_email=author_email,
            group_id=self.group.get_active_id() or "",
        )
        if self.existing_job:
            job.id = self.existing_job.id
            job.enabled = self.existing_job.enabled
            job.initialized = self.existing_job.initialized
            job.last_run = self.existing_job.last_run
            job.last_status = self.existing_job.last_status
            job.last_error = self.existing_job.last_error
            job.last_error_at = self.existing_job.last_error_at
            job.last_error_source = self.existing_job.last_error_source
            job.last_error_log = self.existing_job.last_error_log
        return account, job


class ErrorDetailsDialog(ResponsiveDialog):
    """Show the last failure immediately, without starting an integrity scan."""

    def __init__(self, parent: Gtk.Window, job: SyncJob) -> None:
        super().__init__(title=f"Error details · {job.name}", transient_for=parent, modal=True)
        self.set_default_size(760, 560)
        details = details_for_job(job, cache_root() / "logs")
        area = self.get_content_area()
        area.set_border_width(16)
        area.set_spacing(10)

        heading = Gtk.Label(xalign=0)
        heading.set_markup("<b>Last synchronization error</b>")
        area.pack_start(heading, False, False, 0)
        for title, value in (
            ("Reason", details.reason),
            ("Source file or path", details.source),
            ("Local folder", job.local_path),
            ("Cloud source", job.remote_spec),
            ("Occurred", details.occurred_at),
            ("Job log", details.log_path),
        ):
            label = Gtk.Label(xalign=0)
            label.set_line_wrap(True)
            label.set_selectable(True)
            label.set_markup(
                f"<b>{GLib.markup_escape_text(title)}:</b> "
                f"{GLib.markup_escape_text(value)}"
            )
            area.pack_start(label, False, False, 0)

        excerpt_label = Gtk.Label(label="Recent error output", xalign=0)
        excerpt_label.get_style_context().add_class("dim-label")
        area.pack_start(excerpt_label, False, False, 0)
        excerpt = Gtk.TextView()
        excerpt.set_editable(False)
        excerpt.set_cursor_visible(False)
        excerpt.set_monospace(True)
        excerpt.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        excerpt.get_buffer().set_text(details.excerpt)
        excerpt_scroll = Gtk.ScrolledWindow()
        excerpt_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        excerpt_scroll.set_min_content_height(180)
        excerpt_scroll.add(excerpt)
        area.pack_start(excerpt_scroll, True, True, 0)
        advice = advice_for_error(details.reason, details.excerpt)
        recovery = Gtk.Label(xalign=0)
        recovery.set_line_wrap(True)
        steps = "\n".join(f"• {step}" for step in advice.steps)
        recovery.set_markup(
            f"<b>{GLib.markup_escape_text(advice.title)}</b> "
            f"<small>({GLib.markup_escape_text(advice.code)})</small>\n"
            f"{GLib.markup_escape_text(advice.explanation)}\n"
            f"{GLib.markup_escape_text(steps)}"
        )
        area.pack_start(recovery, False, False, 0)
        self.add_button(tr("close"), Gtk.ResponseType.CLOSE)
        self.connect("response", lambda dialog, _response: dialog.destroy())
        self.show_all()


class RecoveryHistoryDialog(ResponsiveDialog):
    def __init__(self, parent: Gtk.Window, controller: "TuxInDriveApplication", job: SyncJob) -> None:
        super().__init__(title=f"Version history · {job.name}", transient_for=parent, modal=True)
        self.set_default_size(760, 480)
        self.controller, self.job = controller, job
        area = self.get_content_area()
        area.set_border_width(16)
        self.entries = controller.engine.recovery.entries(job.id)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Filter by file path or reason")
        self.search.connect("search-changed", self._refresh)
        area.pack_start(self.search, False, False, 4)
        self.store = Gtk.ListStore(str, str, str, str, object)
        view = Gtk.TreeView(model=self.store)
        for index, title in enumerate(("File", "Saved", "Reason", "Size")):
            view.append_column(Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=index))
        self.view = view
        self.view.get_selection().connect("changed", self._selection_changed)
        scroll = Gtk.ScrolledWindow()
        scroll.add(view)
        area.pack_start(Gtk.Label(label="Select a saved version to restore it locally. The current file is archived first.", xalign=0), False, False, 8)
        area.pack_start(scroll, True, True, 0)
        self.details = Gtk.Label(xalign=0)
        self.details.set_selectable(True)
        self.details.set_line_wrap(True)
        area.pack_start(self.details, False, False, 6)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.add_button("Open saved copy location", 2)
        self.add_button("Restore selected", Gtk.ResponseType.OK)
        self.connect("response", self._response)
        self._refresh()
        self.show_all()

    @staticmethod
    def _size(value: int) -> str:
        amount = float(value)
        for unit in ("B", "KiB", "MiB", "GiB"):
            if amount < 1024 or unit == "GiB":
                return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
            amount /= 1024
        return str(value)

    def _refresh(self, *_args) -> None:
        query = self.search.get_text().strip().lower()
        self.store.clear()
        for entry in self.entries:
            if query and query not in entry.relative_path.lower() and query not in entry.reason.lower():
                continue
            self.store.append([
                entry.relative_path,
                entry.created_at[:19].replace("T", " "),
                entry.reason,
                self._size(entry.size),
                entry,
            ])
        self.details.set_text(
            f"{len(self.store)} saved version(s) shown; retention is {self.job.version_retention_days} days."
        )

    def _selection_changed(self, selection) -> None:
        model, selected = selection.get_selected()
        if selected:
            entry = model[selected][4]
            self.details.set_text(
                f"{entry.relative_path}\nSaved: {entry.created_at}\nReason: {entry.reason}\nSize: {self._size(entry.size)}"
            )

    def _response(self, dialog: Gtk.Dialog, response: int) -> None:
        if response == 2:
            model, selected = self.view.get_selection().get_selected()
            if selected:
                MainWindow._open_path(Path(model[selected][4].stored_path).parent)
            return
        if response != Gtk.ResponseType.OK:
            dialog.destroy()
            return
        model, selected = self.view.get_selection().get_selected()
        if selected:
            entry = model[selected][4]
            try:
                self.controller.engine.recovery.restore(self.job, entry)
                self.job.last_status = f"Restored {entry.relative_path}; synchronization queued"
                self.controller.save()
                self.controller.run_job(self.job)
            except SafetyError as exc:
                self.get_transient_for().message(str(exc), Gtk.MessageType.ERROR)
        dialog.destroy()


class IntegrityDialog(ResponsiveDialog):
    def __init__(self, parent: Gtk.Window, controller: "TuxInDriveApplication", job: SyncJob, conflicts_only: bool = False) -> None:
        super().__init__(title=("Conflict review center" if conflicts_only else "Integrity audit and repair"), transient_for=parent, modal=True)
        self.set_default_size(800, 520)
        self.controller, self.job, self.conflicts_only = controller, job, conflicts_only
        area = self.get_content_area()
        area.set_border_width(16)
        self.status = Gtk.Label(label="Comparing local and remote content…", xalign=0)
        area.pack_start(self.status, False, False, 8)
        self.store = Gtk.ListStore(bool, str, str, str, object)
        view = Gtk.TreeView(model=self.store)
        toggle = Gtk.CellRendererToggle()
        toggle.connect("toggled", lambda _cell, path: self.store.set_value(self.store.get_iter(path), 0, not self.store[path][0]))
        view.append_column(Gtk.TreeViewColumn("Repair", toggle, active=0))
        view.append_column(Gtk.TreeViewColumn("Path", Gtk.CellRendererText(), text=1))
        view.append_column(Gtk.TreeViewColumn("Finding", Gtk.CellRendererText(), text=2))
        choices = Gtk.ListStore(str)
        for choice in ("Keep both", "Use local", "Use cloud/peer", "Skip"):
            choices.append([choice])
        choice_renderer = Gtk.CellRendererCombo()
        choice_renderer.set_property("editable", True)
        choice_renderer.set_property("model", choices)
        choice_renderer.set_property("text-column", 0)
        choice_renderer.set_property("has-entry", False)
        choice_renderer.connect(
            "edited",
            lambda _cell, path, value: self.store.set_value(self.store.get_iter(path), 3, value),
        )
        view.append_column(Gtk.TreeViewColumn("Resolution", choice_renderer, text=3))
        scroll = Gtk.ScrolledWindow()
        scroll.add(view)
        area.pack_start(scroll, True, True, 0)
        self.local_button = self.add_button("Use local versions", 1)
        self.remote_button = self.add_button("Use cloud/peer versions", 2)
        self.apply_button = self.add_button("Apply selected resolutions", 3)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.local_button.set_sensitive(False)
        self.remote_button.set_sensitive(False)
        self.apply_button.set_sensitive(False)
        self.connect("response", self._response)
        self.show_all()
        account = next((item for item in controller.config.accounts if item.remote == job.account_remote), None)
        auditor = IntegrityAuditor(
            controller.engine.rclone_path, controller.engine.recovery, controller.bandwidth
        )
        _run_thread(auditor.audit, self._loaded, job, bool(account and account.provider is Provider.VAULT))

    def _loaded(self, issues: list[AuditIssue] | None, error: Exception | None) -> bool:
        if error:
            self.status.set_text(f"Audit failed safely: {error}")
            return False
        visible = [item for item in (issues or []) if not self.conflicts_only or item.symbol == "*"]
        for issue in visible:
            self.store.append([
                True,
                issue.path,
                issue.description,
                "Keep both" if issue.symbol == "*" else "Skip",
                issue,
            ])
        self.status.set_text(f"{len(visible)} conflict(s) found." if self.conflicts_only else f"Audit complete: {len(visible)} difference(s) require review.")
        self.local_button.set_sensitive(bool(visible))
        self.remote_button.set_sensitive(bool(visible))
        self.apply_button.set_sensitive(bool(visible))
        return False

    def _response(self, dialog: Gtk.Dialog, response: int) -> None:
        if response not in (1, 2, 3):
            dialog.destroy()
            return
        selected = [row for row in self.store if row[0]]
        issues = [row[4] for row in selected]
        if not issues:
            return
        if response == 3:
            mapping = {
                "Use local": "local",
                "Use cloud/peer": "remote",
                "Keep both": "keep_both",
            }
            resolutions = [
                (row[4], mapping[row[3]]) for row in selected if row[3] in mapping
            ]
            if not resolutions:
                return
            summary = f"Apply the selected resolution to {len(resolutions)} item(s)?"
        else:
            winner = "local" if response == 1 else "remote"
            resolutions = [(issue, winner) for issue in issues]
            summary = f"Repair {len(issues)} item(s) using {winner} as the authoritative side?"
        confirm = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.OK_CANCEL, text=summary)
        accepted = confirm.run() == Gtk.ResponseType.OK
        confirm.destroy()
        if not accepted:
            return
        auditor = IntegrityAuditor(
            self.controller.engine.rclone_path,
            self.controller.engine.recovery,
            self.controller.bandwidth,
        )
        _run_thread(self._repair_resolutions, self._repaired, auditor, resolutions)

    def _repair_resolutions(
        self,
        auditor: IntegrityAuditor,
        resolutions: list[tuple[AuditIssue, str]],
    ) -> int:
        return sum(
            auditor.repair(self.job, [issue], winner)
            for issue, winner in resolutions
        )

    def _repaired(self, count: int | None, error: Exception | None) -> bool:
        if error:
            self.status.set_text(f"Repair stopped safely: {error}")
        else:
            self.status.set_text(f"Repair complete: {count} item(s). Run Verify again to confirm integrity.")
            self.local_button.set_sensitive(False)
            self.remote_button.set_sensitive(False)
            self.apply_button.set_sensitive(False)
        return False


class VaultDialog(ResponsiveDialog):
    def __init__(self, parent: Gtk.Window, controller: "TuxInDriveApplication") -> None:
        super().__init__(title="Create encrypted cloud vault", transient_for=parent, modal=True)
        self.controller = controller
        area = self.get_content_area()
        area.set_border_width(20)
        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        area.pack_start(grid, True, True, 0)
        self.remote, self.name, self.folder = Gtk.Entry(), Gtk.Entry(), Gtk.Entry()
        self.remote.set_text(f"vault-{uuid.uuid4().hex[:6]}")
        self.name.set_text("Encrypted vault")
        self.folder.set_text("TuxInDriveEncrypted")
        self.base = Gtk.ComboBoxText()
        bases = [item for item in controller.config.accounts if item.provider not in {Provider.PEER, Provider.VAULT}]
        for item in bases:
            self.base.append(item.remote, f"{item.display_name} · {item.provider.label}")
        if bases:
            self.base.set_active(0)
        self.password, self.confirm, self.salt = Gtk.Entry(), Gtk.Entry(), Gtk.Entry()
        for entry in (self.password, self.confirm, self.salt):
            entry.set_visibility(False)
        self.mode = Gtk.ComboBoxText()
        for value, label in (("standard", "Encrypt file and folder names"), ("obfuscate", "Obfuscate names"), ("off", "Keep names visible")):
            self.mode.append(value, label)
        self.mode.set_active_id("standard")
        rows = (("Vault key", self.remote), ("Display name", self.name), ("Storage account", self.base), ("Dedicated encrypted folder", self.folder), ("Vault password", self.password), ("Confirm password", self.confirm), ("Optional filename salt", self.salt), ("Filename protection", self.mode))
        for row, (label, widget) in enumerate(rows):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
        warning = Gtk.Label(label="Keep the password and optional salt in a password manager. TuxInDrive cannot recover them. Never point a vault at a folder containing unencrypted files.", xalign=0)
        warning.set_line_wrap(True)
        grid.attach(warning, 0, len(rows), 2, 1)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Create vault", Gtk.ResponseType.OK)
        self.show_all()

    def create(self) -> Account:
        if self.password.get_text() != self.confirm.get_text():
            raise RcloneError("The vault passwords do not match")
        base = self.base.get_active_id()
        folder = self.folder.get_text().strip().strip("/")
        if not base or not folder or ".." in Path(folder).parts:
            raise RcloneError("Choose a storage account and a safe dedicated folder")
        remote = self.remote.get_text().strip()
        spec = f"{base}:{folder}"
        self.controller.rclone.create_crypt_remote(remote, spec, self.password.get_text(), self.salt.get_text(), self.mode.get_active_id())
        return Account(remote=remote, provider=Provider.VAULT, display_name=self.name.get_text().strip() or "Encrypted vault", vault_base_remote=base, vault_base_path=folder)


class CollaborativeEditorDialog(ResponsiveDialog):
    """Local-first editor whose immutable operation files travel with a shared folder."""

    def __init__(self, parent: Gtk.Window) -> None:
        # Defused XML and the CRDT/ODF stack are optional dialog costs; keep
        # normal startup lean and load them only when collaboration is opened.
        from .collaboration import (
            CollaborationError as _CollaborationError,
            CollaborationWorkspace as _CollaborationWorkspace,
            ODFAdapter as _ODFAdapter,
            document_capability as _document_capability,
        )
        globals().update({
            "CollaborationError": _CollaborationError,
            "CollaborationWorkspace": _CollaborationWorkspace,
            "ODFAdapter": _ODFAdapter,
            "document_capability": _document_capability,
        })
        super().__init__(title="Collaborative document", transient_for=parent, modal=False)
        _set_window_brand_icon(self)
        self.set_default_size(820, 700)
        self.workspace: CollaborationWorkspace | None = None
        self.crdt = None
        self.source: Path | None = None
        self._buffer_loading = False
        self._autosave_pending = False
        self._alive = True
        area = self.get_content_area()
        area.set_border_width(16)
        area.set_spacing(10)
        intro = Gtk.Label(label=(
            "Markdown/text uses an offline CRDT and immutable operation files. Place the document in a TuxInDrive peer/cloud folder to collaborate. "
            "ODT/ODS use experimental structured checkpoints; DOCX/XLSX/PDF remain protected by lock/version/review workflows."
        ), xalign=0)
        intro.set_line_wrap(True)
        area.pack_start(intro, False, False, 0)
        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        self.file = Gtk.FileChooserButton(title="Collaborative document", action=Gtk.FileChooserAction.OPEN)
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Supported documents")
        for pattern in ("*.md", "*.markdown", "*.txt", "*.odt", "*.ods", "*.docx", "*.xlsx", "*.pdf"):
            file_filter.add_pattern(pattern)
        self.file.add_filter(file_filter)
        self.actor = Gtk.Entry()
        self.actor.set_text(platform.node() or "TuxInDrive device")
        self.presence_key = Gtk.Entry()
        self.presence_key.set_visibility(False)
        self.presence_key.set_placeholder_text("Optional shared passphrase; never stored")
        for row, (label, widget) in enumerate((("Document", self.file), ("Device name", self.actor), ("Encrypted presence passphrase", self.presence_key))):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
        area.pack_start(grid, False, False, 0)
        toolbar = Gtk.Box(spacing=8)
        for label, callback in (("Open/import", self._open), ("Merge peer changes", self._merge), ("Export checkpoint", self._export)):
            button = Gtk.Button(label=label)
            button.connect("clicked", callback)
            toolbar.pack_start(button, False, False, 0)
        area.pack_start(toolbar, False, False, 0)
        self.editor = Gtk.TextView()
        self.editor.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.editor.set_monospace(True)
        self.editor.get_buffer().connect("changed", self._schedule_autosave)
        self.editor.get_buffer().connect("mark-set", self._schedule_autosave)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(330)
        scroll.add(self.editor)
        area.pack_start(scroll, True, True, 0)
        review = Gtk.Box(spacing=8)
        self.review_kind = Gtk.ComboBoxText()
        for value in ("comment", "suggestion", "approval", "task", "tracked-change"):
            self.review_kind.append(value, value.replace("-", " ").title())
        self.review_kind.set_active_id("comment")
        self.review_text = Gtk.Entry()
        self.review_text.set_placeholder_text("Comment, suggestion, mention, approval note, or task")
        add_review = Gtk.Button(label="Add review event")
        add_review.connect("clicked", self._review)
        review.pack_start(self.review_kind, False, False, 0)
        review.pack_start(self.review_text, True, True, 0)
        review.pack_start(add_review, False, False, 0)
        area.pack_start(review, False, False, 0)
        self.review_list = Gtk.Label(xalign=0)
        self.review_list.set_line_wrap(True)
        self.review_list.set_selectable(True)
        area.pack_start(self.review_list, False, False, 0)
        self.status = Gtk.Label(label="Choose a document to begin.", xalign=0)
        self.status.set_line_wrap(True)
        area.pack_start(self.status, False, False, 0)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.connect("response", lambda dialog, _response: dialog.destroy())
        self.connect("destroy", lambda _dialog: setattr(self, "_alive", False))
        self.show_all()
        GLib.timeout_add_seconds(2, self._poll_remote)

    def _selected_text(self) -> str:
        buffer = self.editor.get_buffer()
        return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)

    def _show_reviews(self) -> None:
        if not self.workspace:
            return
        rows = [f"{event.kind.title()} · {event.actor}: {event.body or event.status}" for event in self.workspace.reviews()[-8:]]
        self.review_list.set_text("\n".join(rows) if rows else "No review events yet.")

    def _set_editor_text(self, value: str) -> None:
        self._buffer_loading = True
        try:
            self.editor.get_buffer().set_text(value)
        finally:
            self._buffer_loading = False

    def _schedule_autosave(self, *_args) -> None:
        if self._buffer_loading or not self.crdt or not self.workspace or self._autosave_pending:
            return
        self._autosave_pending = True
        GLib.timeout_add(500, self._autosave)

    def _autosave(self) -> bool:
        self._autosave_pending = False
        if not self._alive or not self.crdt or not self.workspace:
            return False
        try:
            self.workspace.persist(self.crdt.replace(self._selected_text()))
            secret = self.presence_key.get_text()
            if secret:
                key = hashlib.scrypt(secret.encode(), salt=self.workspace.document_id.encode(), n=2**14, r=8, p=1, dklen=32)
                buffer = self.editor.get_buffer()
                self.workspace.write_presence(key, buffer.get_iter_at_mark(buffer.get_insert()).get_offset(), buffer.get_iter_at_mark(buffer.get_selection_bound()).get_offset())
        except Exception as exc:
            self.status.set_text(f"Automatic collaboration save failed: {exc}")
        return False

    def _poll_remote(self) -> bool:
        if not self._alive:
            return False
        if self.workspace and self.crdt:
            try:
                merged = self.workspace.load()
                if merged.text != self.crdt.text:
                    self.crdt = merged
                    self._set_editor_text(merged.text)
                    self.status.set_text("Peer changes merged automatically.")
                self._show_reviews()
            except Exception as exc:
                self.status.set_text(f"Collaboration refresh failed: {exc}")
        return True

    def _open(self, _button: Gtk.Button) -> None:
        try:
            filename = self.file.get_filename()
            if not filename:
                raise CollaborationError("Choose a document")
            self.source = Path(filename)
            capability = document_capability(self.source)
            if capability["mode"] == "lock-version-review":
                self._set_editor_text("")
                self.editor.set_editable(False)
                self.status.set_text(f"{self.source.suffix.upper()} uses safe lock/version/review mode; real-time editing is intentionally disabled.")
                return
            self.editor.set_editable(True)
            self.workspace = CollaborationWorkspace(self.source.parent, self.source.name, self.actor.get_text())
            if capability["mode"] == "realtime-crdt":
                self.crdt = self.workspace.import_checkpoint(self.source)
                value = self.crdt.text
                note = "CRDT document ready; collaboration state is separate in the compatibility metadata directory."
            else:
                document = ODFAdapter.load(self.source)
                value = "\n".join(paragraph.text for paragraph in document.paragraphs) if document.kind == "odt" else "\n".join(f"{cell.sheet}!R{cell.row + 1}C{cell.column + 1}: {cell.formula or cell.value}" for cell in document.cells)
                self.crdt = None
                note = "Structured ODF preview ready. Export creates a deterministic snapshot and retains original XML for recovery. " + " ".join(sorted(set(document.warnings)))
            self._set_editor_text(value)
            self.status.set_text(note)
            self._show_reviews()
        except Exception as exc:
            self.status.set_text(str(exc))

    def _merge(self, _button: Gtk.Button) -> None:
        try:
            if not self.workspace or not self.crdt:
                raise CollaborationError("Open a Markdown or text document first")
            local = self._selected_text()
            self.workspace.persist(self.crdt.replace(local))
            self.crdt = self.workspace.load()
            self._set_editor_text(self.crdt.text)
            secret = self.presence_key.get_text()
            if secret:
                key = hashlib.scrypt(secret.encode(), salt=self.workspace.document_id.encode(), n=2**14, r=8, p=1, dklen=32)
                buffer = self.editor.get_buffer()
                cursor = buffer.get_iter_at_mark(buffer.get_insert()).get_offset()
                bound = buffer.get_iter_at_mark(buffer.get_selection_bound()).get_offset()
                self.workspace.write_presence(key, cursor, bound)
                peers = self.workspace.read_presence(key)
                self.status.set_text(f"Merged deterministically. {len(peers)} encrypted presence record(s) active; presence expires and is not audited.")
            else:
                self.status.set_text("Merged deterministically. Presence remains disabled until a shared passphrase is entered.")
        except Exception as exc:
            self.status.set_text(str(exc))

    def _export(self, _button: Gtk.Button) -> None:
        try:
            if not self.source:
                raise CollaborationError("Open a document first")
            capability = document_capability(self.source)
            if capability["mode"] == "realtime-crdt":
                if not self.workspace or not self.crdt:
                    raise CollaborationError("CRDT state is unavailable")
                self.workspace.persist(self.crdt.replace(self._selected_text()))
                self.crdt = self.workspace.load()
                self.workspace.export_checkpoint(self.source, self.crdt)
            elif capability["mode"] == "structured-experimental":
                document = ODFAdapter.load(self.source)
                lines = self._selected_text().splitlines()
                if document.kind == "odt":
                    for paragraph, value in zip(document.paragraphs, lines):
                        paragraph.text = value
                ODFAdapter.export(document, self.source)
            else:
                raise CollaborationError("This format uses lock/version/review and cannot be exported by the real-time editor")
            self.status.set_text("Checkpoint exported successfully; ordinary editors can open the file.")
        except Exception as exc:
            self.status.set_text(str(exc))

    def _review(self, _button: Gtk.Button) -> None:
        try:
            if not self.workspace:
                raise CollaborationError("Open a collaborative document first")
            buffer = self.editor.get_buffer()
            start, end = buffer.get_selection_bounds() if buffer.get_has_selection() else (buffer.get_iter_at_mark(buffer.get_insert()), buffer.get_iter_at_mark(buffer.get_insert()))
            self.workspace.add_review(self.review_kind.get_active_id() or "comment", self.review_text.get_text().strip(), start.get_offset(), end.get_offset())
            self.review_text.set_text("")
            self._show_reviews()
            self.status.set_text("Workspace review event added for synchronization.")
        except Exception as exc:
            self.status.set_text(str(exc))


class PeerSharingDialog(ResponsiveDialog):
    """Manage direct encrypted folders and connections without an intermediary."""

    def __init__(self, parent: Gtk.Window, controller: "TuxInDriveApplication") -> None:
        super().__init__(title="Peer-to-peer shared folders", transient_for=parent, modal=True)
        _set_window_brand_icon(self)
        self.set_default_size(760, 680)
        self.controller = controller
        self.loaded_invitation: PeerInvitation | None = None
        area = self.get_content_area()
        area.set_border_width(20)
        area.set_spacing(12)
        explanation = Gtk.Label(
            label=(
                "TuxInDrive connects computers over encrypted, host-key-pinned SFTP. "
                "Files are never stored by an intermediary. Use direct addressing, automatic "
                "router mapping, or the optional ciphertext-only reverse relay."
            ),
            xalign=0,
        )
        explanation.set_line_wrap(True)
        area.pack_start(explanation, False, False, 0)
        try:
            identity_key = controller.peers.identity_public_key()
        except Exception as exc:
            identity_key = f"Key generation failed: {exc}"
        identity = Gtk.Expander(label="This computer’s public identity key")
        identity_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        identity_value = Gtk.Entry()
        identity_value.set_text(identity_key)
        identity_value.set_editable(False)
        copy_identity = Gtk.Button(label="Copy public key")
        copy_identity.connect(
            "clicked",
            lambda _button: Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(identity_key, -1),
        )
        identity_box.pack_start(identity_value, False, False, 0)
        identity_box.pack_start(copy_identity, False, False, 0)
        identity.add(identity_box)
        area.pack_start(identity, False, False, 0)

        self.notebook = Gtk.Notebook()
        self.notebook.append_page(self._host_page(), Gtk.Label(label="Share a folder"))
        self.notebook.append_page(self._client_page(), Gtk.Label(label="Connect to a peer"))
        self.notebook.append_page(self._lan_page(), Gtk.Label(label="Find on LAN"))
        self.notebook.append_page(self._collaboration_page(), Gtk.Label(label="Collaborate"))
        area.pack_start(self.notebook, True, True, 0)
        self.status = Gtk.Label(xalign=0)
        self.status.set_line_wrap(True)
        area.pack_start(self.status, False, False, 0)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.connect("response", lambda dialog, _response: dialog.destroy())
        self.show_all()
        self._pending_snapshot: tuple[tuple[str, ...], ...] = ()
        self._reload_share_choices()
        self._reload_connection_choices()
        self._pending_timer = GLib.timeout_add_seconds(2, self._refresh_pending)
        self.connect("destroy", self._stop_pending_refresh)

    @staticmethod
    def _folder_button(title: str) -> Gtk.FileChooserButton:
        chooser = Gtk.FileChooserButton(title=title, action=Gtk.FileChooserAction.SELECT_FOLDER)
        chooser.set_create_folders(True)
        return chooser

    @staticmethod
    def _row(grid: Gtk.Grid, row: int, label: str, widget: Gtk.Widget) -> None:
        grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
        grid.attach(widget, 1, row, 1, 1)

    def _host_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.set_border_width(12)
        self.share_choice = Gtk.ComboBoxText()
        self.share_choice.connect("changed", self._load_share)
        self.share_name = Gtk.Entry()
        self.share_folder = self._folder_button("Folder to share directly")
        self.share_host = Gtk.Entry()
        self.share_host.set_placeholder_text("Public/LAN IP or DNS name")
        self.share_port = Gtk.SpinButton.new_with_range(1024, 65535, 1)
        self.share_port.set_value(2022)
        self.peer_store = Gtk.ListStore(bool, str, str, str)
        peer_view = Gtk.TreeView(model=self.peer_store)
        enabled = Gtk.CellRendererToggle()
        enabled.connect("toggled", lambda _cell, path: self.peer_store.set_value(self.peer_store.get_iter(path), 0, not self.peer_store[path][0]))
        peer_view.append_column(Gtk.TreeViewColumn("Enabled", enabled, active=0))
        peer_view.append_column(Gtk.TreeViewColumn("Device", Gtk.CellRendererText(), text=1))
        peer_view.append_column(Gtk.TreeViewColumn("Public key", Gtk.CellRendererText(), text=2))
        peer_view.append_column(Gtk.TreeViewColumn("Role", Gtk.CellRendererText(), text=3))
        self.peer_view = peer_view
        peer_scroll = Gtk.ScrolledWindow()
        peer_scroll.set_min_content_height(115)
        peer_scroll.add(peer_view)
        self.peer_name = Gtk.Entry()
        self.peer_name.set_placeholder_text("Device name")
        self.share_peer_key = Gtk.Entry()
        self.share_peer_key.set_placeholder_text("Peer’s ssh-ed25519 public key")
        self.peer_role = Gtk.ComboBoxText()
        for role in PeerRole:
            self.peer_role.append(role.value, role.label)
        self.peer_role.set_active_id(PeerRole.READ_WRITE.value)
        peer_add = Gtk.Button(label="Authorize device")
        peer_add.connect("clicked", self._add_authorized_peer)
        peer_remove = Gtk.Button(label="Revoke selected")
        peer_remove.connect("clicked", self._remove_authorized_peer)
        peer_set_role = Gtk.Button(label="Set selected role")
        peer_set_role.connect("clicked", self._set_authorized_peer_role)
        peer_editor = Gtk.Box(spacing=6)
        peer_editor.pack_start(self.peer_name, False, False, 0)
        peer_editor.pack_start(self.share_peer_key, True, True, 0)
        peer_editor.pack_start(self.peer_role, False, False, 0)
        peer_editor.pack_start(peer_add, False, False, 0)
        peer_editor.pack_start(peer_set_role, False, False, 0)
        peer_editor.pack_start(peer_remove, False, False, 0)
        peer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        peer_box.pack_start(peer_scroll, True, True, 0)
        peer_box.pack_start(peer_editor, False, False, 0)
        self.pending_store = Gtk.ListStore(str, str, str, object)
        self.pending_view = Gtk.TreeView(model=self.pending_store)
        for index, title in enumerate(("Pending device", "Fingerprint", "Address")):
            self.pending_view.append_column(Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=index))
        pending_scroll = Gtk.ScrolledWindow()
        pending_scroll.set_min_content_height(90)
        pending_scroll.add(self.pending_view)
        pending_actions = Gtk.Box(spacing=6)
        approve = Gtk.Button(label="Approve selected request")
        approve.connect("clicked", self._approve_pending_peer)
        reject = Gtk.Button(label="Reject")
        reject.connect("clicked", self._reject_pending_peer)
        refresh = Gtk.Button(label="Refresh requests")
        refresh.connect("clicked", lambda _button: self._refresh_pending(force=True))
        for button in (approve, reject, refresh):
            pending_actions.pack_start(button, False, False, 0)
        pending_label = Gtk.Label(label="People waiting for your approval", xalign=0)
        pending_label.set_tooltip_text("Compare the fingerprint with the person before approving access")
        peer_box.pack_start(pending_label, False, False, 4)
        peer_box.pack_start(pending_scroll, True, True, 0)
        peer_box.pack_start(pending_actions, False, False, 0)
        self.share_discovery = Gtk.CheckButton(label="Advertise this share on the local network")
        self.share_discovery.set_active(True)
        self.share_lease_minutes = Gtk.SpinButton.new_with_range(1, 1440, 1)
        self.share_lease_minutes.set_value(10)
        self.share_nat = Gtk.CheckButton(label="Automatically request UPnP/NAT-PMP port mapping")
        self.share_nat.set_active(False)
        self.transport_policy = Gtk.ComboBoxText()
        self.transport_policy.append(PeerTransportPolicy.AUTO.value, "Automatic (direct, then configured alternatives)")
        self.transport_policy.append(PeerTransportPolicy.DIRECT_ONLY.value, "Direct only")
        self.transport_policy.append(PeerTransportPolicy.TOR_ONLY.value, "Tor only (fail closed)")
        self.transport_policy.set_active_id(PeerTransportPolicy.AUTO.value)
        self.onion_enabled = Gtk.CheckButton(label="Publish a Tor v3 Onion Service")
        self.onion_persistent = Gtk.CheckButton(label="Keep the Onion address across restarts")
        self.onion_persistent.set_active(True)
        self.onion_client_auth = Gtk.CheckButton(label="Require per-device Onion client authorization")
        self.no_relay = Gtk.CheckButton(label="Never use a relay")
        self.no_public_ip = Gtk.CheckButton(label="Do not discover or advertise a public IP")
        self.never_cloud = Gtk.CheckButton(label="Never use provider cloud for this workspace")
        self.never_cloud.set_active(True)
        self.tor_bridges = Gtk.Entry()
        self.tor_bridges.set_placeholder_text("Optional bridge line; kept out of invitations and logs")
        self.tor_transport_plugin = Gtk.Entry()
        self.tor_transport_plugin.set_placeholder_text("Optional, e.g. obfs4 exec /usr/bin/obfs4proxy")
        self.relay_host = Gtk.Entry()
        self.relay_host.set_placeholder_text("Optional SSH relay host (forwards ciphertext only)")
        self.relay_user = Gtk.Entry()
        self.relay_user.set_placeholder_text("Relay SSH user")
        self.relay_ssh_port = Gtk.SpinButton.new_with_range(1, 65535, 1)
        self.relay_ssh_port.set_value(22)
        self.relay_public_port = Gtk.SpinButton.new_with_range(0, 65535, 1)
        self.relay_public_port.set_value(0)
        self.drop_expiry = Gtk.SpinButton.new_with_range(1, 168, 1)
        self.drop_expiry.set_value(24)
        grid = Gtk.Grid(column_spacing=12, row_spacing=9)
        self._row(grid, 0, "Saved share", self.share_choice)
        self._row(grid, 1, "Folder name", self.share_name)
        self._row(grid, 2, "Folder to share", self.share_folder)
        self._row(grid, 3, "People and approval requests", peer_box)
        self._row(grid, 4, "Visible on this local network", self.share_discovery)
        page.pack_start(grid, False, False, 0)

        advanced_grid = Gtk.Grid(column_spacing=12, row_spacing=9)
        self._row(advanced_grid, 0, "Address peers use", self.share_host)
        self._row(advanced_grid, 1, "TCP port", self.share_port)
        self._row(advanced_grid, 2, "Edit lease duration (minutes)", self.share_lease_minutes)
        self._row(advanced_grid, 3, "NAT traversal", self.share_nat)
        self._row(advanced_grid, 4, "No-storage relay host", self.relay_host)
        self._row(advanced_grid, 5, "Relay SSH user", self.relay_user)
        self._row(advanced_grid, 6, "Relay SSH port", self.relay_ssh_port)
        self._row(advanced_grid, 7, "Relay public forwarding port", self.relay_public_port)
        self._row(advanced_grid, 8, "Transport policy", self.transport_policy)
        self._row(advanced_grid, 9, "Tor v3 service", self.onion_enabled)
        self._row(advanced_grid, 10, "Onion identity", self.onion_persistent)
        self._row(advanced_grid, 11, "Onion authorization", self.onion_client_auth)
        self._row(advanced_grid, 12, "Fail-closed restrictions", self.no_relay)
        self._row(advanced_grid, 13, "IP privacy", self.no_public_ip)
        self._row(advanced_grid, 14, "Cloud isolation", self.never_cloud)
        self._row(advanced_grid, 15, "Tor bridge profile", self.tor_bridges)
        self._row(advanced_grid, 16, "Pluggable transport", self.tor_transport_plugin)
        advanced = Gtk.Expander(label="Advanced network and privacy settings")
        advanced.add(advanced_grid)
        page.pack_start(advanced, False, False, 0)
        note = Gtk.Label(
            label=(
                "For local collaboration, select a folder and click Share this folder. TuxInDrive advertises only its name and host fingerprint; "
                "files remain inaccessible until you approve a device. Use the advanced settings only for remote or Tor connections."
            ),
            xalign=0,
        )
        note.set_line_wrap(True)
        page.pack_start(note, False, False, 0)
        buttons = Gtk.Box(spacing=8)
        save = Gtk.Button(label="Share this folder")
        save.connect("clicked", self._save_share)
        stop = Gtk.Button(label="Stop")
        stop.connect("clicked", self._stop_share)
        invitation = Gtk.Button(label="Copy invitation")
        invitation.connect("clicked", self._copy_invitation)
        qr = Gtk.Button(label="Show invitation QR")
        qr.connect("clicked", self._show_invitation_qr)
        file_drop = Gtk.Button(label="Create one-time file drop")
        file_drop.set_tooltip_text("Uses the device name/public key fields and creates an expiring upload-only inbox")
        file_drop.connect("clicked", self._create_file_drop)
        delete = Gtk.Button(label="Delete")
        delete.connect("clicked", self._delete_share)
        buttons.pack_start(Gtk.Label(label="Drop expires (hours):"), False, False, 0)
        buttons.pack_start(self.drop_expiry, False, False, 0)
        for button in (save, stop, invitation, qr, file_drop, delete):
            buttons.pack_start(button, False, False, 0)
        page.pack_start(buttons, False, False, 0)
        return page

    def _client_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.set_border_width(12)
        self.connection_choice = Gtk.ComboBoxText()
        self.connection_choice.connect("changed", self._load_connection)
        self.connection_name = Gtk.Entry()
        self.connection_host = Gtk.Entry()
        self.connection_port = Gtk.SpinButton.new_with_range(1024, 65535, 1)
        self.connection_port.set_value(2022)
        self.connection_host_key = Gtk.Entry()
        self.connection_host_key.set_placeholder_text("Host key from the invitation")
        self.connection_folder = self._folder_button("Local synchronized folder")
        self.connection_lease = Gtk.SpinButton.new_with_range(1, 1440, 1)
        self.connection_lease.set_value(10)
        grid = Gtk.Grid(column_spacing=12, row_spacing=9)
        self._row(grid, 0, "Saved connection", self.connection_choice)
        self._row(grid, 1, "Display name", self.connection_name)
        self._row(grid, 2, "Peer IP / DNS", self.connection_host)
        self._row(grid, 3, "Peer TCP port", self.connection_port)
        self._row(grid, 4, "Peer host public key", self.connection_host_key)
        self._row(grid, 5, "My local folder", self.connection_folder)
        self._row(grid, 6, "Cooperative edit lease (minutes)", self.connection_lease)
        page.pack_start(grid, False, False, 0)
        invitation_label = Gtk.Label(label="Paste invitation from the sharing computer", xalign=0)
        page.pack_start(invitation_label, False, False, 0)
        self.invitation_text = Gtk.TextView()
        self.invitation_text.set_monospace(True)
        invitation_scroll = Gtk.ScrolledWindow()
        invitation_scroll.set_min_content_height(100)
        invitation_scroll.add(self.invitation_text)
        page.pack_start(invitation_scroll, True, True, 0)
        buttons = Gtk.Box(spacing=8)
        load = Gtk.Button(label="Load invitation")
        load.connect("clicked", self._load_invitation)
        scan = Gtk.Button(label="Import QR image")
        scan.connect("clicked", self._scan_qr)
        connect = Gtk.Button(label="Save and connect")
        connect.connect("clicked", self._save_connection)
        delete = Gtk.Button(label="Remove connection")
        delete.connect("clicked", self._delete_connection)
        for button in (load, scan, connect, delete):
            buttons.pack_start(button, False, False, 0)
        page.pack_start(buttons, False, False, 0)
        return page

    def _lan_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.set_border_width(12)
        label = Gtk.Label(label=(
            "Choose a nearby folder and request access. The owner sees this device's fingerprint and must approve it before any files are exposed. "
            "After approval, scan again and connect."
        ), xalign=0)
        label.set_line_wrap(True)
        page.pack_start(label, False, False, 0)
        self.discovery_store = Gtk.ListStore(str, str, str, object)
        self.discovery_view = Gtk.TreeView(model=self.discovery_store)
        for index, title in enumerate(("Share", "Address", "Host-key fingerprint")):
            self.discovery_view.append_column(Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=index))
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.discovery_view)
        page.pack_start(scroll, True, True, 0)
        buttons = Gtk.Box(spacing=8)
        find = Gtk.Button(label="Scan local network")
        find.connect("clicked", self._discover_lan)
        use = Gtk.Button(label="Request access / connect")
        use.connect("clicked", self._use_discovered)
        buttons.pack_start(find, False, False, 0)
        buttons.pack_start(use, False, False, 0)
        page.pack_start(buttons, False, False, 0)
        return page

    def _collaboration_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page.set_border_width(16)
        description = Gtk.Label(label=(
            "Edit Markdown and text with offline CRDT convergence, encrypted ephemeral presence, comments, suggestions, approvals and tasks. "
            "Collaboration metadata is synchronized by the same shared folder while exported files remain compatible with ordinary editors."
        ), xalign=0)
        description.set_line_wrap(True)
        page.pack_start(description, False, False, 0)
        open_editor = Gtk.Button(label="Open collaborative editor")
        open_editor.connect("clicked", lambda _button: CollaborativeEditorDialog(self))
        page.pack_start(open_editor, False, False, 0)
        formats = Gtk.Label(label=(
            "Markdown/TXT: real-time and offline · ODT/ODS: structured experimental checkpoints with recovery XML · "
            "DOCX/XLSX/PDF: edit leases, version history and review only"
        ), xalign=0)
        formats.set_line_wrap(True)
        page.pack_start(formats, False, False, 0)
        return page

    def _reload_share_choices(self, selected: str = "new") -> None:
        self.share_choice.remove_all()
        self.share_choice.append("new", "New shared folder")
        for share in self.controller.config.peer_shares:
            if share.id in self.controller.peers.running_shares:
                state = "running"
            elif share.id in self.controller.peers.shared_ids:
                state = "waiting for approval"
            else:
                state = "stopped"
            self.share_choice.append(share.id, f"{share.name} · {state}")
        self.share_choice.set_active_id(selected)

    def _selected_share(self) -> PeerShare | None:
        share_id = self.share_choice.get_active_id()
        return next((item for item in self.controller.config.peer_shares if item.id == share_id), None)

    def _load_share(self, _combo: Gtk.ComboBoxText) -> None:
        share = self._selected_share()
        self.share_name.set_text(share.name if share else "Peer shared folder")
        self.share_host.set_text(share.advertised_host if share else "")
        self.share_port.set_value(share.port if share else 2022)
        self.peer_store.clear()
        if share:
            peers = share.authorized_peers or ([AuthorizedPeer("Legacy peer", share.allowed_peer_key)] if share.allowed_peer_key else [])
            for peer in peers:
                self.peer_store.append([peer.enabled, peer.name, peer.public_key, peer.role.label])
        self.peer_name.set_text("")
        self.share_peer_key.set_text("")
        self.share_discovery.set_active(share.lan_discovery if share else True)
        self.share_lease_minutes.set_value(share.lease_minutes if share else 10)
        self.share_nat.set_active(share.nat_traversal if share else False)
        self.relay_host.set_text(share.relay_host if share else "")
        self.relay_user.set_text(share.relay_user if share else "")
        self.relay_ssh_port.set_value(share.relay_ssh_port if share else 22)
        self.relay_public_port.set_value(share.relay_public_port if share else 0)
        self.transport_policy.set_active_id(share.transport_policy.value if share else PeerTransportPolicy.AUTO.value)
        self.onion_enabled.set_active(share.onion_enabled if share else False)
        self.onion_persistent.set_active(share.onion_persistent if share else True)
        self.onion_client_auth.set_active(share.onion_client_auth if share else False)
        self.no_relay.set_active(share.no_relay if share else False)
        self.no_public_ip.set_active(share.no_public_ip_discovery if share else False)
        self.never_cloud.set_active(share.never_use_provider_cloud if share else True)
        self.tor_bridges.set_text(share.tor_bridge_lines[0] if share and share.tor_bridge_lines else "")
        self.tor_transport_plugin.set_text(share.tor_pluggable_transports[0] if share and share.tor_pluggable_transports else "")
        if share and Path(share.local_path).is_dir():
            self.share_folder.set_filename(str(Path(share.local_path).expanduser()))
        self._refresh_pending(force=True)

    def _stop_pending_refresh(self, _dialog: Gtk.Dialog) -> None:
        timer = getattr(self, "_pending_timer", 0)
        if timer:
            GLib.source_remove(timer)
            self._pending_timer = 0

    def _refresh_pending(self, force: bool = False) -> bool:
        share = self._selected_share()
        requests = self.controller.peers.pending_requests(share.id if share else "") if share else []
        snapshot = tuple((item.id, item.device_name, item.fingerprint, item.source_host) for item in requests)
        if force or snapshot != self._pending_snapshot:
            self.pending_store.clear()
            for request in requests:
                self.pending_store.append([request.device_name, request.fingerprint, request.source_host, request])
            self._pending_snapshot = snapshot
        return bool(self.get_visible())

    def _selected_pending_request(self):
        model, selected = self.pending_view.get_selection().get_selected()
        return model[selected][3] if selected else None

    def _approve_pending_peer(self, _button: Gtk.Button) -> None:
        request = self._selected_pending_request()
        if request is None:
            self._set_status("Select a pending device first.", True)
            return
        share = next((item for item in self.controller.config.peer_shares if item.id == request.share_id), None)
        if share is None:
            self.controller.peers.dismiss_request(request.id)
            self._refresh_pending(force=True)
            self._set_status("That shared folder no longer exists.", True)
            return
        try:
            added_peer = None
            if not any(item.public_key == request.public_key for item in share.authorized_peers):
                role = PeerRole(self.peer_role.get_active_id() or PeerRole.READ_WRITE.value)
                added_peer = AuthorizedPeer(request.device_name, request.public_key, role=role)
                share.authorized_peers.append(added_peer)
            self.controller.peers.stop(share.id)
            try:
                self.controller.peers.start(share)
            except Exception:
                if added_peer is not None:
                    share.authorized_peers.remove(added_peer)
                try:
                    self.controller.peers.start(share)
                except Exception:
                    pass
                raise
            self.controller.peers.dismiss_request(request.id)
            share.last_status = f"Shared with {len([item for item in share.authorized_peers if item.enabled])} approved device(s)"
            self.controller.save()
            self._load_share(self.share_choice)
            self._set_status(
                f"Approved {request.device_name} ({request.fingerprint}). They can rescan and connect now.",
                False,
            )
        except Exception as exc:
            self._set_status(str(exc), True)

    def _reject_pending_peer(self, _button: Gtk.Button) -> None:
        request = self._selected_pending_request()
        if request is None:
            self._set_status("Select a pending device first.", True)
            return
        self.controller.peers.dismiss_request(request.id)
        self._refresh_pending(force=True)
        self._set_status(f"Rejected the request from {request.device_name}.", False)

    def _save_share(self, _button: Gtk.Button) -> None:
        try:
            folder = self.share_folder.get_filename()
            if not folder:
                raise PeerError("Select the local folder to share")
            share = self._selected_share()
            name = self.share_name.get_text().strip() or "Peer shared folder"
            policy = PeerTransportPolicy(self.transport_policy.get_active_id() or PeerTransportPolicy.AUTO.value)
            advertised_host = self.share_host.get_text().strip()
            if not self.no_public_ip.get_active() and policy is not PeerTransportPolicy.TOR_ONLY:
                advertised_host = validate_host(advertised_host or local_network_address())
            port = validate_port(self.share_port.get_value_as_int())
            roles = {role.label: role for role in PeerRole}
            previous_auth = {item.public_key: item.onion_client_public_key for item in (share.authorized_peers if share else [])}
            authorized_peers = [AuthorizedPeer(row[1], normalize_public_key(row[2]), row[0], role=roles.get(row[3], PeerRole.READ_WRITE), onion_client_public_key=previous_auth.get(row[2], "")) for row in self.peer_store]
            if share is None:
                share = PeerShare("", folder, "")
                self.controller.config.peer_shares.append(share)
            else:
                self.controller.peers.stop(share.id)
            share.name = name
            share.local_path = folder
            share.advertised_host = advertised_host
            share.port = port
            share.allowed_peer_key = ""
            share.authorized_peers = authorized_peers
            share.lan_discovery = self.share_discovery.get_active()
            share.lease_minutes = self.share_lease_minutes.get_value_as_int()
            share.nat_traversal = self.share_nat.get_active()
            share.relay_host = self.relay_host.get_text().strip()
            share.relay_user = self.relay_user.get_text().strip()
            share.relay_ssh_port = self.relay_ssh_port.get_value_as_int()
            share.relay_public_port = self.relay_public_port.get_value_as_int()
            share.transport_policy = policy
            share.onion_enabled = self.onion_enabled.get_active()
            share.onion_persistent = self.onion_persistent.get_active()
            share.onion_client_auth = self.onion_client_auth.get_active()
            share.no_relay = self.no_relay.get_active()
            share.no_public_ip_discovery = self.no_public_ip.get_active()
            share.never_use_provider_cloud = self.never_cloud.get_active()
            bridge = self.tor_bridges.get_text().strip()
            share.tor_bridge_lines = [bridge] if bridge else []
            plugin = self.tor_transport_plugin.get_text().strip()
            share.tor_pluggable_transports = [plugin] if plugin else []
            share.enabled = True
            self.controller.peers.start(share)
            if not any(item.enabled for item in authorized_peers):
                share.last_status = "Advertised on LAN; waiting for approval requests"
            else:
                share.last_status = f"Listening at {share.onion_address}" if share.onion_enabled else f"Listening on TCP {share.port}"
            self.controller.save()
            self._reload_share_choices(share.id)
            self._set_status(
                "Folder is visible on the local network. Approve a person when their request appears below."
                if not any(item.enabled for item in authorized_peers)
                else "Direct encrypted share is running.",
                False,
            )
        except Exception as exc:
            self._set_status(str(exc), True)

    def _add_authorized_peer(self, _button: Gtk.Button) -> None:
        try:
            name = self.peer_name.get_text().strip() or f"Peer {len(self.peer_store) + 1}"
            key = normalize_public_key(self.share_peer_key.get_text())
            if any(row[2] == key for row in self.peer_store):
                raise PeerError("That public key is already authorized")
            role = PeerRole(self.peer_role.get_active_id() or PeerRole.READ_WRITE.value)
            self.peer_store.append([True, name, key, role.label])
            self.peer_name.set_text("")
            self.share_peer_key.set_text("")
            self._set_status(f"{name} added. Save and start to apply authorization.", False)
        except Exception as exc:
            self._set_status(str(exc), True)

    def _selected_peer_role(self) -> PeerRole:
        model, selected = self.peer_view.get_selection().get_selected()
        if not selected:
            return PeerRole.READ_WRITE
        return next((role for role in PeerRole if role.label == model[selected][3]), PeerRole.READ_WRITE)

    def _create_file_drop(self, _button: Gtk.Button) -> None:
        share = self._selected_share()
        if not share:
            self._set_status("Save and start the shared folder first.", True)
            return
        try:
            name = self.peer_name.get_text().strip() or "One-time sender"
            key = normalize_public_key(self.share_peer_key.get_text())
            expiry = datetime.now(timezone.utc) + timedelta(hours=self.drop_expiry.get_value_as_int())
            drop = OneTimeDrop(name, key, f".tuxdrive-drops/{uuid.uuid4().hex}", expiry.isoformat())
            share.one_time_drops.append(drop)
            self.controller.peers.stop(share.id)
            self.controller.peers.start(share)
            invitation = self.controller.peers.one_time_invitation(share, drop)
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(invitation, -1)
            self.controller.audit.record("peer", "one-time drop created", "success", peer=name, path=drop.inbox_path, detail=f"expires {drop.expires_at}")
            self.controller.save()
            self._set_status("Expiring upload-only invitation copied. It is revoked after the first received file.", False)
        except Exception as exc:
            self._set_status(str(exc), True)

    def _remove_authorized_peer(self, _button: Gtk.Button) -> None:
        model, selected = self.peer_view.get_selection().get_selected()
        if selected:
            name = model[selected][1]
            model.remove(selected)
            self._set_status(f"{name} revoked. Save and start to apply immediately.", False)

    def _set_authorized_peer_role(self, _button: Gtk.Button) -> None:
        model, selected = self.peer_view.get_selection().get_selected()
        if not selected:
            self._set_status("Select an authorized device first.", True)
            return
        role = PeerRole(self.peer_role.get_active_id() or PeerRole.READ_WRITE.value)
        model.set_value(selected, 3, role.label)
        self._set_status(f"Role changed to {role.label}. Save and start, then issue a new invitation.", False)

    def _stop_share(self, _button: Gtk.Button) -> None:
        share = self._selected_share()
        if not share:
            return
        self.controller.peers.stop(share.id)
        share.enabled = False
        share.last_status = "Stopped"
        self.controller.save()
        self._reload_share_choices(share.id)
        self._set_status("Share stopped.", False)

    def _copy_invitation(self, _button: Gtk.Button) -> None:
        share = self._selected_share()
        if not share:
            self._set_status("Save the shared folder first.", True)
            return
        try:
            role = self._selected_peer_role()
            model, selected = self.peer_view.get_selection().get_selected()
            peer_name = model[selected][1] if selected else ""
            value = self.controller.peers.invitation(share, role, peer_name)
            self.controller.save()
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(value, -1)
            self._set_status(f"{role.label} invitation copied. Send it through a trusted channel.", False)
        except Exception as exc:
            self._set_status(str(exc), True)

    def _show_invitation_qr(self, _button: Gtk.Button) -> None:
        share = self._selected_share()
        if not share:
            self._set_status("Save the shared folder first.", True)
            return
        try:
            model, selected = self.peer_view.get_selection().get_selected()
            peer_name = model[selected][1] if selected else ""
            value = self.controller.peers.invitation(share, self._selected_peer_role(), peer_name)
            self.controller.save()
            encoder = shutil.which("qrencode")
            if not encoder:
                raise PeerError("QR support is missing; reinstall the complete TuxInDrive package")
            with tempfile.NamedTemporaryFile(suffix=".png") as image_file:
                result = subprocess.run([encoder, "-o", image_file.name, "-s", "7", "--", value], capture_output=True, text=True, timeout=20, check=False)
                if result.returncode:
                    raise PeerError((result.stderr or "Could not generate QR code").strip())
                dialog = ResponsiveDialog(title=f"Pair with {share.name}", transient_for=self, modal=True)
                dialog.get_content_area().set_border_width(18)
                dialog.get_content_area().pack_start(Gtk.Image.new_from_file(image_file.name), True, True, 0)
                fingerprint = key_fingerprint(self.controller.peers.host_public_key(share))
                detail = Gtk.Label(label=f"Verify this host-key fingerprint on both computers:\n{fingerprint}")
                detail.set_selectable(True)
                dialog.get_content_area().pack_start(detail, False, False, 8)
                dialog.add_button("Close", Gtk.ResponseType.CLOSE)
                dialog.show_all()
                dialog.run()
                dialog.destroy()
        except Exception as exc:
            self._set_status(str(exc), True)

    def _delete_share(self, _button: Gtk.Button) -> None:
        share = self._selected_share()
        if not share:
            return
        self.controller.peers.stop(share.id)
        self.controller.config.peer_shares.remove(share)
        self.controller.save()
        self._reload_share_choices()
        self._set_status("Share definition removed; files were not deleted.", False)

    def _peer_accounts(self) -> list[Account]:
        return [item for item in self.controller.config.accounts if item.provider is Provider.PEER]

    def _reload_connection_choices(self, selected: str = "new") -> None:
        self.connection_choice.remove_all()
        self.connection_choice.append("new", "New peer connection")
        for account in self._peer_accounts():
            self.connection_choice.append(account.remote, account.display_name)
        self.connection_choice.set_active_id(selected)

    def _selected_connection(self) -> Account | None:
        remote = self.connection_choice.get_active_id()
        return next((item for item in self._peer_accounts() if item.remote == remote), None)

    def _load_connection(self, _combo: Gtk.ComboBoxText) -> None:
        account = self._selected_connection()
        self.connection_name.set_text(account.display_name if account else "Peer folder")
        self.connection_host.set_text(account.peer_host if account else "")
        self.connection_port.set_value(account.peer_port if account else 2022)
        self.connection_host_key.set_text(account.peer_host_key if account else "")
        if account:
            job = next((item for item in self.controller.config.jobs if item.account_remote == account.remote), None)
            if job and job.local.is_dir():
                self.connection_folder.set_filename(str(job.local))
            if job:
                self.connection_lease.set_value(job.peer_lease_minutes)

    def _load_invitation(self, _button: Gtk.Button) -> None:
        buffer = self.invitation_text.get_buffer()
        value = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        try:
            invitation = PeerInvitation.decode(value)
            self._apply_invitation(invitation)
        except Exception as exc:
            self._set_status(str(exc), True)

    def _scan_qr(self, _button: Gtk.Button) -> None:
        chooser = Gtk.FileChooserDialog(title="Select invitation QR image", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        chooser.add_button("Cancel", Gtk.ResponseType.CANCEL)
        chooser.add_button("Open", Gtk.ResponseType.OK)
        if chooser.run() == Gtk.ResponseType.OK:
            try:
                decoder = shutil.which("zbarimg")
                if not decoder:
                    raise PeerError("QR scanning support is missing; reinstall the complete TuxInDrive package")
                result = subprocess.run([decoder, "--quiet", "--raw", chooser.get_filename()], capture_output=True, text=True, timeout=20, check=False)
                if result.returncode or not result.stdout.strip():
                    raise PeerError("No valid TuxInDrive invitation QR code was found")
                invitation = PeerInvitation.decode(result.stdout.strip())
                self._apply_invitation(invitation)
            except Exception as exc:
                self._set_status(str(exc), True)
        chooser.destroy()

    def _apply_invitation(self, invitation: PeerInvitation) -> None:
        invitation.assert_usable()
        self.loaded_invitation = invitation
        self.connection_name.set_text(invitation.name)
        self.connection_host.set_text(invitation.host)
        self.connection_port.set_value(invitation.port)
        self.connection_host_key.set_text(invitation.host_key)
        self.connection_lease.set_value(invitation.lease_minutes)
        self._set_status(f"{invitation.role.label} invitation loaded. Verify fingerprint {key_fingerprint(invitation.host_key)} before connecting.", False)

    def _discover_lan(self, _button: Gtk.Button) -> None:
        self.discovery_store.clear()
        self._set_status("Scanning the local network for TuxInDrive shares…", False)
        _run_thread(self.controller.peers.discover, self._discovery_loaded, 4.0)

    def _discovery_loaded(self, peers: list[DiscoveredPeer] | None, error: Exception | None) -> bool:
        if error:
            self._set_status(f"LAN discovery failed: {error}", True)
            return False
        for peer in peers or []:
            state = "approval needed" if peer.approval_required else "approved"
            self.discovery_store.append([f"{peer.name} · {state}", f"{peer.host}:{peer.port}", peer.fingerprint, peer])
        self._set_status(f"Found {len(peers or [])} local TuxInDrive share(s). Verify the fingerprint before use.", False)
        return False

    def _use_discovered(self, _button: Gtk.Button) -> None:
        model, selected = self.discovery_view.get_selection().get_selected()
        if not selected:
            self._set_status("Select a discovered share first.", True)
            return
        peer = model[selected][3]
        if peer.approval_required:
            try:
                self.controller.peers.request_access(peer)
                self._set_status(
                    f"Access requested from {peer.name}. Ask its owner to compare your identity fingerprint, approve you, then scan again.",
                    False,
                )
            except Exception as exc:
                self._set_status(str(exc), True)
            return
        self._apply_invitation(peer.invitation())
        self.notebook.set_current_page(1)
        self._set_status(f"Approved access loaded for {peer.name}. Select a local folder and click Save and connect.", False)

    def _save_connection(self, _button: Gtk.Button) -> None:
        try:
            folder = self.connection_folder.get_filename()
            if not folder:
                raise PeerError("Select a local folder for the synchronized copy")
            invitation = PeerInvitation(
                self.connection_name.get_text().strip() or "Peer folder",
                validate_host(self.connection_host.get_text()),
                validate_port(self.connection_port.get_value_as_int()),
                normalize_public_key(self.connection_host_key.get_text()),
                lease_minutes=self.connection_lease.get_value_as_int(),
            )
            if (
                self.loaded_invitation
                and self.loaded_invitation.host == invitation.host
                and self.loaded_invitation.host_key == invitation.host_key
            ):
                invitation.relay_host = self.loaded_invitation.relay_host
                invitation.relay_port = self.loaded_invitation.relay_port
                invitation.role = self.loaded_invitation.role
                invitation.remote_path = self.loaded_invitation.remote_path
                invitation.one_time_drop_id = self.loaded_invitation.one_time_drop_id
                invitation.expires_at = self.loaded_invitation.expires_at
            invitation.assert_usable()
            account = self._selected_connection()
            remote = account.remote if account else "peer-" + datetime.now().strftime("%H%M%S")
            candidate = remote + "-verify"
            try:
                self.controller.rclone.delete_remote(candidate)
            except Exception:
                pass
            endpoint_invitations = [invitation]
            if invitation.relay_host and invitation.relay_port:
                endpoint_invitations.append(PeerInvitation(
                    invitation.name, invitation.relay_host, invitation.relay_port,
                    invitation.host_key, invitation.share_id, invitation.lease_minutes,
                ))
            connected = None
            last_error = None
            for endpoint in endpoint_invitations:
                try:
                    self.controller.peers.configure_connection(candidate, endpoint)
                    self.controller.rclone.validate_remote(candidate)
                    connected = endpoint
                    break
                except Exception as exc:
                    last_error = exc
                finally:
                    try:
                        self.controller.rclone.delete_remote(candidate)
                    except Exception:
                        pass
            if connected is None:
                raise PeerError(f"Direct and relay endpoints failed: {last_error}")
            self.controller.peers.configure_connection(remote, connected)
            if account is None:
                account = Account(remote, Provider.PEER, invitation.name)
                self.controller.config.accounts.append(account)
                job = SyncJob(
                    account_remote=remote,
                    local_path=folder,
                    name=invitation.name,
                    cloud_location_name="Direct encrypted peer",
                    remote_path=invitation.remote_path,
                    mode=invitation.role.sync_mode,
                    peer_leases=True,
                    peer_lease_minutes=invitation.lease_minutes,
                    peer_delta=True,
                    peer_role=invitation.role,
                    one_time_drop_id=invitation.one_time_drop_id,
                )
                self.controller.config.jobs.append(job)
            else:
                job = next((item for item in self.controller.config.jobs if item.account_remote == remote), None)
                if job:
                    job.local_path = folder
                    job.name = invitation.name
                    job.initialized = False
                    job.peer_leases = True
                    job.peer_lease_minutes = invitation.lease_minutes
                    job.peer_delta = True
                    job.remote_path = invitation.remote_path
                    job.mode = invitation.role.sync_mode
                    job.peer_role = invitation.role
                    job.one_time_drop_id = invitation.one_time_drop_id
            account.display_name = invitation.name
            account.peer_host = invitation.host
            account.peer_port = invitation.port
            account.peer_host_key = invitation.host_key
            self.controller.save()
            self.controller.reconfigure_callbacks()
            if self.controller.window:
                self.controller.window.refresh()
            if job:
                self.controller.run_job(job)
            self._reload_connection_choices(remote)
            self.controller.audit.record("peer", "connection verified", "success", job_id=job.id if job else "", peer=invitation.name, path=invitation.remote_path, detail=invitation.role.label)
            self._set_status(f"Peer verified; {invitation.role.label.lower()} synchronization started.", False)
        except Exception as exc:
            self._set_status(str(exc), True)

    def _delete_connection(self, _button: Gtk.Button) -> None:
        account = self._selected_connection()
        if not account:
            return
        for job in [item for item in self.controller.config.jobs if item.account_remote == account.remote]:
            self.controller.stop_job(job)
            self.controller.config.jobs.remove(job)
        try:
            self.controller.rclone.delete_remote(account.remote)
        except Exception:
            pass
        self.controller.config.accounts.remove(account)
        self.controller.save()
        self._reload_connection_choices()
        if self.controller.window:
            self.controller.window.refresh()
        self._set_status("Peer connection removed; local and remote files were not deleted.", False)

    def _set_status(self, message: str, error: bool) -> None:
        color = "#c01c28" if error else "#2ec27e"
        self.status.set_markup(
            f"<span foreground='{color}'>{GLib.markup_escape_text(message)}</span>"
        )


class ProfileDialog(ResponsiveDialog):
    """Encrypted, user-owned cloud profile backup and device restore."""

    def __init__(self, parent: Gtk.Window, controller: "TuxInDriveApplication") -> None:
        super().__init__(title="TuxInDrive Profile and device migration", transient_for=parent, modal=True)
        self.controller = controller
        self.set_default_size(650, 470)
        _set_window_brand_icon(self)
        area = self.get_content_area()
        area.set_border_width(24)
        area.set_spacing(12)
        title = Gtk.Label(xalign=0)
        title.set_markup("<span size='large' weight='bold'>Encrypted TuxInDrive Profile</span>")
        area.pack_start(title, False, False, 0)
        description = Gtk.Label(xalign=0)
        description.set_line_wrap(True)
        description.set_text(
            "Link TuxInDrive to one of your OAuth cloud accounts. Configuration is encrypted "
            "on this device before upload; TuxInDrive operates no profile server. On a new "
            "device, connect the same provider, then restore this profile."
        )
        area.pack_start(description, False, False, 0)
        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        self.remote = Gtk.ComboBoxText()
        accounts = [item for item in controller.config.accounts if item.provider.browser_oauth]
        for account in accounts:
            self.remote.append(account.remote, f"{account.provider.label} · {account.display_name}")
        preferred = controller.config.settings.profile_remote
        if not (preferred and self.remote.set_active_id(preferred)) and accounts:
            self.remote.set_active(0)
        self.password = Gtk.Entry()
        self.password.set_visibility(False)
        self.password.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self.password.set_placeholder_text("At least 14 characters")
        self.confirm = Gtk.Entry()
        self.confirm.set_visibility(False)
        self.confirm.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self.include = Gtk.CheckButton(label="Include OAuth credentials and peer private keys")
        self.include.set_tooltip_text("Sensitive: permits a full device migration, but increases the impact of a weak or lost backup password")
        for row, (label, widget) in enumerate((
            ("Profile storage account", self.remote),
            ("Backup password", self.password),
            ("Confirm password", self.confirm),
            ("Sensitive migration", self.include),
        )):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
        area.pack_start(grid, False, False, 0)
        warning = Gtk.Label(xalign=0)
        warning.set_line_wrap(True)
        warning.set_markup(
            "<b>Keep the password safe.</b> It is never uploaded and cannot be recovered. "
            "Credential migration is off by default. Restoring replaces this device's TuxInDrive configuration; a local pre-migration copy is retained."
        )
        area.pack_start(warning, False, False, 0)
        self.spinner = Gtk.Spinner()
        self.status = Gtk.Label(label="Ready", xalign=0)
        self.status.set_line_wrap(True)
        row = Gtk.Box(spacing=10)
        row.pack_start(self.spinner, False, False, 0)
        row.pack_start(self.status, True, True, 0)
        area.pack_start(row, False, False, 0)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.add_button("Inspect cloud backup", 1)
        self.add_button("Restore this device", 2)
        self.add_button("Store encrypted backup", 3)
        self.add_button("Show mobile transfer QR", 4)
        self.connect("response", self._response)
        self.show_all()
        if not accounts:
            self._status("Connect Google Drive, OneDrive, Dropbox, Box, or pCloud first.", True)

    def _status(self, text: str, error: bool = False) -> None:
        color = "#c01c28" if error else "#2ec27e"
        self.status.set_markup(f"<span foreground='{color}'>{GLib.markup_escape_text(text)}</span>")

    def _response(self, dialog: Gtk.Dialog, response: int) -> None:
        if response in (Gtk.ResponseType.CLOSE, Gtk.ResponseType.DELETE_EVENT):
            dialog.destroy()
            return
        remote, password = self.remote.get_active_id(), self.password.get_text()
        if response != 4 and not remote:
            self._status("Choose a connected OAuth account.", True)
            return
        if response in (3, 4) and password != self.confirm.get_text():
            self._status("The backup passwords do not match.", True)
            return
        self.spinner.start()
        self.set_response_sensitive(1, False)
        self.set_response_sensitive(2, False)
        self.set_response_sensitive(3, False)
        self.set_response_sensitive(4, False)
        operation = {1: self._inspect, 2: self._restore, 3: self._backup, 4: self._mobile_qr}[response]
        _run_thread(operation, self._done, remote, password)

    def _inspect(self, remote: str, password: str):
        data = self.controller.profiles.download(remote)
        return ("inspect", self.controller.profiles.summary(data, password))

    def _backup(self, remote: str, password: str):
        self.controller.config.settings.profile_remote = remote
        summary = self.controller.profiles.upload(
            remote, self.controller.config, password, self.include.get_active()
        )
        return ("backup", summary)

    def _restore(self, remote: str, password: str):
        data = self.controller.profiles.download(remote)
        summary = self.controller.profiles.summary(data, password)
        restored = self.controller.profiles.restore(
            data, password, restore_credentials=self.include.get_active()
        )
        restored.settings.profile_remote = remote
        return ("restore", summary, restored)

    def _mobile_qr(self, _remote: str | None, password: str):
        data = self.controller.profiles.create_mobile_bytes(self.controller.config, password)
        return ("qr", encode_profile_frames(data))

    def _done(self, result, error: Exception | None) -> bool:
        self.spinner.stop()
        for response in (1, 2, 3, 4):
            self.set_response_sensitive(response, True)
        if error:
            self._status(f"Profile operation failed safely: {error}", True)
            return False
        action = result[0]
        if action == "qr":
            try:
                ProfileQrDialog(self, result[1]).run_and_close()
                self._status(
                    f"Generated {len(result[1])} encrypted QR frame(s). Scan every frame on Android."
                )
            except Exception as exc:
                self._status(f"QR transfer failed safely: {exc}", True)
            return False
        summary = result[1]
        if action == "restore":
            self.controller.config = result[2]
            self.controller.rclone = RcloneClient(self.controller.config.settings.rclone_path)
            self.controller.bandwidth.configure(
                self.controller.config.settings.global_bandwidth_limit
            )
            self.controller.bandwidth.configure_automatic(
                self.controller.config.settings.automatic_bandwidth_control,
                self.controller.config.settings.bandwidth_headroom_percent,
            )
            self.controller.engine = SyncEngine(
                self.controller.config.settings.rclone_path,
                proton=self.controller.proton,
                bandwidth=self.controller.bandwidth,
            )
            self.controller.engine.configure_streaming_refresh(
                self.controller.config.settings.streaming_refresh_mode
            )
            self.controller.profiles = ProfileManager(self.controller.store, self.controller.rclone)
            self.controller.save()
            if self.controller.window:
                self.controller.window.refresh()
        elif action == "backup":
            self.controller.config.settings.profile_last_backup = summary.created_at
            self.controller.save()
        verb = "Restored" if action == "restore" else "Stored" if action == "backup" else "Found"
        secret = "includes credentials" if summary.includes_credentials else "configuration only"
        self._status(
            f"{verb} profile from {summary.device_name}, TuxInDrive {summary.app_version}: "
            f"{summary.accounts} account(s), {summary.jobs} job(s), {secret}."
        )
        return False


class ProfileQrDialog(ResponsiveDialog):
    """Display one encrypted profile transfer frame at a time."""

    def __init__(self, parent: Gtk.Window, frames: list[str]) -> None:
        super().__init__(title="Transfer encrypted profile to Android", transient_for=parent, modal=True)
        encoder = shutil.which("qrencode")
        if not encoder:
            raise MigrationError("QR support is missing; install qrencode or use the .tdx file")
        self.encoder = encoder
        self.frames = frames
        self.index = 0
        self.temporary = tempfile.TemporaryDirectory(prefix="tuxindrive-profile-qr-")
        self.image_path = Path(self.temporary.name) / "profile.png"
        self.set_default_size(620, 720)
        area = self.get_content_area()
        area.set_border_width(18)
        area.set_spacing(10)
        warning = Gtk.Label(xalign=0)
        warning.set_line_wrap(True)
        warning.set_markup(
            "<b>Encrypted local transfer.</b> Scan every frame in order or any order. "
            "This mobile transfer includes the cloud credentials and configuration unlock key, "
            "but excludes peer private-key files. "
            "The QR data remains protected by the 14+ character backup passphrase; "
            "enter that passphrase on Android and do not display these frames publicly."
        )
        area.pack_start(warning, False, False, 0)
        self.image = Gtk.Image()
        area.pack_start(self.image, True, True, 0)
        self.detail = Gtk.Label()
        area.pack_start(self.detail, False, False, 0)
        self.add_button("Previous", 1)
        self.add_button("Next", 2)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.connect("response", self._response)
        self._render()
        self.show_all()

    def _render(self) -> None:
        result = subprocess.run(
            [self.encoder, "-l", "L", "-m", "2", "-s", "5", "-o", str(self.image_path), "--", self.frames[self.index]],
            capture_output=True, text=True, timeout=20, check=False,
        )
        if result.returncode:
            raise MigrationError((result.stderr or "Could not generate profile QR code").strip())
        self.image.set_from_file(str(self.image_path))
        self.detail.set_text(f"Frame {self.index + 1} of {len(self.frames)}")
        self.set_response_sensitive(1, self.index > 0)
        self.set_response_sensitive(2, self.index + 1 < len(self.frames))

    def _response(self, _dialog: Gtk.Dialog, response: int) -> None:
        if response == 1 and self.index > 0:
            self.index -= 1
            self._render()
        elif response == 2 and self.index + 1 < len(self.frames):
            self.index += 1
            self._render()
        else:
            self.destroy()

    def run_and_close(self) -> None:
        try:
            self.run()
        finally:
            self.destroy()
            self.temporary.cleanup()


class OperationsDashboard(ResponsiveDialog):
    def __init__(self, parent: Gtk.Window, controller: "TuxInDriveApplication") -> None:
        super().__init__(title="TuxInDrive sync health and audit", transient_for=parent, modal=False)
        self.set_default_size(920, 620)
        _set_window_brand_icon(self)
        notebook = Gtk.Notebook()
        notebook.append_page(self._health(controller), Gtk.Label(label="Sync health"))
        notebook.append_page(self._audit(controller), Gtk.Label(label="Audit timeline"))
        notebook.append_page(self._capabilities(), Gtk.Label(label="Provider capabilities"))
        policy = Gtk.Label(label=controller.managed_policy.summary, xalign=0, yalign=0)
        policy.set_line_wrap(True)
        policy.set_selectable(True)
        policy.set_margin_start(16)
        policy.set_margin_end(16)
        policy.set_margin_top(16)
        notebook.append_page(policy, Gtk.Label(label="Managed policy"))
        self.get_content_area().set_border_width(12)
        self.get_content_area().pack_start(notebook, True, True, 0)
        if controller.managed_policy.allow_audit_export:
            self.add_button("Export audit…", 2)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.connect("response", self._response)
        self.show_all()

    def _response(self, dialog: Gtk.Dialog, response: int) -> None:
        if response != 2:
            dialog.destroy()
            return
        chooser = Gtk.FileChooserDialog(
            title="Export private audit timeline", transient_for=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        chooser.add_button("Cancel", Gtk.ResponseType.CANCEL)
        chooser.add_button("Export", Gtk.ResponseType.OK)
        chooser.set_current_name("tuxindrive-audit.csv")
        chooser.set_do_overwrite_confirmation(True)
        if chooser.run() == Gtk.ResponseType.OK:
            path = Path(chooser.get_filename())
            try:
                export_format = "jsonl" if path.suffix.lower() == ".jsonl" else "csv"
                count = self.get_transient_for().controller.audit.export(
                    path, format=export_format
                )
                self.get_transient_for().message(f"Exported {count} private audit events to {path}.")
            except (OSError, ValueError) as exc:
                self.get_transient_for().message(f"Audit export failed: {exc}", Gtk.MessageType.ERROR)
        chooser.destroy()

    @staticmethod
    def _tree(columns: tuple[str, ...], rows: list[tuple[str, ...]]) -> Gtk.Widget:
        store = Gtk.ListStore(*([str] * len(columns)))
        for row in rows:
            store.append(list(row))
        view = Gtk.TreeView(model=store)
        for index, title in enumerate(columns):
            renderer = Gtk.CellRendererText()
            renderer.set_property("ellipsize", 3)
            view.append_column(Gtk.TreeViewColumn(title, renderer, text=index))
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(view)
        return scroll

    def _health(self, controller: "TuxInDriveApplication") -> Gtk.Widget:
        rows = []
        running, mounted, callbacks = controller.engine.running_jobs, controller.engine.mounted_jobs, controller.engine.callback_jobs
        for job in controller.config.jobs:
            state = "Synchronizing" if job.id in running else "Streaming" if job.id in mounted else "Error" if job.last_error else "Paused" if not job.enabled else "Healthy" if job.initialized else "Pending"
            callback = "Active" if job.id in callbacks else "Inactive"
            rows.append((job.name, state, job.mode.label, job.peer_role.label if job.peer_delta else "Cloud", callback, job.last_run or "Never", job.last_error or job.last_status))
        return self._tree(("Folder", "State", "Mode", "Access", "Callbacks", "Last run", "Detail"), rows)

    def _audit(self, controller: "TuxInDriveApplication") -> Gtk.Widget:
        rows = [
            (event.timestamp, event.category, event.action, event.outcome, event.peer, event.path, event.detail)
            for event in controller.audit.recent(500)
        ]
        return self._tree(("Time", "Category", "Action", "Result", "Peer", "Path", "Detail"), rows)

    def _capabilities(self) -> Gtk.Widget:
        rows = []
        for provider, value in CAPABILITIES.items():
            rows.append((provider.label, "Yes" if value.streaming else "No", "Yes" if value.polling else "No", "Yes" if value.hashes else "No", "Yes" if value.server_move else "No", "Yes" if value.share_links else "No", "Yes" if value.versions else "No", value.notes))
        return self._tree(("Provider", "Streaming", "Polling", "Hashes", "Moves", "Share links", "Versions", "Notes"), rows)


class HelpCenterDialog(ResponsiveDialog):
    """Searchable offline documentation in the selected UI language."""

    def __init__(self, parent: Gtk.Window) -> None:
        from .help_content import topics as help_topics
        super().__init__(title=tr("documentation"), transient_for=parent, modal=False)
        _set_window_brand_icon(self)
        self.set_default_size(900, 700)
        self._topics = help_topics(get_language())
        self._rtl = is_rtl()
        text_direction = Gtk.TextDirection.RTL if self._rtl else Gtk.TextDirection.LTR
        area = self.get_content_area()
        area.set_border_width(16)
        area.set_spacing(10)
        title = Gtk.Label(xalign=1 if self._rtl else 0)
        title.set_direction(text_direction)
        title.set_markup(f"<span size='x-large' weight='bold'>{GLib.markup_escape_text(tr('documentation'))}</span>\n<small>{GLib.markup_escape_text(tr('documentation_intro'))}</small>")
        area.pack_start(title, False, False, 0)
        self.search = Gtk.SearchEntry()
        self.search.set_direction(text_direction)
        self.search.set_placeholder_text(tr("search_help"))
        self.search.connect("search-changed", self._filter)
        area.pack_start(self.search, False, False, 0)
        split = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        self.topic_list = Gtk.ListBox()
        self.topic_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.topic_list.connect("row-selected", self._selected)
        topic_scroll = Gtk.ScrolledWindow()
        topic_scroll.set_size_request(280, -1)
        topic_scroll.add(self.topic_list)
        split.pack1(topic_scroll, False, False)
        self.body = Gtk.TextView()
        self.body.set_direction(text_direction)
        self.body.set_editable(False)
        self.body.set_cursor_visible(False)
        self.body.set_wrap_mode(Gtk.WrapMode.WORD)
        self.body.set_left_margin(18)
        self.body.set_right_margin(18)
        self.body.set_top_margin(18)
        body_scroll = Gtk.ScrolledWindow()
        body_scroll.add(self.body)
        split.pack2(body_scroll, True, False)
        area.pack_start(split, True, True, 0)
        self.add_button(tr("close"), Gtk.ResponseType.CLOSE)
        self.connect("response", lambda dialog, _response: dialog.destroy())
        self._populate(self._topics)
        self.show_all()

    def _populate(self, selected) -> None:
        for child in self.topic_list.get_children():
            self.topic_list.remove(child)
        for topic in selected:
            row = Gtk.ListBoxRow()
            row.topic = topic
            label = Gtk.Label(label=topic.title, xalign=1 if self._rtl else 0)
            label.set_direction(Gtk.TextDirection.RTL if self._rtl else Gtk.TextDirection.LTR)
            label.set_line_wrap(True)
            label.set_margin_start(8)
            label.set_margin_end(8)
            label.set_margin_top(7)
            label.set_margin_bottom(7)
            row.add(label)
            self.topic_list.add(row)
        self.topic_list.show_all()
        rows = self.topic_list.get_children()
        if rows:
            self.topic_list.select_row(rows[0])
        else:
            self.body.get_buffer().set_text(tr("all_topics"))

    def _filter(self, _entry: Gtk.SearchEntry) -> None:
        query = self.search.get_text().casefold().strip()
        selected = tuple(topic for topic in self._topics if not query or query in f"{topic.title}\n{topic.body}".casefold())
        self._populate(selected)

    def _selected(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if not row:
            return
        topic = row.topic
        self.body.get_buffer().set_text(f"{topic.title}\n\n{topic.body}")


class FolderSearchDialog(ResponsiveDialog):
    """Search the private filename index without contacting cloud providers."""

    def __init__(self, parent: Gtk.Window, controller: "TuxInDriveApplication") -> None:
        super().__init__(title="Search synchronized folders", transient_for=parent, modal=False)
        self.set_default_size(900, 620)
        self.controller = controller
        self._results: list[SearchResult] = []
        self._query_source = 0
        self._preview_serial = 0
        self._closed = False
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.connect("response", lambda dialog, _response: dialog.destroy())
        self.connect("destroy", self._destroyed)

        content = self.get_content_area()
        content.set_border_width(18)
        content.set_spacing(10)
        self.intro = Gtk.Label(xalign=0)
        self.intro.set_line_wrap(True)
        content.pack_start(self.intro, False, False, 0)

        search_row = Gtk.Box(spacing=8)
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("File or folder name")
        self.search_entry.connect("search-changed", self._search_changed)
        self.search_entry.connect("activate", lambda _entry: self._run_search())
        search_row.pack_start(self.search_entry, True, True, 0)
        refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        refresh.set_tooltip_text("Refresh the local index")
        refresh.connect("clicked", self._refresh_index)
        search_row.pack_start(refresh, False, False, 0)
        self.preview_enabled = Gtk.CheckButton(label="Enable preview")
        self.preview_enabled.set_tooltip_text(
            "Off by default. When enabled, only the selected local file is read within strict limits."
        )
        self.preview_enabled.connect("toggled", self._preview_toggled)
        search_row.pack_start(self.preview_enabled, False, False, 0)
        self.content_index_enabled = Gtk.CheckButton(label="Index local file contents")
        self.content_index_enabled.set_active(
            self.controller.config.settings.search_content_indexing
        )
        self.content_index_enabled.set_tooltip_text(
            "Opt in to a private bounded text index for supported local files. Cloud-only files are never downloaded."
        )
        self.content_index_enabled.connect("toggled", self._content_index_toggled)
        search_row.pack_start(self.content_index_enabled, False, False, 0)
        content.pack_start(search_row, False, False, 0)
        self._update_intro()

        self.store = Gtk.ListStore(str, str, str, str, str)
        self.view = Gtk.TreeView(model=self.store)
        self.view.set_headers_visible(True)
        for index, title in enumerate(("Name", "Synchronized folder", "Location", "Size", "Match")):
            renderer = Gtk.CellRendererText()
            renderer.set_property("ellipsize", 3)
            column = Gtk.TreeViewColumn(title, renderer, text=index)
            column.set_resizable(True)
            column.set_expand(index == 2)
            self.view.append_column(column)
        self.view.connect("row-activated", lambda *_args: self._open_selected())
        self.view.get_selection().connect("changed", self._selection_changed)
        result_scroll = Gtk.ScrolledWindow()
        result_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        result_scroll.set_min_content_height(260)
        result_scroll.add(self.view)

        self.preview_frame = Gtk.Frame(label="Selected-file preview")
        preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        preview_box.set_border_width(10)
        self.preview_meta = Gtk.Label(xalign=0)
        self.preview_meta.set_line_wrap(True)
        preview_box.pack_start(self.preview_meta, False, False, 0)
        self.preview_stack = Gtk.Stack()
        self.preview_text = Gtk.TextView()
        self.preview_text.set_editable(False)
        self.preview_text.set_cursor_visible(False)
        self.preview_text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.preview_text.set_left_margin(10)
        self.preview_text.set_right_margin(10)
        self.preview_text.set_top_margin(10)
        self.preview_text.set_bottom_margin(10)
        preview_text_scroll = Gtk.ScrolledWindow()
        preview_text_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        preview_text_scroll.add(self.preview_text)
        self.preview_stack.add_named(preview_text_scroll, "text")
        self.preview_image = Gtk.Image()
        preview_image_scroll = Gtk.ScrolledWindow()
        preview_image_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        preview_image_scroll.add_with_viewport(self.preview_image)
        self.preview_stack.add_named(preview_image_scroll, "image")
        preview_box.pack_start(self.preview_stack, True, True, 0)
        self.preview_frame.add(preview_box)

        result_split = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        result_split.set_position(530)
        result_split.pack1(result_scroll, True, False)
        result_split.pack2(self.preview_frame, True, False)
        content.pack_start(result_split, True, True, 0)

        footer = Gtk.Box(spacing=8)
        self.status = Gtk.Label(xalign=0)
        self.status.set_line_wrap(True)
        footer.pack_start(self.status, True, True, 0)
        open_button = Gtk.Button(label="Open selected")
        open_button.connect("clicked", lambda _button: self._open_selected())
        footer.pack_end(open_button, False, False, 0)
        content.pack_start(footer, False, False, 0)
        self.status.set_text(f"{self.controller.search_index.count()} indexed items. Type to search.")
        self.show_all()
        self.preview_frame.hide()
        self.search_entry.grab_focus()

    def _search_changed(self, _entry: Gtk.SearchEntry) -> None:
        if self._query_source:
            GLib.source_remove(self._query_source)
        self._query_source = GLib.timeout_add(180, self._run_search)

    def _destroyed(self, _dialog: Gtk.Widget) -> None:
        self._closed = True
        self._preview_serial += 1
        if self._query_source:
            GLib.source_remove(self._query_source)
            self._query_source = 0

    def _run_search(self) -> bool:
        self._query_source = 0
        if self._closed:
            return False
        query = self.search_entry.get_text().strip()
        self.store.clear()
        if not query:
            self._results = []
            self.status.set_text(f"{self.controller.search_index.count()} indexed items. Type to search.")
            return False
        self.status.set_text("Searching the private local index…")

        def ready(results: list[SearchResult] | None, error: Exception | None) -> bool:
            if self._closed or query != self.search_entry.get_text().strip():
                return False
            if error:
                self.status.set_text(f"Search failed: {error}")
                return False
            self._results = results or []
            self._render_results(query)
            return False

        _run_thread(self.controller.search_index.search, ready, query)
        return False

    def _render_results(self, query: str) -> None:
        self.store.clear()
        for result in self._results:
            size = "Folder" if result.is_directory else format_bytes(result.size)
            self.store.append((
                result.name, result.job_name, result.relative_path, size,
                "Content" if result.matched_content else "Name/path",
            ))
        suffix = " (first 200 shown)" if len(self._results) == 200 else ""
        self.status.set_text(f"{len(self._results)} matches for “{query}”{suffix}")

    def _refresh_index(self, _button: Gtk.Widget) -> None:
        self.status.set_text("Refreshing the private local index…")
        self.controller.refresh_search_index(self._refresh_ready)

    def _content_index_toggled(self, button: Gtk.CheckButton) -> None:
        enabled = button.get_active()
        if enabled and not self.controller.managed_policy.allow_content_indexing:
            button.set_active(False)
            self.status.set_text("Content indexing is disabled by the managed desktop policy.")
            return
        self._update_intro()
        self.controller.config.settings.search_content_indexing = enabled
        self.controller.save()
        self.status.set_text(
            "Building the private bounded content index…"
            if enabled else "Removing indexed content while retaining file names…"
        )
        self.controller.refresh_search_index(self._refresh_ready)

    def _update_intro(self) -> None:
        if self.content_index_enabled.get_active():
            detail = (
                "Supported local file contents are read within strict size limits and stored "
                "only in the private local index."
            )
        else:
            detail = "File contents are not read."
        self.intro.set_text(
            "Searches synchronized folders using a private local index. "
            f"{detail} Files-on-demand drives are excluded so indexing cannot download cloud data."
        )

    def _refresh_ready(self, result: IndexStats | None, error: Exception | None) -> bool:
        if self._closed:
            return False
        if error:
            self.status.set_text(f"Index refresh failed: {error}")
            return False
        assert result is not None
        note = f"; {result.limited_jobs} very large folder(s) kept at the safety limit" if result.limited_jobs else ""
        self.status.set_text(f"Indexed {result.indexed} items; removed {result.removed} stale items{note}.")
        self._run_search()
        return False

    def _selection_changed(self, _selection: Gtk.TreeSelection) -> None:
        if self.preview_enabled.get_active():
            self._preview_selected()

    def _preview_toggled(self, button: Gtk.CheckButton) -> None:
        self._preview_serial += 1
        if not button.get_active():
            self.preview_frame.hide()
            self.preview_meta.set_text("")
            self.preview_text.get_buffer().set_text("")
            self.preview_image.clear()
            return
        self.preview_frame.show_all()
        self._preview_selected()

    def _selected_result(self) -> SearchResult | None:
        model, selected = self.view.get_selection().get_selected()
        if selected is None:
            return None
        index = model.get_path(selected).get_indices()[0]
        return self._results[index] if index < len(self._results) else None

    @staticmethod
    def _resolved_result(result: SearchResult) -> Path:
        if result.local_path.is_symlink():
            raise ValueError("The indexed item was replaced by a symbolic link")
        root = result.root.resolve(strict=True)
        target = result.local_path.resolve(strict=True)
        if target != root and root not in target.parents:
            raise ValueError("The indexed path is outside its synchronized folder")
        return target

    def _preview_selected(self) -> None:
        self._preview_serial += 1
        serial = self._preview_serial
        result = self._selected_result()
        self.preview_image.clear()
        self.preview_stack.set_visible_child_name("text")
        if result is None:
            self.preview_meta.set_text("Select a result to preview it.")
            self.preview_text.get_buffer().set_text(
                "Preview is opt-in and reads only the selected local item. Search indexing remains metadata-only."
            )
            return
        try:
            target = self._resolved_result(result)
        except (OSError, ValueError) as exc:
            self.preview_meta.set_text("Preview unavailable")
            self.preview_text.get_buffer().set_text(f"This item is no longer available locally: {exc}")
            return
        self.preview_meta.set_text(f"Loading a bounded local preview of {result.name}…")
        self.preview_text.get_buffer().set_text("")

        def ready(data: PreviewData | None, error: Exception | None) -> bool:
            if self._closed or serial != self._preview_serial or not self.preview_enabled.get_active():
                return False
            if error:
                self.preview_meta.set_text("Preview unavailable")
                self.preview_text.get_buffer().set_text(str(error))
                self.preview_stack.set_visible_child_name("text")
                return False
            assert data is not None
            note = " · truncated to the preview limit" if data.truncated else ""
            self.preview_meta.set_text(f"{data.format_label}{note} · local read only")
            if data.kind == "image":
                try:
                    pixbuf = self._preview_pixbuf(data.image_bytes)
                except (GLib.Error, PreviewError, ValueError) as exc:
                    self.preview_text.get_buffer().set_text(f"Image preview could not be rendered safely: {exc}")
                    self.preview_stack.set_visible_child_name("text")
                else:
                    self.preview_image.set_from_pixbuf(pixbuf)
                    self.preview_stack.set_visible_child_name("image")
            else:
                self.preview_text.get_buffer().set_text(data.text)
                self.preview_stack.set_visible_child_name("text")
            return False

        _run_thread(preview_path, ready, target)

    @staticmethod
    def _preview_pixbuf(content: bytes):
        if not content:
            raise PreviewError("The image is empty")
        loader = GdkPixbuf.PixbufLoader()
        invalid: list[str] = []

        def prepared(current, width: int, height: int) -> None:
            if width <= 0 or height <= 0 or width > 100_000 or height > 100_000:
                invalid.append("invalid image dimensions")
                current.set_size(1, 1)
                return
            scale = min(1.0, 720 / width, 720 / height)
            current.set_size(max(1, int(width * scale)), max(1, int(height * scale)))

        loader.connect("size-prepared", prepared)
        loader.write(content)
        loader.close()
        if invalid:
            raise PreviewError(invalid[0])
        pixbuf = loader.get_pixbuf()
        if pixbuf is None:
            raise PreviewError("The image decoder produced no preview")
        return pixbuf

    def _open_selected(self) -> None:
        result = self._selected_result()
        if result is None:
            self.status.set_text("Select a result first.")
            return
        try:
            target = self._resolved_result(result)
        except (OSError, ValueError) as exc:
            self.status.set_text(f"This item is no longer available locally: {exc}")
            return
        subprocess.Popen(
            _desktop_open_command(str(target)),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


class CloudTransferDialog(ResponsiveDialog):
    """Preview and run a non-destructive copy between configured cloud accounts."""

    def __init__(self, parent: Gtk.Window, controller: "TuxInDriveApplication") -> None:
        super().__init__(title="Cloud-to-cloud copy", transient_for=parent, modal=False)
        self.set_default_size(700, 500)
        self.controller = controller
        self._previewed: tuple[str, str, str, str] | None = None
        self._running = False
        self.accounts = [
            account for account in controller.config.accounts
            if account.backend == "rclone"
            and account.provider not in {Provider.GITHUB, Provider.PEER}
        ]
        area = self.get_content_area()
        area.set_border_width(18)
        area.set_spacing(10)
        explanation = Gtk.Label(
            label=(
                "Copies files without deleting either endpoint. TuxInDrive first runs a dry-run preview. "
                "The provider may perform the transfer server-side; otherwise the global bandwidth controller applies."
            ),
            xalign=0,
        )
        explanation.set_line_wrap(True)
        area.pack_start(explanation, False, False, 0)
        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        self.source = Gtk.ComboBoxText()
        self.destination = Gtk.ComboBoxText()
        for account in self.accounts:
            label = f"{account.display_name} · {account.provider.label}"
            self.source.append(account.remote, label)
            self.destination.append(account.remote, label)
        if self.accounts:
            self.source.set_active(0)
            self.destination.set_active(1 if len(self.accounts) > 1 else 0)
        self.source_path = Gtk.Entry()
        self.source_path.set_placeholder_text("Source folder (blank = account root)")
        self.destination_path = Gtk.Entry()
        self.destination_path.set_placeholder_text("Destination folder (blank = account root)")
        for row, (label, widget) in enumerate((
            ("Source account", self.source),
            ("Source folder", self.source_path),
            ("Destination account", self.destination),
            ("Destination folder", self.destination_path),
        )):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
        area.pack_start(grid, False, False, 0)
        self.output = Gtk.TextView()
        self.output.set_editable(False)
        self.output.set_cursor_visible(False)
        self.output.set_monospace(True)
        self.output.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(180)
        scroll.add(self.output)
        area.pack_start(scroll, True, True, 0)
        self.status = Gtk.Label(xalign=0)
        self.status.set_line_wrap(True)
        area.pack_start(self.status, False, False, 0)
        self.preview_button = self.add_button("Preview copy", 2)
        self.copy_button = self.add_button("Start verified copy", 3)
        self.copy_button.set_sensitive(False)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.connect("response", self._response)
        for widget in (self.source, self.destination, self.source_path, self.destination_path):
            signal = "changed" if isinstance(widget, Gtk.ComboBoxText) else "changed"
            widget.connect(signal, self._selection_changed)
        if not controller.managed_policy.allow_cloud_to_cloud:
            self.status.set_text("Cloud-to-cloud copy is disabled by the managed desktop policy.")
            self.preview_button.set_sensitive(False)
        elif len(self.accounts) < 2:
            self.status.set_text("Connect at least two rclone-backed cloud accounts first.")
            self.preview_button.set_sensitive(False)
        self.show_all()

    def _spec(self) -> tuple[str, str, str, str]:
        return (
            self.source.get_active_id() or "",
            self.source_path.get_text().strip(),
            self.destination.get_active_id() or "",
            self.destination_path.get_text().strip(),
        )

    def _selection_changed(self, _widget: Gtk.Widget) -> None:
        self._previewed = None
        self.copy_button.set_sensitive(False)

    def _response(self, dialog: Gtk.Dialog, response: int) -> None:
        if response in {Gtk.ResponseType.CLOSE, Gtk.ResponseType.DELETE_EVENT}:
            if not self._running:
                dialog.destroy()
            return
        if self._running:
            return
        values = self._spec()
        if response == 2:
            self._run(values, dry_run=True)
        elif response == 3 and values == self._previewed:
            self._run(values, dry_run=False)

    def _run(self, values: tuple[str, str, str, str], *, dry_run: bool) -> None:
        self._running = True
        self.preview_button.set_sensitive(False)
        self.copy_button.set_sensitive(False)
        self.status.set_text("Previewing the copy…" if dry_run else "Copying between cloud accounts…")

        def operation():
            with self.controller.bandwidth.guard():
                return self.controller.rclone.copy_between_remotes(
                    *values,
                    dry_run=dry_run,
                    bandwidth_args=self.controller.bandwidth.rclone_args(),
                )

        def ready(result, error: Exception | None) -> bool:
            self._running = False
            self.preview_button.set_sensitive(True)
            if error:
                self.status.set_text(f"Cloud copy failed safely: {error}")
                self.controller.audit.record(
                    "cloud-copy", "preview" if dry_run else "copy", "failed",
                    path=f"{values[0]}:{values[1]}", detail=str(error),
                )
                return False
            output = ((result.stdout or "") + (result.stderr or "")).strip()
            self.output.get_buffer().set_text(output[-20_000:] or "No changes are required.")
            if dry_run:
                self._previewed = values
                self.copy_button.set_sensitive(True)
                self.status.set_text("Preview complete. Review it, then start the verified non-destructive copy.")
            else:
                self._previewed = None
                self.status.set_text("Cloud-to-cloud copy completed.")
            self.controller.audit.record(
                "cloud-copy", "preview" if dry_run else "copy", "success",
                path=f"{values[0]}:{values[1]}", detail=f"destination={values[2]}:{values[3]}",
            )
            return False

        _run_thread(operation, ready)


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, application: "TuxInDriveApplication") -> None:
        super().__init__(application=application, title="TuxInDrive")
        self.controller = application
        self.set_resizable(True)
        self.set_default_size(1100, 760)
        _set_window_brand_icon(self)
        self.get_style_context().add_class("tuxindrive-surface")
        self.connect("delete-event", self._hide_instead_of_close)

        header = Gtk.HeaderBar(title="TuxInDrive", subtitle=tr("subtitle"))
        header.get_style_context().add_class("tuxindrive-header")
        header.set_show_close_button(True)
        self.set_titlebar(header)
        brand = _brand_image(Gtk.IconSize.LARGE_TOOLBAR)
        brand.set_tooltip_text("TuxInDrive")
        header.pack_start(brand)
        add_account = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
        add_account.set_tooltip_text(tr("connect_cloud"))
        add_account.connect("clicked", self._choose_provider)
        header.pack_start(add_account)
        peers = Gtk.Button.new_from_icon_name("network-workgroup-symbolic", Gtk.IconSize.BUTTON)
        peers.set_tooltip_text(tr("peer_folders"))
        peers.connect("clicked", self._show_peer_sharing)
        header.pack_start(peers)
        health = Gtk.Button.new_from_icon_name("view-statistics-symbolic", Gtk.IconSize.BUTTON)
        health.set_tooltip_text(tr("health"))
        health.connect("clicked", lambda _button: OperationsDashboard(self, self.controller))
        header.pack_start(health)
        search = Gtk.Button.new_from_icon_name("edit-find-symbolic", Gtk.IconSize.BUTTON)
        search.set_tooltip_text("Search synchronized folders")
        search.connect("clicked", lambda _button: FolderSearchDialog(self, self.controller))
        header.pack_start(search)
        cloud_copy = Gtk.Button.new_from_icon_name("edit-copy-symbolic", Gtk.IconSize.BUTTON)
        cloud_copy.set_tooltip_text("Copy between cloud accounts")
        cloud_copy.connect("clicked", lambda _button: CloudTransferDialog(self, self.controller))
        header.pack_start(cloud_copy)
        settings = Gtk.Button.new_from_icon_name("emblem-system-symbolic", Gtk.IconSize.BUTTON)
        settings.set_tooltip_text(tr("settings"))
        settings.connect("clicked", self._show_settings)
        header.pack_end(settings)
        help_button = Gtk.Button.new_from_icon_name("help-browser-symbolic", Gtk.IconSize.BUTTON)
        help_button.set_tooltip_text(tr("help"))
        help_button.connect("clicked", lambda _button: HelpCenterDialog(self))
        header.pack_end(help_button)
        self.language = Gtk.ComboBoxText()
        self.language.set_tooltip_text(tr("language"))
        for language in LANGUAGES:
            self.language.append(language.code, f"{language.flag} {language.name}")
        self.language.set_active_id(get_language())
        self.language.connect("changed", self._language_changed)
        header.pack_end(self.language)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.get_style_context().add_class("tuxindrive-root")
        self.add(root)
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        root.pack_start(content, True, True, 0)

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        sidebar.set_size_request(260, -1)
        sidebar.set_border_width(16)
        sidebar.get_style_context().add_class("sidebar")
        account_label = Gtk.Label(xalign=0)
        account_label.set_markup(f"<b>{GLib.markup_escape_text(tr('cloud_accounts'))}</b>")
        sidebar.pack_start(account_label, False, False, 0)
        self.account_list = Gtk.ListBox()
        self.account_list.get_style_context().add_class("account-list")
        self.account_list.set_selection_mode(Gtk.SelectionMode.NONE)
        sidebar.pack_start(self.account_list, False, False, 0)
        connect_button = Gtk.Button(label=tr("connect_account"))
        connect_button.get_style_context().add_class("primary-outline")
        connect_button.connect("clicked", self._choose_provider)
        sidebar.pack_start(connect_button, False, False, 0)
        content.pack_start(sidebar, False, False, 0)

        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        main.get_style_context().add_class("workspace")
        main.set_border_width(20)
        heading_row = Gtk.Box(spacing=10)
        heading_row.get_style_context().add_class("workspace-heading")
        heading = Gtk.Label(xalign=0)
        heading.set_markup(f"<span size='large' weight='bold'>{GLib.markup_escape_text(tr('synced_folders'))}</span>")
        heading_row.pack_start(heading, True, True, 0)
        add_job = Gtk.Button(label=tr("add_folder"))
        add_job.get_style_context().add_class("primary-action")
        add_job.connect("clicked", self._add_job)
        heading_row.pack_end(add_job, False, False, 0)
        add_group = Gtk.Button(label=tr("new_group"))
        add_group.get_style_context().add_class("secondary-action")
        add_group.set_tooltip_text("Create an internal group without moving local or cloud folders")
        add_group.connect("clicked", self._create_group)
        heading_row.pack_end(add_group, False, False, 0)
        main.pack_start(heading_row, False, False, 0)
        self.network_strip = Gtk.Box(spacing=14)
        self.network_strip.get_style_context().add_class("network-meter")
        network_title = Gtk.Label(label=tr("network_traffic"), xalign=0)
        network_title.get_style_context().add_class("network-title")
        network_title.set_tooltip_text(tr("network_traffic_hint"))
        self.network_strip.pack_start(network_title, False, False, 0)
        hide_network = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
        hide_network.set_relief(Gtk.ReliefStyle.NONE)
        hide_network.set_tooltip_text("Hide network traffic and stop meter rendering")
        hide_network.connect("clicked", self._hide_network_usage)
        self.network_strip.pack_end(hide_network, False, False, 0)
        self.network_values: dict[str, Gtk.Label] = {}
        for key, icon_name, label in (
            ("download_rate", "go-down-symbolic", tr("download_now")),
            ("upload_rate", "go-up-symbolic", tr("upload_now")),
            ("download_today", "document-save-symbolic", tr("download_today")),
            ("upload_today", "document-send-symbolic", tr("upload_today")),
        ):
            item = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            item.pack_start(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU), False, False, 0)
            caption = Gtk.Label(label=label)
            caption.get_style_context().add_class("network-label")
            item.pack_start(caption, False, False, 0)
            value = Gtk.Label(label="0 B/s" if key.endswith("rate") else "0 B")
            value.get_style_context().add_class("network-value")
            item.pack_start(value, False, False, 0)
            self.network_values[key] = value
            self.network_strip.pack_start(item, False, False, 0)
        main.pack_start(self.network_strip, False, False, 0)
        self.network_strip.set_no_show_all(
            not self.controller.config.settings.show_network_usage
        )
        self.summary_strip = Gtk.Box(spacing=12)
        self.summary_values: dict[str, Gtk.Label] = {}
        for key, icon_name, label in (
            ("services", "network-server-symbolic", tr("connected_services")),
            ("active", "emblem-synchronizing-symbolic", tr("active_syncs")),
            ("protected", "folder-symbolic", tr("protected_folders")),
        ):
            card = Gtk.Box(spacing=12)
            card.set_name(f"summary-{key}")
            card.get_style_context().add_class("summary-card")
            card.pack_start(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.DND), False, False, 0)
            copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            caption = Gtk.Label(label=label, xalign=0)
            caption.get_style_context().add_class("summary-label")
            value = Gtk.Label(label="0", xalign=0)
            value.get_style_context().add_class("summary-value")
            copy.pack_start(caption, False, False, 0)
            copy.pack_start(value, False, False, 0)
            card.pack_start(copy, True, True, 0)
            self.summary_values[key] = value
            self.summary_strip.pack_start(card, True, True, 0)
        main.pack_start(self.summary_strip, False, False, 0)
        self.job_list = Gtk.ListBox()
        self.job_list.get_style_context().add_class("job-list")
        self.job_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_width(1)
        scroll.set_propagate_natural_width(False)
        scroll.add(self.job_list)
        main.pack_start(scroll, True, True, 0)

        activity = Gtk.Expander()
        self.activity_panel = activity
        activity.get_style_context().add_class("activity-panel")
        activity.set_expanded(True)
        activity_header = Gtk.Box(spacing=8)
        activity_header.pack_start(Gtk.Label(label=tr("live_log")), True, True, 0)
        hide_activity = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
        hide_activity.set_relief(Gtk.ReliefStyle.NONE)
        hide_activity.set_tooltip_text("Hide the live activity log and stop rendering it")
        hide_activity.connect("clicked", self._hide_activity_log)
        activity_header.pack_end(hide_activity, False, False, 0)
        activity.set_label_widget(activity_header)
        self.activity_view = Gtk.TextView()
        self.activity_view.set_editable(False)
        self.activity_view.set_cursor_visible(False)
        self.activity_view.set_monospace(True)
        self.activity_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.activity_view.get_style_context().add_class("activity-log")
        activity_scroll = Gtk.ScrolledWindow()
        activity_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        activity_scroll.set_size_request(-1, 190)
        activity_scroll.add(self.activity_view)
        activity.add(activity_scroll)
        main.pack_start(activity, False, True, 0)
        activity.set_no_show_all(
            not self.controller.config.settings.show_live_activity_log
        )
        content.pack_start(main, True, True, 0)

        self.infobar = Gtk.InfoBar()
        self.infobar.set_no_show_all(True)
        self.info_label = Gtk.Label(xalign=0)
        self.infobar.get_content_area().add(self.info_label)
        self.infobar.connect("response", lambda bar, _response: bar.hide())
        root.pack_end(self.infobar, False, False, 0)
        self._activity_content = ""
        self._activity_files: dict[Path, tuple[int, int, int, str]] = {}
        self._refresh_source = 0
        self._render_signature: tuple | None = None
        self._job_widgets: dict[str, dict[str, object]] = {}
        self._account_widgets: dict[str, dict[str, Gtk.Widget]] = {}
        self.update_dialog: Gtk.Dialog | None = None
        self.update_status: Gtk.Label | None = None
        self.update_progress: Gtk.ProgressBar | None = None
        self.update_close_button: Gtk.Button | None = None
        self.update_install_button: Gtk.Button | None = None
        self._pending_update: UpdateRelease | None = None
        self._update_pulsing = False
        self._update_operation_active = False
        GLib.timeout_add_seconds(1, self._refresh_activity_log)
        self._network_refreshing = False
        self._network_active = True
        self._network_source = 0
        self._network_worker: threading.Thread | None = None
        self._network_worker_stop = threading.Event()
        self._network_sample_request = threading.Event()
        self.connect("destroy", self._stop_network_usage)
        self.set_network_meter_enabled(
            self.controller.config.settings.show_network_usage
        )
        self._refresh_now()

    def _refresh_network_usage(self) -> bool:
        if not self._network_active:
            return False
        if (
            not self.controller.config.settings.show_network_usage
            or not self.get_visible()
        ):
            return True
        if not self._network_refreshing:
            self._network_refreshing = True
            self._network_sample_request.set()
        return True

    def _start_network_worker(self) -> None:
        if self._network_worker is not None and self._network_worker.is_alive():
            return
        self._network_worker_stop.clear()
        self._network_worker = threading.Thread(
            target=self._network_usage_loop,
            name="tuxindrive-network-meter",
            daemon=True,
        )
        self._network_worker.start()

    def _network_usage_loop(self) -> None:
        while not self._network_worker_stop.is_set():
            self._network_sample_request.wait()
            self._network_sample_request.clear()
            if self._network_worker_stop.is_set():
                return
            try:
                usage, error = self.controller.network_meter.sample(), None
            except Exception as exc:
                usage, error = None, exc
            GLib.idle_add(self._network_usage_ready, usage, error)

    def _network_usage_ready(self, usage, error: Exception | None) -> bool:
        self._network_refreshing = False
        if self._network_active and usage is not None and error is None:
            self._render_network_usage(usage)
        return False

    def _stop_network_usage(self, *_args) -> None:
        self._network_active = False
        self._network_worker_stop.set()
        self._network_sample_request.set()
        if self._network_source:
            GLib.source_remove(self._network_source)
            self._network_source = 0

    def set_network_meter_enabled(self, enabled: bool) -> None:
        self.controller.config.settings.show_network_usage = enabled
        self.network_strip.set_no_show_all(not enabled)
        self.network_strip.set_visible(enabled)
        if enabled:
            self._start_network_worker()
            self._render_network_usage(self.controller.network_meter.usage)
            if not self._network_source and self._network_active:
                self._network_source = GLib.timeout_add_seconds(
                    1, self._refresh_network_usage
                )
        elif self._network_source:
            GLib.source_remove(self._network_source)
            self._network_source = 0

    def _hide_network_usage(self, _button: Gtk.Widget) -> None:
        self.set_network_meter_enabled(False)
        self.controller.save()

    def set_activity_log_enabled(self, enabled: bool) -> None:
        self.controller.config.settings.show_live_activity_log = enabled
        self.activity_panel.set_no_show_all(not enabled)
        self.activity_panel.set_visible(enabled)
        if enabled:
            self.activity_panel.set_expanded(True)
            self._refresh_activity_log()
        else:
            self.activity_panel.set_expanded(False)
            self._activity_files.clear()
            self._activity_content = ""
            self.activity_view.get_buffer().set_text("")

    def _hide_activity_log(self, _button: Gtk.Widget) -> None:
        self.set_activity_log_enabled(False)
        self.controller.save()

    def _render_network_usage(self, usage) -> None:
        if not usage.available:
            for value in self.network_values.values():
                value.set_text(tr("unavailable"))
            return
        self.network_values["download_rate"].set_text(format_bytes(usage.download_rate, rate=True))
        self.network_values["upload_rate"].set_text(format_bytes(usage.upload_rate, rate=True))
        self.network_values["download_today"].set_text(format_bytes(usage.downloaded_today))
        self.network_values["upload_today"].set_text(format_bytes(usage.uploaded_today))

    def apply_visual_theme(self, key: str) -> None:
        """Apply the small structural differences that CSS alone cannot express."""
        if normalize_theme(key) == "bento_cloud":
            self.summary_strip.show_all()
        else:
            self.summary_strip.hide()

    def _language_changed(self, combo: Gtk.ComboBoxText) -> None:
        code = combo.get_active_id() or "en"
        if code != get_language():
            self.controller.change_language(code)

    def refresh(self) -> None:
        """Coalesce bursts of state notifications into one GTK update."""
        if not self._refresh_source:
            self._refresh_source = GLib.timeout_add(75, self._run_scheduled_refresh)

    def _run_scheduled_refresh(self) -> bool:
        self._refresh_source = 0
        self._refresh_now()
        return False

    def _structure_signature(self) -> tuple:
        return (
            tuple((item.remote, item.display_name, item.provider.value) for item in self.controller.config.accounts),
            tuple((item.id, item.name, item.collapsed) for item in self.controller.config.folder_groups),
            tuple(
                (job.id, job.name, job.account_remote, job.local_path, job.remote_path,
                 job.remote_scope, job.cloud_location_name, job.mode.value, job.group_id,
                 job.repository_url, job.repository_branch, tuple(job.offline_paths))
                for job in self.controller.config.jobs
            ),
        )

    def _update_dynamic_rows(self) -> None:
        self.summary_values["services"].set_text(str(len(self.controller.config.accounts)))
        self.summary_values["active"].set_text(str(len(self.controller.engine.running_jobs)))
        self.summary_values["protected"].set_text(str(len(self.controller.config.jobs)))
        running = self.controller.engine.running_jobs
        mounted = self.controller.engine.mounted_jobs
        for account in self.controller.config.accounts:
            widgets = self._account_widgets.get(account.remote)
            if not widgets:
                continue
            jobs = [job for job in self.controller.config.jobs if job.account_remote == account.remote]
            state = (
                tr("synchronizing") if any(job.id in running for job in jobs) else
                tr("attention") if any(job.last_error for job in jobs) else tr("connected")
            )
            widgets["label"].set_markup(
                f"<b>{GLib.markup_escape_text(account.display_name)}</b>\n"
                f"<small>{account.provider.label} · {state}</small>"
            )
            widgets["icon"].set_tooltip_text(f"{account.provider.label} · {state}")
        for job in self.controller.config.jobs:
            widgets = self._job_widgets.get(job.id)
            if not widgets:
                continue
            widgets["status"].set_text(job.last_status)
            toggle = widgets["toggle"]
            if toggle.get_active() != job.enabled:
                toggle.handler_block(widgets["toggle_handler"])
                try:
                    toggle.set_active(job.enabled)
                finally:
                    toggle.handler_unblock(widgets["toggle_handler"])
            widgets["sync"].set_label(
                tr("open_drive") if job.id in mounted else
                tr("start_streaming") if job.mode is SyncMode.VIRTUAL_DRIVE else tr("sync_now")
            )

    def _refresh_now(self) -> None:
        signature = self._structure_signature()
        if signature == self._render_signature:
            self._update_dynamic_rows()
            self.apply_visual_theme(self.controller.config.settings.visual_theme)
            self.infobar.hide()
            return
        self._render_signature = signature
        self._job_widgets.clear()
        self._account_widgets.clear()
        self._update_dynamic_rows()
        for child in self.account_list.get_children():
            self.account_list.remove(child)
        for account in self.controller.config.accounts:
            row = Gtk.ListBoxRow()
            row.get_style_context().add_class("account-card")
            box = Gtk.Box(spacing=10)
            box.set_border_width(8)
            account_jobs = [
                job for job in self.controller.config.jobs if job.account_remote == account.remote
            ]
            if any(job.id in self.controller.engine.running_jobs for job in account_jobs):
                account_state = tr("synchronizing")
            elif any(job.last_error for job in account_jobs):
                account_state = tr("attention")
            else:
                account_state = tr("connected")
            icon = Gtk.Image.new_from_icon_name(account.provider.icon_name, Gtk.IconSize.DND)
            icon.set_tooltip_text(f"{account.provider.label} · {account_state}")
            text = Gtk.Label(xalign=0)
            text.set_markup(
                f"<b>{GLib.markup_escape_text(account.display_name)}</b>\n"
                f"<small>{account.provider.label} · {account_state}</small>"
            )
            menu = Gtk.MenuButton()
            menu.set_image(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
            popup = Gtk.Menu()
            online = Gtk.MenuItem(label=tr("peer_settings") if account.provider is Provider.PEER else tr("open_online"))
            online.connect("activate", self._open_online, account)
            reconnect = Gtk.MenuItem(label=tr("reconnect"))
            reconnect.connect("activate", self._reconnect, account)
            remove = Gtk.MenuItem(label=tr("remove_account"))
            remove.connect("activate", self._remove_account, account)
            popup.append(online)
            popup.append(reconnect)
            popup.append(remove)
            popup.show_all()
            menu.set_popup(popup)
            self._account_widgets[account.remote] = {"label": text, "icon": icon}
            box.pack_start(icon, False, False, 0)
            box.pack_start(text, True, True, 0)
            box.pack_end(menu, False, False, 0)
            row.add(box)
            self.account_list.add(row)

        for child in self.job_list.get_children():
            self.job_list.remove(child)
        if not self.controller.config.jobs and not self.controller.config.folder_groups:
            empty = Gtk.Label(
                label=tr("empty_jobs")
            )
            empty.set_margin_top(60)
            empty.get_style_context().add_class("dim-label")
            self.job_list.add(empty)
        valid_groups = {item.id for item in self.controller.config.folder_groups}
        for group in self.controller.config.folder_groups:
            self.job_list.add(self._group_row(group))
            if not group.collapsed:
                for job in self.controller.config.jobs:
                    if job.group_id == group.id:
                        self.job_list.add(self._job_row(job))
        ungrouped = [
            job for job in self.controller.config.jobs
            if not job.group_id or job.group_id not in valid_groups
        ]
        if ungrouped and self.controller.config.folder_groups:
            self.job_list.add(self._group_row(None))
        for job in ungrouped:
            self.job_list.add(self._job_row(job))
        self.show_all()
        self.apply_visual_theme(self.controller.config.settings.visual_theme)
        self.infobar.hide()

    def _group_row(self, group: FolderGroup | None) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.get_style_context().add_class("group-card")
        row.set_activatable(False)
        box = Gtk.Box(spacing=10)
        box.set_border_width(10)
        icon = Gtk.Image.new_from_icon_name("folder-symbolic", Gtk.IconSize.BUTTON)
        name = Gtk.Label(xalign=0)
        name.set_markup(
            f"<b>{GLib.markup_escape_text(group.name if group else tr('ungrouped'))}</b>"
        )
        box.pack_start(icon, False, False, 0)
        box.pack_start(name, False, False, 0)
        if group:
            group_jobs = [job for job in self.controller.config.jobs if job.group_id == group.id]
            if group.collapsed:
                icons = Gtk.Box(spacing=5)
                for job in group_jobs:
                    account = next(
                        (item for item in self.controller.config.accounts if item.remote == job.account_remote),
                        None,
                    )
                    provider_icon = Gtk.Image.new_from_icon_name(
                        account.provider.icon_name if account else "folder-remote-symbolic",
                        Gtk.IconSize.MENU,
                    )
                    provider_icon.set_tooltip_text(
                        f"{job.name} · {account.provider.label if account else tr('cloud_storage')}"
                    )
                    icons.pack_start(provider_icon, False, False, 0)
                box.pack_start(icons, False, False, 0)
            spacer = Gtk.Box()
            box.pack_start(spacer, True, True, 0)
            collapse = Gtk.Button.new_from_icon_name(
                "pan-end-symbolic" if group.collapsed else "pan-down-symbolic",
                Gtk.IconSize.BUTTON,
            )
            collapse.set_tooltip_text(tr("expand_group") if group.collapsed else tr("minimize_group"))
            collapse.connect("clicked", self._toggle_group, group)
            rename = Gtk.Button.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.BUTTON)
            rename.set_tooltip_text("Rename group")
            rename.connect("clicked", self._rename_group, group)
            delete = Gtk.Button.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.BUTTON)
            delete.set_tooltip_text("Delete group; synchronized folders become ungrouped")
            delete.connect("clicked", self._delete_group, group)
            box.pack_end(delete, False, False, 0)
            box.pack_end(rename, False, False, 0)
            box.pack_end(collapse, False, False, 0)
        else:
            spacer = Gtk.Box()
            box.pack_start(spacer, True, True, 0)
        row.add(box)
        self._enable_job_drop_target(row, group.id if group else "")
        row.set_tooltip_text(tr("drop_group_hint"))
        return row

    def _job_row(self, job: SyncJob) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.get_style_context().add_class("job-card")
        mounted = job.id in self.controller.engine.mounted_jobs
        account = next((item for item in self.controller.config.accounts if item.remote == job.account_remote), None)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_border_width(14)
        top = Gtk.Box(spacing=12)
        drag_handle = Gtk.EventBox()
        drag_handle.get_style_context().add_class("drag-handle")
        drag_handle.set_visible_window(False)
        drag_handle.set_above_child(True)
        drag_handle.set_size_request(32, 32)
        drag_icon = Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON)
        drag_handle.add(drag_icon)
        drag_handle.set_tooltip_text(tr("drag_folder_hint"))
        top.pack_start(drag_handle, False, False, 0)
        icon_name = account.provider.icon_name if account else "folder-remote-symbolic"
        job_icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.DND)
        job_icon.set_tooltip_text(account.provider.label if account else tr("cloud_storage"))
        top.pack_start(job_icon, False, False, 0)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(xalign=0)
        title.set_markup(f"<b>{GLib.markup_escape_text(job.name)}</b>")
        detail = Gtk.Label(
            label=(
                f"{job.mode.label} · "
                + (
                    f"{job.cloud_location_name} · {job.repository_branch}"
                    if job.is_git else
                    f"{job.cloud_location_name or job.account_remote}:/{job.remote_path}"
                )
                + f"  →  {job.local_path}"
            ),
            xalign=0,
        )
        detail.set_ellipsize(3)
        status = Gtk.Label(label=job.last_status, xalign=0)
        status.get_style_context().add_class("dim-label")
        status.get_style_context().add_class("status-label")
        labels.pack_start(title, False, False, 0)
        labels.pack_start(detail, False, False, 0)
        labels.pack_start(status, False, False, 0)
        top.pack_start(labels, True, True, 0)
        toggle = Gtk.Switch(active=job.enabled)
        toggle.set_name("tuxindrive-job-switch")
        toggle.set_size_request(46, 26)
        toggle.set_hexpand(False)
        toggle.set_vexpand(False)
        toggle.set_valign(Gtk.Align.CENTER)
        toggle.set_halign(Gtk.Align.END)
        toggle.set_tooltip_text(tr("automatic_sync"))
        toggle_handler = toggle.connect("notify::active", self._toggle_job, job)
        top.pack_end(toggle, False, False, 0)
        outer.pack_start(top, False, False, 0)
        actions = Gtk.Box(spacing=8)
        sync = Gtk.Button(label=(
            tr("open_drive") if mounted else
            tr("start_streaming") if job.mode is SyncMode.VIRTUAL_DRIVE else
            tr("sync_now")
        ))
        if job.mode is SyncMode.VIRTUAL_DRIVE:
            sync.set_tooltip_text(
                tr("stream_hint")
            )
        sync.connect(
            "clicked",
            lambda _button: (
                self._open_path(job.local)
                if mounted
                else self.controller.run_job(job)
            ),
        )
        cancel = Gtk.Button(
            label=tr("disconnect") if job.mode is SyncMode.VIRTUAL_DRIVE else tr("stop")
        )
        cancel.connect("clicked", lambda _button: self.controller.stop_job(job))
        availability_button = None
        if job.mode is SyncMode.VIRTUAL_DRIVE:
            keep_offline = not bool(job.offline_paths)
            availability_button = Gtk.Button(label=(
                tr("keep_drive_offline") if keep_offline else tr("make_drive_online_only")
            ))
            availability_button.set_tooltip_text(
                tr("keep_drive_offline_hint") if keep_offline else tr("make_drive_online_only_hint")
            )
            availability_button.connect(
                "clicked",
                lambda _button, available=keep_offline: self.controller._request_offline_path(
                    str(job.local), available
                ),
            )
        open_button = Gtk.Button(label=tr("open_folder"))
        open_button.connect("clicked", lambda _button: self._open_path(job.local))
        log_button = Gtk.Button(label=tr("view_log"))
        log_button.connect("clicked", lambda _button: self._open_path(cache_root() / "logs"))
        error_button = Gtk.Button(label=tr("error_details"))
        error_button.set_tooltip_text("Show the last error immediately without loading conflicts")
        error_button.connect("clicked", lambda _button: ErrorDetailsDialog(self, job))
        edit_button = Gtk.Button(label=tr("edit"))
        edit_button.connect("clicked", self._edit_job, job)
        rename_button = Gtk.Button(label=tr("rename"))
        rename_button.set_tooltip_text("Change only the name displayed in TuxInDrive")
        rename_button.connect("clicked", self._rename_job, job)
        group_button = Gtk.Button(label=tr("group"))
        group_button.set_tooltip_text("Move this entry to an internal TuxInDrive group")
        group_button.connect("clicked", self._move_to_group, job)
        online_button = Gtk.Button(label=tr("open_online_folder"))
        online_button.set_tooltip_text(
            "Open this synchronized folder at its provider without creating a public share link"
        )
        online_button.connect(
            "clicked", lambda _button: self.controller._open_online_path(str(job.local))
        )
        online_button.set_sensitive(bool(account and account.provider not in {Provider.PEER, Provider.VAULT}))
        if not online_button.get_sensitive():
            online_button.set_tooltip_text(
                "Peer folders and encrypted vaults have no safe provider web location"
            )
        share_button = Gtk.Button(label=tr("share_link"))
        share_button.set_tooltip_text(
            "Create a provider-managed public link after explicit confirmation"
        )
        share_button.set_sensitive(bool(
            account and capabilities_for(account.provider).share_links and not job.is_git
        ))
        share_button.connect(
            "clicked", lambda _button: self.controller._create_share_link(job)
        )
        history_button = Gtk.Button(label=tr("history"))
        history_button.set_tooltip_text("Restore locally retained versions and recycled files")
        history_button.connect(
            "clicked",
            lambda _button: (
                webbrowser.open(repository_item_url(job.repository_url, job.repository_branch).replace("/tree/", "/commits/"))
                if job.is_git else RecoveryHistoryDialog(self, self.controller, job)
            ),
        )
        verify_button = Gtk.Button(label=tr("verify"))
        verify_button.set_tooltip_text("Compare content and repair selected integrity differences")
        verify_button.connect("clicked", lambda _button: IntegrityDialog(self, self.controller, job))
        verify_button.set_sensitive(not job.is_git)
        if job.is_git:
            verify_button.set_tooltip_text("GitHub verifies transferred objects; use Git status and history for repository integrity")
        conflicts_button = Gtk.Button(label=tr("conflicts"))
        conflicts_button.connect("clicked", lambda _button: IntegrityDialog(self, self.controller, job, True))
        conflicts_button.set_sensitive(not job.is_git)
        remove = Gtk.Button.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.BUTTON)
        remove.set_tooltip_text(tr("remove_sync"))
        remove.connect("clicked", self._remove_job, job)
        for widget in (sync, cancel, availability_button, open_button, online_button, share_button, history_button, verify_button, conflicts_button, group_button, rename_button, edit_button, log_button, error_button):
            if widget is None:
                continue
            actions.pack_start(widget, False, False, 0)
        actions.pack_end(remove, False, False, 0)
        actions_scroll = Gtk.ScrolledWindow()
        actions_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        actions_scroll.set_min_content_width(1)
        actions_scroll.set_propagate_natural_width(False)
        actions_scroll.set_shadow_type(Gtk.ShadowType.NONE)
        actions_scroll.add(actions)
        outer.pack_start(actions_scroll, False, False, 0)
        row.add(outer)
        self._job_widgets[job.id] = {
            "status": status, "toggle": toggle, "toggle_handler": toggle_handler,
            "sync": sync,
        }
        self._enable_job_drag_source(drag_handle, job)
        self._enable_job_drop_target(row, job.group_id, job)
        return row

    @staticmethod
    def _job_drag_targets() -> list[Gtk.TargetEntry]:
        # Gtk.SelectionData.set_text()/get_text() only support recognized text
        # targets. The former private MIME target caused every real GTK drop to
        # arrive without a job id even though the pointer drag had started.
        return [Gtk.TargetEntry.new(JOB_DND_TARGET, Gtk.TargetFlags.SAME_APP, 0)]

    def _enable_job_drag_source(self, widget: Gtk.Widget, job: SyncJob) -> None:
        widget.drag_source_set(
            Gdk.ModifierType.BUTTON1_MASK,
            self._job_drag_targets(),
            Gdk.DragAction.MOVE,
        )
        widget.drag_source_set_icon_name("open-menu-symbolic")
        widget.connect("drag-data-get", self._job_drag_data_get, job.id)

    def _enable_job_drop_target(
        self,
        row: Gtk.ListBoxRow,
        group_id: str,
        anchor: SyncJob | None = None,
    ) -> None:
        row.drag_dest_set(
            Gtk.DestDefaults.ALL,
            self._job_drag_targets(),
            Gdk.DragAction.MOVE,
        )
        row.connect("drag-data-received", self._job_drag_data_received, group_id, anchor)

    def _job_drag_data_get(
        self,
        _widget: Gtk.Widget,
        _context: Gdk.DragContext,
        selection: Gtk.SelectionData,
        _info: int,
        _time: int,
        job_id: str,
    ) -> None:
        payload = job_drag_payload(job_id)
        if payload:
            selection.set_text(payload, -1)

    def _job_drag_data_received(
        self,
        row: Gtk.ListBoxRow,
        context: Gdk.DragContext,
        _x: int,
        y: int,
        selection: Gtk.SelectionData,
        _info: int,
        time: int,
        group_id: str,
        anchor: SyncJob | None,
    ) -> None:
        job_id = job_id_from_drag_payload(selection.get_text())
        valid = any(job.id == job_id for job in self.controller.config.jobs)
        changed = False
        if valid:
            after = bool(anchor and y >= max(row.get_allocated_height(), 1) / 2)
            changed = move_job(
                self.controller.config.jobs,
                self.controller.config.folder_groups,
                job_id,
                group_id,
                anchor_job_id=anchor.id if anchor else "",
                after=after,
            )
        Gtk.drag_finish(context, valid, False, time)
        if changed:
            self.controller.save()
            self.refresh()

    def _choose_provider(self, _button: Gtk.Widget) -> None:
        dialog = ResponsiveDialog(title=tr("choose_provider"), transient_for=self, modal=True)
        dialog.set_default_size(560, 360)
        area = dialog.get_content_area()
        area.set_border_width(24)
        prompt = Gtk.Label(xalign=0)
        prompt.set_markup(f"<span size='large' weight='bold'>{GLib.markup_escape_text(tr('choose_provider_heading'))}</span>\n<small>{GLib.markup_escape_text(tr('provider_hint'))}</small>")
        area.pack_start(prompt, False, False, 8)
        grid = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)
        providers = [
            provider for provider in Provider
            if provider not in {Provider.PEER, Provider.VAULT}
            and self.controller.managed_policy.provider_allowed(provider)
        ]
        for index, provider in enumerate(providers, start=1):
            button = Gtk.Button(label=provider.label)
            button.set_image(Gtk.Image.new_from_icon_name(provider.icon_name, Gtk.IconSize.DND))
            button.set_always_show_image(True)
            button.set_hexpand(True)
            button.connect("clicked", lambda _button, response=index: dialog.response(response))
            grid.attach(button, (index - 1) % 2, (index - 1) // 2, 1, 1)
        area.pack_start(grid, True, True, 8)
        if not providers:
            restricted = Gtk.Label(
                label="No cloud provider is permitted by the managed desktop policy.",
                xalign=0,
            )
            restricted.get_style_context().add_class("warning")
            area.pack_start(restricted, False, False, 8)
        vault_response = len(providers) + 1
        vault = Gtk.Button(label=tr("create_vault"))
        vault.set_image(Gtk.Image.new_from_icon_name(Provider.VAULT.icon_name, Gtk.IconSize.DND))
        vault.set_always_show_image(True)
        vault.connect("clicked", lambda _button: dialog.response(vault_response))
        if self.controller.managed_policy.provider_allowed(Provider.VAULT):
            area.pack_start(vault, False, False, 8)
        dialog.add_button(tr("cancel"), Gtk.ResponseType.CANCEL)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if 1 <= response <= len(providers):
            provider = providers[response - 1]
            if provider is Provider.GITHUB:
                self._configure_github()
            elif provider is Provider.PROTON_DRIVE:
                ProtonAuthDialog(
                    self,
                    self.controller.proton,
                    self.controller.add_account,
                    self.controller.config.accounts,
                )
            else:
                OAuthWizard(self, self.controller.rclone, provider, self.controller.add_account)
        elif response == vault_response:
            vault_dialog = VaultDialog(self, self.controller)
            if vault_dialog.run() == Gtk.ResponseType.OK:
                try:
                    self.controller.add_account(vault_dialog.create())
                except (RcloneError, OSError) as exc:
                    self.message(f"Vault creation failed safely: {exc}", Gtk.MessageType.ERROR)
            vault_dialog.destroy()

    def _configure_github(
        self, account: Account | None = None, job: SyncJob | None = None
    ) -> None:
        dialog = GitHubSyncDialog(
            self, self.controller.config.folder_groups, account=account, job=job
        )
        if dialog.run() == Gtk.ResponseType.OK:
            try:
                updated_account, updated_job = dialog.values()
                duplicate_path = next(
                    (
                        item for item in self.controller.config.jobs
                        if item.id != updated_job.id and paths_overlap(item.local_path, updated_job.local_path)
                    ),
                    None,
                )
                if duplicate_path:
                    raise GitHubSyncError(
                        f"The local folder overlaps synchronized folder ‘{duplicate_path.name}’"
                    )
                duplicate_account = next(
                    (
                        item for item in self.controller.config.accounts
                        if item.remote == updated_account.remote and (not account or item.remote != account.remote)
                    ),
                    None,
                )
                if duplicate_account:
                    raise GitHubSyncError("This repository and branch are already connected")
                if job and account:
                    self.controller.stop_job(job)
                    self.controller.config.accounts[
                        self.controller.config.accounts.index(account)
                    ] = updated_account
                    self.controller.config.jobs[
                        self.controller.config.jobs.index(job)
                    ] = updated_job
                else:
                    self.controller.config.accounts.append(updated_account)
                    self.controller.config.jobs.append(updated_job)
                self.controller.save()
                self.controller.reconfigure_callbacks()
                self.refresh()
                self.controller.run_job(updated_job)
            except (GitHubSyncError, OSError, ValueError) as exc:
                self.message(str(exc), Gtk.MessageType.ERROR)
        dialog.destroy()

    def _create_group(self, _button: Gtk.Widget) -> None:
        name = self._group_name_dialog("Create group", "Create")
        if name:
            self.controller.config.folder_groups.append(FolderGroup(name=name))
            self.controller.save()
            self.refresh()

    def _rename_group(self, _button: Gtk.Widget, group: FolderGroup) -> None:
        name = self._group_name_dialog("Rename group", "Rename", group.name)
        if name:
            group.name = name
            self.controller.save()
            self.refresh()

    def _toggle_group(self, _button: Gtk.Widget, group: FolderGroup) -> None:
        group.collapsed = not group.collapsed
        self.controller.save()
        self.refresh()

    def _group_name_dialog(self, title: str, action: str, value: str = "") -> str:
        dialog = ResponsiveDialog(title=title, transient_for=self, modal=True)
        area = dialog.get_content_area()
        area.set_border_width(20)
        entry = Gtk.Entry()
        entry.set_text(value)
        entry.set_placeholder_text("Example: Work, Personal, Customers")
        entry.set_activates_default(True)
        area.pack_start(Gtk.Label(label="Group name", xalign=0), False, False, 6)
        area.pack_start(entry, False, False, 0)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button(action, Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.show_all()
        name = entry.get_text().strip() if dialog.run() == Gtk.ResponseType.OK else ""
        dialog.destroy()
        if name and any(
            item.name.casefold() == name.casefold() and item.name != value
            for item in self.controller.config.folder_groups
        ):
            self.message("A group with this name already exists.", Gtk.MessageType.WARNING)
            return ""
        if not name and value:
            self.message("The group name cannot be empty.", Gtk.MessageType.WARNING)
        return name

    def _delete_group(self, _button: Gtk.Widget, group: FolderGroup) -> None:
        if not self._confirm(
            f"Delete group ‘{group.name}’? Its synchronized folders will become ungrouped; no files are moved or deleted."
        ):
            return
        for job in self.controller.config.jobs:
            if job.group_id == group.id:
                job.group_id = ""
        self.controller.config.folder_groups.remove(group)
        self.controller.save()
        self.refresh()

    def _move_to_group(self, _button: Gtk.Widget, job: SyncJob) -> None:
        dialog = ResponsiveDialog(title="Move to group", transient_for=self, modal=True)
        area = dialog.get_content_area()
        area.set_border_width(20)
        combo = Gtk.ComboBoxText()
        combo.append("", "Ungrouped")
        for group in self.controller.config.folder_groups:
            combo.append(group.id, group.name)
        combo.set_active_id(job.group_id if any(group.id == job.group_id for group in self.controller.config.folder_groups) else "")
        area.pack_start(Gtk.Label(label="Internal TuxInDrive group", xalign=0), False, False, 6)
        area.pack_start(combo, False, False, 0)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Move", Gtk.ResponseType.OK)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            job.group_id = combo.get_active_id() or ""
            self.controller.save()
            self.refresh()
        dialog.destroy()

    def _add_job(self, _button: Gtk.Widget) -> None:
        accounts = [
            item for item in self.controller.config.accounts
            if item.provider is not Provider.GITHUB
        ]
        if not accounts:
            self.message("Connect a cloud account first.", Gtk.MessageType.WARNING)
            return
        dialog = SyncJobDialog(self, self.controller.cloud_browser, accounts)
        while dialog.run() == Gtk.ResponseType.OK:
            jobs = dialog.jobs()
            existing_jobs = list(self.controller.config.jobs)
            if not jobs:
                dialog.validation_error("Select at least one cloud folder.")
                continue
            elif any(
                paths_overlap(job.local_path, item.local_path)
                and not safe_streaming_overlap(job, item)
                for job in jobs
                for item in existing_jobs
            ):
                dialog.validation_error(
                    "That folder overlaps another job in an unsafe direction. A streaming drive may be an empty child folder of a normal sync job.",
                )
                continue
            else:
                self.controller.config.jobs.extend(jobs)
                self.controller.save()
                self.controller.reconfigure_callbacks()
                self.refresh()
                for job in jobs:
                    self.controller.run_job(job)
                break
        dialog.destroy()

    def _toggle_job(self, switch: Gtk.Switch, _property, job: SyncJob) -> None:
        job.enabled = switch.get_active()
        self.controller.save()
        if not job.enabled:
            self.controller.stop_job(job)
        elif job.initialized:
            self.controller.start_callbacks(job)

    def _edit_job(self, _button: Gtk.Button, job: SyncJob) -> None:
        if job.is_git:
            account = next(
                (item for item in self.controller.config.accounts if item.remote == job.account_remote),
                None,
            )
            if not account:
                self.message("The GitHub account for this job is missing.", Gtk.MessageType.ERROR)
                return
            self._configure_github(account, job)
            return
        dialog = SyncJobDialog(
            self, self.controller.cloud_browser, self.controller.config.accounts, existing=job
        )
        while dialog.run() == Gtk.ResponseType.OK:
            values = dialog.jobs()
            if not values:
                dialog.validation_error("Select one cloud folder.")
                continue
            updated = values[0]
            duplicate = any(
                item.id != job.id
                and paths_overlap(item.local_path, updated.local_path)
                and not safe_streaming_overlap(updated, item)
                for item in self.controller.config.jobs
            )
            if duplicate:
                dialog.validation_error(
                    "Unsafe overlap. A streaming drive may be an empty child folder of a normal sync job, but not its parent.",
                )
                continue
            else:
                index = self.controller.config.jobs.index(job)
                if (job.local_path, job.remote_spec, job.mode) != (
                    updated.local_path,
                    updated.remote_spec,
                    updated.mode,
                ):
                    updated.initialized = False
                self.controller.stop_job(job)
                self.controller.config.jobs[index] = updated
                self.controller.save()
                self.controller.reconfigure_callbacks()
                self.refresh()
                break
        dialog.destroy()

    def _rename_job(self, _button: Gtk.Button, job: SyncJob) -> None:
        dialog = ResponsiveDialog(title="Rename synchronized folder", transient_for=self, modal=True)
        area = dialog.get_content_area()
        area.set_border_width(20)
        area.set_spacing(10)
        label = Gtk.Label(
            label="This changes only the name shown in TuxInDrive. Cloud and local folder names stay unchanged.",
            xalign=0,
        )
        label.set_line_wrap(True)
        entry = Gtk.Entry()
        entry.set_text(job.name)
        entry.set_activates_default(True)
        area.pack_start(label, False, False, 0)
        area.pack_start(entry, False, False, 0)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        save = dialog.add_button("Rename", Gtk.ResponseType.OK)
        save.get_style_context().add_class("suggested-action")
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            name = entry.get_text().strip()
            if name:
                job.name = name
                self.controller.save()
                self.refresh()
            else:
                self.message("The displayed name cannot be empty.", Gtk.MessageType.WARNING)
        dialog.destroy()

    def _remove_job(self, _button: Gtk.Button, job: SyncJob) -> None:
        if not self._confirm(f"Stop and remove ‘{job.name}’? Local and cloud files will not be deleted."):
            return
        self.controller.stop_job(job)
        self.controller.config.jobs.remove(job)
        self.controller.save()
        self.controller.reconfigure_callbacks()
        self.refresh()

    def _remove_account(self, _item: Gtk.MenuItem, account: Account) -> None:
        if any(job.account_remote == account.remote for job in self.controller.config.jobs):
            self.message("Remove synchronized folders using this account first.", Gtk.MessageType.WARNING)
            return
        if not self._confirm(f"Remove {account.display_name} and its local authorization?"):
            return
        if account.provider is Provider.PROTON_DRIVE and account.backend == "proton_cli":
            try:
                self.controller.proton.logout()
            except ProtonDriveError as exc:
                self.message(str(exc), Gtk.MessageType.ERROR)
                return
        elif account.provider is not Provider.GITHUB:
            try:
                self.controller.rclone.delete_remote(account.remote)
            except RcloneError as exc:
                self.message(str(exc), Gtk.MessageType.ERROR)
                return
        self.controller.config.accounts.remove(account)
        self.controller.save()
        self.refresh()

    def _open_online(self, _item: Gtk.MenuItem, account: Account) -> None:
        if account.provider is Provider.PEER:
            self._show_peer_sharing(_item)
            return
        if account.provider is Provider.GITHUB:
            webbrowser.open(repository_item_url(account.repository_url, account.repository_branch))
            return
        if account.provider.home_url:
            webbrowser.open(account.provider.home_url)
        elif account.provider is Provider.VAULT:
            self.message("Encrypted vaults have no unencrypted provider website. Open the backing account only to inspect ciphertext.")
        else:
            self.message("This Nextcloud account uses its configured server URL.")

    def _reconnect(self, _item: Gtk.MenuItem, account: Account) -> None:
        if account.provider is Provider.PEER:
            self._show_peer_sharing(_item)
            return
        if account.provider is Provider.GITHUB:
            job = next(
                (item for item in self.controller.config.jobs if item.account_remote == account.remote),
                None,
            )
            if job:
                self._configure_github(account, job)
            return
        if account.provider is Provider.VAULT:
            self.message("Vault keys cannot be refreshed or recovered. Create a new vault to change its encryption credentials.", Gtk.MessageType.WARNING)
            return
        if account.provider is Provider.PROTON_DRIVE:
            ProtonAuthDialog(
                self,
                self.controller.proton,
                self.controller.add_account,
                self.controller.config.accounts,
                existing=account,
            )
            return
        if not account.provider.browser_oauth:
            OAuthWizard(
                self, self.controller.rclone, account.provider,
                self.controller.add_account, existing=account,
            )
            return
        self.message("Authorization is opening in your browser…", Gtk.MessageType.INFO)
        _run_thread(self.controller.rclone.reconnect, self._reconnect_done, account.remote)

    def _reconnect_done(self, _result, error: Exception | None) -> bool:
        self.message(str(error) if error else "Account authorization refreshed.", Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO)
        return False

    def _show_settings(self, _button: Gtk.Widget) -> None:
        dialog = ResponsiveDialog(title="TuxInDrive settings", transient_for=self, modal=True)
        _set_window_brand_icon(dialog)
        dialog.set_default_size(580, 700)
        dialog.get_style_context().add_class("tuxindrive-dialog")
        dialog.get_content_area().set_border_width(24)
        identity = Gtk.Box(spacing=12)
        identity.pack_start(_brand_image(Gtk.IconSize.DIALOG), False, False, 0)
        version = Gtk.Label(xalign=0)
        version.set_markup(f"<b>TuxInDrive {GLib.markup_escape_text(__version__)}</b>\n<small>Cloud desktop client</small>")
        identity.pack_start(version, True, True, 0)
        dialog.get_content_area().pack_start(identity, False, False, 6)
        launch = Gtk.CheckButton(label="Start TuxInDrive automatically after sign-in")
        launch.set_active(self.controller.config.settings.launch_at_login)
        notifications = Gtk.CheckButton(label="Show desktop notifications")
        notifications.set_active(self.controller.config.settings.notifications)
        minimized = Gtk.CheckButton(label="Start minimized")
        minimized.set_active(self.controller.config.settings.start_minimized)
        nautilus = Gtk.CheckButton(label="Enable Nautilus integration (restart Files after changing)")
        nautilus.set_active(self.controller.config.settings.nautilus_integration)
        network_usage = Gtk.CheckButton(label="Show current and daily network usage")
        network_usage.set_active(self.controller.config.settings.show_network_usage)
        live_activity = Gtk.CheckButton(label="Show and render the Live activity log")
        live_activity.set_active(self.controller.config.settings.show_live_activity_log)
        server_integration = Gtk.CheckButton(label="Enable TuxInDrive server integration (preview)")
        server_integration.set_active(self.controller.config.settings.server_integration_enabled)
        server_url = Gtk.Entry()
        server_url.set_placeholder_text("Server URL, for example https://server.example:9443")
        server_url.set_text(self.controller.config.settings.server_url)
        server_token = Gtk.Entry()
        server_token.set_visibility(False)
        server_token.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        server_token.set_placeholder_text("API token (leave blank to keep the stored token)")
        server_ca = Gtk.Entry()
        server_ca.set_placeholder_text("Optional private CA certificate path")
        server_ca.set_text(self.controller.config.settings.server_ca_file)
        server_hint = Gtk.Label(
            label=(
                "Disabled by default. When enabled, TuxInDrive can contact your self-hosted "
                "server for health, encrypted mailbox/object/rendezvous/collaboration roles, "
                "and headless job status. The API token is stored in the native credential store."
            ),
            xalign=0,
        )
        server_hint.set_line_wrap(True)
        theme_frame = Gtk.Frame(label=tr("visual_style"))
        theme_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        theme_box.set_border_width(12)
        theme = Gtk.ComboBoxText()
        for visual_theme in THEMES:
            theme.append(visual_theme.key, visual_theme.label)
        theme.set_active_id(normalize_theme(self.controller.config.settings.visual_theme))
        theme_description = Gtk.Label(xalign=0)
        theme_description.set_line_wrap(True)
        theme_description.get_style_context().add_class("theme-description")

        def update_theme_description(combo: Gtk.ComboBoxText) -> None:
            selected = theme_by_key(combo.get_active_id())
            theme_description.set_text(selected.description + " " + tr("theme_applies_after_save"))

        theme.connect("changed", update_theme_description)
        update_theme_description(theme)
        theme_box.pack_start(theme, False, False, 0)
        theme_box.pack_start(theme_description, False, False, 0)
        theme_frame.add(theme_box)
        policy = Gtk.ComboBoxText()
        policy.append("maximum", "Maximum usage (no policy limits)")
        policy.append("controlled", "Apply network, battery and schedule policies")
        policy.set_active_id(self.controller.config.settings.network_policy)
        metered = Gtk.CheckButton(label="Allow synchronization on metered networks")
        metered.set_active(self.controller.config.settings.allow_metered_networks)
        global_bandwidth = Gtk.Entry()
        global_bandwidth.set_placeholder_text("Global bandwidth, e.g. 10M or 2M:10M")
        global_bandwidth.set_text(
            self.controller.config.settings.global_bandwidth_limit
        )
        automatic_bandwidth = Gtk.CheckButton(
            label="Automatically reserve bandwidth for other applications"
        )
        automatic_bandwidth.set_active(
            self.controller.config.settings.automatic_bandwidth_control
        )
        automatic_bandwidth.set_tooltip_text(
            "Keeps headroom and fairly divides the global ceiling across simultaneous syncs and streaming drives"
        )
        bandwidth_headroom = Gtk.SpinButton.new_with_range(0, 80, 5)
        bandwidth_headroom.set_value(
            self.controller.config.settings.bandwidth_headroom_percent
        )
        bandwidth_headroom.set_tooltip_text(
            "Percentage of the configured ceiling kept free for calls, browsing, and other devices"
        )
        bandwidth_protection = Gtk.Grid(column_spacing=12, row_spacing=6)
        bandwidth_protection.attach(automatic_bandwidth, 0, 0, 2, 1)
        bandwidth_protection.attach(
            Gtk.Label(label="Reserved network headroom (%)", xalign=0), 0, 1, 1, 1
        )
        bandwidth_protection.attach(bandwidth_headroom, 1, 1, 1, 1)
        battery = Gtk.SpinButton.new_with_range(0, 100, 5)
        battery.set_value(self.controller.config.settings.pause_below_battery_percent)
        battery.set_tooltip_text("0 disables battery pausing")
        cache_max = Gtk.SpinButton.new_with_range(1, 1024, 1)
        cache_max.set_value(self.controller.config.settings.streaming_cache_max_gib)
        cache_max.set_tooltip_text("Maximum unpinned streaming cache for each drive (GiB)")
        cache_free = Gtk.SpinButton.new_with_range(1, 1024, 1)
        cache_free.set_value(self.controller.config.settings.streaming_cache_min_free_gib)
        cache_free.set_tooltip_text("Minimum free disk space retained by cache cleanup (GiB)")
        streaming_refresh = Gtk.ComboBoxText()
        streaming_refresh.append("realtime", "Streaming refresh: Realtime (30 seconds)")
        streaming_refresh.append("balanced", "Streaming refresh: Balanced (2 minutes)")
        streaming_refresh.append("low_traffic", "Streaming refresh: Low traffic (5 minutes)")
        streaming_refresh.set_active_id(
            self.controller.config.settings.streaming_refresh_mode
        )
        cache_row = Gtk.Grid(column_spacing=12, row_spacing=6)
        cache_row.attach(Gtk.Label(label="Streaming cache maximum (GiB)", xalign=0), 0, 0, 1, 1)
        cache_row.attach(cache_max, 1, 0, 1, 1)
        cache_row.attach(Gtk.Label(label="Keep disk space free (GiB)", xalign=0), 0, 1, 1, 1)
        cache_row.attach(cache_free, 1, 1, 1, 1)
        schedule_start = Gtk.Entry()
        schedule_start.set_placeholder_text("Allowed from HH:MM (blank = anytime)")
        schedule_start.set_text(self.controller.config.settings.schedule_start)
        schedule_end = Gtk.Entry()
        schedule_end.set_placeholder_text("Allowed until HH:MM")
        schedule_end.set_text(self.controller.config.settings.schedule_end)
        for widget in (theme_frame, launch, notifications, minimized, nautilus, network_usage, live_activity, policy, metered, global_bandwidth, bandwidth_protection, battery, cache_row, streaming_refresh, schedule_start, schedule_end, server_integration, server_url, server_token, server_ca, server_hint):
            dialog.get_content_area().pack_start(widget, False, False, 6)
        dialog.add_button("Test server connection", 5)
        dialog.add_button("Peer-to-peer sharing…", 3)
        dialog.add_button("TuxInDrive Profile / migrate…", 4)
        dialog.add_button("Check for updates", 2)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            start_value = schedule_start.get_text().strip()
            end_value = schedule_end.get_text().strip()
            clock = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
            if bool(start_value) != bool(end_value) or any(
                value and not clock.fullmatch(value) for value in (start_value, end_value)
            ):
                dialog.destroy()
                self.message(
                    "Enter both schedule times as HH:MM (00:00–23:59), or leave both blank.",
                    Gtk.MessageType.ERROR,
                )
                return
            try:
                bandwidth_value = normalize_bandwidth_limit(
                    global_bandwidth.get_text()
                )
                server_url_value = normalize_server_url(server_url.get_text())
            except ValueError as exc:
                dialog.destroy()
                self.message(str(exc), Gtk.MessageType.ERROR)
                return
            if server_token.get_text():
                try:
                    store_server_token(server_url_value, server_token.get_text())
                except RuntimeError as exc:
                    dialog.destroy()
                    self.message(str(exc), Gtk.MessageType.ERROR)
                    return
            self.controller.config.settings.launch_at_login = launch.get_active()
            self.controller.config.settings.notifications = notifications.get_active()
            self.controller.config.settings.start_minimized = minimized.get_active()
            self.controller.config.settings.nautilus_integration = nautilus.get_active()
            self.controller.config.settings.show_network_usage = network_usage.get_active()
            self.controller.config.settings.show_live_activity_log = live_activity.get_active()
            self.controller.config.settings.server_integration_enabled = server_integration.get_active()
            self.controller.config.settings.server_url = server_url_value
            self.controller.config.settings.server_ca_file = server_ca.get_text().strip()
            selected_theme = normalize_theme(theme.get_active_id())
            theme_changed = selected_theme != self.controller.config.settings.visual_theme
            self.controller.config.settings.visual_theme = selected_theme
            self.controller.config.settings.network_policy = policy.get_active_id() or "maximum"
            self.controller.config.settings.allow_metered_networks = metered.get_active()
            self.controller.config.settings.global_bandwidth_limit = bandwidth_value
            self.controller.config.settings.automatic_bandwidth_control = (
                automatic_bandwidth.get_active()
            )
            self.controller.config.settings.bandwidth_headroom_percent = (
                bandwidth_headroom.get_value_as_int()
            )
            self.controller.bandwidth.configure(bandwidth_value)
            self.controller.bandwidth.configure_automatic(
                automatic_bandwidth.get_active(),
                bandwidth_headroom.get_value_as_int(),
            )
            self.controller.config.settings.pause_below_battery_percent = battery.get_value_as_int()
            self.controller.config.settings.streaming_cache_max_gib = cache_max.get_value_as_int()
            self.controller.config.settings.streaming_cache_min_free_gib = cache_free.get_value_as_int()
            self.controller.config.settings.streaming_refresh_mode = (
                streaming_refresh.get_active_id() or "realtime"
            )
            self.controller.engine.configure_streaming_refresh(
                self.controller.config.settings.streaming_refresh_mode
            )
            self.controller.config.settings.schedule_start = start_value
            self.controller.config.settings.schedule_end = end_value
            self.controller.save()
            self.controller.server_client = (
                ServerClient(server_url_value, server_ca.get_text().strip())
                if server_integration.get_active()
                else None
            )
            self.controller.configure_autostart()
            self.set_network_meter_enabled(network_usage.get_active())
            self.set_activity_log_enabled(live_activity.get_active())
            if theme_changed:
                self.controller.apply_visual_theme(selected_theme)
        dialog.destroy()
        if response == 2:
            self._check_for_updates()
        elif response == 3:
            self._show_peer_sharing(_button)
        elif response == 4:
            ProfileDialog(self, self.controller)
        elif response == 5:
            try:
                test_url = normalize_server_url(server_url.get_text())
                client = ServerClient(
                    test_url,
                    server_ca.get_text().strip(),
                    token=server_token.get_text() or None,
                )
            except (ValueError, RuntimeError, ServerClientError) as exc:
                self.message(str(exc), Gtk.MessageType.ERROR)
                return
            self.message("Testing the TuxInDrive server connection…")
            _run_thread(client.health, self._server_health_ready)

    def _server_health_ready(self, result: dict | None, error: Exception | None) -> bool:
        if error or not result:
            self.message(f"TuxInDrive server connection failed: {error}", Gtk.MessageType.ERROR)
            return False
        roles = ", ".join(str(item) for item in result.get("roles", [])) or "health only"
        self.message(
            f"TuxInDrive server {result.get('version', 'unknown')} is available. Roles: {roles}.",
            Gtk.MessageType.INFO,
        )
        return False

    def _show_peer_sharing(self, _button: Gtk.Widget) -> None:
        PeerSharingDialog(self, self.controller)

    def _check_for_updates(self) -> None:
        if self.update_dialog:
            self.update_dialog.present()
            return
        dialog = ResponsiveDialog(title="TuxInDrive update", transient_for=self, modal=True)
        _set_window_brand_icon(dialog)
        dialog.set_default_size(520, 210)
        area = dialog.get_content_area()
        area.set_border_width(24)
        area.set_spacing(14)
        title = Gtk.Label(xalign=0)
        title.set_markup(f"<span size='large' weight='bold'>Checking for updates</span>\n<small>Installed version: {GLib.markup_escape_text(__version__)}</small>")
        status = Gtk.Label(label="Contacting the TuxInDrive release repository…", xalign=0)
        status.set_line_wrap(True)
        progress = Gtk.ProgressBar()
        progress.set_show_text(True)
        progress.set_text("Checking…")
        area.pack_start(title, False, False, 0)
        area.pack_start(status, False, False, 0)
        area.pack_start(progress, False, False, 0)
        self.update_install_button = dialog.add_button("Download and install", Gtk.ResponseType.OK)
        self.update_install_button.set_sensitive(False)
        self.update_close_button = dialog.add_button("Close", Gtk.ResponseType.CANCEL)
        self.update_close_button.set_sensitive(False)
        dialog.connect("response", self._update_dialog_response)
        self.update_dialog = dialog
        self.update_status = status
        self.update_progress = progress
        self._pending_update = None
        self._update_operation_active = False
        self._update_pulsing = True
        GLib.timeout_add(120, self._pulse_update_progress)
        dialog.show_all()
        _run_thread(self.controller.updater.check, self._update_checked)

    def _pulse_update_progress(self) -> bool:
        if not self.update_dialog or not self._update_pulsing or not self.update_progress:
            return False
        self.update_progress.pulse()
        return True

    def _update_dialog_response(self, dialog: Gtk.Dialog, response: int) -> None:
        if response == Gtk.ResponseType.OK and self._pending_update:
            release = self._pending_update
            self._pending_update = None
            self._update_operation_active = True
            dialog.set_deletable(False)
            self.update_install_button.set_sensitive(False)
            self.update_close_button.set_sensitive(False)
            self._update_pulsing = False
            self.update_progress.set_fraction(0)
            self.update_progress.set_text("Downloading…")
            self.update_status.set_text(f"Downloading TuxInDrive {release.version} from the repository…")
            _run_thread(
                self.controller.updater.download,
                self._update_downloaded,
                release,
                self._report_update_download,
            )
            return
        if self._update_operation_active:
            # The title-bar close button and Escape can emit a response even
            # while the action buttons are disabled. Keep the dialog alive so
            # the asynchronous completion callback always has valid widgets.
            if self.update_status:
                self.update_status.set_text("The verified update operation is still running. Please wait…")
            return
        self._destroy_update_dialog()

    def _destroy_update_dialog(self) -> None:
        self._update_pulsing = False
        if self.update_dialog:
            self.update_dialog.destroy()
        self.update_dialog = None
        self.update_status = None
        self.update_progress = None
        self.update_close_button = None
        self.update_install_button = None
        self._pending_update = None

    def _report_update_download(self, received: int, total: int) -> None:
        GLib.idle_add(self._apply_update_download_progress, received, total)

    def _apply_update_download_progress(self, received: int, total: int) -> bool:
        if not self.update_progress:
            return False
        if total > 0:
            fraction = min(1.0, received / total)
            self.update_progress.set_fraction(fraction)
            self.update_progress.set_text(f"Downloading… {fraction:.0%}")
        else:
            self.update_progress.pulse()
            self.update_progress.set_text(f"Downloaded {received / 1024:.0f} KiB")
        return False

    def _update_checked(self, release: UpdateRelease | None, error: Exception | None) -> bool:
        if error:
            self._update_pulsing = False
            self.update_progress.set_fraction(0)
            self.update_progress.set_text("Check failed")
            self.update_status.set_text(f"Update check failed: {error}")
            self.update_close_button.set_sensitive(True)
            return False
        if release is None:
            self._update_pulsing = False
            self.update_progress.set_fraction(1)
            self.update_progress.set_text("Up to date")
            self.update_status.set_text(f"TuxInDrive {__version__} is the newest available version.")
            self.update_close_button.set_sensitive(True)
            return False
        self._update_pulsing = False
        self._pending_update = release
        self.update_progress.set_fraction(1)
        self.update_progress.set_text(f"Version {release.version} available")
        self.update_status.set_text(
            f"{release.notes or 'A newer TuxInDrive release is available.'}\n\n"
            "Select Download and install to verify and install it."
        )
        self.update_install_button.set_sensitive(True)
        self.update_close_button.set_sensitive(True)
        return False

    def _update_downloaded(self, package: Path | None, error: Exception | None) -> bool:
        if not self.update_dialog or not self.update_progress or not self.update_status:
            self._update_operation_active = False
            return False
        if error or package is None:
            self._update_operation_active = False
            self.update_dialog.set_deletable(True)
            self.update_progress.set_fraction(0)
            self.update_progress.set_text("Download failed")
            self.update_status.set_text(f"Update download or verification failed: {error}")
            self.update_close_button.set_sensitive(True)
            return False
        self._update_pulsing = True
        GLib.timeout_add(120, self._pulse_update_progress)
        self.update_progress.set_text("Installing…")
        if platform.system() == "Linux":
            message = "Package verified. Approve the system authorization prompt to install it…"
        else:
            message = "Package verified. The signed platform installer is opening…"
        self.update_status.set_text(message)
        _run_thread(self.controller.updater.install, self._update_installed, package)
        return False

    def _update_installed(self, _result, error: Exception | None) -> bool:
        self._update_operation_active = False
        if not self.update_dialog or not self.update_progress or not self.update_status:
            return False
        self.update_dialog.set_deletable(True)
        if error:
            self.update_progress.set_fraction(0)
            self.update_progress.set_text("Installation failed")
            self.update_status.set_text(f"Update installation failed: {error}")
        else:
            self.update_progress.set_fraction(1)
            self.update_progress.set_text("Update installed")
            self.update_status.set_text("TuxInDrive was updated successfully. Restart the app to use the new version.")
        self._update_pulsing = False
        self.update_close_button.set_sensitive(True)
        return False

    def message(self, text: str, kind: Gtk.MessageType = Gtk.MessageType.INFO) -> None:
        self.infobar.set_message_type(kind)
        self.info_label.set_text(text)
        self.infobar.show_all()

    def prompt_blocked_google_file(self, job: SyncJob, blocked_path: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text="Google blocked a file as suspected malware or spam",
        )
        dialog.format_secondary_text(
            f"{blocked_path}\n\n"
            "The recommended action is to exclude this file. Only allow the download "
            "if you trust its origin and accept the malware risk."
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Allow unsafe download and retry", 2)
        recommended = dialog.add_button("Exclude file and retry", 1)
        recommended.get_style_context().add_class("suggested-action")
        response = dialog.run()
        dialog.destroy()
        if response == 1:
            rule = f"/{blocked_path.lstrip('/')}"
            if rule not in job.exclude_patterns:
                job.exclude_patterns.append(rule)
            job.acknowledge_google_abuse = False
        elif response == 2:
            job.acknowledge_google_abuse = True
        else:
            return
        job.initialized = False
        job.enabled = True
        job.last_error = ""
        job.last_status = "Recovery synchronization queued…"
        self.controller.save()
        self.refresh()
        self.controller.run_job(job)

    def _refresh_activity_log(self) -> bool:
        if (
            not self.controller.config.settings.show_live_activity_log
            or not self.get_visible()
            or not self.activity_panel.get_expanded()
        ):
            return True
        sources = [application_log_path()]
        sync_directory = cache_root() / "logs"
        if sync_directory.exists():
            sources.extend(
                sorted(sync_directory.glob("*.log"), key=lambda item: item.stat().st_mtime)[-3:]
            )
        active = set(sources)
        self._activity_files = {
            path: value for path, value in self._activity_files.items() if path in active
        }
        sections: list[str] = []
        for source in sources:
            try:
                stat = source.stat()
                fingerprint = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
            except OSError:
                continue
            cached = self._activity_files.get(source)
            if cached and cached[:3] == fingerprint:
                content = cached[3]
            elif cached and cached[0] == stat.st_ino and stat.st_size > cached[1]:
                content = self._append_tail(source, cached[1], cached[3])
                self._activity_files[source] = (*fingerprint, content)
            else:
                content = self._tail_file(source)
                self._activity_files[source] = (*fingerprint, content)
            if content:
                sections.append(f"── {source.name} ──\n{content.strip()}")
        combined = "\n\n".join(sections) or "No activity recorded yet."
        if combined != self._activity_content:
            self._activity_content = combined
            buffer = self.activity_view.get_buffer()
            buffer.set_text(combined)
            self.activity_view.scroll_to_iter(buffer.get_end_iter(), 0.0, False, 0.0, 1.0)
        return True

    @staticmethod
    def _tail_file(path: Path, limit: int = 32 * 1024) -> str:
        try:
            with path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - limit))
                data = handle.read()
            if size > limit:
                data = data.split(b"\n", 1)[-1]
            return data.decode("utf-8", errors="replace")
        except OSError:
            return ""

    @staticmethod
    def _append_tail(
        path: Path, offset: int, previous: str, limit: int = 32 * 1024
    ) -> str:
        """Read only newly appended log bytes and retain a bounded tail."""
        try:
            with path.open("rb") as handle:
                handle.seek(max(0, offset))
                appended = handle.read(limit + 1)
                if len(appended) > limit:
                    # A single update exceeded the display budget. Read the
                    # authoritative tail rather than allocating unbounded text.
                    return MainWindow._tail_file(path, limit)
            combined = previous.encode("utf-8", errors="replace") + appended
            if len(combined) > limit:
                combined = combined[-limit:]
                combined = combined.split(b"\n", 1)[-1]
            return combined.decode("utf-8", errors="replace")
        except OSError:
            return previous

    def _confirm(self, text: str) -> bool:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=text,
        )
        result = dialog.run() == Gtk.ResponseType.OK
        dialog.destroy()
        return result

    @staticmethod
    def _open_path(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(_desktop_open_command(str(path)), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _hide_instead_of_close(self, *_args) -> bool:
        self.hide()
        self.controller.notify("TuxInDrive is still running", "Synchronization continues in the background.")
        return True


class TuxInDriveApplication(Gtk.Application):
    def __init__(self, background: bool = False) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.add_main_option(
            "open-online", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
            "Open the cloud location corresponding to a local TuxInDrive path", "PATH",
        )
        for name, description in (
            ("offline-path", "Keep a streaming item available offline"),
            ("online-only-path", "Release a streaming item's cached content"),
        ):
            self.add_main_option(name, 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING, description, "PATH")
        self.background = background
        self.store = ConfigStore()
        try:
            self.config = self.store.load()
        except RuntimeError:
            self.config = AppConfig()
        try:
            self.managed_policy = load_managed_policy()
        except RuntimeError as exc:
            LOGGER.error("Managed policy rejected: %s", exc)
            self.managed_policy = ManagedPolicy()
        self.managed_policy.apply(self.config.settings)
        self.bandwidth = GlobalBandwidthController(
            self.config.settings.global_bandwidth_limit,
            automatic=self.config.settings.automatic_bandwidth_control,
            headroom_percent=self.config.settings.bandwidth_headroom_percent,
        )
        self.updater = UpdateManager(__version__, bandwidth=self.bandwidth)
        set_language(self.config.settings.language)
        self.rclone = RcloneClient(self.config.settings.rclone_path)
        self.proton = ProtonDriveClient(self.config.settings.proton_drive_path)
        self.cloud_browser = CloudBrowserClient(
            self.rclone, self.proton, lambda: self.config.accounts
        )
        self.engine = SyncEngine(
            self.config.settings.rclone_path,
            proton=self.proton,
            bandwidth=self.bandwidth,
        )
        self.engine.configure_streaming_refresh(
            self.config.settings.streaming_refresh_mode
        )
        self.audit = AuditTimeline()
        self.peers = PeerManager(self.config.settings.rclone_path, audit=self.audit)
        self.profiles = ProfileManager(self.store, self.rclone)
        self.network_meter = NetworkUsageMeter()
        self.search_index = FolderSearchIndex(cache_root() / "folder-search.sqlite3")
        self._search_index_lock = threading.Lock()
        self._search_index_started = False
        self.server_client = (
            ServerClient(
                self.config.settings.server_url,
                self.config.settings.server_ca_file,
            )
            if self.config.settings.server_integration_enabled
            else None
        )
        self.window: MainWindow | None = None
        self.indicator = None
        self._runtime_ready_once = False
        self._pending_nautilus_paths: list[str] = []
        self._pending_nautilus_online: list[str] = []
        self._pending_offline_requests: list[tuple[str, bool]] = []
        self._offline_pending_paths: dict[str, set[str]] = {}
        self._offline_verified_paths: dict[str, set[str]] = {}
        self._nautilus_active_jobs: set[str] = set()
        self._last_started: dict[str, datetime] = {}
        self._last_full_completed: dict[str, datetime] = {}
        self._mount_failures: dict[str, list[datetime]] = {}
        self._css_provider: Gtk.CssProvider | None = None
        self._last_nautilus_state: bytes | None = None
        self._last_cache_maintenance = 0.0
        self._cache_maintenance_running = False
        self._runtime_ready_monotonic = 0.0

    def change_language(self, code: str) -> None:
        if code not in LANGUAGE_CODES:
            code = "en"
        set_language(code)
        self.config.settings.language = code
        self.save()
        previous = self.window
        self.window = MainWindow(self)
        if previous is not None:
            previous.destroy()
        self.window.show_all()
        self.window.present()
        LOGGER.info("UI language changed to %s", code)

    def apply_visual_theme(self, key: str) -> None:
        key = normalize_theme(key)
        self.config.settings.visual_theme = key
        self._install_css()
        if self.window is not None:
            self.window.apply_visual_theme(key)
        LOGGER.info("Visual theme changed to %s", key)

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        self.hold()
        LOGGER.info("GTK application startup completed")
        host_report = inspect_host()
        for line in format_report(host_report).splitlines():
            LOGGER.info("Host capability: %s", line)
        recovered = set(self.engine.recover_stale_mounts(self.config.jobs))
        for job in self.config.jobs:
            if job.id in recovered:
                job.last_status = "Recovered a disconnected files-on-demand mount; reconnecting…"
                LOGGER.warning("Detached stale streaming mount: %s", job.local_path)
        if recovered:
            self.save()
        self._install_css()
        GLib.timeout_add_seconds(30, self._scheduler_tick)
        self.configure_autostart()
        self._create_indicator()
        for name, callback in (
            ("show-path", self._nautilus_show_path),
            ("sync-path", self._nautilus_sync_path),
            ("open-online-path", self._nautilus_open_online),
            ("open-logs", self._nautilus_open_logs),
            ("offline-path", self._nautilus_keep_offline),
            ("online-only-path", self._nautilus_make_online_only),
        ):
            action = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            action.connect("activate", callback)
            self.add_action(action)
        self._publish_nautilus_state()

    def do_activate(self) -> None:
        if self.window is None:
            self.window = MainWindow(self)
            self.window.message(tr("preparing"))
            _run_thread(self._load_runtime, self._runtime_loaded)
        if not self._search_index_started:
            self._search_index_started = True
            self.refresh_search_index()
        tray_available = self.indicator is not None
        if not (tray_available and (self.background or self.config.settings.start_minimized)):
            self.window.show_all()
            self.window.present()
        self.background = False
        LOGGER.info("Application activated; window_visible=%s", self.window.get_visible())

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        """Receive Nautilus requests in the primary application instance."""
        arguments = list(command_line.get_arguments())[1:]
        options = command_line.get_options_dict()
        for name, available in (("offline-path", True), ("online-only-path", False)):
            selected = options.lookup_value(name, GLib.VariantType.new("s"))
            value = selected.get_string() if selected is not None else ""
            if not value:
                value = command_line_path(arguments, name)
            if value:
                LOGGER.info("Received Nautilus offline-state request: %s available=%s", value, available)
                if self.window is None:
                    self.background = True
                    self.activate()
                self._request_offline_path(value, available)
                return 0
        option = options.lookup_value(
            "open-online", GLib.VariantType.new("s")
        )
        if option is not None or "--open-online" in arguments:
            if option is not None:
                value = option.get_string()
            else:
                index = arguments.index("--open-online")
                if index + 1 >= len(arguments):
                    LOGGER.error("Nautilus online-folder request had no local path")
                    return 2
                value = arguments[index + 1]
            LOGGER.info("Received Nautilus online/cloud request: %s", value)
            if self.window is None:
                self.background = True
                self.activate()
            if self._runtime_ready_once:
                self._open_online_path(value)
            else:
                self._pending_nautilus_online.append(value)
            return 0
        self.activate()
        return 0

    def _request_offline_path(self, value: str, available: bool) -> None:
        """Dispatch availability without waiting on unrelated account discovery."""
        job = self._job_for_local_path(value)
        if not job or job.mode is not SyncMode.VIRTUAL_DRIVE:
            LOGGER.warning("Offline-state request is not inside a streaming drive: %s", value)
            self._offline_request_failed(
                "The selected path is not inside a configured streaming drive."
            )
            return
        if not available:
            # Releasing a saved pin/cache is a local operation and must remain
            # available from the app even while the streaming drive is
            # disconnected. Do not mount the cloud merely to make it online-only.
            self._set_offline_path(value, False)
            return
        mounted = job.id in self.engine.mounted_jobs or os.path.ismount(job.local)
        route = availability_route(
            mounted=mounted,
            runtime_ready=self._runtime_ready_once,
            enabled=job.enabled,
        )
        if route == "dispatch":
            self._set_offline_path(value, available)
            return
        request = (value, available)
        if request not in self._pending_offline_requests:
            self._pending_offline_requests.append(request)
        LOGGER.info("Queued offline-state request until streaming mount is ready: %s", value)
        if route == "start-mount":
            self.run_job(job, quiet=True)
            if job.id in self.engine.mounted_jobs or os.path.ismount(job.local):
                try:
                    self._pending_offline_requests.remove(request)
                except ValueError:
                    pass
                self._set_offline_path(value, available)
            elif job.last_error:
                self._offline_request_failed(job.last_error)

    def _set_offline_path(self, value: str, available: bool) -> None:
        job = self._job_for_local_path(value)
        if not job or job.mode is not SyncMode.VIRTUAL_DRIVE:
            self._offline_request_failed(
                "The selected path is not inside a configured streaming drive."
            )
            return
        try:
            relative = lexical_relative_path(value, job.local)
        except (OSError, TypeError, ValueError):
            self._offline_request_failed("The selected streaming path is invalid or no longer available.")
            return
        if relative in self._offline_pending_paths.get(job.id, set()):
            LOGGER.info("Offline-state request already running for %s", value)
            return
        self._offline_pending_paths.setdefault(job.id, set()).add(relative)
        self._publish_nautilus_state()
        _run_thread(
            self._change_offline_availability,
            lambda result, error: self._offline_state_ready(
                result, error, job, relative, available
            ),
            job,
            relative,
            available,
        )

    def _change_offline_availability(
        self,
        job: SyncJob,
        relative: str,
        available: bool,
    ) -> str:
        """Hydrate or release exactly the selected item without remounting."""
        # The mount starts with the stable retention policy required by pinned
        # content. A per-item action must never detach the live FUSE view: doing
        # so invalidates Nautilus' FileInfo objects and can make it re-read
        # neighbouring files while reconstructing the directory.
        return self.engine.set_offline(job, relative, available)

    def _offline_state_ready(
        self,
        result: str | None,
        error: Exception | None,
        job: SyncJob,
        relative: str,
        available: bool,
    ) -> bool:
        pending = self._offline_pending_paths.get(job.id, set())
        pending.discard(relative)
        if not pending:
            self._offline_pending_paths.pop(job.id, None)
        if error:
            LOGGER.error("Could not change offline availability: %s", error)
            self._publish_nautilus_state()
        else:
            verified = verified_rules_after(
                self._offline_verified_paths.get(job.id, set()),
                job.offline_paths,
                relative,
                available,
            )
            self._offline_verified_paths[job.id] = verified
            if not verified:
                self._offline_verified_paths.pop(job.id, None)
            LOGGER.info("Offline availability changed: %s", result)
            self.save()
        if self.window:
            self.window.refresh()
            self.window.message(str(error) if error else str(result), Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO)
        if error:
            self._offline_request_failed(str(error), show_window=False)
        return False

    def _offline_request_failed(self, detail: str, *, show_window: bool = True) -> None:
        LOGGER.error("Offline availability request failed: %s", detail)
        notification = Gio.Notification.new("Could not change offline availability")
        notification.set_body(detail)
        self.send_notification("offline-availability-error", notification)
        if show_window and self.window:
            self.window.message(detail, Gtk.MessageType.ERROR)

    def _nautilus_keep_offline(self, _action: Gio.SimpleAction, parameter: GLib.Variant) -> None:
        self._request_offline_path(parameter.get_string(), True)

    def _nautilus_make_online_only(self, _action: Gio.SimpleAction, parameter: GLib.Variant) -> None:
        self._request_offline_path(parameter.get_string(), False)

    def _job_for_local_path(self, value: str) -> SyncJob | None:
        try:
            selected = Path(os.path.abspath(os.path.expanduser(value)))
        except (OSError, TypeError, ValueError):
            return None
        matches: list[tuple[int, SyncJob]] = []
        for job in self.config.jobs:
            try:
                lexical_relative_path(selected, job.local)
                root = Path(os.path.abspath(os.path.expanduser(job.local_path)))
                matches.append((len(root.parts), job))
            except (OSError, TypeError, ValueError):
                continue
        return max(matches, default=(0, None), key=lambda item: item[0])[1]

    def _nautilus_show_path(self, _action: Gio.SimpleAction, parameter: GLib.Variant) -> None:
        self.activate()
        value = parameter.get_string()
        job = self._job_for_local_path(value)
        if self.window:
            self.window.message(
                f"{job.name}: {job.last_status}" if job else "That path is not part of an enabled TuxInDrive folder.",
                Gtk.MessageType.INFO if job else Gtk.MessageType.WARNING,
            )

    def _nautilus_sync_path(self, _action: Gio.SimpleAction, parameter: GLib.Variant) -> None:
        value = parameter.get_string()
        self.activate()
        if not self._runtime_ready_once:
            self._pending_nautilus_paths.append(value)
            if self.window:
                self.window.message("Preparing TuxInDrive, then synchronization will start…")
            return
        job = self._job_for_local_path(value)
        if not job or not job.enabled:
            if self.window:
                self.window.message("That path is not part of an enabled TuxInDrive folder.", Gtk.MessageType.WARNING)
            return
        if job.mode is SyncMode.VIRTUAL_DRIVE:
            if self.window:
                self.window.message("This is a files-on-demand drive; opening a file streams its content.")
            return
        self.run_job(job)

    def _nautilus_open_logs(self, _action: Gio.SimpleAction, _parameter: GLib.Variant) -> None:
        MainWindow._open_path(log_directory())

    def _nautilus_open_online(self, _action: Gio.SimpleAction, parameter: GLib.Variant) -> None:
        value = parameter.get_string()
        if not self._runtime_ready_once:
            self._pending_nautilus_online.append(value)
            LOGGER.info("Queued online/cloud location while runtime initializes: %s", value)
            return
        self._open_online_path(value)

    def _open_online_path(self, value: str) -> None:
        job = self._job_for_local_path(value)
        if not job:
            if self.window:
                self.window.message("That path is not part of a TuxInDrive folder.", Gtk.MessageType.WARNING)
            return
        account = next((item for item in self.config.accounts if item.remote == job.account_remote), None)
        if not account or account.provider in {Provider.PEER, Provider.VAULT}:
            if self.window:
                self.window.message("This peer or encrypted-vault path has no safe provider web page.", Gtk.MessageType.WARNING)
            return
        try:
            local_root = Path(os.path.abspath(os.path.expanduser(job.local_path)))
            selected = Path(os.path.abspath(os.path.expanduser(value)))
            relative = selected.relative_to(local_root)
        except (OSError, ValueError):
            relative = Path()
        remote_path = "/".join(
            part for part in (job.remote_path.strip("/"), relative.as_posix().strip("/"))
            if part and part != "."
        )
        if account.provider is Provider.GITHUB:
            url = repository_item_url(
                job.repository_url, job.repository_branch, relative.as_posix()
            )
            _run_thread(self._launch_online_url, self._online_launch_ready, url, True)
            return
        if account.provider is Provider.PROTON_DRIVE and account.backend == "proton_cli":
            # Proton's official CLI exposes filesystem paths but does not
            # currently publish a stable private web-route contract for an
            # item. Never route the native account through the legacy rclone
            # backend or manufacture a public sharing URL.
            _run_thread(
                self._launch_online_url,
                self._online_launch_ready,
                account.provider.home_url,
                False,
            )
            return
        remote = job.remote_scope or job.account_remote
        remote_spec = f"{remote}:{remote_path}" if remote_path else f"{remote}:"
        if self.window:
            self.window.message("Locating the corresponding provider page…")
        _run_thread(self.rclone.online_url, self._online_url_ready, remote_spec, account.provider)

    def _create_share_link(self, job: SyncJob) -> None:
        account = next(
            (item for item in self.config.accounts if item.remote == job.account_remote),
            None,
        )
        if not account or not capabilities_for(account.provider).share_links:
            if self.window:
                self.window.message(
                    "This provider does not advertise secure public-link support.",
                    Gtk.MessageType.WARNING,
                )
            return
        confirm = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Create a public provider link?",
        )
        confirm.format_secondary_text(
            "Anyone who receives the URL may be able to access this synchronized "
            "folder. The link is created and controlled by your storage provider."
        )
        accepted = confirm.run() == Gtk.ResponseType.OK
        confirm.destroy()
        if accepted:
            _run_thread(self.rclone.public_link, self._share_link_ready, job.remote_spec)

    def _share_link_ready(self, link: str | None, error: Exception | None) -> bool:
        if error or not link:
            if self.window:
                self.window.message(
                    f"Share link could not be created: {error}", Gtk.MessageType.ERROR
                )
            return False
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(link, -1)
        clipboard.store()
        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Provider share link copied to the clipboard",
        )
        dialog.format_secondary_text(link)
        dialog.run()
        dialog.destroy()
        return False

    def _online_url_ready(self, result: tuple[str, bool] | None, error: Exception | None) -> bool:
        if error or not result or not result[0]:
            if self.window:
                self.window.message(
                    str(error or "This provider does not expose a safe web-folder URL."),
                    Gtk.MessageType.WARNING,
                )
            return False
        url, exact = result
        LOGGER.info("Launching online/cloud location: %s", url)
        _run_thread(self._launch_online_url, self._online_launch_ready, url, exact)
        return False

    @staticmethod
    def _launch_online_url(url: str, exact: bool) -> tuple[bool, str]:
        """Launch through the freedesktop handler and return a checked result."""
        result = subprocess.run(
            _desktop_open_command(url),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(detail or f"desktop opener exited with status {result.returncode}")
        return exact, url

    def _online_launch_ready(
        self, result: tuple[bool, str] | None, error: Exception | None
    ) -> bool:
        if error or not result:
            detail = str(error or "The desktop URL handler did not return a result.")
            LOGGER.error("Could not open online/cloud location: %s", detail)
            notification = Gio.Notification.new("Could not open online/cloud folder")
            notification.set_body(detail)
            self.send_notification("online-folder-error", notification)
            if self.window:
                self.window.message(f"Could not open the default web browser: {detail}", Gtk.MessageType.ERROR)
            return False
        exact, url = result
        LOGGER.info("Desktop browser accepted online/cloud location: %s", url)
        if self.window:
            self.window.message(
                "Opened the matching online item."
                if exact else
                "This provider cannot address that exact path safely; opened the account root instead."
            )
        return False

    def _publish_nautilus_state(self) -> None:
        target = cache_root() / "nautilus-state.json"
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(target.parent, 0o700)
        mounted = self.engine.mounted_jobs
        payload: dict[str, dict[str, object]] = {}
        for job in self.config.jobs:
            state = (
                "syncing" if job.id in self._nautilus_active_jobs else
                "streaming" if job.id in mounted else
                "error" if job.last_error else
                "paused" if not job.enabled or job.last_status == "Stopped" else
                "synced" if job.initialized else "pending"
            )
            payload[job.id] = {
                "state": state,
                "detail": job.last_status or state.title(),
                # A configured rule is only advertised as available offline
                # after this process has completely read it from the mount.
                # This prevents a stale rule or externally-cleared VFS cache
                # from receiving a misleading green badge.
                "offline_paths": sorted(self._offline_verified_paths.get(job.id, set())),
                "configured_offline_paths": sorted(job.offline_paths),
                "online_only_paths": sorted(job.online_only_paths),
                "offline_pending_paths": sorted(self._offline_pending_paths.get(job.id, set())),
            }
        payload["__tuxindrive__"] = {
            "nautilus_integration": self.config.settings.nautilus_integration,
            "jobs": [
                {
                    "id": job.id,
                    "local_path": job.local_path,
                    "mode": job.mode.value,
                    "enabled": job.enabled,
                    "offline_paths": list(job.offline_paths),
                    "online_only_paths": list(job.online_only_paths),
                }
                for job in self.config.jobs
            ],
        }
        serialized = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        if self._last_nautilus_state == serialized:
            try:
                os.chmod(target, 0o600)
                return
            except OSError:
                pass
        try:
            if target.read_bytes() == serialized:
                os.chmod(target, 0o600)
                self._last_nautilus_state = serialized
                return
        except OSError:
            pass
        descriptor, temporary = tempfile.mkstemp(
            prefix="nautilus-state-", suffix=".json", dir=target.parent
        )
        try:
            private_descriptor(descriptor)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(serialized.decode("utf-8"))
            os.replace(temporary, target)
            self._last_nautilus_state = serialized
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def add_account(self, account: Account) -> None:
        if not self.managed_policy.provider_allowed(account.provider):
            LOGGER.warning(
                "Managed policy rejected account provider %s", account.provider.value
            )
            if self.window:
                self.window.message(
                    f"{account.provider.label} is disabled by the managed desktop policy.",
                    Gtk.MessageType.ERROR,
                )
            return
        previous = next(
            (item for item in self.config.accounts if item.remote == account.remote),
            None,
        )
        if (
            account.provider is Provider.PROTON_DRIVE
            and account.backend == "proton_cli"
        ):
            for job in self.config.jobs:
                if job.account_remote != account.remote:
                    continue
                job.realtime_sync = False
                if job.mode is SyncMode.VIRTUAL_DRIVE:
                    job.enabled = False
                    job.initialized = False
                    job.last_status = (
                        "Proton streaming is unavailable with the official CLI; edit this job and choose a synchronization mode."
                    )
            if previous and previous.backend != "proton_cli":
                try:
                    self.rclone.delete_remote(previous.remote)
                except RcloneError as exc:
                    LOGGER.warning(
                        "Official Proton session connected, but legacy encrypted rclone remote cleanup failed: %s",
                        exc,
                    )
        self.config.accounts = [item for item in self.config.accounts if item.remote != account.remote]
        self.config.accounts.append(account)
        self.save()
        if self.window:
            self.window.refresh()
            self.window.message(f"{account.display_name} connected successfully.")
        if account.provider.browser_oauth:
            _run_thread(self.profiles.available, self._profile_checked, account.remote)

    def _profile_checked(self, available: bool | None, error: Exception | None) -> bool:
        if available and not error and self.window:
            self.window.message(
                "An encrypted TuxInDrive Profile is available. Open Settings → TuxInDrive Profile / migrate to inspect or restore it.",
                Gtk.MessageType.INFO,
            )
        return False

    def run_job(
        self,
        job: SyncJob,
        quiet: bool = False,
        decision: PolicyDecision | None = None,
    ) -> None:
        self.engine.configure_jobs(self.config.jobs, self.config.accounts)
        if not job.enabled and not quiet:
            job.enabled = True
        if job.id in self.engine.running_jobs:
            if self.window and not quiet:
                self.window.message(f"{job.name} is already synchronizing.")
            return
        decision = decision or TransferPolicy(self.config.settings).evaluate()
        if not decision.allowed:
            job.last_status = decision.reason
            LOGGER.info("Policy deferred job %s: %s", job.id, decision.reason)
            self.audit.record("sync", "policy deferred", "paused", job_id=job.id, detail=decision.reason)
            self._publish_nautilus_state()
            if self.window and not quiet:
                self.window.message(decision.reason, Gtk.MessageType.INFO)
            return
        self.engine.stop_callbacks(job.id)
        job.last_status = (
            "Connecting files-on-demand drive…"
            if job.mode is SyncMode.VIRTUAL_DRIVE
            else "Synchronizing…"
        )
        LOGGER.info(
            "Starting job %s (%s): %s -> %s",
            job.id,
            job.name,
            job.remote_spec,
            job.local_path,
        )
        self.audit.record("sync", "job started", "running", job_id=job.id, path=job.remote_path, detail=job.mode.label)
        self._set_tray_state("syncing", job.name)
        self._last_started[job.id] = datetime.now(timezone.utc)
        self._nautilus_active_jobs.add(job.id)
        self._publish_nautilus_state()
        if self.window:
            self.window.refresh()
        started = self.engine.run_async(job, self._job_finished)
        if not started:
            self._nautilus_active_jobs.discard(job.id)
            self._publish_nautilus_state()
        if not started and self.window and not quiet:
            self.window.message("The job could not be started.", Gtk.MessageType.WARNING)

    def stop_job(self, job: SyncJob) -> None:
        self.engine.stop_callbacks(job.id)
        stopped = self.engine.stop_mount(job) if job.mode is SyncMode.VIRTUAL_DRIVE else self.engine.cancel(job.id)
        if stopped:
            self._nautilus_active_jobs.discard(job.id)
            self._offline_verified_paths.pop(job.id, None)
            job.last_status = "Stopped"
            self.audit.record("sync", "job stopped", "success", job_id=job.id, detail=job.name)
            self.save()
            if self.window:
                self.window.refresh()

    def _job_finished(self, result: JobResult) -> None:
        GLib.idle_add(self._apply_job_result, result)

    def refresh_search_index(
        self,
        callback: Callable[[IndexStats | None, Exception | None], bool] | None = None,
        job: SyncJob | None = None,
    ) -> None:
        """Refresh filename metadata in a background thread."""

        jobs = list(self.config.jobs)

        def refresh() -> IndexStats:
            with self._search_index_lock:
                return (
                    self.search_index.refresh_job(
                        job,
                        include_content=self.config.settings.search_content_indexing,
                    )
                    if job is not None
                    else self.search_index.refresh(
                        jobs,
                        include_content=self.config.settings.search_content_indexing,
                    )
                )

        def ready(result: IndexStats | None, error: Exception | None) -> bool:
            if error:
                LOGGER.warning("Synchronized-folder index refresh failed: %s", error)
            if callback is not None:
                return callback(result, error)
            return False

        _run_thread(refresh, ready)

    def _apply_job_result(self, result: JobResult) -> bool:
        job = next((item for item in self.config.jobs if item.id == result.job_id), None)
        if not job:
            return False
        self._nautilus_active_jobs.discard(job.id)
        now = datetime.now(timezone.utc)
        job.last_run = now.isoformat()
        job.last_status = result.message
        job.last_error = "" if result.success else result.message
        job.last_error_at = "" if result.success else now.isoformat()
        job.last_error_source = "" if result.success else result.blocked_path
        job.last_error_log = "" if result.success else str(result.log_path)
        if result.requires_resync:
            job.initialized = False
            job.enabled = False
            job.last_status = f"{result.message} Automatic sync paused; recovery sync required."
            job.last_error = job.last_status
        if result.mass_change_blocked:
            job.enabled = False
            job.last_status = f"{result.message} Review the log, then re-enable the job to approve a later retry."
            job.last_error = job.last_status
        if result.success and job.mode is not SyncMode.VIRTUAL_DRIVE:
            job.initialized = True
        if result.success and not result.incremental and job.mode is not SyncMode.VIRTUAL_DRIVE:
            self._last_full_completed[job.id] = now
        if job.mode is SyncMode.VIRTUAL_DRIVE and (result.success or result.mount_lost):
            # Every new mount must prove its persistent cache again.  A lost
            # mount must never leave stale green per-item badges behind.
            self._offline_verified_paths.pop(job.id, None)
        self._set_tray_state("ready" if result.success else "error", result.message)
        LOGGER.info("Job %s finished: success=%s message=%s", job.id, result.success, result.message)
        account = next((item for item in self.config.accounts if item.remote == job.account_remote), None)
        result.network_sessions, result.payload_bytes = self.engine.finalize_traffic(
            job.id, result.log_path
        )
        self.audit.record(
            "peer" if job.peer_delta else "sync",
            "incremental transfer" if result.incremental else "synchronization",
            "success" if result.success else "failed",
            job_id=job.id,
            peer=account.display_name if account and account.provider is Provider.PEER else "",
            path=job.remote_path,
            detail=(
                f"{result.message}; provider sessions since start="
                f"{result.network_sessions}; recorded payload={result.payload_bytes} bytes"
            ),
        )
        if result.success and job.one_time_drop_id:
            job.enabled = False
            job.last_status = "One-time file drop sent; invitation retired"
            self.audit.record("peer", "one-time drop sent", "success", job_id=job.id, path=job.remote_path)
        self.save()
        if result.success and not result.incremental:
            self.start_callbacks(job)
        if result.success and job.mode is not SyncMode.VIRTUAL_DRIVE:
            self.refresh_search_index(job=job)
        if result.success and job.mode is SyncMode.VIRTUAL_DRIVE:
            # Reconnects must never trigger an implicit download.  Verify only
            # TuxInDrive's local cache markers; a missing/old 0.20.2 marker stays
            # unconfirmed until the user explicitly chooses Keep available
            # offline again.
            verified = self.engine.verified_offline_rules(job)
            if verified:
                self._offline_verified_paths[job.id] = verified
            else:
                self._offline_verified_paths.pop(job.id, None)
            self._publish_nautilus_state()
            # A user may request Keep available offline while the drive is
            # disconnected. run_job is asynchronous, so dispatch that exact
            # queued request only after this mount has actually succeeded.
            for request in list(self._pending_offline_requests):
                value, available = request
                requested_job = self._job_for_local_path(value)
                if requested_job and requested_job.id == job.id:
                    self._pending_offline_requests.remove(request)
                    self._set_offline_path(value, available)
        if result.mount_lost and job.enabled:
            recent = self._mount_failures.setdefault(job.id, [])
            cutoff = now.timestamp() - 300
            recent[:] = [item for item in recent if item.timestamp() >= cutoff]
            recent.append(now)
            if len(recent) <= 3:
                delay = 3 * len(recent)
                job.last_status = f"Streaming drive disconnected; retrying in {delay} seconds…"
                self.save()
                GLib.timeout_add_seconds(delay, self._retry_mount, job.id)
        if self.window:
            self.window.refresh()
            if not result.success:
                if result.blocked_path:
                    self.window.prompt_blocked_google_file(job, result.blocked_path)
                else:
                    self.window.message(f"{job.name}: {job.last_status}", Gtk.MessageType.ERROR)
        if not result.incremental or not result.success:
            self.notify(job.name, result.message)
        return False

    def _retry_mount(self, job_id: str) -> bool:
        job = next((item for item in self.config.jobs if item.id == job_id), None)
        if job and job.enabled and job.mode is SyncMode.VIRTUAL_DRIVE:
            self.run_job(job, quiet=True)
        return False

    def start_callbacks(self, job: SyncJob) -> None:
        self.engine.configure_jobs(self.config.jobs, self.config.accounts)
        self.engine.start_callbacks(
            job,
            self._job_finished,
            lambda item: GLib.idle_add(self.run_job, item, True),
        )

    def reconfigure_callbacks(self) -> None:
        self.engine.configure_jobs(self.config.jobs, self.config.accounts)
        for item in self.config.jobs:
            self.engine.stop_callbacks(item.id)
        for item in self.config.jobs:
            if (
                item.enabled
                and item.initialized
                and item.realtime_sync
                and item.mode is not SyncMode.VIRTUAL_DRIVE
            ):
                self.engine.start_callbacks(
                    item,
                    self._job_finished,
                    lambda changed: GLib.idle_add(self.run_job, changed, True),
                )

    def _scheduler_tick(self) -> bool:
        monotonic = time.monotonic()
        if (
            not self._cache_maintenance_running
            and monotonic - self._last_cache_maintenance >= 300
        ):
            gib = 1024 ** 3
            self._cache_maintenance_running = True
            _run_thread(
                self.engine.maintain_streaming_cache,
                self._cache_maintenance_ready,
                list(self.config.jobs),
                self.config.settings.streaming_cache_max_gib * gib,
                self.config.settings.streaming_cache_min_free_gib * gib,
            )
            self._last_cache_maintenance = monotonic
        now = datetime.now(timezone.utc)
        policy_decision: PolicyDecision | None = None
        for job in self.config.jobs:
            if not job.enabled or job.mode is SyncMode.VIRTUAL_DRIVE or job.id in self.engine.running_jobs:
                continue
            baseline = self._last_full_completed.get(job.id) or self._last_started.get(job.id)
            if baseline is None and job.last_run:
                baseline = persisted_run_time(job.last_run, now)
                if baseline is None:
                    LOGGER.warning("Ignoring invalid persisted last_run for job %s", job.id)
            due = baseline is None or (now - baseline).total_seconds() >= job.interval_minutes * 60
            # A healthy callback already preserves the configured remote scan
            # latency. Keep full bisync as an hourly safety checkpoint instead
            # of duplicating the same recursive provider traversal every tick.
            if due and self.engine.callback_healthy(job.id) and baseline is not None:
                due = (now - baseline).total_seconds() >= 3600
            if (
                due and job.initialized and job.realtime_sync
                and self.engine.has_durable_bisync_baseline(job)
                and self._runtime_ready_monotonic
                and monotonic - self._runtime_ready_monotonic < 120
            ):
                due = False
            if due:
                if policy_decision is None:
                    policy_decision = TransferPolicy(self.config.settings).evaluate()
                self.run_job(job, quiet=True, decision=policy_decision)
        return True

    def _cache_maintenance_ready(self, results, error: Exception | None) -> bool:
        self._cache_maintenance_running = False
        if error:
            LOGGER.warning("Streaming cache maintenance failed safely: %s", error)
            return False
        for result in results or []:
            if result.released_files:
                LOGGER.info(
                    "Streaming cache cleanup job=%s files=%s bytes=%s",
                    result.job_id, result.released_files, result.released_bytes,
                )
        return False

    def _create_indicator(self) -> None:
        if AyatanaAppIndicator3 is None:
            LOGGER.error("AyatanaAppIndicator3 is unavailable; tray icon cannot be created")
            return
        self.indicator = AyatanaAppIndicator3.Indicator.new(
            "tuxindrive",
            "tuxindrive",
            AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_title("TuxInDrive")
        self.indicator.set_icon_theme_path("/usr/share/icons/hicolor/scalable/apps")
        self.indicator.set_icon_full("tuxindrive", "TuxInDrive is running")
        self.indicator.set_attention_icon_full("tuxindrive-error", "TuxInDrive needs attention")
        menu = Gtk.Menu()
        show = Gtk.MenuItem(label="Open TuxInDrive")
        show.connect("activate", lambda _item: self.activate())
        sync_all = Gtk.MenuItem(label="Synchronize all now")
        sync_all.connect(
            "activate",
            lambda _item: [self.run_job(job) for job in self.config.jobs if job.enabled],
        )
        pause_all = Gtk.CheckMenuItem(label="Pause all synchronization")

        def toggle_pause(item: Gtk.CheckMenuItem) -> None:
            paused = item.get_active()
            for job in self.config.jobs:
                job.enabled = not paused
                if paused:
                    self.stop_job(job)
            self.save()
            if self.window:
                self.window.refresh()

        pause_all.connect("toggled", toggle_pause)
        logs = Gtk.MenuItem(label="Open diagnostic logs")
        logs.connect("activate", lambda _item: MainWindow._open_path(log_directory()))
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda _item: self.quit())
        for item in (show, sync_all, pause_all, logs, Gtk.SeparatorMenuItem(), quit_item):
            menu.append(item)
        menu.show_all()
        self.indicator.set_menu(menu)
        LOGGER.info("Tray indicator initialized")
        GLib.timeout_add_seconds(
            2,
            lambda: (self.notify("TuxInDrive loaded", "Cloud synchronization is running in the tray"), False)[1],
        )

    def _set_tray_state(self, state: str, detail: str = "") -> None:
        if not self.indicator or AyatanaAppIndicator3 is None:
            return
        icon = {
            "ready": "tuxindrive",
            "syncing": "tuxindrive-sync",
            "error": "tuxindrive-error",
        }.get(state, "tuxindrive")
        self.indicator.set_icon_full(icon, f"TuxInDrive: {detail or state}")
        self.indicator.set_status(
            AyatanaAppIndicator3.IndicatorStatus.ATTENTION
            if state == "error"
            else AyatanaAppIndicator3.IndicatorStatus.ACTIVE
        )

    def save(self) -> None:
        self.store.save(self.config)
        self._publish_nautilus_state()

    def notify(self, title: str, body: str) -> None:
        if not self.config.settings.notifications:
            return
        notification = Gio.Notification.new(title)
        notification.set_body(body)
        self.send_notification(None, notification)

    def configure_autostart(self) -> None:
        system = platform.system()
        if system == "Windows":
            import winreg

            with winreg.CreateKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"
            ) as key:
                if self.config.settings.launch_at_login:
                    executable = str(Path(sys.executable).resolve())
                    winreg.SetValueEx(key, "TuxInDrive", 0, winreg.REG_SZ, f'"{executable}" --background')
                else:
                    try:
                        winreg.DeleteValue(key, "TuxInDrive")
                    except FileNotFoundError:
                        pass
            return
        if system == "Darwin":
            target = Path.home() / "Library" / "LaunchAgents" / f"{APP_ID}.plist"
            if self.config.settings.launch_at_login:
                target.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "Label": APP_ID,
                    "ProgramArguments": [
                        "/Applications/TuxInDrive.app/Contents/MacOS/tuxindrive", "--background"
                    ],
                    "RunAtLoad": True,
                    "ProcessType": "Interactive",
                }
                target.write_bytes(plistlib.dumps(payload))
            elif target.exists():
                target.unlink()
            return
        target = Path.home() / ".config" / "autostart" / "tuxindrive.desktop"
        legacy_target = target.with_name("tuxdrive.desktop")
        if self.config.settings.launch_at_login:
            target.parent.mkdir(parents=True, exist_ok=True)
            content = (
                "[Desktop Entry]\nType=Application\nName=TuxInDrive\n"
                "Exec=tuxindrive --background\nIcon=tuxindrive\n"
                "X-GNOME-Autostart-enabled=true\nNoDisplay=true\n"
            )
            target.write_text(content, encoding="utf-8")
            legacy_target.unlink(missing_ok=True)
        elif target.exists():
            target.unlink()
        if not self.config.settings.launch_at_login:
            legacy_target.unlink(missing_ok=True)

    def _load_runtime(self) -> dict[str, Provider]:
        executable = self.rclone.ensure_available()
        self.engine.rclone_path = executable
        LOGGER.info("Cloud transfer engine ready: %s", executable)
        return self.rclone.discover_accounts()

    def _runtime_loaded(
        self, existing: dict[str, Provider] | None, error: Exception | None
    ) -> bool:
        if error:
            LOGGER.error(
                "Runtime initialization failed",
                exc_info=(type(error), error, error.__traceback__),
            )
            self._set_tray_state("error", "Runtime initialization failed")
            if self.window:
                self.window.message(
                    f"Runtime preparation failed: {error}. Logs: {crash_log_path()}",
                    Gtk.MessageType.ERROR,
                )
            return False
        existing = existing or {}
        known = {account.remote for account in self.config.accounts}
        for remote, provider in existing.items():
            if remote not in known:
                self.config.accounts.append(Account(remote, provider, remote))
        legacy_proton = {
            account.remote for account in self.config.accounts
            if account.provider is Provider.PROTON_DRIVE and account.backend != "proton_cli"
        }
        for job in self.config.jobs:
            if job.account_remote in legacy_proton and job.enabled:
                self.engine.stop_callbacks(job.id)
                job.enabled = False
                job.last_status = (
                    "Reconnect this Proton account in the browser to migrate from the legacy rclone login."
                )
        self.save()
        if self.window:
            self.window.refresh()
            self.window.message(tr("loaded"))
        profile_accounts = [item for item in self.config.accounts if item.provider.browser_oauth]
        if profile_accounts:
            preferred = self.config.settings.profile_remote
            account = next((item for item in profile_accounts if item.remote == preferred), profile_accounts[0])
            _run_thread(self.profiles.available, self._profile_checked, account.remote)
        self._set_tray_state("ready", "Loaded")
        if not self._runtime_ready_once:
            self._runtime_ready_once = True
            for share in self.config.peer_shares:
                if share.enabled:
                    try:
                        self.peers.start(share)
                        share.last_status = f"Listening on TCP {share.port}"
                    except Exception as exc:
                        share.last_status = f"Could not start: {exc}"
                        LOGGER.error("Peer share %s failed: %s", share.id, exc)
            if any(
                share.enabled and share.lan_discovery
                for share in self.config.peer_shares
            ):
                self.peers.start_discovery()
            self.save()
            self._runtime_ready_monotonic = time.monotonic()
            for job in self.config.jobs:
                if job.enabled and job.mode is SyncMode.VIRTUAL_DRIVE:
                    self.run_job(job, quiet=True)
                elif job.enabled and job.initialized and job.realtime_sync:
                    if self.engine.has_durable_bisync_baseline(job):
                        self._last_started[job.id] = datetime.now(timezone.utc)
                    self.start_callbacks(job)
            pending, self._pending_nautilus_paths = self._pending_nautilus_paths, []
            started_jobs: set[str] = set()
            for value in pending:
                job = self._job_for_local_path(value)
                if job and job.id not in started_jobs and job.enabled and job.mode is not SyncMode.VIRTUAL_DRIVE:
                    started_jobs.add(job.id)
                    self.run_job(job)
            pending_online, self._pending_nautilus_online = self._pending_nautilus_online, []
            for value in pending_online:
                self._open_online_path(value)
            pending_offline, self._pending_offline_requests = self._pending_offline_requests, []
            for value, available in pending_offline:
                self._request_offline_path(value, available)
        return False

    def _install_css(self) -> None:
        screen = Gdk.Screen.get_default()
        if self._css_provider is not None and screen is not None:
            Gtk.StyleContext.remove_provider_for_screen(screen, self._css_provider)
        provider = Gtk.CssProvider()
        selected = theme_by_key(self.config.settings.visual_theme)
        provider.load_from_data(css_for_theme(selected.key))
        if screen is not None:
            Gtk.StyleContext.add_provider_for_screen(
                screen,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
        self._css_provider = provider
        gtk_settings = Gtk.Settings.get_default()
        if gtk_settings is not None:
            gtk_settings.set_property("gtk-application-prefer-dark-theme", selected.dark)

    def do_shutdown(self) -> None:
        LOGGER.info("TuxInDrive shutting down")
        self.network_meter.save()
        self.peers.shutdown()
        self.engine.shutdown()
        self.release()
        Gtk.Application.do_shutdown(self)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TuxInDrive cloud synchronization client")
    parser.add_argument("--background", action="store_true", help="start without opening the main window")
    parser.add_argument("--version", action="store_true", help="show version and exit")
    parser.add_argument("--diagnostics", action="store_true", help="show diagnostic log locations and exit")
    args, gtk_args = parser.parse_known_args(argv)
    if args.version:
        print(f"TuxInDrive {__version__}")
        return 0
    if args.diagnostics:
        print(f"Application log: {application_log_path()}")
        print(f"Crash log: {crash_log_path()}")
        return 0
    application = TuxInDriveApplication(background=args.background)
    return application.run([sys.argv[0], *gtk_args])


if __name__ == "__main__":
    raise SystemExit(main())
