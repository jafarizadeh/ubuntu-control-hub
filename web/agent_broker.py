"""Verify Ed25519-signed outbound desktop reports without sharing private keys."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import pathlib
import re
import stat
import threading
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class AgentBroker:
    def __init__(self, public_key_file: pathlib.Path, offline_after: int = 35):
        self.public_key_file = public_key_file
        self.offline_after = offline_after
        self._lock = threading.RLock()
        self._last_monotonic = 0.0
        self._last_epoch = 0
        self._report = None
        self._seen_nonces: dict[str, float] = {}

    def configured(self) -> bool:
        try:
            info = self.public_key_file.lstat()
            return stat.S_ISREG(info.st_mode) and 30 < info.st_size <= 4096
        except OSError:
            return False

    def authorized(self, headers: dict, raw: bytes) -> bool:
        if not self.configured() or not 0 < len(raw) <= 16384:
            return False
        stamp = headers.get("X-UC-Agent-Time", "")
        nonce = headers.get("X-UC-Agent-Nonce", "")
        encoded = headers.get("X-UC-Agent-Signature", "")
        if not isinstance(stamp, str) or not stamp.isdecimal() or len(stamp) > 12:
            return False
        if not isinstance(nonce, str) or not re.fullmatch(r"[a-f0-9]{32}", nonce):
            return False
        if not isinstance(encoded, str) or len(encoded) > 128:
            return False
        now = time.time()
        if abs(now - int(stamp)) > 75:
            return False
        try:
            signature = base64.b64decode(encoded, validate=True)
            if len(signature) != 64:
                return False
            key = serialization.load_pem_public_key(self.public_key_file.read_bytes())
            if not isinstance(key, Ed25519PublicKey):
                return False
            digest = hashlib.sha256(raw).hexdigest()
            signed = f"{stamp}\n{nonce}\n{digest}".encode("ascii")
            key.verify(signature, signed)
        except (OSError, ValueError, TypeError, binascii.Error, InvalidSignature):
            return False
        with self._lock:
            # Prevent an old signed request being replayed within the time window.
            self._seen_nonces = {k: t for k, t in self._seen_nonces.items() if now - t < 150}
            if nonce in self._seen_nonces:
                return False
            self._seen_nonces[nonce] = now
        return True

    def accept(self, raw: bytes) -> bool:
        if not 0 < len(raw) <= 16384:
            return False
        try:
            message = json.loads(raw)
        except (UnicodeError, ValueError, TypeError):
            return False
        if not isinstance(message, dict) or message.get("schema_version") != 1:
            return False
        report = message.get("status")
        if not isinstance(report, dict) or report.get("schema_version") != 1:
            return False
        if not all(isinstance(report.get(name), dict) for name in ("cpu", "memory", "storage")):
            return False
        if not isinstance(report.get("hostname"), str) or len(report["hostname"]) > 120:
            return False
        if not isinstance(report.get("gpus", []), list) or len(report.get("gpus", [])) > 8:
            return False
        if not isinstance(report.get("fans", []), list) or len(report.get("fans", [])) > 32:
            return False
        snapshot = json.loads(json.dumps(report))
        with self._lock:
            self._last_monotonic = time.monotonic()
            self._last_epoch = int(time.time())
            self._report = snapshot
        return True

    def desktop_state(self) -> dict:
        with self._lock:
            report = self._report
            seen = self._last_monotonic
            epoch = self._last_epoch
            if report is not None and time.monotonic() - seen <= self.offline_after:
                return {
                    "control_agent": "online",
                    "agent_transport": "signed_private_https_outbound",
                    "last_agent_report_unix": epoch,
                    "metrics": report,
                }
        return {
            "control_agent": "unavailable" if self.configured() else "not_configured",
            "agent_transport": "signed_private_https_outbound",
            "last_agent_report_unix": epoch or None,
        }
