"""Non-destructive tests of adaptive CPU Details updates and owner-only watch."""

import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"web"))
sys.path.insert(0, str(ROOT/"agent"))
import cpu_watch
import test_command_channel as command_tests
from test_outbound_agent import outbound

server = command_tests.server
headers = command_tests.headers


class CPUWatchLeaseTests(unittest.TestCase):
    def test_watch_is_expiring_and_read_only(self):
        with mock.patch.object(cpu_watch.time,"monotonic",return_value=100):
            watch=cpu_watch.CPUWatch(ttl_seconds=7)
            self.assertFalse(watch.active())
            watch.touch()
            self.assertTrue(watch.active())
        with mock.patch.object(cpu_watch.time,"monotonic",return_value=106):
            self.assertTrue(watch.active())
        with mock.patch.object(cpu_watch.time,"monotonic",return_value=107.01):
            self.assertFalse(watch.active())
        with mock.patch.object(cpu_watch.time,"monotonic",return_value=109):
            watch.touch()
            self.assertTrue(watch.active())
        with mock.patch.object(cpu_watch.time,"monotonic",return_value=108):
            self.assertFalse(watch.active())

    def test_lease_rejects_unsafe_configurations(self):
        for value in (0,2,31):
            with self.subTest(value=value),self.assertRaises(ValueError):
                cpu_watch.CPUWatch(ttl_seconds=value)

    def test_agent_interval_only_accepts_true_boolean(self):
        self.assertEqual(outbound.next_report_interval({"cpu_watch_active":True},10),2)
        for value in (False,None,1,2,"true",[],{}):
            with self.subTest(value=value):
                self.assertEqual(outbound.next_report_interval({"cpu_watch_active":value},10),10)
        self.assertEqual(outbound.next_report_interval({"cpu_watch_active":True},20),2)
        self.assertEqual(outbound.next_report_interval({},10),10)


class WatchEndpointTests(unittest.TestCase):
    def make_handler(self, body=b"{}"):
        handler=server.Handler.__new__(server.Handler)
        handler.path="/api/cpu/watch"
        handler.headers=headers()
        handler.headers["Content-Type"]="application/json"
        handler.headers["Content-Length"]=str(len(body))
        handler.rfile=io.BytesIO(body)
        handler._json=mock.Mock()
        return handler

    def test_watch_denied_before_identity_or_csrf(self):
        handler=self.make_handler()
        with mock.patch.object(server,"can_control",return_value=False),\
             mock.patch.object(server.CPU_WATCH,"touch") as touch:
            handler.do_POST()
            self.assertEqual(handler._json.call_args.args[1],403)
            touch.assert_not_called()
        with mock.patch.object(server,"can_control",return_value=True),\
             mock.patch.object(server.CPU_WATCH,"touch") as touch:
            handler.do_POST()
            self.assertEqual(handler._json.call_args.args[1],403)
            touch.assert_not_called()
            handler.headers["Origin"]="https://pi.example.ts.net"
            handler.do_POST()
            self.assertEqual(handler._json.call_args.args[1],403)
            touch.assert_not_called()

    def test_watch_requires_signed_owner_cookie_and_empty_body(self):
        handler=self.make_handler()
        handler.headers["Origin"]="https://pi.example.ts.net"
        handler.headers["Cookie"]="uc_hub=fake-cookie"
        handler.headers["X-UC-CSRF"]=handler._token("fake-cookie")
        cpu_report={
            "cpu":{"usage_percent":5.2,"per_core":[{"index":0,"usage_percent":8.0}],
                   "history":[{"time_unix":1790000000,"usage_percent":5.2}]},
            "gpus":[{"usage_percent":3}],
            "checked_at_unix":1790000000,
            "private_matter":"not for browser",
        }
        with mock.patch.object(server,"can_control",return_value=True),\
             mock.patch.object(server.CPU_WATCH,"touch") as touch,\
             mock.patch.object(server.BROKER,"desktop_state",return_value={
                 "control_agent":"online","last_agent_report_unix":1790000000,
                 "metrics":cpu_report}):
            handler.do_POST()
            touch.assert_called_once()
            reply=handler._json.call_args.args[0]
            self.assertEqual(reply["control_agent"],"online")
            self.assertTrue(reply["watch_active"])
            self.assertEqual(reply["metrics"]["cpu"]["usage_percent"],5.2)
            self.assertEqual(reply["metrics"]["gpus"][0]["usage_percent"],3)
            self.assertNotIn("private_matter",reply["metrics"])
        with mock.patch.object(server,"can_control",return_value=True),\
             mock.patch.object(server.CPU_WATCH,"touch") as touch:
            other=self.make_handler(body=b'{"action":"shutdown"}')
            other.headers["Origin"]="https://pi.example.ts.net"
            other.headers["Cookie"]="uc_hub=fake-cookie"
            other.headers["X-UC-CSRF"]=other._token("fake-cookie")
            other.do_POST()
            self.assertEqual(other._json.call_args.args[1],400)
            touch.assert_not_called()

    def test_fails_closed_without_cpu_agent(self):
        handler=self.make_handler()
        handler.headers["Origin"]="https://pi.example.ts.net"
        handler.headers["Cookie"]="uc_hub=fake-cookie"
        handler.headers["X-UC-CSRF"]=handler._token("fake-cookie")
        with mock.patch.object(server,"can_control",return_value=True),\
             mock.patch.object(server.BROKER,"desktop_state",return_value={
                 "control_agent":"unavailable","last_agent_report_unix":None}):
            handler.do_POST()
            reply=handler._json.call_args.args[0]
            self.assertEqual(reply["control_agent"],"unavailable")
            self.assertIsNone(reply["metrics"]["cpu"])
            self.assertEqual(reply["metrics"]["gpus"],[])


class BrowserContractTests(unittest.TestCase):
    def test_fast_watch_is_scoped_to_cpu_details(self):
        js=(ROOT/"web/static/app.js").read_text()
        backend=(ROOT/"web/server.py").read_text()
        self.assertIn('"/api/cpu/watch"',js)
        self.assertIn('if (app.tab !== "cpu" || document.hidden',js)
        self.assertIn('clearInterval(app.cpuWatchTimer)',js)
        self.assertIn('2000)',js)
        self.assertIn('15000)',js)
        self.assertIn('X-UC-CSRF',js)
        self.assertIn('if request:',backend)
        self.assertIn('"cpu_watch_active"',backend)
        self.assertNotIn("subprocess.run", (ROOT/"web/cpu_watch.py").read_text())


if __name__=="__main__":
    unittest.main()
