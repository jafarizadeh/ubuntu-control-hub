"""Read-only Ubuntu telemetry extensions for the iPhone dashboard."""

from pathlib import Path
import importlib.util
import json
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("desktop_status_observability", ROOT / "agent/desktop_status.py")
desktop = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(desktop)


class UbuntuObservabilityTests(unittest.TestCase):
    def test_audio_readonly_volume(self):
        proc = subprocess.CompletedProcess([], 0, "Volume: 0.63\n", "")
        with mock.patch.object(desktop.shutil, "which", return_value="/usr/bin/wpctl"):
            with mock.patch.object(desktop.subprocess, "run", return_value=proc) as run:
                self.assertEqual(desktop.audio_status(),
                                 {"available": True, "volume_percent": 63, "muted": False})
        self.assertEqual(run.call_args.args[0], ["/usr/bin/wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])

    def test_audio_muted(self):
        proc = subprocess.CompletedProcess([], 0, "Volume: 0.50 [MUTED]\n", "")
        with mock.patch.object(desktop.shutil, "which", return_value="/usr/bin/wpctl"):
            with mock.patch.object(desktop.subprocess, "run", return_value=proc):
                self.assertTrue(desktop.audio_status()["muted"])

    def test_network_readonly_connection_names(self):
        proc = subprocess.CompletedProcess([], 0,
            "enp4s0:ethernet:connected:Wired\nwlp5s0:wifi:connected:Home Wi-Fi\nlo:loopback:connected:lo\n", "")
        with mock.patch.object(desktop.shutil, "which", return_value="/usr/bin/nmcli"):
            with mock.patch.object(desktop.subprocess, "run", return_value=proc) as run:
                state = desktop.network_status()
        self.assertTrue(state["connected"])
        self.assertEqual(len(state["connections"]), 2)
        self.assertEqual(run.call_args.args[0][1:3], ["-t", "-f"])
        self.assertNotIn("down", run.call_args.args[0])

    def test_workload_manager_profile_readonly(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / "cpu-workload-manager"
            base.mkdir()
            (base / "cpuwm.py").write_text("# placeholder")
            (base / "config.json").write_text(json.dumps({"profile": "quiet"}))
            with mock.patch.object(desktop.Path, "home", return_value=Path(folder)):
                self.assertEqual(desktop.workload_manager_status(),
                                 {"available": True, "profile": "quiet"})

    def test_workload_manager_profile_invalid(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / "cpu-workload-manager"
            base.mkdir()
            (base / "cpuwm.py").write_text("# placeholder")
            (base / "config.json").write_text(json.dumps({"profile": "unsafe"}))
            with mock.patch.object(desktop.Path, "home", return_value=Path(folder)):
                self.assertFalse(desktop.workload_manager_status()["available"])

    def test_no_command_execution_in_dashboard_readers(self):
        source = (ROOT / "agent/desktop_status.py").read_text()
        for forbidden in ("wpctl set-volume", "nmcli networking off", "cpuwm.py profile"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
