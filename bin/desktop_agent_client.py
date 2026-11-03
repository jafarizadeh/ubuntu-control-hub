#!/usr/bin/env python3
"""Get Ubuntu Desktop read-only telemetry through restricted SSH."""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path
import re
import stat
import subprocess


def fetch_status(desktop: dict, timeout: int = 7) -> dict:
    settings = desktop.get("agent_ssh")
    if not isinstance(settings, dict) or not settings.get("enabled"):
        return {"control_agent": "not_configured"}
    try:
        host = str(ipaddress.ip_address(desktop["ip"]))
        username = settings["username"]
        identity = Path(settings["identity_file"])
        if not isinstance(username, str) or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", username):
            raise ValueError("Invalid SSH username")
        if not identity.is_absolute() or not identity.is_file():
            raise ValueError("SSH private key missing")
        if stat.S_IMODE(identity.stat().st_mode) & 0o077:
            raise ValueError("SSH private key permissions too broad")

        command = [
            "ssh", "-T", "-F", "/dev/null", "-i", str(identity),
            "-o", "IdentitiesOnly=yes",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=3",
            "-o", "ConnectionAttempts=1",
            "-o", "LogLevel=ERROR",
            f"{username}@{host}",
            "ubuntu-control-status-v1",
        ]
        result = subprocess.run(
            command, capture_output=True, text=True,
            check=False, timeout=timeout,
        )
        if result.returncode != 0 or len(result.stdout) > 32768:
            return {"control_agent": "unavailable"}
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            return {"control_agent": "unavailable"}
        if not isinstance(payload.get("cpu"), dict):
            return {"control_agent": "unavailable"}
        if not isinstance(payload.get("memory"), dict):
            return {"control_agent": "unavailable"}
        if not isinstance(payload.get("storage"), dict):
            return {"control_agent": "unavailable"}
        return {"control_agent": "online", "metrics": payload}
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError,
            subprocess.TimeoutExpired):
        return {"control_agent": "unavailable"}
