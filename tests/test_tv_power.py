"""Pure, non-destructive LG webOS power-state parsing tests."""

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("tv_power", ROOT / "web/tv_power.py")
tv = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tv)


class LGPowerStateTests(unittest.TestCase):
    def test_verified_active(self):
        self.assertEqual(tv.classify_power_reply("{'returnValue': True, 'state': 'Active'}"), "on")

    def test_verified_screen_dark_but_webos_awake(self):
        self.assertEqual(tv.classify_power_reply("{'returnValue': True, 'state': 'Screen Off'}"), "screen_off")

    def test_verified_sleep_states(self):
        for state in ("Suspend", "Power Off"):
            with self.subTest(state=state):
                self.assertEqual(tv.classify_power_reply(
                    "{'returnValue': True, 'state': '" + state + "'}"), "off")

    def test_invalid_or_unsupported_response_is_unknown(self):
        for raw in (
            "", "not-json", "{}", "{'returnValue': False, 'state': 'Active'}",
            "{'returnValue': 'true', 'state': 'Active'}",
            "{'returnValue': True, 'state': 'Mystery'}",
            "{'state': 'Active'}", '{"returnValue":true, "state": "Active"}',
            "True", "123", "[]",
            "{'returnValue': True, 'state': 'Active'}" + " " * 501,
            "__import__('os').system('true')",
        ):
            with self.subTest(raw=raw[:42]):
                self.assertEqual(tv.classify_power_reply(raw), "unknown")

    def test_untrusted_input_never_runs_code(self):
        import os
        from unittest import mock
        with mock.patch.object(os, "system") as run:
            self.assertEqual(tv.classify_power_reply(
                "{'state': __import__('os').system('false'), 'returnValue': True}"), "unknown")
            run.assert_not_called()

    def test_status_uses_webos_only_after_pairing(self):
        backend = (ROOT / "web/server.py").read_text()
        self.assertIn('report["tv"]["paired"] and report["tv"].get("webos_api_reachable")', backend)
        self.assertIn('classify_power_reply(call_tv("get_power_state"))', backend)
        self.assertIn('"screen_on"', backend)
        self.assertIn('call_tv("turn_screen_on")', backend)
        self.assertIn('invalidate_status_cache()', backend)

    def test_unknown_fallback_is_not_off(self):
        status = (ROOT / "bin/status.py").read_text()
        self.assertIn('"power_state": "unknown"', status)
        self.assertNotIn('unknown_without_webos_pairing', status)


if __name__ == "__main__":
    unittest.main()
