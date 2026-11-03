#!/usr/bin/env python3
"""Outbound-only signed HTTPS telemetry from Ubuntu to Raspberry Pi."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import ssl
import stat
import sys
import time
from urllib import error, parse, request

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from desktop_status import collect_status
from command_executor import CommandExecutor

DEFAULT_CONFIG = Path.home() / ".config" / "ubuntu-control-agent" / "client.json"


def load_private_key(path: Path) -> Ed25519PrivateKey:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("Identity key must be an absolute, regular, non-symlink file")
    mode = path.stat()
    if not stat.S_ISREG(mode.st_mode) or mode.st_uid != os.geteuid():
        raise ValueError("Identity key must be owned by the current user")
    if stat.S_IMODE(mode.st_mode) & 0o077:
        raise ValueError("Identity key permissions are too broad")
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Expected Ed25519 identity")
    return key


def load_config(path: Path) -> tuple[str, Ed25519PrivateKey, int]:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("Configuration path must be absolute and not a symlink")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    base = cfg["hub_url"].rstrip("/")
    url = parse.urlsplit(base)
    if url.scheme != "https" or not (url.hostname or "").endswith(".ts.net"):
        raise ValueError("Hub URL must be private *.ts.net HTTPS")
    if url.username or url.password or url.query or url.fragment or url.path or url.port not in (None, 443):
        raise ValueError("Hub URL must contain only the Tailscale hostname")
    identity = load_private_key(Path(cfg["identity_file"]))
    interval = int(cfg.get("interval_seconds", 10))
    if not 5 <= interval <= 120:
        raise ValueError("Agent interval outside safe bounds")
    return base, identity, interval


def make_request(base: str, identity: Ed25519PrivateKey, status: dict, ack=None) -> request.Request:
    message = {"schema_version": 1, "status": status}
    if ack is not None:
        message["ack"] = ack
    body = json.dumps(message,
                      separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if not 0 < len(body) <= 16384:
        raise ValueError("Report exceeds size limit")
    epoch = str(int(time.time()))
    nonce = secrets.token_hex(16)
    digest = hashlib.sha256(body).hexdigest()
    signed = f"{epoch}\n{nonce}\n{digest}".encode("ascii")
    signature = base64.b64encode(identity.sign(signed)).decode("ascii")
    return request.Request(
        base + "/api/agent/report",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-UC-Agent-Time": epoch,
            "X-UC-Agent-Nonce": nonce,
            "X-UC-Agent-Signature": signature,
            "User-Agent": "UbuntuControlAgent/0.2",
        },
        method="POST",
    )


def report_once(base: str, identity: Ed25519PrivateKey, *, payload: dict | None = None, executor=None) -> dict:
    status = payload if payload is not None else collect_status()
    req = make_request(base, identity, status, executor.ack if executor else None)
    with request.urlopen(req, timeout=8, context=ssl.create_default_context()) as response:
        if response.status != 200:
            raise RuntimeError("Hub rejected status report")
        result = json.loads(response.read(4097))
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError("Hub did not acknowledge report")
    if executor is not None:
        executor.acknowledged()
        if "command" in result:
            executor.execute(result["command"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    try:
        base, identity, interval = load_config(args.config)
        executor = CommandExecutor(args.config.parent / "command-state.json")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print("Invalid agent configuration: " + type(exc).__name__, file=sys.stderr)
        return 2

    if args.once:
        try:
            report_once(base, identity, executor=executor)
            print("Ubuntu Control signed status report accepted")
            return 0
        except (OSError, ValueError, RuntimeError, error.URLError,
                json.JSONDecodeError) as exc:
            print("Unable to report status: " + type(exc).__name__, file=sys.stderr)
            return 1

    print("Ubuntu Control outbound signed telemetry started", flush=True)
    failures = 0
    while True:
        try:
            report_once(base, identity, executor=executor)
            failures = 0
        except (OSError, ValueError, RuntimeError, error.URLError,
                json.JSONDecodeError) as exc:
            failures += 1
            if failures in (1, 5, 20):
                print("Report failure: " + type(exc).__name__, file=sys.stderr, flush=True)
        time.sleep(interval if failures == 0 else min(max(interval, 5) * 2, 60))


if __name__ == "__main__":
    sys.exit(main())
