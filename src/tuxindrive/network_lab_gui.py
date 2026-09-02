"""Separate GTK window for the loopback-only TuxInDrive Network Lab."""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

from .network_lab import NetworkLabRunner, ScenarioResult


def main() -> int:
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib, Gtk
    except (ImportError, ValueError) as exc:
        print(f"GTK 3 is required for the Network Lab window: {exc}")
        return 2

    class Window(Gtk.ApplicationWindow):
        def __init__(self, application):
            super().__init__(application=application, title="TuxInDrive Network Lab")
            self.set_default_size(1100, 760)
            self.set_size_request(640, 420)
            self.runner: NetworkLabRunner | None = None
            self.cancel = threading.Event()
            self.running = False
            self.completed_scenarios = 0
            self.total_scenarios = len(NetworkLabRunner.SCENARIOS)
            self.topology_state = "idle"
            self.active_scenario = ""

            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            root.set_border_width(12)
            self.add(root)
            heading = Gtk.Label()
            heading.set_markup("<span size='x-large' weight='bold'>TuxInDrive Network Lab</span>")
            heading.set_xalign(0)
            root.pack_start(heading, False, False, 0)
            boundary = Gtk.Label(label="LOCAL SANDBOX · FICTIONAL DATA · NO CLOUD ACCOUNTS · NO INTERNET")
            boundary.set_xalign(0)
            boundary.get_style_context().add_class("warning")
            root.pack_start(boundary, False, False, 0)
            explanation = Gtk.Label(label="Runs the production server and local clients on loopback, automatically checks networking scenarios, and records actionable diagnostics.")
            explanation.set_xalign(0); explanation.set_line_wrap(True)
            root.pack_start(explanation, False, False, 0)

            toolbar = Gtk.Box(spacing=8)
            self.run_button = Gtk.Button(label="Run all scenarios")
            self.stop_button = Gtk.Button(label="Stop")
            self.open_button = Gtk.Button(label="Open logs")
            self.stop_button.set_sensitive(False); self.open_button.set_sensitive(False)
            self.run_button.connect("clicked", self._run)
            self.stop_button.connect("clicked", lambda _button: self.cancel.set())
            self.open_button.connect("clicked", self._open_logs)
            for button in (self.run_button, self.stop_button, self.open_button): toolbar.pack_start(button, False, False, 0)
            root.pack_start(toolbar, False, False, 0)

            self.progress = Gtk.ProgressBar()
            self.progress.set_show_text(True)
            self.progress.set_fraction(0.0)
            self.progress.set_text(f"Ready · 0/{self.total_scenarios} scenarios")
            root.pack_start(self.progress, False, False, 0)

            topology_frame = Gtk.Frame(label="Local network traffic visualization")
            topology_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            topology_box.set_border_width(6)
            topology_frame.add(topology_box)
            self.topology = Gtk.DrawingArea()
            self.topology.set_size_request(-1, 170)
            self.topology.connect("draw", self._draw_topology)
            topology_box.pack_start(self.topology, True, True, 0)
            self.traffic_label = Gtk.Label(
                label="Waiting · Alice 127.0.0.2 ↔ Server 127.0.0.1 ↔ Bob 127.0.0.3"
            )
            self.traffic_label.set_xalign(0.5)
            self.traffic_label.set_selectable(True)
            topology_box.pack_start(self.traffic_label, False, False, 0)
            root.pack_start(topology_frame, False, False, 0)

            self.store = Gtk.ListStore(str, str, str, str)
            tree = Gtk.TreeView(model=self.store)
            for index, title in enumerate(("Status", "Scenario", "Duration", "Detail")):
                renderer = Gtk.CellRendererText()
                column = Gtk.TreeViewColumn(title, renderer, text=index)
                column.set_resizable(True)
                if index == 3: column.set_expand(True)
                tree.append_column(column)
            scroll = Gtk.ScrolledWindow(); scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC); scroll.add(tree)
            root.pack_start(scroll, True, True, 0)

            self.summary = Gtk.Label(label="Ready to run isolated scenarios")
            self.summary.set_xalign(0); self.summary.set_selectable(True)
            root.pack_start(self.summary, False, False, 0)

        def _run(self, _button):
            if self.running: return
            self.running = True; self.cancel.clear(); self.store.clear(); self.completed_scenarios = 0
            self.run_button.set_sensitive(False); self.stop_button.set_sensitive(True); self.open_button.set_sensitive(False)
            self.summary.set_text("Starting private loopback sandbox…")
            self.topology_state = "starting"; self.active_scenario = "sandbox-boundary"
            self.traffic_label.set_text(
                "Starting local nodes · no external interface or Internet route is used"
            )
            self.topology.queue_draw()
            self.progress.set_fraction(0.0)
            self.progress.set_text(f"Starting sandbox · 0/{self.total_scenarios} scenarios")
            self.runner = NetworkLabRunner(pace_seconds=0.35)
            threading.Thread(target=self._worker, daemon=True).start()

        def _worker(self):
            assert self.runner is not None
            results = self.runner.run(lambda result, identifier: GLib.idle_add(self._result, result, identifier), self.cancel)
            GLib.idle_add(self._finished, results)

        def _result(self, result: ScenarioResult, _identifier: str):
            self.active_scenario = _identifier
            if result.status == "running":
                self.topology_state = "traffic" if _identifier == "loopback-traffic" else "running"
                fraction = self.completed_scenarios / max(1, self.total_scenarios)
                self.progress.set_fraction(fraction)
                self.progress.set_text(
                    f"Running · {self.completed_scenarios}/{self.total_scenarios} · {result.name}"
                )
                self.summary.set_text(f"Running: {result.name}")
                if _identifier == "loopback-traffic":
                    self.traffic_label.set_text(
                        "ACTIVE · opening 127.0.0.2 and 127.0.0.3 connections and transferring fictional blocks"
                    )
                else:
                    self.traffic_label.set_text(
                        f"Local protocol activity · {result.name}"
                    )
                self.topology.queue_draw()
                return False
            if result.status != "cancelled":
                self.completed_scenarios += 1
            self.store.append((result.status.upper(), result.name, f"{result.duration_ms} ms", result.detail))
            self.summary.set_text(f"{result.status.capitalize()}: {result.name}")
            fraction = min(1.0, self.completed_scenarios / max(1, self.total_scenarios))
            self.progress.set_fraction(fraction)
            self.progress.set_text(
                f"{round(fraction * 100)}% · {self.completed_scenarios}/{self.total_scenarios} · {result.name}"
            )
            self.topology_state = result.status
            if self.runner and self.runner.loopback_connections:
                self.traffic_label.set_text(
                    f"Observed {self.runner.loopback_connections} real connections · "
                    f"{self.runner.loopback_bytes:,} bytes · loopback only"
                )
            self.topology.queue_draw()
            return False

        def _finished(self, results):
            self.running = False; self.run_button.set_sensitive(True); self.stop_button.set_sensitive(False); self.open_button.set_sensitive(True)
            passed = sum(item.status == "passed" for item in results); failed = sum(item.status == "failed" for item in results)
            self.summary.set_text(f"Finished: {passed} passed, {failed} failed · Logs: {self.runner.output_dir if self.runner else ''}")
            if results and all(item.status != "cancelled" for item in results):
                self.progress.set_fraction(1.0)
                self.progress.set_text(f"100% · {passed} passed · {failed} failed")
                self.topology_state = "failed" if failed else "passed"
            else:
                self.progress.set_text(
                    f"Cancelled · {self.completed_scenarios}/{self.total_scenarios} scenarios"
                )
                self.topology_state = "cancelled"
            self.topology.queue_draw()
            return False

        def _draw_topology(self, widget, context):
            allocation = widget.get_allocation()
            width, height = allocation.width, allocation.height
            centers = ((width * 0.18, height * 0.52), (width * 0.50, height * 0.52), (width * 0.82, height * 0.52))
            active = self.topology_state in {"starting", "running", "traffic"}
            if self.topology_state == "failed":
                line_color = (0.82, 0.16, 0.20)
            elif self.topology_state == "passed":
                line_color = (0.18, 0.65, 0.30)
            elif active:
                line_color = (0.35, 0.22, 0.85)
            else:
                line_color = (0.55, 0.55, 0.60)
            context.set_line_width(6 if self.topology_state == "traffic" else 3)
            context.set_source_rgb(*line_color)
            for left, right in ((centers[0], centers[1]), (centers[1], centers[2])):
                context.move_to(left[0] + 54, left[1])
                context.line_to(right[0] - 54, right[1])
                context.stroke()
                midpoint = ((left[0] + right[0]) / 2, left[1])
                context.move_to(midpoint[0] + 9, midpoint[1])
                context.line_to(midpoint[0] - 7, midpoint[1] - 7)
                context.line_to(midpoint[0] - 7, midpoint[1] + 7)
                context.close_path(); context.fill()
            labels = (
                ("Alice", "127.0.0.2"),
                ("TuxInDrive Server", "127.0.0.1"),
                ("Bob", "127.0.0.3"),
            )
            for index, ((x, y), (name, address)) in enumerate(zip(centers, labels)):
                if self.topology_state == "failed":
                    color = (0.82, 0.16, 0.20)
                elif self.topology_state == "passed":
                    color = (0.18, 0.65, 0.30)
                elif active:
                    color = (0.42, 0.28, 0.90) if index == 1 else (0.20, 0.48, 0.88)
                else:
                    color = (0.45, 0.47, 0.52)
                context.set_source_rgb(*color)
                context.arc(x, y, 44, 0, 6.283185307)
                context.fill()
                context.set_source_rgb(1, 1, 1)
                context.select_font_face("Sans", 0, 1)
                context.set_font_size(13)
                name_extents = context.text_extents(name)
                context.move_to(x - name_extents.width / 2, y - 3)
                context.show_text(name)
                context.set_font_size(11)
                address_extents = context.text_extents(address)
                context.move_to(x - address_extents.width / 2, y + 17)
                context.show_text(address)
            return False

        def _open_logs(self, _button):
            if not self.runner: return
            opener = "/usr/bin/xdg-open"
            if Path(opener).is_file():
                subprocess.Popen([opener, str(self.runner.output_dir)], close_fds=True, start_new_session=True)

        def do_delete_event(self, event):
            self.cancel.set()
            return False

    class App(Gtk.Application):
        def __init__(self): super().__init__(application_id="io.github.tuxindrive.NetworkLab")
        def do_activate(self):
            window = self.props.active_window or Window(self)
            window.show_all()
            window.present()

    return int(App().run(None))


if __name__ == "__main__":
    raise SystemExit(main())
