"""Offline unit tests for the read-only desktop agent and SSH client."""

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_module(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


agent = load_module(ROOT / "agent/desktop_status.py", "agent_desktop_status")
client = load_module(ROOT / "bin/desktop_agent_client.py", "desktop_agent_client")


class TelemetryParsingTests(unittest.TestCase):
    def test_cpu_counters_and_usage(self):
        a = agent.parse_cpu_times("cpu  100 0 50 850 0 0 0 0 0 0\ncpu0 5 6 7 8")
        b = agent.parse_cpu_times("cpu  140 0 60 900 0 0 0 0 0 0")
        self.assertEqual(a, (1000, 850))
        self.assertEqual(agent.usage_percent(a, b), 50.0)

    def test_cpu_zero_elapsed(self):
        self.assertIsNone(agent.usage_percent((100, 90), (100, 90)))

    def test_invalid_cpu_counters(self):
        with self.assertRaises(ValueError):
            agent.parse_cpu_times("intr 12345")

    def test_memory(self):
        info = agent.parse_meminfo("MemTotal:        2048000 kB\nMemAvailable:   1024000 kB\n")
        self.assertEqual(info, {"total_mib": 2000, "available_mib": 1000, "used_percent": 50.0})

    def test_memory_missing_or_invalid(self):
        self.assertIsNone(agent.parse_meminfo("MemFree: 100 kB"))
        self.assertIsNone(agent.parse_meminfo("MemTotal: 100 kB\nMemAvailable: 200 kB"))

    def test_temperature_sanity(self):
        self.assertEqual(agent.temperature_c("42000"), 42.0)
        self.assertIsNone(agent.temperature_c("garbage"))
        self.assertIsNone(agent.temperature_c("200000"))

    def test_ssh_entry_requires_exact_original_command(self):
        with mock.patch.object(sys, "argv", ["desktop_status.py", "--ssh"]):
            with mock.patch.dict("os.environ", {"SSH_ORIGINAL_COMMAND": "shutdown"}, clear=False):
                self.assertEqual(agent.main(), 2)

    def test_runtime_schema(self):
        with mock.patch.object(agent, "cpu_usage", return_value=17.5):
            with mock.patch.object(agent, "cpu_temperature", return_value=None):
                with mock.patch.object(agent, "gpu_status", return_value=[]):
                    with mock.patch.object(agent, "fan_speeds", return_value=[]):
                        payload = agent.collect_status()
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["cpu"]["usage_percent"], 17.5)
        self.assertIn("memory", payload)
        self.assertIn("storage", payload)
        json.dumps(payload)


class SSHClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.key = pathlib.Path(self.temp.name, "id_ed25519_status")
        self.key.write_text("placeholder for tests only")
        self.key.chmod(0o600)
        self.config = {
            "ip": "192.0.2.20",
            "agent_ssh": {
                "enabled": True,
                "username": "testuser",
                "identity_file": str(self.key),
            },
        }

    def test_disabled_returns_not_configured_without_ssh(self):
        with mock.patch.object(client.subprocess, "run") as run:
            self.assertEqual(client.fetch_status({"ip": "192.0.2.20"}), {"control_agent": "not_configured"})
            run.assert_not_called()

    def test_no_unsafe_username_or_ip(self):
        with mock.patch.object(client.subprocess, "run") as run:
            self.config["agent_ssh"]["username"] = "-oProxyCommand=bad"
            self.assertEqual(client.fetch_status(self.config), {"control_agent": "unavailable"})
            self.config["agent_ssh"]["username"] = "testuser"
            self.config["ip"] = "-oProxyCommand=bad"
            self.assertEqual(client.fetch_status(self.config), {"control_agent": "unavailable"})
            run.assert_not_called()

    def test_rejects_world_readable_key(self):
        self.key.chmod(0o644)
        with mock.patch.object(client.subprocess, "run") as run:
            self.assertEqual(client.fetch_status(self.config), {"control_agent": "unavailable"})
            run.assert_not_called()

    def test_ssh_command_is_fixed_and_restricted(self):
        payload = {
            "schema_version": 1, "cpu": {"usage_percent": 12.5},
            "memory": {"available_mib": 4000},
            "storage": {"free_gib": 30},
        }
        completed = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
        with mock.patch.object(client.subprocess, "run", return_value=completed) as run:
            response = client.fetch_status(self.config)
        self.assertEqual(response["control_agent"], "online")
        self.assertEqual(response["metrics"]["cpu"]["usage_percent"], 12.5)
        args = run.call_args.args[0]
        self.assertEqual(args[0], "ssh")
        self.assertIn("BatchMode=yes", args)
        self.assertIn("StrictHostKeyChecking=yes", args)
        self.assertEqual(args[-1], "ubuntu-control-status-v1")
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_rejects_unexpected_payload(self):
        completed = subprocess.CompletedProcess([], 0, '{"schema_version":2}', "")
        with mock.patch.object(client.subprocess, "run", return_value=completed):
            self.assertEqual(client.fetch_status(self.config), {"control_agent": "unavailable"})

    def test_timeout_returns_unavailable(self):
        with mock.patch.object(client.subprocess, "run", side_effect=subprocess.TimeoutExpired("ssh", 7)):
            self.assertEqual(client.fetch_status(self.config), {"control_agent": "unavailable"})


if __name__ == "__main__":
    unittest.main()
