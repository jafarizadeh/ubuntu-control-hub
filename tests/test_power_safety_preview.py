"""Offline safety and simulation tests; no power subprocess or live state access."""
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import subprocess
import stat
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
        with mock.patch.object(safety, "read_command", side_effect=[active, HEADER + BLOCK + DELAY + "2 inhibitors listed.", "codex\nns3-run\natlas\ncpuwm\n", None]):
            report = safety.collect_power_safety()
        self.assertFalse(report["safe_to_request"])
        self.assertEqual(report["atlas_state"], "active")
        self.assertIn("Codex", report["workload_categories"])
        self.assertTrue(report["warnings"])
        self.assertTrue(report["unknowns"])
        self.assertIsNotNone(datetime.fromisoformat(report["checked_at"]).tzinfo)
        self.assertNotIn("private", json.dumps(report))
        for results in ([INACTIVE, "No inhibitors listed.", "", None], [None, None, None, None]):
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


class CpuwmSafetyTests(unittest.TestCase):
    NOW = datetime(2026, 11, 3, 17, 11, 10, tzinfo=timezone.utc)

    def status(self):
        return {"profile": "balanced", "active_managed_scopes": [], "active_roles": [],
                "last_monitor": {"timestamp": "2026-11-03T18:11:05+0100", "profile": "balanced",
                                 "twt_enforcement": {"primary_active": True,
                                                     "secondary_active": False, "ok": True}}}

    def parse(self, data):
        return safety.parse_cpuwm(json.dumps(data), self.NOW)

    def collect(self, data, atlas=INACTIVE, processes="", inhibitors="No inhibitors listed."):
        with mock.patch.object(safety, "read_command", side_effect=[atlas, inhibitors, processes, json.dumps(data)]) as reader, mock.patch.object(safety, "datetime", wraps=datetime) as clock, mock.patch.object(safety, "inspect_power", return_value={"eligible":False,"blockers":["Test: no power authorization"]}), mock.patch.object(safety.subprocess, "Popen") as popen:
            clock.now.return_value = self.NOW
            report = safety.collect_power_safety()
        self.assertEqual(reader.call_args_list, [mock.call(args) for args in
                         (safety.ATLAS, safety.INHIBITORS, safety.PROCESSES, safety.CPUWM)])
        popen.assert_not_called()
        self.assertFalse(report["safe_to_request"])
        self.assertTrue(report["blocked_reasons"])
        return report

    def test_fresh_counts_and_only_sanitized_fields(self):
        data = self.status()
        data["active_managed_scopes"] = ["/private/user/job.scope"]
        data["active_roles"] = ["secret-role"]
        data["private"] = {"pid": 987654, "user": "hidden-user"}
        result = self.collect(data)
        self.assertEqual(result["cpuwm"], {"status": "fresh", "managed_scopes": 1,
                         "managed_roles": 1, "primary_active": True, "secondary_active": False,
                         "enforcement_ok": True, "monitor_age_seconds": 5.0})
        for secret in ("private", "secret-role", "987654", "hidden-user", "balanced", "job.scope"):
            self.assertNotIn(secret, json.dumps(result))

    def test_zero_scopes_never_idle_for_any_atlas_state(self):
        for atlas in (INACTIVE, INACTIVE.replace("inactive", "active").replace("dead", "running"), None):
            data = self.status()
            data["last_monitor"]["twt_enforcement"]["primary_active"] = False
            report = self.collect(data, atlas=atlas)
            self.assertEqual(report["cpuwm"]["managed_scopes"], 0)
            self.assertIn("zero scopes cannot prove idle", " ".join(report["warnings"]))
            self.assertIn("CPUWM active-job state is not verified", " ".join(report["unknowns"]))

    def test_freshness_boundaries(self):
        for timestamp, expected in (("2026-11-03T17:11:15+00:00", "fresh"),
                                    ("2026-11-03T17:11:15.001+00:00", "stale"),
                                    ("2026-11-03T17:10:10Z", "fresh"),
                                    ("2026-11-03T17:10:09.999Z", "stale")):
            data = self.status()
            data["last_monitor"]["timestamp"] = timestamp
            result = self.parse(data)
            self.assertEqual(result["status"], expected)
            if expected == "stale":
                for key in ("managed_scopes", "managed_roles", "primary_active", "secondary_active", "enforcement_ok"):
                    self.assertIsNone(result[key])

    def test_timestamp_must_be_aware_and_valid(self):
        for timestamp in (None, 123, "", "bad", "2026-11-03T17:11:05", "2026-11-03"):
            data = self.status()
            data["last_monitor"]["timestamp"] = timestamp
            self.assertEqual(self.parse(data)["status"], "unavailable")

    def test_only_monitor_timestamp_controls_freshness(self):
        data = self.status()
        data.update(timestamp=self.NOW.isoformat(), epoch=self.NOW.timestamp(), ok=True)
        data["last_monitor"]["timestamp"] = "2000-01-01T00:00:00Z"
        report = self.collect(data)
        self.assertEqual(report["cpuwm"]["status"], "stale")
        self.assertIn("CPUWM status is stale", " ".join(report["blocked_reasons"]))

    def test_profile_allowlist_and_monitor_consistency(self):
        for profile in ("quiet", "balanced", "performance"):
            data = self.status()
            data["profile"] = data["last_monitor"]["profile"] = profile
            self.assertEqual(self.parse(data)["status"], "fresh")
        for profile in (None, [], {}, True, "unknown", "balanced; reboot"):
            data = self.status()
            data["profile"] = profile
            self.assertEqual(self.parse(data)["status"], "unavailable")
        data = self.status()
        data["last_monitor"]["profile"] = "quiet"
        self.assertEqual(self.parse(data)["status"], "unavailable")

    def test_list_types_limits_and_entries(self):
        for key in ("active_managed_scopes", "active_roles"):
            for values in (None, {}, "role", 0, [None], [1], [{}], [""], ["  "], ["x"] * 129):
                data = self.status()
                data[key] = values
                self.assertEqual(self.parse(data)["status"], "unavailable")
            data = self.status()
            data[key] = ["x"] * 128
            self.assertEqual(self.parse(data)["status"], "fresh")

    def test_enforcement_requires_boolean_schema_and_ok(self):
        for key in ("primary_active", "secondary_active", "ok"):
            for value in (None, 0, 1, "true", [], {}):
                data = self.status()
                data["last_monitor"]["twt_enforcement"][key] = value
                self.assertEqual(self.parse(data)["status"], "unavailable")
        data = self.status()
        data["last_monitor"]["twt_enforcement"]["ok"] = False
        report = self.collect(data)
        self.assertIsNone(report["cpuwm"]["primary_active"])
        self.assertIsNone(report["cpuwm"]["secondary_active"])
        self.assertIn("enforcement is not confirmed", " ".join(report["blocked_reasons"]))

    def test_missing_schema_and_malformed_json(self):
        for key in self.status():
            data = self.status()
            del data[key]
            self.assertEqual(self.parse(data)["status"], "unavailable")
        for value in (None, "", "{", "[]", "null", "true", '{"profile":"quiet","profile":"balanced"}',
                      "x" * (safety.LIMIT + 1), "[" * 2000):
            self.assertEqual(safety.parse_cpuwm(value, self.NOW)["status"], "unavailable")

    def test_unavailable_command_fails_closed(self):
        with mock.patch.object(safety, "read_command", return_value=None):
            report = safety.collect_power_safety()
        self.assertFalse(report["safe_to_request"])
        self.assertEqual(report["cpuwm"]["status"], "unavailable")
        self.assertIn("CPUWM status is unavailable", " ".join(report["blocked_reasons"]))

    def test_desktop_categories_and_session_block_remain_unverifiable(self):
        report = self.collect(self.status(), processes="firefox\ncode\nsoffice.bin\nprivate-name\n",
                              inhibitors=HEADER + BLOCK + "1 inhibitor listed.")
        self.assertEqual(report["desktop_work"]["app_categories"], ["Browser", "Editor", "Document tools"])
        self.assertEqual(report["desktop_work"]["status"], "unverifiable")
        self.assertTrue(report["desktop_work"]["session_shutdown_blocked"])
        self.assertIn("desktop session blocks shutdown", " ".join(report["blocked_reasons"]))
        self.assertNotIn("private-name", json.dumps(report))
        for processes in ("", None):
            report = self.collect(self.status(), processes=processes)
            self.assertEqual(report["desktop_work"]["status"], "unverifiable")

    def test_cpuwm_fixed_argv_and_no_mutator(self):
        self.assertEqual(safety.CPUWM, ["/usr/bin/python3", "-B", str(safety.CPUWM_SCRIPT), "status"])
        self.assertEqual(safety.CPUWM_SCRIPT.name, "cpuwm.py")
        with mock.patch.object(Path, "lstat", side_effect=[mock.Mock(st_mode=stat.S_IFREG), mock.Mock(st_mode=stat.S_IFDIR)]), mock.patch.object(safety.subprocess, "Popen", side_effect=FileNotFoundError) as run:
            self.assertIsNone(safety.read_command(safety.CPUWM))
            self.assertEqual(run.call_args.args[0], safety.CPUWM)
            self.assertIs(run.call_args.kwargs["shell"], False)
        for action in ("profile", "monitor", "run", "budget", "status; reboot"):
            with mock.patch.object(safety.subprocess, "Popen") as run:
                with self.assertRaises(ValueError):
                    safety.read_command(safety.CPUWM[:-1] + [action])
                run.assert_not_called()

    def test_cpuwm_reader_bounds_timeout_and_exit_cleanup(self):
        for case in ("timeout", "deadline", "overflow", "wait_timeout", "exit", "decode", "ok"):
            with self.subTest(case=case):
                child = mock.MagicMock()
                child.poll.return_value = None
                child.wait.side_effect = [subprocess.TimeoutExpired("reader", 3), 0] if case == "wait_timeout" else None
                child.wait.return_value = 1 if case == "exit" else 0
                selector = mock.MagicMock()
                selector.select.return_value = [] if case == "timeout" else [(None, None)]
                chunks = [b"x" * 4096] * 8 + [b"x"] if case == "overflow" else [b"\xff" if case == "decode" else b"{}", b""]
                with mock.patch.object(Path, "lstat", side_effect=[mock.Mock(st_mode=stat.S_IFREG), mock.Mock(st_mode=stat.S_IFDIR)]), mock.patch.object(safety.subprocess, "Popen") as run, mock.patch.object(safety.selectors, "DefaultSelector") as select, mock.patch.object(safety.os, "read", side_effect=chunks) as read, mock.patch.object(safety.time, "monotonic", side_effect=[10, 14] if case == "deadline" else None, return_value=10):
                    run.return_value.__enter__.return_value = child
                    select.return_value.__enter__.return_value = selector
                    result = safety.read_command(safety.CPUWM)
                self.assertEqual(result, "{}" if case == "ok" else None)
                child.kill.assert_called_once()
                for call in read.call_args_list:
                    self.assertLessEqual(call.args[1], 4096)
                if case == "overflow":
                    self.assertEqual(read.call_args.args[1], 1)
                if case not in ("deadline", "timeout", "overflow"):
                    self.assertEqual(child.wait.call_args_list[0], mock.call(timeout=3))

    def test_missing_symlink_or_special_script_never_executes(self):
        for mode in (stat.S_IFLNK, stat.S_IFDIR, stat.S_IFIFO, stat.S_IFSOCK):
            with mock.patch.object(Path, "lstat", return_value=mock.Mock(st_mode=mode)), mock.patch.object(safety.subprocess, "Popen") as run:
                self.assertIsNone(safety.read_command(safety.CPUWM))
                run.assert_not_called()
        with mock.patch.object(Path, "lstat", side_effect=FileNotFoundError), mock.patch.object(safety.subprocess, "Popen") as run:
            self.assertIsNone(safety.read_command(safety.CPUWM))
            run.assert_not_called()
        with mock.patch.object(Path, "lstat", side_effect=[mock.Mock(st_mode=stat.S_IFREG), mock.Mock(st_mode=stat.S_IFLNK)]), mock.patch.object(safety.subprocess, "Popen") as run:
            self.assertIsNone(safety.read_command(safety.CPUWM))
            run.assert_not_called()


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

    def test_public_power_safety_summary_is_bounded_and_redacted(self):
        clean = {"status": "fresh", "managed_scopes": 0, "managed_roles": 0,
                 "primary_active": False, "secondary_active": False,
                 "enforcement_ok": True, "monitor_age_seconds": 1.2,
                 "private_path": "/not-for-browser"}
        result = server.safe_cpuwm_summary(clean)
        self.assertEqual(result["managed_scopes"], 0)
        self.assertNotIn("private_path", result)
        self.assertEqual(server.safe_cpuwm_summary({**clean, "managed_scopes": 500})["status"], "unavailable")
        desktop = server.safe_desktop_work({"status": "unverifiable",
            "app_categories": ["Browser"], "process_observation": "available",
            "session_shutdown_blocked": True, "private_filename": "secret.odt"})
        self.assertEqual(desktop["app_categories"], ["Browser"])
        self.assertNotIn("private_filename", desktop)
        self.assertEqual(server.safe_desktop_work({"status":"saved", "app_categories":[]})["status"], "unverifiable")

    def test_frontend_preview_is_control_only(self):
        html = (ROOT / "web/static/index.html").read_text()
        js = (ROOT / "web/static/app.js").read_text()
        dashboard, control = html.split('id="view-control"', 1)
        self.assertNotIn('id="power-preview-card"', dashboard)
        self.assertIn('id="desktop-power-button" disabled', dashboard)
        self.assertIn('id="power-preview-card"', control)
        self.assertIn("Simulation only — will NOT turn off or restart Ubuntu.", control)
        self.assertIn('data.remaining_seconds', js)
        self.assertIn('"/api/power/cancel"', js)
        self.assertNotIn('remaining_seconds--', js)
        self.assertIn('put("power-safety-status"', js)
