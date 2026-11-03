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




if __name__ == "__main__":
    unittest.main()
