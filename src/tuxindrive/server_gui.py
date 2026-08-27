"""GTK administration application for the separately packaged server."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from . import __version__
from .server import DEFAULT_ROLES, ServerConfig, ServerError


SERVICE = "tuxindrive-server.service"
PACKAGED_LAUNCHER = "/usr/bin/tuxindrive-server"


def _run(arguments: list[str], *, privileged: bool = False, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    command = (["/usr/bin/pkexec"] if privileged else []) + arguments
    return subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": os.environ.get("LANG", "C.UTF-8")},
    )


def _message(parent: Gtk.Window, title: str, detail: str, kind: Gtk.MessageType = Gtk.MessageType.INFO) -> None:
    dialog = Gtk.MessageDialog(
        transient_for=parent,
        modal=True,
        message_type=kind,
        buttons=Gtk.ButtonsType.CLOSE,
        text=title,
    )
    dialog.format_secondary_text(detail)
    dialog.run()
    dialog.destroy()


def _row(grid: Gtk.Grid, row: int, label: str, widget: Gtk.Widget) -> None:
    text = Gtk.Label(label=label, xalign=0)
    text.set_hexpand(False)
    grid.attach(text, 0, row, 1, 1)
    grid.attach(widget, 1, row, 1, 1)


class ServerWindow(Gtk.ApplicationWindow):
    def __init__(self, application: Gtk.Application) -> None:
        super().__init__(application=application, title="TuxInDrive Server")
        self.set_resizable(True)
        self.set_default_size(1100, 760)
        self.set_icon_name("tuxindrive-server")
        self._tokens: dict[str, str] = {}
        self._build()
        GLib.idle_add(self.refresh_status)

    def _build(self) -> None:
        header = Gtk.HeaderBar(title="TuxInDrive Server", subtitle=f"Administration application · {__version__}")
        header.set_show_close_button(True)
        self.set_titlebar(header)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_border_width(16)
        self.add(outer)

        status_box = Gtk.Box(spacing=12)
        self.status = Gtk.Label(label="Service status: checking…", xalign=0)
        self.status.set_hexpand(True)
        status_box.pack_start(self.status, True, True, 0)
        refresh = Gtk.Button(label="Refresh")
        refresh.connect("clicked", lambda _button: self.refresh_status())
        status_box.pack_start(refresh, False, False, 0)
        outer.pack_start(status_box, False, False, 0)

        actions = Gtk.Box(spacing=8)
        for label, action in (
            ("Start", "start"), ("Stop", "stop"), ("Restart", "restart"),
            ("Enable at boot", "enable"), ("Disable", "disable"),
        ):
            button = Gtk.Button(label=label)
            button.connect("clicked", self._service_action, action)
            actions.pack_start(button, False, False, 0)
        log_button = Gtk.Button(label="Load service log")
        log_button.connect("clicked", self._load_log)
        actions.pack_end(log_button, False, False, 0)
        outer.pack_start(actions, False, False, 0)

        notebook = Gtk.Notebook()
        notebook.set_scrollable(True)
        outer.pack_start(notebook, True, True, 0)

        notebook.append_page(self._configuration_page(), Gtk.Label(label="Configuration"))
        notebook.append_page(self._roles_page(), Gtk.Label(label="Roles and limits"))
        notebook.append_page(self._tokens_page(), Gtk.Label(label="API tokens"))
        notebook.append_page(self._log_page(), Gtk.Label(label="Service log"))

        footer = Gtk.Box(spacing=8)
        load = Gtk.Button(label="Load installed configuration")
        load.connect("clicked", self._load_config)
        validate = Gtk.Button(label="Validate")
        validate.connect("clicked", self._validate)
        save = Gtk.Button(label="Save configuration")
        save.get_style_context().add_class("suggested-action")
        save.connect("clicked", self._save_config, False)
        save_restart = Gtk.Button(label="Save and restart")
        save_restart.connect("clicked", self._save_config, True)
        footer.pack_start(load, False, False, 0)
        footer.pack_start(validate, False, False, 0)
        footer.pack_end(save_restart, False, False, 0)
        footer.pack_end(save, False, False, 0)
        outer.pack_end(footer, False, False, 0)

    def _scroll(self, child: Gtk.Widget) -> Gtk.ScrolledWindow:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(child)
        return scroll

    def _configuration_page(self) -> Gtk.Widget:
        grid = Gtk.Grid(column_spacing=16, row_spacing=10)
        grid.set_border_width(16)
        self.bind = Gtk.Entry(text="127.0.0.1")
        self.port = Gtk.SpinButton.new_with_range(1, 65535, 1); self.port.set_value(9443)
        self.tls_certificate = Gtk.Entry(); self.tls_private_key = Gtk.Entry()
        self.database = Gtk.Entry(text="/var/lib/tuxindrive-server/server.sqlite3")
        self.client_config = Gtk.Entry()
        for entry in (self.bind, self.tls_certificate, self.tls_private_key, self.database, self.client_config):
            entry.set_hexpand(True)
        _row(grid, 0, "Bind address", self.bind)
        _row(grid, 1, "TCP port", self.port)
        _row(grid, 2, "TLS certificate", self.tls_certificate)
        _row(grid, 3, "TLS private key", self.tls_private_key)
        _row(grid, 4, "SQLite database", self.database)
        _row(grid, 5, "Headless client configuration", self.client_config)
        hint = Gtk.Label(
            label="A non-loopback address requires both TLS files. The service account must be able to read every configured file.",
            xalign=0,
        )
        hint.set_line_wrap(True)
        grid.attach(hint, 0, 6, 2, 1)
        return self._scroll(grid)

    def _roles_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(16)
        role_frame = Gtk.Frame(label="Enabled server roles")
        role_grid = Gtk.Grid(column_spacing=18, row_spacing=8, margin=12)
        self.roles: dict[str, Gtk.CheckButton] = {}
        for index, role in enumerate(DEFAULT_ROLES):
            check = Gtk.CheckButton(label=role); check.set_active(True)
            self.roles[role] = check
            role_grid.attach(check, index % 3, index // 3, 1, 1)
        role_frame.add(role_grid); box.pack_start(role_frame, False, False, 0)

        limits = Gtk.Grid(column_spacing=16, row_spacing=10)
        self.quota = Gtk.SpinButton.new_with_range(16, 1024 * 1024, 16); self.quota.set_value(512)
        self.ttl = Gtk.SpinButton.new_with_range(60, 30 * 86400, 60); self.ttl.set_value(86400)
        self.bandwidth = Gtk.Entry(text="10M")
        self.automatic_bandwidth = Gtk.CheckButton(label="Automatic bandwidth protection")
        self.automatic_bandwidth.set_active(True)
        self.bandwidth_headroom = Gtk.SpinButton.new_with_range(0, 80, 5)
        self.bandwidth_headroom.set_value(50)
        self.max_requests = Gtk.SpinButton.new_with_range(4, 256, 1); self.max_requests.set_value(16)
        self.max_source_requests = Gtk.SpinButton.new_with_range(1, 256, 1); self.max_source_requests.set_value(4)
        self.request_timeout = Gtk.SpinButton.new_with_range(5, 300, 1); self.request_timeout.set_value(30)
        self.max_relays = Gtk.SpinButton.new_with_range(1, 64, 1); self.max_relays.set_value(4)
        self.max_tenant_relays = Gtk.SpinButton.new_with_range(1, 64, 1); self.max_tenant_relays.set_value(2)
        self.relay_idle_timeout = Gtk.SpinButton.new_with_range(5, 300, 1); self.relay_idle_timeout.set_value(30)
        _row(limits, 0, "Quota per tenant (MiB)", self.quota)
        _row(limits, 1, "Default expiry (seconds)", self.ttl)
        _row(limits, 2, "Global bandwidth limit", self.bandwidth)
        _row(limits, 3, "Automatic bandwidth protection", self.automatic_bandwidth)
        _row(limits, 4, "Reserved headroom (%)", self.bandwidth_headroom)
        _row(limits, 5, "Concurrent requests", self.max_requests)
        _row(limits, 6, "Requests per source", self.max_source_requests)
        _row(limits, 7, "Request timeout (seconds)", self.request_timeout)
        _row(limits, 8, "Concurrent relays", self.max_relays)
        _row(limits, 9, "Relays per tenant", self.max_tenant_relays)
        _row(limits, 10, "Relay idle timeout (seconds)", self.relay_idle_timeout)
        box.pack_start(limits, False, False, 0)

        self.relay_targets = Gtk.TextView(); self.relay_targets.set_monospace(True)
        self.manifests = Gtk.TextView(); self.manifests.set_monospace(True)
        for label, view in (("Allowed relay targets (one HOST:PORT per line)", self.relay_targets), ("Signed update manifest paths/URLs (one per line)", self.manifests)):
            frame = Gtk.Frame(label=label); frame.set_size_request(-1, 130)
            frame.add(self._scroll(view)); box.pack_start(frame, True, True, 0)
        return self._scroll(box)

    def _tokens_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(16)
        self.token_store = Gtk.ListStore(str, str)
        self.token_view = Gtk.TreeView(model=self.token_store)
        for index, label in enumerate(("Tenant", "SHA-256 token digest")):
            self.token_view.append_column(Gtk.TreeViewColumn(label, Gtk.CellRendererText(), text=index))
        box.pack_start(self._scroll(self.token_view), True, True, 0)
        buttons = Gtk.Box(spacing=8)
        add = Gtk.Button(label="Generate tenant token"); add.connect("clicked", self._add_token)
        remove = Gtk.Button(label="Remove selected token"); remove.connect("clicked", self._remove_token)
        reveal = Gtk.Button(label="Reveal bootstrap token"); reveal.connect("clicked", self._reveal_bootstrap)
        erase = Gtk.Button(label="Securely remove bootstrap copy"); erase.connect("clicked", self._delete_bootstrap)
        buttons.pack_start(add, False, False, 0); buttons.pack_start(remove, False, False, 0)
        buttons.pack_end(erase, False, False, 0); buttons.pack_end(reveal, False, False, 0)
        box.pack_end(buttons, False, False, 0)
        return box

    def _log_page(self) -> Gtk.Widget:
        self.log = Gtk.TextView(); self.log.set_editable(False); self.log.set_monospace(True)
        self.log.get_buffer().set_text("Select “Load service log” to read the latest service events.")
        return self._scroll(self.log)

    def _server_admin(self, arguments: list[str], timeout: int = 90) -> subprocess.CompletedProcess[str]:
        return _run([PACKAGED_LAUNCHER, "admin", *arguments], privileged=True, timeout=timeout)

    def _failure(self, title: str, result: subprocess.CompletedProcess[str]) -> None:
        detail = (result.stderr or result.stdout or "Operation was cancelled").strip()
        _message(self, title, detail, Gtk.MessageType.ERROR)

    def refresh_status(self) -> bool:
        active = _run(["/usr/bin/systemctl", "is-active", SERVICE], timeout=15)
        enabled = _run(["/usr/bin/systemctl", "is-enabled", SERVICE], timeout=15)
        active_text = active.stdout.strip() or "unknown"
        enabled_text = enabled.stdout.strip() or "unknown"
        self.status.set_text(f"Service: {active_text} · Start at boot: {enabled_text}")
        return False

    def _service_action(self, _button: Gtk.Button, action: str) -> None:
        arguments = {
            "start": ["start", SERVICE], "stop": ["stop", SERVICE], "restart": ["restart", SERVICE],
            "enable": ["enable", "--now", SERVICE], "disable": ["disable", "--now", SERVICE],
        }[action]
        result = _run(["/usr/bin/systemctl", *arguments], privileged=True)
        if result.returncode:
            self._failure(f"Could not {action} the service", result)
        self.refresh_status()

    def _load_config(self, _button: Gtk.Button | None = None) -> None:
        result = self._server_admin(["read-config"])
        if result.returncode:
            self._failure("Could not load configuration", result); return
        try:
            config = ServerConfig.from_dict(json.loads(result.stdout))
        except (json.JSONDecodeError, ServerError, TypeError, ValueError) as exc:
            _message(self, "Invalid installed configuration", str(exc), Gtk.MessageType.ERROR); return
        self._apply_config(config)
        _message(self, "Configuration loaded", "The installed server configuration is ready for editing.")

    def _apply_config(self, config: ServerConfig) -> None:
        self.bind.set_text(config.bind); self.port.set_value(config.port)
        self.tls_certificate.set_text(config.tls_certificate); self.tls_private_key.set_text(config.tls_private_key)
        self.database.set_text(config.database); self.client_config.set_text(config.client_config)
        self.quota.set_value(config.quota_mib_per_tenant); self.ttl.set_value(config.default_ttl_seconds)
        self.bandwidth.set_text(config.global_bandwidth_limit)
        self.automatic_bandwidth.set_active(config.automatic_bandwidth_control)
        self.bandwidth_headroom.set_value(config.bandwidth_headroom_percent)
        self.max_requests.set_value(config.max_concurrent_requests)
        self.max_source_requests.set_value(config.max_requests_per_source)
        self.request_timeout.set_value(config.request_timeout_seconds)
        self.max_relays.set_value(config.max_relay_connections)
        self.max_tenant_relays.set_value(config.max_relay_connections_per_tenant)
        self.relay_idle_timeout.set_value(config.relay_idle_timeout_seconds)
        for role, check in self.roles.items(): check.set_active(role in config.enabled_roles)
        self._set_lines(self.relay_targets, config.relay_targets); self._set_lines(self.manifests, config.update_manifests)
        self._tokens = dict(config.token_hashes); self._render_tokens()

    @staticmethod
    def _set_lines(view: Gtk.TextView, values: list[str]) -> None:
        view.get_buffer().set_text("\n".join(values))

    @staticmethod
    def _lines(view: Gtk.TextView) -> list[str]:
        buffer = view.get_buffer(); text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        return [line.strip() for line in text.splitlines() if line.strip()]

    def _collect(self) -> ServerConfig:
        raw = {
            "schema": 1, "bind": self.bind.get_text().strip(), "port": self.port.get_value_as_int(),
            "tls_certificate": self.tls_certificate.get_text().strip(),
            "tls_private_key": self.tls_private_key.get_text().strip(),
            "database": self.database.get_text().strip(), "client_config": self.client_config.get_text().strip(),
            "enabled_roles": [role for role, check in self.roles.items() if check.get_active()],
            "token_hashes": dict(self._tokens), "quota_mib_per_tenant": self.quota.get_value_as_int(),
            "default_ttl_seconds": self.ttl.get_value_as_int(),
            "global_bandwidth_limit": self.bandwidth.get_text().strip(),
            "automatic_bandwidth_control": self.automatic_bandwidth.get_active(),
            "bandwidth_headroom_percent": self.bandwidth_headroom.get_value_as_int(),
            "max_concurrent_requests": self.max_requests.get_value_as_int(),
            "max_requests_per_source": self.max_source_requests.get_value_as_int(),
            "request_timeout_seconds": self.request_timeout.get_value_as_int(),
            "max_relay_connections": self.max_relays.get_value_as_int(),
            "max_relay_connections_per_tenant": self.max_tenant_relays.get_value_as_int(),
            "relay_idle_timeout_seconds": self.relay_idle_timeout.get_value_as_int(),
            "relay_targets": self._lines(self.relay_targets), "update_manifests": self._lines(self.manifests),
        }
        return ServerConfig.from_dict(raw)

    def _validate(self, _button: Gtk.Button | None = None) -> bool:
        try:
            self._collect()
        except (OSError, ServerError, TypeError, ValueError) as exc:
            _message(self, "Configuration is invalid", str(exc), Gtk.MessageType.ERROR); return False
        _message(self, "Configuration is valid", "All fields and security requirements passed validation.")
        return True

    def _save_config(self, _button: Gtk.Button, restart: bool) -> None:
        try:
            config = self._collect()
        except (OSError, ServerError, TypeError, ValueError) as exc:
            _message(self, "Configuration is invalid", str(exc), Gtk.MessageType.ERROR); return
        descriptor, name = tempfile.mkstemp(prefix="tuxindrive-server-config-", suffix=".json")
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(asdict(config), handle, indent=2); handle.write("\n")
            result = self._server_admin(["write-config", "--source", name])
        finally:
            try: Path(name).unlink()
            except FileNotFoundError: pass
        if result.returncode:
            self._failure("Could not save configuration", result); return
        if restart:
            service = _run(["/usr/bin/systemctl", "restart", SERVICE], privileged=True)
            if service.returncode:
                self._failure("Configuration saved, but restart failed", service); return
        _message(self, "Configuration saved", "The validated private configuration was installed atomically.")
        self.refresh_status()

    def _render_tokens(self) -> None:
        self.token_store.clear()
        for digest, tenant in sorted(self._tokens.items(), key=lambda item: (item[1], item[0])):
            self.token_store.append((tenant, digest))

    def _add_token(self, _button: Gtk.Button) -> None:
        dialog = Gtk.Dialog(title="Generate API token", transient_for=self, modal=True)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Generate", Gtk.ResponseType.OK)
        entry = Gtk.Entry(); entry.set_placeholder_text("Tenant identifier")
        box = dialog.get_content_area(); box.set_spacing(8); box.set_border_width(12)
        box.add(Gtk.Label(label="Tenant identifiers may contain letters, numbers and -_.:@", xalign=0)); box.add(entry)
        dialog.show_all(); response = dialog.run(); tenant = entry.get_text().strip(); dialog.destroy()
        if response != Gtk.ResponseType.OK: return
        token = secrets.token_urlsafe(48); digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        try:
            ServerConfig.from_dict({"token_hashes": {digest: tenant}})
        except (ServerError, ValueError) as exc:
            _message(self, "Invalid tenant", str(exc), Gtk.MessageType.ERROR); return
        self._tokens[digest] = tenant; self._render_tokens()
        clipboard = Gtk.Clipboard.get_default(self.get_display()); clipboard.set_text(token, -1)
        _message(self, "Token generated and copied", f"Tenant: {tenant}\n\n{token}\n\nSave the configuration, deliver this token securely, and do not store another plaintext copy.")

    def _remove_token(self, _button: Gtk.Button) -> None:
        model, iterator = self.token_view.get_selection().get_selected()
        if iterator is None: return
        digest = model.get_value(iterator, 1)
        if len(self._tokens) <= 1:
            _message(self, "Token cannot be removed", "At least one API token must remain.", Gtk.MessageType.WARNING); return
        self._tokens.pop(digest, None); self._render_tokens()

    def _reveal_bootstrap(self, _button: Gtk.Button) -> None:
        result = self._server_admin(["read-bootstrap-token"])
        if result.returncode:
            self._failure("Could not read bootstrap token", result); return
        token = result.stdout.strip(); Gtk.Clipboard.get_default(self.get_display()).set_text(token, -1)
        _message(self, "Bootstrap token copied", token + "\n\nRemove the bootstrap copy after storing the token in the client.")

    def _delete_bootstrap(self, _button: Gtk.Button) -> None:
        result = self._server_admin(["delete-bootstrap-token"])
        if result.returncode: self._failure("Could not remove bootstrap token", result); return
        _message(self, "Bootstrap copy removed", "The root-only plaintext bootstrap file has been deleted.")

    def _load_log(self, _button: Gtk.Button) -> None:
        result = _run(["/usr/bin/journalctl", "--unit", SERVICE, "--lines", "250", "--no-pager", "--output", "short-iso"], privileged=True)
        if result.returncode:
            self._failure("Could not read service log", result); return
        self.log.get_buffer().set_text(result.stdout or "No service log entries are available.")


class ServerApplication(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="io.github.tuxindrive.Server", flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self) -> None:
        window = self.props.active_window or ServerWindow(self)
        window.show_all(); window.present()


def main() -> int:
    if os.geteuid() == 0:
        print("Run the TuxInDrive Server GUI as a normal desktop user; it requests authorization per administrative action.", file=sys.stderr)
        return 2
    return int(ServerApplication().run([]))


if __name__ == "__main__":
    raise SystemExit(main())
