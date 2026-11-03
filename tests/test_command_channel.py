"""Offline command transport tests; subprocesses and HTTP are mocked."""
import email.message
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web"))
import agent_broker
import command_executor
from command_queue import CommandQueue, validate_action
import test_outbound_agent as signed_tests
from test_outbound_agent import EXAMPLE, outbound

ROOT = Path(__file__).resolve().parents[1]
# Import server without reading private device config or creating real state.
original_read = Path.read_text
with mock.patch.object(agent_broker, "AgentBroker"), mock.patch.object(
        Path, "read_text", lambda path, *a, **k: '{}' if path.name == "devices.json" else original_read(path, *a, **k)):
    spec = importlib.util.spec_from_file_location("command_test_server", ROOT / "web/server.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)


def headers(login="placeholder@example.com", host="pi.example.ts.net"):
    result = email.message.Message()
    result["Host"] = host
    if login is not None:
        result["Tailscale-User-Login"] = login
    return result


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "queue.sqlite"
        self.queue = CommandQueue(self.path)
        self.addCleanup(self.queue.db.close)

    def test_validation(self):
        for action in ({"action": "audio.set_volume", "value": 0},
                       {"action": "audio.set_volume", "value": 100},
                       {"action": "audio.set_mute", "value": False},
                       {"action": "cpuwm.set_profile", "value": "quiet", "confirm": True}):
            validate_action(action)
        for action in ({"action": "audio.set_volume", "value": True},
                       {"action": "audio.set_volume", "value": 101},
                       {"action": "audio.set_volume", "value": -1},
                       {"action": "audio.set_mute", "value": 1},
                       {"action": "shutdown", "value": True},
                       {"action": "cpuwm.set_profile", "value": "quiet"},
                       {"action": "cpuwm.set_profile", "value": "quiet", "confirm": 1},
                       {"action": "cpuwm.set_profile", "value": "shell", "confirm": True}):
            with self.subTest(action=action), self.assertRaises(ValueError):
                validate_action(action)

    def test_capacity_delivery_ack_restart_expiry(self):
        items = [self.queue.enqueue({"action": "audio.set_mute", "value": True}) for _ in range(16)]
        with self.assertRaises(OverflowError):
            self.queue.enqueue({"action": "audio.set_mute", "value": True})
        self.assertEqual(items[0]["status"], "queued")
        response = self.queue.report_response()
        self.assertEqual(response["command"]["id"], items[0]["id"])
        self.assertEqual(self.queue.status(items[0]["id"]), "delivered")
        restarted = CommandQueue(self.path)
        self.addCleanup(restarted.db.close)
        self.assertNotEqual(restarted.report_response()["command"]["id"], items[0]["id"])
        restarted.report_response({"id": items[0]["id"], "status": "failed"})
        self.assertEqual(self.queue.status(items[0]["id"]), "failed")
        # Acks cannot complete commands that have never been delivered.
        self.queue.report_response({"id": items[-1]["id"], "status": "succeeded"})
        self.assertEqual(self.queue.status(items[-1]["id"]), "queued")
        with mock.patch("time.time", return_value=time.time() + 46):
            self.assertNotIn("command", self.queue.report_response())
            self.assertEqual(self.queue.status(items[1]["id"]), "expired")
            self.queue.report_response({"id": items[1]["id"], "status": "succeeded"})
            self.assertEqual(self.queue.status(items[1]["id"]), "expired")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)


class IdentityTests(unittest.TestCase):
    def test_denials_and_capabilities(self):
        with tempfile.TemporaryDirectory() as folder:
            operator = Path(folder) / "operator.json"
            with mock.patch.object(server, "OPERATOR", operator):
                self.assertFalse(server.can_control(headers()))
                operator.write_text('{"allowed_login":"placeholder@example.com"}')
                operator.chmod(0o600)
                self.assertTrue(server.can_control(headers()))
                self.assertTrue(server.can_control(headers(host="pi.example.ts.net:443")))
                operator.chmod(0o644)
                self.assertFalse(server.can_control(headers()))
                operator.chmod(0o600)
                for h in (headers(None), headers("other@example.com"), headers(host="localhost"),
                          headers(host="127.0.0.1"), headers("Placeholder@example.com")):
                    self.assertFalse(server.can_control(h))
                duplicate = headers()
                duplicate["Tailscale-User-Login"] = "placeholder@example.com"
                self.assertFalse(server.can_control(duplicate))
                handler = server.Handler.__new__(server.Handler)
                handler.headers = headers()
                handler.path = "/api/control/capabilities"
                handler._json = mock.Mock()
                handler.do_GET()
                handler._json.assert_called_once_with({"can_control": True})
                handler.path = "/api/commands/" + "a" * 32
                with mock.patch.object(server.BROKER.commands, "status", return_value="delivered"):
                    handler._json.reset_mock()
                    handler.do_GET()
                    handler._json.assert_called_once_with({"status": "delivered"}, 200)

    def test_post_requires_identity_origin_csrf(self):
        handler = server.Handler.__new__(server.Handler)
        handler.path = "/api/commands"
        handler._json = mock.Mock()
        handler.headers = headers()
        handler.headers["Content-Type"] = "application/json"
        body = b'{"action":"audio.set_mute","value":true}'
        handler.headers["Content-Length"] = str(len(body))
        with mock.patch.object(server, "can_control", return_value=False):
            handler.do_POST()
            self.assertEqual(handler._json.call_args.args[1], 403)
        with mock.patch.object(server, "can_control", return_value=True):
            handler.do_POST()
            self.assertEqual(handler._json.call_args.args[1], 403)
            handler.headers["Origin"] = "https://pi.example.ts.net"
            handler.do_POST()
            self.assertEqual(handler._json.call_args.args[1], 403)
            handler.headers["Cookie"] = "uc_hub=fake-cookie"
            handler.headers["X-UC-CSRF"] = handler._token("fake-cookie")
            handler.rfile = io.BytesIO(body)
            with mock.patch.object(server.BROKER.commands, "enqueue", return_value={"id": "a" * 32, "status": "queued"}):
                handler.do_POST()
                self.assertEqual(handler._json.call_args.args[1], 202)
                self.assertEqual(handler._json.call_args.args[0]["status"], "queued")


class SignedCommandTests(unittest.TestCase):
    setUp = signed_tests.SignedAgentTests.setUp
    def test_ack_signed_and_nonce_survives_restart(self):
        queue_path = self.root / "state.sqlite"
        relay = agent_broker.AgentBroker(self.public, state_file=queue_path)
        self.addCleanup(relay.commands.db.close)
        item = relay.commands.enqueue({"action": "audio.set_mute", "value": False})
        relay.commands.report_response()
        ack = {"id": item["id"], "status": "succeeded"}
        req = outbound.make_request("https://pi.example.ts.net", self.key, EXAMPLE, ack)
        h = email.message.Message()
        for name, value in req.header_items():
            h[name] = value
        self.assertFalse(relay.authorized(h, req.data.replace(b'succeeded', b'failed')))
        self.assertTrue(relay.authorized(h, req.data))
        self.assertTrue(relay.accept(req.data))
        relay.commands.report_response(json.loads(req.data)["ack"])
        self.assertEqual(relay.commands.status(item["id"]), "succeeded")
        restarted = agent_broker.AgentBroker(self.public, state_file=queue_path)
        self.addCleanup(restarted.commands.db.close)
        self.assertFalse(restarted.authorized(h, req.data))

    def test_http_report_delivers_one_and_rejects_replay(self):
        relay = agent_broker.AgentBroker(self.public)
        self.addCleanup(relay.commands.db.close)
        items = [relay.commands.enqueue({"action": "audio.set_mute", "value": False}) for _ in range(2)]
        req = outbound.make_request("https://pi.example.ts.net", self.key, EXAMPLE)
        handler = server.Handler.__new__(server.Handler)
        handler.path = "/api/agent/report"
        handler.headers = headers(None)
        for name, value in req.header_items():
            handler.headers[name] = value
        handler.headers["Content-Length"] = str(len(req.data))
        handler.rfile = io.BytesIO(req.data)
        handler._json = mock.Mock()
        with mock.patch.object(server, "BROKER", relay):
            handler.do_POST()
            response = handler._json.call_args.args[0]
            self.assertEqual(set(response), {"ok", "command"})
            self.assertEqual(response["command"]["id"], items[0]["id"])
            self.assertEqual(relay.commands.status(items[1]["id"]), "queued")
            handler.rfile = io.BytesIO(req.data)
            handler.do_POST()
            self.assertEqual(handler._json.call_args.args[1], 403)
            self.assertEqual(relay.commands.status(items[1]["id"]), "queued")

    def test_agent_ack_is_signed_and_command_processed(self):
        executor = mock.Mock()
        executor.ack = {"id": "a" * 32, "status": "failed"}
        command = {"id": "b" * 32}
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = json.dumps({"ok": True, "command": command}).encode()
        with mock.patch.object(outbound.request, "urlopen", return_value=response) as send:
            outbound.report_once("https://pi.example.ts.net", self.key, payload=EXAMPLE, executor=executor)
        req = send.call_args.args[0]
        self.assertEqual(json.loads(req.data)["ack"], executor.ack)
        relay = agent_broker.AgentBroker(self.public)
        self.addCleanup(relay.commands.db.close)
        h = email.message.Message()
        for name, value in req.header_items():
            h[name] = value
        self.assertTrue(relay.authorized(h, req.data))
        executor.acknowledged.assert_called_once_with()
        executor.execute.assert_called_once_with(command)


class ExecutorTests(unittest.TestCase):
    def test_crash_reservation_and_multiple_instances(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            first = command_executor.CommandExecutor(path)
            second = command_executor.CommandExecutor(path)
            now = int(time.time())
            command = {"id": "a" * 32, "action": "audio.set_mute", "value": False,
                       "created_at": now, "expires_at": now + 45}
            with mock.patch.object(command_executor.subprocess, "run", side_effect=KeyboardInterrupt) as run:
                with self.assertRaises(KeyboardInterrupt):
                    first.execute(command)
                second.execute(command)
                restarted = command_executor.CommandExecutor(path)
                restarted.execute(command)
                self.assertEqual(run.call_count, 1)
                self.assertEqual(restarted.ack["status"], "failed")

    def test_execution_dedupe_and_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            executor = command_executor.CommandExecutor(path)
            command = {"id": "a" * 32, "action": "audio.set_volume", "value": 37,
                       "created_at": int(time.time()), "expires_at": int(time.time()) + 45}
            with mock.patch.object(command_executor.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
                executor.execute(command)
                run.assert_called_once_with(["/usr/bin/wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "37%"],
                                            shell=False, timeout=15, capture_output=True, check=False)
                self.assertEqual(executor.ack["status"], "succeeded")
                executor = command_executor.CommandExecutor(path)
                executor.execute(command)
                self.assertEqual(run.call_count, 1)
                mute = {**command, "id": "b" * 32, "action": "audio.set_mute", "value": True}
                run.side_effect = subprocess.TimeoutExpired("fake", 15)
                executor.execute(mute)
                self.assertEqual(executor.ack["status"], "failed")
                executor.execute(mute)
                self.assertEqual(run.call_count, 2)
                self.assertEqual(run.call_args.args[0][-1], "1")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with mock.patch.object(command_executor.subprocess, "run") as run, mock.patch.object(command_executor.Path, "home", return_value=Path(folder)):
                profile = {**command, "id": "c" * 32, "action": "cpuwm.set_profile", "value": "quiet", "confirm": True}
                executor.execute(profile)
                run.assert_not_called()
                self.assertEqual(executor.ack["status"], "failed")
                manager = Path(folder) / "cpu-workload-manager/cpuwm.py"
                manager.parent.mkdir()
                manager.write_text("# fake")
                run.return_value = subprocess.CompletedProcess([], 0)
                executor.execute({**profile, "id": "d" * 32})
                self.assertEqual(run.call_args.args[0], [sys.executable, str(manager), "profile", "quiet"])
            with mock.patch.object(command_executor.subprocess, "run") as run:
                for changes in ({"value": True}, {"action": "shutdown"}, {"expires_at": 0}, {"extra": "bad"}):
                    with self.assertRaises(ValueError):
                        executor.execute({**command, **changes})
                run.assert_not_called()
            path.write_text("invalid")
            with self.assertRaises(ValueError):
                command_executor.CommandExecutor(path)
