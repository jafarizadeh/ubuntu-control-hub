"""Offline safety and simulation tests; no power subprocess or live state access."""
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from test_command_channel import server, headers
import power_safety as safety
from power_preview import PreviewStore
from command_queue import CommandQueue

ROOT = Path(__file__).resolve().parents[1]
HEADER = "WHO UID USER PID COMM WHAT WHY MODE\n"
BLOCK = "desktop 1000 private 123 gnome-session-s shutdown unsaved work block\n"
DELAY = "browser 1000 private 456 chrome shutdown save session delay\n"
INACTIVE = "LoadState=loaded\nActiveState=inactive\nSubState=dead\n"


class SafetyTests(unittest.TestCase):
    def test_service_states(self):
        self.assertEqual(safety.parse_atlas(INACTIVE), "inactive")
        self.assertEqual(safety.parse_atlas(INACTIVE.replace("inactive", "active").replace("dead", "running")), "active")
        for text in (None, "", "LoadState=not-found\n", INACTIVE + "ActiveState=inactive\n",
                     INACTIVE.replace("inactive", "activating"), INACTIVE.replace("dead", "failed")):
            self.assertEqual(safety.parse_atlas(text), "unknown")

    def test_inhibitors_private_columns_never_returned(self):
        parsed = safety.parse_inhibitors(HEADER + BLOCK + DELAY + "2 inhibitors listed.")
        self.assertTrue(parsed["shutdown_block"])
        self.assertTrue(parsed["session_block"])
        self.assertTrue(parsed["shutdown_delay"])
        self.assertFalse(parsed["unknown"])
        self.assertNotIn("private", json.dumps(parsed))
        self.assertNotIn("123", json.dumps(parsed))
        delay = safety.parse_inhibitors(HEADER + DELAY + "1 inhibitor listed.")
        self.assertFalse(delay["shutdown_block"])
        self.assertTrue(delay["shutdown_delay"])
        self.assertFalse(safety.parse_inhibitors("No inhibitors listed.\n")["unknown"])

    def test_inhibitor_ambiguity_closed(self):
        for text in (None, "", "garbage", HEADER + BLOCK, HEADER + BLOCK + "2 inhibitors listed.",
                     HEADER + BLOCK.replace("block", "mystery") + "1 inhibitor listed.",
                     HEADER + BLOCK.replace("shutdown", "unknown") + "1 inhibitor listed."):
            self.assertTrue(safety.parse_inhibitors(text)["unknown"], text)

    def test_collection_conservative_and_redacted(self):
        active = INACTIVE.replace("inactive", "active").replace("dead", "running")
        with mock.patch.object(safety, "read_command", side_effect=[active, HEADER + BLOCK + DELAY + "2 inhibitors listed.", "codex\nns3-run\natlas\ncpuwm\n"]):
            report = safety.collect_power_safety()
        self.assertFalse(report["safe_to_request"])
        self.assertEqual(report["atlas_state"], "active")
        self.assertIn("Codex", report["workload_categories"])
        self.assertTrue(report["warnings"])
        self.assertTrue(report["unknowns"])
        self.assertIsNotNone(datetime.fromisoformat(report["checked_at"]).tzinfo)
        self.assertNotIn("private", json.dumps(report))
        for results in ([INACTIVE, "No inhibitors listed.", ""], [None, None, None]):
            with mock.patch.object(safety, "read_command", side_effect=results):
                report = safety.collect_power_safety()
            self.assertFalse(report["safe_to_request"])
            self.assertTrue(report["blocked_reasons"])

    def test_subprocess_fixed_readers_and_missing(self):
        for args in (safety.ATLAS, safety.INHIBITORS, safety.PROCESSES):
            with mock.patch.object(safety.subprocess, "Popen", side_effect=FileNotFoundError) as run:
                self.assertIsNone(safety.read_command(args))
                self.assertEqual(run.call_args.args[0], args)
                self.assertIs(run.call_args.kwargs["shell"], False)
        with mock.patch.object(safety.subprocess, "Popen") as run:
            with self.assertRaises(ValueError):
                safety.read_command(["unexpected"])
            run.assert_not_called()

    def test_subprocess_timeout_overflow_exit_and_decode(self):
        for case in ("timeout", "overflow", "exit", "decode", "ok"):
            child = mock.MagicMock()
            child.poll.return_value = None
            child.wait.return_value = 1 if case == "exit" else 0
            selector = mock.MagicMock()
            selector.select.return_value = [] if case == "timeout" else [(None, None)]
            chunks = [b"x" * 4096] * 9 if case == "overflow" else [b"\xff" if case == "decode" else b"ok", b""]
            with mock.patch.object(safety.subprocess, "Popen") as run, mock.patch.object(safety.selectors, "DefaultSelector") as select, mock.patch.object(safety.os, "read", side_effect=chunks):
                run.return_value.__enter__.return_value = child
                select.return_value.__enter__.return_value = selector
                result = safety.read_command(safety.ATLAS)
            self.assertEqual(result, "ok" if case == "ok" else None)
            child.kill.assert_called_once()


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "preview.sqlite"
        self.store = PreviewStore(self.path)
        self.assertFalse(self.path.exists())

    def test_lifecycle_restart_and_cancel(self):
        with mock.patch("power_preview.time.time", return_value=1000):
            self.assertEqual(self.store.get()["state"], "absent")
            draft = self.store.create({"action": "shutdown", "delay_minutes": 1})
            self.assertEqual(draft["remaining_seconds"], 60)
            with self.assertRaises(FileExistsError):
                PreviewStore(self.path).create({"action": "restart", "delay_minutes": 2})
        with mock.patch("power_preview.time.time", return_value=1030):
            restarted = PreviewStore(self.path)
            self.assertEqual(restarted.get()["remaining_seconds"], 30)
            canceled = restarted.cancel({})
            self.assertEqual(canceled["state"], "canceled")
            self.assertEqual(canceled["remaining_seconds"], 0)
            self.assertEqual(restarted.cancel({})["state"], "canceled")
            self.store.create({"action": "restart", "delay_minutes": 240})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_elapsed_never_executes_or_queues(self):
        queue = CommandQueue(Path(self.folder.name) / "queue.sqlite")
        self.addCleanup(queue.db.close)
        with mock.patch.object(subprocess, "Popen") as popen, mock.patch.object(subprocess, "run") as run, mock.patch.object(CommandQueue, "enqueue") as enqueue:
            with mock.patch("power_preview.time.time", return_value=1000):
                self.store.create({"action": "restart", "delay_minutes": 1})
            with mock.patch("power_preview.time.time", return_value=1060):
                result = PreviewStore(self.path).get()
                self.assertEqual(result["state"], "elapsed")
                self.assertEqual(self.store.cancel({})["state"], "elapsed")
                self.assertTrue(result["preview_only"])
                self.assertFalse(result["will_execute"])
                self.assertEqual(result["remaining_seconds"], 0)
            popen.assert_not_called()
            run.assert_not_called()
            enqueue.assert_not_called()
        for action in ("shutdown", "restart", "poweroff", "reboot"):
            with self.assertRaises(ValueError):
                queue.enqueue({"action": action, "value": True})

    def test_allowlist(self):
        bad = []
        for n in (True, False, 0, 241, 1.0, "1", None, [], {}):
            bad.append({"action": "shutdown", "delay_minutes": n})
        for action in ("reboot", "poweroff", "SHUTDOWN", [], None):
            bad.append({"action": action, "delay_minutes": 1})
        bad.extend([None, [], {}, {"action": "shutdown", "delay_minutes": 1, "execute": True}])
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.store.create(payload)
        self.assertFalse(self.path.exists())
        with self.assertRaises(ValueError):
            self.store.cancel({"execute": True})


class EndpointTests(unittest.TestCase):
    setUp = PreviewTests.setUp

    def handler(self, path, body=None):
        handler = server.Handler.__new__(server.Handler)
        handler.path = path
        handler.headers = headers()
        handler._json = mock.Mock()
        if body is not None:
            raw = json.dumps(body).encode()
            handler.headers["Origin"] = "https://pi.example.ts.net"
            handler.headers["Cookie"] = "uc_hub=example"
            handler.headers["X-UC-CSRF"] = handler._token("example")
            handler.headers["Content-Type"] = "application/json"
            handler.headers["Content-Length"] = str(len(raw))
            handler.rfile = io.BytesIO(raw)
        return handler

    def test_unauthorized_and_csrf(self):
        for path, body in (("/api/power/safety", None), ("/api/power/preview", None),
                           ("/api/power/preview", {"action": "shutdown", "delay_minutes": 1}), ("/api/power/cancel", {})):
            h = self.handler(path, body)
            with mock.patch.object(server, "can_control", return_value=False), mock.patch.object(server, "PREVIEWS") as store:
                h.do_GET() if body is None else h.do_POST()
                self.assertEqual(h._json.call_args.args[1], 403)
                store.get.assert_not_called()
                store.create.assert_not_called()
                store.cancel.assert_not_called()
        for field in ("Origin", "Cookie", "X-UC-CSRF"):
            h = self.handler("/api/power/preview", {"action": "shutdown", "delay_minutes": 1})
            del h.headers[field]
            with mock.patch.object(server, "can_control", return_value=True):
                h.do_POST()
                self.assertEqual(h._json.call_args.args[1], 403)
        self.assertFalse(self.path.exists())

    def test_safety_offline_stale_and_signed_fresh(self):
        fresh = safety.collect_power_safety
        with mock.patch.object(safety, "read_command", return_value=None):
            report = fresh()
        cases = [({"control_agent": "unavailable"}, "absent"),
                 ({"control_agent": "unavailable", "last_agent_report_unix": 1}, "stale"),
                 ({"control_agent": "online", "metrics": {}}, "absent"),
                 ({"control_agent": "online", "metrics": {"power_safety": {"checked_at": report["checked_at"]}}}, "stale"),
                 ({"control_agent": "online", "metrics": {"power_safety": {**report, "checked_at": "bad"}}}, "stale"),
                 ({"control_agent": "online", "metrics": {"power_safety": {**report, "checked_at": "2000-01-01T00:00:00+00:00"}}}, "stale"),
                 ({"control_agent": "online", "metrics": {"power_safety": {**report, "checked_at": "2099-01-01T00:00:00+00:00"}}}, "stale"),
                 ({"control_agent": "online", "metrics": {"power_safety": {**report, "checked_at": datetime.now().isoformat()}}}, "stale"),
                 ({"control_agent": "online", "metrics": {"power_safety": report}}, "fresh")]
        for state, expected in cases:
            h = self.handler("/api/power/safety")
            with mock.patch.object(server, "can_control", return_value=True), mock.patch.object(server.BROKER, "desktop_state", return_value=state), mock.patch.object(server, "status") as pi:
                h.do_GET()
                result = h._json.call_args.args[0]
                self.assertEqual(result["status"], expected)
                self.assertFalse(result["safe_to_request"])
                pi.assert_not_called()

    def test_blocked_preview_endpoints(self):
        with mock.patch.object(server, "can_control", return_value=True), mock.patch.object(server, "PREVIEWS", self.store), mock.patch.object(server, "power_safety", return_value={"status": "stale", "safe_to_request": False, "blocked_reasons": ["Unavailable"]}), mock.patch.object(server.BROKER.commands, "enqueue") as enqueue:
            for path, body, expected in (("/api/power/preview", {"action": "shutdown", "delay_minutes": 1}, "draft"),
                                         ("/api/power/preview", None, "draft"), ("/api/power/cancel", {}, "canceled")):
                h = self.handler(path, body)
                h.do_GET() if body is None else h.do_POST()
                result = h._json.call_args.args[0]
                self.assertEqual(result["state"], expected)
                self.assertTrue(result["preview_only"])
                self.assertFalse(result["will_execute"])
                self.assertIn("Blocked", result["message"])
            enqueue.assert_not_called()

    def test_endpoint_conflict_validation_and_cancel(self):
        with mock.patch.object(server, "can_control", return_value=True), mock.patch.object(server, "PREVIEWS", self.store), mock.patch.object(server, "power_safety", return_value={"status": "absent"}):
            cases = [("/api/power/preview", {"action": "shutdown", "delay_minutes": True}, 400),
                     ("/api/power/cancel", {"extra": True}, 400),
                     ("/api/power/preview", {"action": "restart", "delay_minutes": 1}, None),
                     ("/api/power/preview", {"action": "shutdown", "delay_minutes": 1}, 409)]
            for path, body, code in cases:
                h = self.handler(path, body)
                h.do_POST()
                if code:
                    self.assertEqual(h._json.call_args.args[1], code)
                else:
                    self.assertEqual(h._json.call_args.args[0]["state"], "draft")

    def test_frontend_preview_is_control_only(self):
        html = (ROOT / "web/static/index.html").read_text()
        js = (ROOT / "web/static/app.js").read_text()
        dashboard, control = html.split('id="view-control"', 1)
        self.assertNotIn('id="power-preview-card"', dashboard)
        self.assertIn('id="desktop-off" disabled', dashboard)
        self.assertIn('id="power-preview-card"', control)
        self.assertIn("Simulation only — will NOT turn off or restart Ubuntu.", control)
        self.assertIn('data.remaining_seconds', js)
        self.assertIn('"/api/power/cancel"', js)
        self.assertNotIn('remaining_seconds--', js)
        self.assertIn('put("power-safety-status"', js)
