"""Native Nautilus context menu and status integration for TuxInDrive."""

from __future__ import annotations

import json
import os
from pathlib import Path

import gi

# Nautilus loads its own GI namespace before importing extensions. Do not pin
# a minor version here: Ubuntu 26.04 currently exposes 4.1, while earlier
# supported Nautilus 4 releases expose 4.0. Requiring either exact minor after
# the host has loaded the other prevents the complete extension from loading.
from gi.repository import Gio, GLib, GObject, Nautilus

APP_ID = "io.github.tuxindrive.TuxInDrive"
APP_PATH = "/io/github/tuxindrive/TuxInDrive"
_LAST_VALID_JOBS: list[dict] = []
_LAST_VALID_STATE: dict = {}
_LAST_VALID_JOB_ROOTS: list[tuple[Path, dict]] = []
_RUNTIME_STATES_CACHE: dict[str, dict] = {}
_JOBS_CACHE_READY = False
_STATE_CACHE_READY = False


def _brand_root(root: Path) -> Path:
    current = root / "tuxindrive"
    legacy = root / "tuxdrive"
    return legacy if legacy.exists() and not current.exists() else current


def _dict_list(value) -> list[dict]:
    """Return only complete mapping entries from an external JSON list."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _rule_list(value) -> list[str]:
    """Normalize availability rules without letting bad state unload Nautilus."""
    if not isinstance(value, (list, tuple, set)):
        return []
    return [item for item in value if isinstance(item, str)]


def _config_path() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return _brand_root(root) / "config.json"


def _cache_jobs(jobs: list[dict]) -> list[dict]:
    """Publish normalized jobs and their roots as one in-memory snapshot."""
    global _JOBS_CACHE_READY, _LAST_VALID_JOBS, _LAST_VALID_JOB_ROOTS
    _LAST_VALID_JOBS = _dict_list(jobs)
    roots: list[tuple[Path, dict]] = []
    for job in _LAST_VALID_JOBS:
        try:
            roots.append((Path(os.path.abspath(os.path.expanduser(job["local_path"]))), job))
        except (KeyError, OSError, TypeError, ValueError):
            continue
    _LAST_VALID_JOB_ROOTS = roots
    _JOBS_CACHE_READY = True
    return list(_LAST_VALID_JOBS)


def _jobs(*, force: bool = False) -> list[dict]:
    # Prefer the small extension snapshot. It is written atomically, contains
    # no provider credentials and avoids parsing unrelated application state
    # for every item in a FUSE directory.
    global _JOBS_CACHE_READY
    if _JOBS_CACHE_READY and not force:
        return list(_LAST_VALID_JOBS)
    document = _state_document()
    meta = document.get("__tuxindrive__", document.get("__tuxdrive__", {}))
    if isinstance(meta, dict) and isinstance(meta.get("jobs"), list):
        if not meta.get("nautilus_integration", True):
            return _cache_jobs([])
        return _cache_jobs(meta["jobs"])
    try:
        value = json.loads(_config_path().read_text(encoding="utf-8"))
        if not value.get("settings", {}).get("nautilus_integration", True):
            return _cache_jobs([])
        jobs = value.get("jobs", [])
        if isinstance(jobs, list):
            return _cache_jobs(jobs)
        _JOBS_CACHE_READY = True
        return list(_LAST_VALID_JOBS)
    except (OSError, ValueError, TypeError):
        # The app publishes a minimal, non-secret snapshot specifically for
        # the extension.  A transient/invalid full configuration read must not
        # make the complete TuxInDrive menu disappear inside a live FUSE mount.
        # Keep the last complete credential-free snapshot. Menu construction
        # often races the atomic state-file replacement after a pin changes;
        # a single failed read must not make the menu disappear.
        _JOBS_CACHE_READY = True
        return list(_LAST_VALID_JOBS)


def _state_path() -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return _brand_root(root) / "nautilus-state.json"


def _state_document(*, force: bool = False) -> dict:
    global _LAST_VALID_STATE, _RUNTIME_STATES_CACHE, _STATE_CACHE_READY
    if _STATE_CACHE_READY and not force:
        return _LAST_VALID_STATE
    try:
        value = json.loads(_state_path().read_text(encoding="utf-8"))
        meta = (
            value.get("__tuxindrive__", value.get("__tuxdrive__", {}))
            if isinstance(value, dict) else {}
        )
        # The app always publishes the job snapshot and runtime states in one
        # atomic document. Treat only that complete shape as a new snapshot;
        # a short ENOENT/partial observation during replacement must not erase
        # already verified badges until the next metadata event.
        if isinstance(meta, dict) and isinstance(meta.get("jobs"), list):
            _LAST_VALID_STATE = value
            _RUNTIME_STATES_CACHE = {
                str(key): entry
                for key, entry in value.items()
                if key not in {"__tuxindrive__", "__tuxdrive__"} and isinstance(entry, dict)
            }
            _STATE_CACHE_READY = True
            return value
        _STATE_CACHE_READY = True
        return _LAST_VALID_STATE
    except (OSError, ValueError, TypeError):
        # Cache even an initially absent snapshot. The directory monitor will
        # force a reload when the app publishes it; retrying the same failed
        # disk read for every visible file makes Nautilus badges arrive late.
        _STATE_CACHE_READY = True
        return _LAST_VALID_STATE


def _runtime_states() -> dict[str, dict]:
    _state_document()
    return _RUNTIME_STATES_CACHE


def _local_path(file_info: Nautilus.FileInfo) -> Path | None:
    location = file_info.get_location()
    value = location.get_path() if location else None
    # Never resolve/stat a path from Nautilus. A disconnected FUSE child can
    # return ENOTCONN, and an InfoProvider must not turn that into a directory
    # listing failure. Lexical normalization is sufficient for configured roots.
    return Path(os.path.abspath(os.path.expanduser(value))) if value else None


def _containing_job(path: Path, configured_jobs: list[dict] | None = None) -> dict | None:
    matches: list[tuple[int, dict]] = []
    jobs = configured_jobs if configured_jobs is not None else _jobs()
    if configured_jobs is None and _JOBS_CACHE_READY and jobs == _LAST_VALID_JOBS:
        roots = _LAST_VALID_JOB_ROOTS
    else:
        roots = []
        for job in jobs:
            try:
                roots.append((Path(os.path.abspath(os.path.expanduser(job["local_path"]))), job))
            except (KeyError, OSError, TypeError, ValueError):
                continue
    for root, job in roots:
        try:
            path.relative_to(root)
            matches.append((len(root.parts), job))
        except (OSError, TypeError, ValueError):
            continue
    return max(matches, default=(0, None), key=lambda item: item[0])[1]


def _relative_path(path: Path, job: dict) -> str:
    root = Path(os.path.abspath(os.path.expanduser(job["local_path"])))
    value = path.relative_to(root).as_posix()
    return "." if value in {"", "."} else value.strip("/")


def _matches_rule(relative: str, rules: list[str]) -> bool:
    # A file rule applies only to that exact file. The descendant form is
    # intentionally one-way so ``folder/one.txt`` never matches its parent or
    # the sibling ``folder/two.txt``.
    return any(
        rule == "." or relative == rule or relative.startswith(rule.rstrip("/") + "/")
        for rule in rules
    )


def _available_offline(relative: str, offline_rules: list[str], online_only_rules: list[str]) -> bool:
    candidates: list[tuple[int, bool]] = []
    for available, rules in ((True, offline_rules), (False, online_only_rules)):
        for rule in rules:
            if _matches_rule(relative, [rule]):
                depth = 0 if rule == "." else len(rule.split("/"))
                candidates.append((depth, available))
    return max(candidates, default=(-1, False), key=lambda item: (item[0], not item[1]))[1]


class TuxInDriveExtension(GObject.GObject, Nautilus.MenuProvider, Nautilus.InfoProvider):
    """Expose only local, configured TuxInDrive paths to Nautilus."""

    def __init__(self) -> None:
        super().__init__()
        # FileInfo values passed to InfoProvider are owned by Nautilus. Keeping
        # those wrappers after the callback can leave Python holding a stale
        # object when a FUSE file changes from streamed to locally cached.
        # Remember only stable URIs and reacquire the current cached FileInfo
        # immediately before requesting a badge refresh.
        self._known_uris: dict[str, None] = {}
        self._monitors: list[Gio.FileMonitor] = []
        self._invalidation_source = 0
        for directory in {_config_path().parent, _state_path().parent}:
            try:
                monitor = Gio.File.new_for_path(str(directory)).monitor_directory(Gio.FileMonitorFlags.NONE, None)
                monitor.connect("changed", self._metadata_changed)
                self._monitors.append(monitor)
            except GLib.Error:
                continue

    def _metadata_changed(self, _monitor, changed, _other, _event) -> None:
        # Config/state writers use an atomic temporary-file + rename sequence.
        # Depending on the GLib/GVfs version, the directory monitor can report
        # either side of that move, so inspect both paths and the temporary
        # prefixes instead of waiting only for a direct target-file event.
        basenames = {
            item.get_basename()
            for item in (changed, _other)
            if item is not None
        }
        if not any(
            name in {"config.json", "nautilus-state.json"}
            or name.startswith(("config-", "nautilus-state-"))
            for name in basenames if isinstance(name, str)
        ):
            return
        # State and config are both replaced atomically when an availability
        # action completes. Invalidating FileInfo objects synchronously from
        # each directory-monitor callback can re-enter Nautilus' provider while
        # it is still rebuilding the context menu. Nautilus 4.1 may then
        # suppress the provider for that item. Coalesce the burst and perform
        # one refresh from the main loop after the final document is visible.
        if not self._invalidation_source:
            self._invalidation_source = GLib.timeout_add(200, self._refresh_metadata)

    def _refresh_metadata(self) -> bool:
        self._invalidation_source = 0
        # Prime the last-known-good snapshots before asking Nautilus to query
        # the provider again. A completed pin can therefore change its action
        # from Keep offline to Make online-only without losing the root menu.
        _state_document(force=True)
        _jobs(force=True)
        # MenuProvider has its own refresh signal. Using it prevents badge
        # invalidation from being (incorrectly) relied on to rebuild a context
        # menu after Keep available offline completes.
        try:
            Nautilus.menu_provider_emit_items_updated_signal(self)
        except (AttributeError, TypeError):
            # Older bindings may omit the helper; menus are still rebuilt on
            # the next selection change or right-click.
            pass

        for uri in list(self._known_uris):
            try:
                file_info = Nautilus.FileInfo.lookup_for_uri(uri)
                if file_info is None or file_info.is_gone():
                    self._known_uris.pop(uri, None)
                    continue
                file_info.invalidate_extension_info()
            except Exception:
                # A URI can leave Nautilus' cache while a view changes. Drop
                # it without affecting subsequent menu-provider callbacks.
                self._known_uris.pop(uri, None)
                continue
        return GLib.SOURCE_REMOVE

    def _activate(self, action: str, path: Path | None = None) -> None:
        if action == "open-online-path":
            # GApplication forwards this request to the primary TuxInDrive
            # process. This avoids org.gtk.Actions discovery differences in
            # Nautilus 4.1 while preserving one application instance.
            Gio.Subprocess.new(
                [
                    "/usr/bin/tuxindrive",
                    "--open-online",
                    str(path or ""),
                ],
                Gio.SubprocessFlags.NONE,
            )
            return
        group = Gio.DBusActionGroup.get(Gio.bus_get_sync(Gio.BusType.SESSION), APP_ID, APP_PATH)
        parameter = GLib.Variant("s", str(path or ""))
        if action in group.list_actions():
            group.activate_action(action, parameter)
            return

        # Start the registered desktop application, then retry without blocking Nautilus.
        Gio.Subprocess.new(["/usr/bin/tuxindrive", "--background"], Gio.SubprocessFlags.NONE)

        def retry(remaining: int = 20) -> bool:
            refreshed = Gio.DBusActionGroup.get(Gio.bus_get_sync(Gio.BusType.SESSION), APP_ID, APP_PATH)
            if action in refreshed.list_actions():
                refreshed.activate_action(action, parameter)
                return GLib.SOURCE_REMOVE
            if remaining <= 1:
                if action in {"offline-path", "online-only-path"}:
                    Gio.Subprocess.new(
                        [
                            "/usr/bin/tuxindrive",
                            {
                                "offline-path": "--offline-path",
                                "online-only-path": "--online-only-path",
                            }[action],
                            str(path or ""),
                        ],
                        Gio.SubprocessFlags.NONE,
                    )
                return GLib.SOURCE_REMOVE
            GLib.timeout_add(150, retry, remaining - 1)
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(150, retry)

    def _menu_items(
        self,
        files: list[Nautilus.FileInfo],
        *,
        allow_availability: bool,
    ) -> list[Nautilus.MenuItem]:
        if not files:
            return []
        paths = [_local_path(item) for item in files]
        if any(path is None for path in paths):
            return []
        configured_jobs = _jobs()
        jobs = [_containing_job(path, configured_jobs) for path in paths if path]
        if not jobs or any(job is None for job in jobs):
            return []

        submenu = Nautilus.Menu()
        show = Nautilus.MenuItem(
            name="TuxInDrive::Show",
            label="Show in TuxInDrive",
            tip="Open TuxInDrive and show synchronization status",
            icon="tuxindrive",
        )
        show.connect("activate", lambda _item: self._activate("show-path", paths[0]))
        submenu.append_item(show)

        unique_jobs = {job.get("id") for job in jobs if job}
        if len(unique_jobs) == 1 and jobs[0].get("mode") != "virtual_drive":
            sync = Nautilus.MenuItem(
                name="TuxInDrive::Sync",
                label="Synchronize this TuxInDrive folder now",
                tip="Start the configured safety-checked synchronization job",
                icon="tuxindrive-sync",
            )
            sync.connect("activate", lambda _item: self._activate("sync-path", paths[0]))
            submenu.append_item(sync)

        logs = Nautilus.MenuItem(
            name="TuxInDrive::Logs",
            label="Open TuxInDrive activity logs",
            tip="Open diagnostic and synchronization logs",
            icon="text-x-generic-symbolic",
        )
        logs.connect("activate", lambda _item: self._activate("open-logs", paths[0]))
        submenu.append_item(logs)

        if len(unique_jobs) == 1:
            online = Nautilus.MenuItem(
                name="TuxInDrive::Online",
                label="Open online/cloud folder",
                tip="Open the corresponding provider page without creating a public share link",
                icon="web-browser-symbolic",
            )
            online.connect("activate", lambda _item: self._activate("open-online-path", paths[0]))
            submenu.append_item(online)
            if (
                allow_availability
                and len(paths) == 1
                and jobs[0].get("mode") == "virtual_drive"
            ):
                relative = _relative_path(paths[0], jobs[0])
                runtime = _runtime_states().get(str(jobs[0].get("id", "")), {})
                pending = _matches_rule(relative, _rule_list(runtime.get("offline_pending_paths", [])))
                configured_rules = _rule_list(runtime.get(
                    "configured_offline_paths", jobs[0].get("offline_paths", [])
                ))
                verified_rules = _rule_list(runtime.get("offline_paths", []))
                online_only_rules = _rule_list(runtime.get(
                    "online_only_paths", jobs[0].get("online_only_paths", [])
                ))
                configured_offline = _available_offline(
                    relative, configured_rules, online_only_rules
                )
                verified_offline = _available_offline(
                    relative, verified_rules, online_only_rules
                )
                if not configured_offline and not pending:
                    offline = Nautilus.MenuItem(
                        name="TuxInDrive::Offline",
                        label="Keep available offline",
                        tip="Download this item completely and retain it in TuxInDrive's local VFS cache",
                        icon="emblem-downloads-symbolic",
                    )
                    offline.connect("activate", lambda _item: self._activate("offline-path", paths[0]))
                    submenu.append_item(offline)
                else:
                    online_only = Nautilus.MenuItem(
                        name="TuxInDrive::OnlineOnly",
                        label=(
                            "Downloading for offline availability…" if pending else
                            "Free local space (make online-only)" if verified_offline else
                            "Remove saved offline rule (make online-only)"
                        ),
                        tip="Override a pinned parent if needed and release matching cached content",
                        icon="edit-clear-symbolic",
                    )
                    # Nautilus.MenuItem.new() accepts exactly name, label, tip
                    # and icon. ``sensitive`` is a writable GObject property,
                    # not an additional constructor argument and not a GTK
                    # widget setter. Passing it to the constructor makes the
                    # real Nautilus 4.1 binding raise TypeError and discard the
                    # whole provider menu as soon as this state-only branch is
                    # entered. Set the property through GObject instead.
                    online_only.set_property("sensitive", not pending)
                    online_only.connect("activate", lambda _item: self._activate("online-only-path", paths[0]))
                    submenu.append_item(online_only)

        root = Nautilus.MenuItem(
            name="TuxInDrive::Root",
            label="TuxInDrive",
            tip="TuxInDrive synchronization actions",
            icon="tuxindrive",
        )
        root.set_submenu(submenu)
        return [root]

    def get_file_items(self, files: list[Nautilus.FileInfo]) -> list[Nautilus.MenuItem]:
        # Availability actions must have an explicit selected file/folder.
        # Nautilus also asks providers for background items using the current
        # folder itself; treating that callback as a selection silently turns
        # one intended file pin into a recursive folder/drive hydration.
        return self._menu_items(files, allow_availability=True)

    def get_file_items_full(self, _provider, files: list[Nautilus.FileInfo]) -> list[Nautilus.MenuItem]:
        """Nautilus 4 menu callback paired with the items-updated signal."""
        return self._menu_items(files, allow_availability=True)

    def get_background_items(self, current_folder: Nautilus.FileInfo) -> list[Nautilus.MenuItem]:
        return self._menu_items([current_folder], allow_availability=False)

    def get_background_items_full(
        self,
        _provider,
        current_folder: Nautilus.FileInfo,
    ) -> list[Nautilus.MenuItem]:
        """Nautilus 4 background callback paired with the update signal."""
        return self._menu_items([current_folder], allow_availability=False)

    def _apply_file_info(self, file_info: Nautilus.FileInfo) -> None:
        path = _local_path(file_info)
        job = _containing_job(path) if path else None
        if not job:
            return
        self._known_uris[file_info.get_uri()] = None
        # Retain enough URI keys for normal directories without allowing a
        # long Nautilus session to grow without bound.
        while len(self._known_uris) > 2048:
            self._known_uris.pop(next(iter(self._known_uris)))
        mode = job.get("mode")
        runtime = _runtime_states().get(str(job.get("id", "")), {})
        relative = _relative_path(path, job)
        pending = _matches_rule(relative, _rule_list(runtime.get("offline_pending_paths", [])))
        pinned = _available_offline(
            relative,
            _rule_list(runtime.get("offline_paths", [])),
            _rule_list(runtime.get("online_only_paths", job.get("online_only_paths", []))),
        )
        state = str(("syncing" if pending else "synced" if pinned else "") or runtime.get("state") or (
            "error" if job.get("last_error") else
            "paused" if not job.get("enabled", True) else
            "streaming" if mode == "virtual_drive" else
            "synced" if job.get("initialized") else "pending"
        ))
        status = (
            "Downloading for offline availability"
            if pending else
            "Available offline"
            if pinned else
            str(runtime.get("detail") or {
            "syncing": "TuxInDrive is synchronizing",
            "synced": "Synchronized by TuxInDrive",
            "streaming": "TuxInDrive files on demand",
            "paused": "TuxInDrive synchronization paused",
            "error": "TuxInDrive needs attention",
            "pending": "TuxInDrive synchronization pending",
            }.get(state, "Managed by TuxInDrive"))
        )
        file_info.add_string_attribute("tuxindrive_status", status)
        # Nautilus expects the installed icon-theme name. Use the complete
        # emblem identity rather than relying on a desktop-version-specific
        # implicit ``emblem-`` prefix.
        emblem = f"emblem-tuxindrive-{state}" if state in {"syncing", "synced", "streaming", "paused", "error", "pending"} else "emblem-tuxindrive-pending"
        file_info.add_emblem(emblem)

    def update_file_info_full(self, _provider, _handle, _closure, file_info: Nautilus.FileInfo):
        """Nautilus 4 InfoProvider vfunc; synchronous metadata completion."""
        self._apply_file_info(file_info)
        return Nautilus.OperationResult.COMPLETE

    def update_file_info(self, file_info: Nautilus.FileInfo):
        """Compatibility entry point for older python-nautilus bindings."""
        self._apply_file_info(file_info)
        return Nautilus.OperationResult.COMPLETE

    def cancel_update(self, _provider, _handle) -> None:
        return None
