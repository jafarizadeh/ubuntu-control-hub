"""Non-destructive tests for signed outbound desktop telemetry."""

import email.message
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]


def module_at(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "web"))
outbound = module_at("outbound_agent", ROOT / "agent/outbound.py")
broker = module_at("agent_broker", ROOT / "web/agent_broker.py")

EXAMPLE = {
    "schema_version": 1, "hostname": "ubuntu-desktop",
    "cpu": {"usage_percent": 2.0}, "memory": {"total_mib": 100},
    "storage": {"free_gib": 250}, "gpus": [], "fans": [],
}


class SignedAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.key = Ed25519PrivateKey.generate()
        self.private = self.root / "identity.key"
        self.public = self.root / "identity.pub"
        self.private.write_bytes(self.key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
        self.private.chmod(0o600)
        self.public.write_bytes(self.key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))

    def signed_request(self):
        req = outbound.make_request("https://pi.example.ts.net", self.key, EXAMPLE)
        headers = email.message.Message()
        for name, value in req.header_items():
            headers[name] = value
        return req, headers

    def test_private_key_is_restricted(self):
        self.assertIsInstance(outbound.load_private_key(self.private), Ed25519PrivateKey)
        self.private.chmod(0o644)
        with self.assertRaises(ValueError):
            outbound.load_private_key(self.private)

    def test_reject_private_key_symlink(self):
        link = self.root / "identity-link.key"
        link.symlink_to(self.private)
        with self.assertRaises(ValueError):
            outbound.load_private_key(link)

    def test_reject_non_tailscale_url(self):
        cfg = self.root / "client.json"
        cfg.write_text(json.dumps({"hub_url": "http://example.com",
                                   "identity_file": str(self.private)}))
        with self.assertRaises(ValueError):
            outbound.load_config(cfg)

    def test_valid_client_config(self):
        cfg = self.root / "client.json"
        cfg.write_text(json.dumps({"hub_url": "https://pi.example.ts.net",
                                   "identity_file": str(self.private),
                                   "interval_seconds": 10}))
        url, identity, interval = outbound.load_config(cfg)
        self.assertEqual(url, "https://pi.example.ts.net")
        self.assertIsInstance(identity, Ed25519PrivateKey)
        self.assertEqual(interval, 10)

    def test_broker_accepts_valid_signed_report(self):
        relay = broker.AgentBroker(self.public, offline_after=35)
        req, headers = self.signed_request()
        self.assertTrue(relay.authorized(headers, req.data))
        self.assertTrue(relay.accept(req.data))
        self.assertEqual(relay.desktop_state()["control_agent"], "online")
        self.assertEqual(relay.desktop_state()["metrics"]["cpu"]["usage_percent"], 2.0)
        relay._last_monotonic -= 40
        self.assertEqual(relay.desktop_state()["control_agent"], "unavailable")

    def test_signature_replay_rejected(self):
        relay = broker.AgentBroker(self.public)
        req, headers = self.signed_request()
        self.assertTrue(relay.authorized(headers, req.data))
        self.assertFalse(relay.authorized(headers, req.data))

    def test_signature_tamper_rejected(self):
        relay = broker.AgentBroker(self.public)
        req, headers = self.signed_request()
        self.assertFalse(relay.authorized(headers, req.data + b"\n"))

    def test_missing_signature_rejected(self):
        relay = broker.AgentBroker(self.public)
        req, headers = self.signed_request()
        self.assertFalse(relay.authorized({}, req.data))

    def test_request_body_limit(self):
        with self.assertRaises(ValueError):
            outbound.make_request("https://pi.example.ts.net", self.key,
                                  {**EXAMPLE, "hostname": "x" * 20000})

    def test_signed_http_request_headers(self):
        req, headers = self.signed_request()
        self.assertEqual(req.method, "POST")
        self.assertIn("/api/agent/report", req.full_url)
        self.assertTrue(headers.get("X-UC-Agent-Signature"))
        self.assertFalse(headers.get("Authorization"))

    def test_http_result(self):
        class FakeResponse:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, amount): return b'{"ok":true}'
        with mock.patch.object(outbound.request, "urlopen",
                               return_value=FakeResponse()) as mocked:
            result = outbound.report_once("https://pi.example.ts.net", self.key,
                                          payload=EXAMPLE)
        self.assertTrue(result["ok"])
        self.assertTrue(mocked.called)


if __name__ == "__main__":
    unittest.main()
