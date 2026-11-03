"""Read-only verification of a future Atlas per-Codex owner-stop receipt.

This file is a verifier, NOT a stop implementation. Atlas must atomically
enforce the dispatch barrier, collect acknowledgements from every physical
worker, and renew the heartbeat before a verified receipt can exist.
"""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import pwd
import re
import sqlite3
import stat
import time

ATLAS_POLICY = Path(pwd.getpwuid(os.getuid()).pw_dir) / "TWT_Roadmap_Atlas" / "policy.json"
TABLE_CONTROL = "codex_owner_stop_control"
TABLE_ACKS = "codex_owner_stop_acks"
LEASE_SECONDS = 15
FUTURE_TOLERANCE_SECONDS = 3
GENERATION = re.compile(r"^[0-9a-f]{32}$")
REQUIRED_ROLES = frozenset(("primary", "secondary", "codex3"))
SUPPORTED_STATES = frozenset(("STOP_REQUESTED", "DRAINING", "STOPPED", "RESUMED"))


def _empty(status: str = "unsupported") -> dict:
    return {
        "status": status,
        "expected_workers": None,
        "acknowledged_workers": 0,
        "dispatch_frozen": False,
        "evidence_age_seconds": None,
    }


def _roster(policy_path: Path) -> tuple[dict[str, str], str] | None:
    try:
        file = Path(policy_path)
        info = file.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1_000_000:
            return None
        config = json.loads(file.read_text(encoding="utf-8"))
        agents = config.get("agents")
        if (not isinstance(agents, dict) or set(agents) != REQUIRED_ROLES
                or config.get("permanent_role_roster", {}).get("enabled") is not True
                or config.get("parallel_final_auditor", {}).get("enabled") is True):
            return None
        roster = {}
        for role in sorted(REQUIRED_ROLES):
            a = agents[role]
            account = a.get("account") if isinstance(a, dict) else None
            if (not isinstance(account, str) or not 1 <= len(account) <= 64
                    or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,63}", account)):
                return None
            roster[role] = account
        if len(set(roster.values())) != len(roster):
            return None
        digest = sha256(json.dumps(roster, sort_keys=True,
                                   separators=(",", ":")).encode("utf-8")).hexdigest()
        return roster, digest
    except (OSError, ValueError, TypeError, UnicodeError, AttributeError, RecursionError):
        return None


def _event_is_exact_owner_stop(details: str, generation: str) -> bool:
    if not isinstance(details, str) or not 0 < len(details) <= 4096:
        return False

    def unique_keys(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate event key")
            obj[key] = value
        return obj

    try:
        event = json.loads(details, object_pairs_hook=unique_keys)
        return (isinstance(event, dict) and event.get("generation") == generation
                and event.get("initiator") == "interactive_owner"
                and event.get("confirmed") is True
                and event.get("action") == "stop_all_codex_workers")
    except (ValueError, TypeError, RecursionError):
        return False


def _leased_age(timestamp: float, now: float) -> float | None:
    if type(timestamp) not in (float, int) or not isinstance(now, (float, int)):
        return None
    age = now - timestamp
    if not -FUTURE_TOLERANCE_SECONDS <= age <= LEASE_SECONDS:
        return None
    return round(max(0.0, age), 2)


def verify_codex_stop(
    conn: sqlite3.Connection,
    *,
    mode: str,
    in_flight_attempts: int,
    running_packages: int,
    policy_path: Path = ATLAS_POLICY,
    now: float | None = None,
    boot_id_path: Path = Path("/proc/sys/kernel/random/boot_id"),
) -> dict:
    """Validate a future Atlas proof in the caller's SQLite read transaction.

    Current production Atlas has neither contract table: report 'unsupported'.
    Never infer a stop from zero running tasks or the global owner STOP alone.
    """
    try:
        existing = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?)",
                (TABLE_CONTROL, TABLE_ACKS),
            )
        }
        if not existing:
            return _empty("unsupported")
        if existing != {TABLE_CONTROL, TABLE_ACKS}:
            return _empty("invalid")
        policy = _roster(policy_path)
        if not policy:
            return _empty("unavailable")
        roster, expected_digest = policy
        try:
            actual_boot_id = Path(boot_id_path).read_text(encoding="ascii").strip().lower()
        except (OSError, UnicodeError):
            return _empty("unavailable")
        if not re.fullmatch(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", actual_boot_id):
            return _empty("unavailable")
        now = time.time() if now is None else now
        row = conn.execute(
            "SELECT generation, state, event_seq, dispatch_barrier_active, "
            "barrier_checked_at, roster_sha256, active_worker_processes, "
            "all_lanes_drained, boot_id FROM codex_owner_stop_control WHERE id=1"
        ).fetchone()
        if row is None:
            return _empty("not_requested")
        generation, state, event_seq, barrier, checked_at, digest, processes, drained, boot_id = row
        if state == "RESUMED":
            return _empty("resumed")
        if (not isinstance(generation, str) or not GENERATION.fullmatch(generation)
                or state not in SUPPORTED_STATES
                or type(event_seq) is not int or event_seq < 1
                or type(barrier) is not int or barrier not in (0, 1)
                or type(processes) is not int or not 0 <= processes <= 100000
                or type(drained) is not int or drained not in (0, 1)
                or digest != expected_digest or boot_id != actual_boot_id):
            return _empty("invalid")
        # Any later resume or global owner control change invalidates the
        # generation. The event is Atlas-owned, not a browser-supplied flag.
        latest = conn.execute(
            "SELECT seq,kind,details FROM events "
            "WHERE kind IN ('codex_owner_stop_request','codex_owner_resume','owner_mode') "
            "ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        if (latest is None or latest[0] != event_seq
                or latest[1] != "codex_owner_stop_request"
                or not _event_is_exact_owner_stop(latest[2], generation)):
            return _empty("invalid")
        count = len(roster)
        if state in ("STOP_REQUESTED", "DRAINING"):
            return {**_empty("draining"), "expected_workers": count,
                    "dispatch_frozen": barrier == 1}
        age = _leased_age(checked_at, now)
        if age is None:
            return {**_empty("stale"), "expected_workers": count}
        if (mode not in ("RUN", "STOP") or barrier != 1 or drained != 1 or
                processes != 0 or in_flight_attempts != 0 or running_packages != 0):
            return {**_empty("draining"), "expected_workers": count,
                    "dispatch_frozen": barrier == 1, "evidence_age_seconds": age}
        rows = conn.execute(
            "SELECT role,account,state,generation,acknowledged_at "
            "FROM codex_owner_stop_acks LIMIT 32"
        ).fetchall()
        if len(rows) > count:
            return {**_empty("invalid"), "expected_workers": count}
        recognized = set()
        for role, account, worker_state, ack_generation, ack_time in rows:
            if (role not in roster or role in recognized
                    or account != roster[role] or worker_state != "STOPPED"
                    or ack_generation != generation
                    or _leased_age(ack_time, now) is None):
                return {**_empty("invalid"), "expected_workers": count}
            recognized.add(role)
        if recognized != set(roster):
            return {**_empty("draining"), "expected_workers": count,
                    "acknowledged_workers": len(recognized),
                    "dispatch_frozen": True, "evidence_age_seconds": age}
        return {
            "status": "verified",
            "expected_workers": count,
            "acknowledged_workers": count,
            "dispatch_frozen": True,
            "evidence_age_seconds": age,
        }
    except (sqlite3.Error, OSError, ValueError, TypeError, OverflowError):
        return _empty("unavailable")
