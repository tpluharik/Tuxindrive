from tests import signal_safety as _signal_safety  # noqa: F401

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def load_extension():
    class FakeMenu:
        def __init__(self):
            self.items = []

        def append_item(self, item):
            self.items.append(item)

    class FakeMenuItem:
        def __init__(self, *, name, label, tip, icon):
            # Mirror Nautilus.MenuItem.new() rather than accepting arbitrary
            # kwargs like a generic GObject constructor. In particular,
            # ``sensitive`` is a property and is not a fifth constructor arg.
            self.values = {
                "name": name,
                "label": label,
                "tip": tip,
                "icon": icon,
            }
            self.submenu = None

        def connect(self, *_args):
            return None

        def set_submenu(self, submenu):
            self.submenu = submenu

        def set_property(self, name, value):
            self.values[name] = value

    gi = types.ModuleType("gi")
    repository = types.ModuleType("gi.repository")
    repository.Gio = types.SimpleNamespace()
    repository.GLib = types.SimpleNamespace()
    repository.GObject = types.SimpleNamespace(GObject=type("GObject", (), {}))
    repository.Nautilus = types.SimpleNamespace(
        MenuProvider=type("MenuProvider", (), {}),
        InfoProvider=type("InfoProvider", (), {}),
        FileInfo=types.SimpleNamespace(lookup_for_uri=lambda _uri: None),
        Menu=FakeMenu,
        MenuItem=FakeMenuItem,
        menu_provider_emit_items_updated_signal=lambda _provider: None,
        OperationResult=types.SimpleNamespace(COMPLETE=0),
    )
    gi.repository = repository
    spec = importlib.util.spec_from_file_location(
        "tuxindrive_nautilus_extension_test",
        Path("packaging/nautilus-extension-tuxindrive.py"),
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"gi": gi, "gi.repository": repository}):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


class NautilusExtensionTests(unittest.TestCase):
    def test_status_uses_the_complete_installed_emblem_identity(self):
        extension = load_extension()
        provider = object.__new__(extension.TuxInDriveExtension)
        provider._known_uris = {}
        job = {
            "id": "drive",
            "local_path": "/mnt/Cloud",
            "mode": "two_way",
            "initialized": True,
        }

        class FileInfo:
            def __init__(self):
                self.emblems = []

            def get_uri(self):
                return "file:///mnt/Cloud"

            def add_string_attribute(self, *_args):
                return None

            def add_emblem(self, name):
                self.emblems.append(name)

        info = FileInfo()
        with patch.object(extension, "_jobs", return_value=[job]), patch.object(
            extension, "_runtime_states", return_value={}
        ), patch.object(extension, "_local_path", return_value=Path("/mnt/Cloud")):
            provider._apply_file_info(info)

        self.assertEqual(info.emblems, ["emblem-tuxindrive-synced"])

    def test_existing_legacy_metadata_directory_remains_visible(self):
        extension = load_extension()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = root / "tuxdrive"
            legacy.mkdir()
            self.assertEqual(extension._brand_root(root), legacy)
            self.assertFalse((root / "tuxindrive").exists())

    def test_file_rule_does_not_tag_siblings_or_parent(self):
        extension = load_extension()
        self.assertTrue(extension._matches_rule("folder/one.txt", ["folder/one.txt"]))
        self.assertFalse(extension._matches_rule("folder/two.txt", ["folder/one.txt"]))
        self.assertFalse(extension._matches_rule("folder", ["folder/one.txt"]))

    def test_transient_metadata_read_keeps_last_valid_menu_jobs(self):
        extension = load_extension()
        job = {"id": "drive", "local_path": "/mnt/Cloud", "mode": "virtual_drive"}
        with patch.object(
            extension,
            "_state_document",
            return_value={"__tuxindrive__": {"nautilus_integration": True, "jobs": [job]}},
        ):
            self.assertEqual(extension._jobs(), [job])

        with patch.object(
            extension,
            "_state_document",
            return_value={"__tuxdrive__": {"nautilus_integration": True, "jobs": [job]}},
        ):
            self.assertEqual(extension._jobs(force=True), [job])

        with tempfile.TemporaryDirectory() as temporary, patch.object(
            extension, "_state_document", return_value={}
        ), patch.object(
            extension, "_config_path", return_value=Path(temporary) / "missing.json"
        ):
            self.assertEqual(extension._jobs(force=True), [job])

    def test_badges_reuse_one_monitor_invalidated_metadata_snapshot(self):
        extension = load_extension()
        provider = object.__new__(extension.TuxInDriveExtension)
        provider._known_uris = {}
        state = {
            "drive": {"state": "synced", "detail": "Ready"},
            "__tuxindrive__": {
                "nautilus_integration": True,
                "jobs": [{
                    "id": "drive",
                    "local_path": "/mnt/Cloud",
                    "mode": "two_way",
                    "initialized": True,
                }],
            },
        }

        class Location:
            def __init__(self, path):
                self.path = path

            def get_path(self):
                return self.path

        class FileInfo:
            def __init__(self, path):
                self.path = path

            def get_location(self):
                return Location(self.path)

            def get_uri(self):
                return "file://" + self.path

            def add_string_attribute(self, *_args):
                return None

            def add_emblem(self, *_args):
                return None

        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "nautilus-state.json"
            state_path.write_text(__import__("json").dumps(state), encoding="utf-8")
            with patch.object(extension, "_state_path", return_value=state_path), patch.object(
                extension.json, "loads", wraps=extension.json.loads
            ) as loads:
                provider._apply_file_info(FileInfo("/mnt/Cloud/one.txt"))
                provider._apply_file_info(FileInfo("/mnt/Cloud/two.txt"))
                provider._apply_file_info(FileInfo("/mnt/Cloud/three.txt"))

        self.assertEqual(loads.call_count, 1)

    def test_transient_state_read_keeps_verified_badges(self):
        extension = load_extension()
        state = {
            "drive": {"offline_paths": ["folder/one.txt"]},
            "__tuxindrive__": {
                "nautilus_integration": True,
                "jobs": [{"id": "drive", "local_path": "/mnt/Cloud"}],
            },
        }
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            extension, "_state_path", return_value=Path(temporary) / "state.json"
        ):
            path = extension._state_path()
            path.write_text(__import__("json").dumps(state), encoding="utf-8")
            self.assertEqual(extension._runtime_states()["drive"]["offline_paths"], ["folder/one.txt"])
            path.unlink()
            self.assertEqual(extension._runtime_states()["drive"]["offline_paths"], ["folder/one.txt"])

    def test_background_menu_cannot_trigger_recursive_offline_action(self):
        source = Path("packaging/nautilus-extension-tuxindrive.py").read_text(encoding="utf-8")
        self.assertIn("return self._menu_items(files, allow_availability=True)", source)
        self.assertIn(
            "return self._menu_items([current_folder], allow_availability=False)",
            source,
        )

    def test_completed_file_keeps_root_menu_and_exposes_online_only_action(self):
        extension = load_extension()
        provider = object.__new__(extension.TuxInDriveExtension)
        job = {
            "id": "drive",
            "local_path": "/mnt/Cloud",
            "mode": "virtual_drive",
            "offline_paths": ["folder/one.txt"],
            "online_only_paths": [],
        }
        path = Path("/mnt/Cloud/folder/one.txt")
        with patch.object(extension, "_jobs", return_value=[job]), patch.object(
            extension,
            "_runtime_states",
            return_value={
                "drive": {
                    "offline_paths": ["folder/one.txt"],
                    "configured_offline_paths": ["folder/one.txt"],
                    "online_only_paths": [],
                    "offline_pending_paths": [],
                }
            },
        ), patch.object(extension, "_local_path", return_value=path):
            menu = provider._menu_items([object()], allow_availability=True)

        self.assertEqual(len(menu), 1)
        self.assertEqual(menu[0].values["label"], "TuxInDrive")
        labels = [item.values["label"] for item in menu[0].submenu.items]
        self.assertIn("Free local space (make online-only)", labels)

    def test_pending_file_sets_supported_sensitive_property_after_construction(self):
        extension = load_extension()
        provider = object.__new__(extension.TuxInDriveExtension)
        job = {
            "id": "drive",
            "local_path": "/mnt/Cloud",
            "mode": "virtual_drive",
            "offline_paths": ["folder/one.txt"],
            "online_only_paths": [],
        }
        path = Path("/mnt/Cloud/folder/one.txt")
        with patch.object(extension, "_jobs", return_value=[job]), patch.object(
            extension,
            "_runtime_states",
            return_value={
                "drive": {
                    "offline_paths": [],
                    "configured_offline_paths": ["folder/one.txt"],
                    "online_only_paths": [],
                    "offline_pending_paths": ["folder/one.txt"],
                }
            },
        ), patch.object(extension, "_local_path", return_value=path):
            menu = provider._menu_items([object()], allow_availability=True)

        online_only = next(
            item for item in menu[0].submenu.items
            if item.values["name"] == "TuxInDrive::OnlineOnly"
        )
        self.assertEqual(online_only.values["label"], "Downloading for offline availability…")
        self.assertFalse(online_only.values["sensitive"])

    def test_completed_file_does_not_pass_sensitive_to_nautilus_constructor(self):
        extension = load_extension()
        provider = object.__new__(extension.TuxInDriveExtension)
        job = {
            "id": "drive",
            "local_path": "/mnt/Cloud",
            "mode": "virtual_drive",
            "offline_paths": ["folder/one.txt"],
            "online_only_paths": [],
        }
        path = Path("/mnt/Cloud/folder/one.txt")
        with patch.object(extension, "_jobs", return_value=[job]), patch.object(
            extension,
            "_runtime_states",
            return_value={
                "drive": {
                    "offline_paths": ["folder/one.txt"],
                    "configured_offline_paths": ["folder/one.txt"],
                    "online_only_paths": [],
                    "offline_pending_paths": [],
                }
            },
        ), patch.object(extension, "_local_path", return_value=path):
            menu = provider._menu_items([object()], allow_availability=True)

        online_only = next(
            item for item in menu[0].submenu.items
            if item.values["name"] == "TuxInDrive::OnlineOnly"
        )
        self.assertEqual(online_only.values["label"], "Free local space (make online-only)")
        self.assertTrue(online_only.values["sensitive"])

    def test_metadata_burst_rebuilds_menu_and_reacquires_current_file_info(self):
        extension = load_extension()
        provider = object.__new__(extension.TuxInDriveExtension)
        provider._invalidation_source = 0
        provider._known_uris = {}
        changed = types.SimpleNamespace(get_basename=lambda: "nautilus-state.json")
        with patch.object(
            extension.GLib, "timeout_add", return_value=41, create=True
        ) as timeout_add:
            provider._metadata_changed(None, changed, None, None)
            provider._metadata_changed(None, changed, None, None)
        timeout_add.assert_called_once_with(200, provider._refresh_metadata)
        self.assertEqual(provider._invalidation_source, 41)

        class CurrentFile:
            def __init__(inner_self):
                inner_self.invalidated = False

            def is_gone(inner_self):
                return False

            def invalidate_extension_info(inner_self):
                inner_self.invalidated = True

        current = CurrentFile()
        provider._known_uris = {"file:///one": None}
        extension.GLib.SOURCE_REMOVE = False
        with patch.object(extension, "_state_document", return_value={}), patch.object(
            extension, "_jobs", return_value=[]
        ), patch.object(
            extension.Nautilus, "menu_provider_emit_items_updated_signal"
        ) as menu_updated, patch.object(
            extension.Nautilus.FileInfo, "lookup_for_uri", return_value=current
        ) as lookup:
            self.assertFalse(provider._refresh_metadata())
        menu_updated.assert_called_once_with(provider)
        lookup.assert_called_once_with("file:///one")
        self.assertTrue(current.invalidated)
        self.assertEqual(provider._known_uris, {"file:///one": None})

    def test_info_provider_retains_only_uri_not_caller_owned_file_info(self):
        extension = load_extension()
        provider = object.__new__(extension.TuxInDriveExtension)
        provider._known_uris = {}

        class Location:
            def get_path(self):
                return "/mnt/Cloud/folder/one.txt"

        class CallerOwnedFile:
            def get_location(self):
                return Location()

            def get_uri(self):
                return "file:///mnt/Cloud/folder/one.txt"

            def add_string_attribute(self, *_args):
                pass

            def add_emblem(self, *_args):
                pass

        file_info = CallerOwnedFile()
        job = {
            "id": "drive",
            "local_path": "/mnt/Cloud",
            "mode": "virtual_drive",
            "enabled": True,
        }
        with patch.object(extension, "_jobs", return_value=[job]), patch.object(
            extension, "_runtime_states", return_value={"drive": {"state": "streaming"}}
        ):
            provider._apply_file_info(file_info)

        self.assertEqual(
            provider._known_uris,
            {"file:///mnt/Cloud/folder/one.txt": None},
        )
        self.assertTrue(all(value is None for value in provider._known_uris.values()))


if __name__ == "__main__":
    unittest.main()
