"""Read-only Atlas owner-stop evidence for Ubuntu Control.

Do not equate an idle scheduler, empty queues, or quota exhaustion with
an explicit human stop. Only a verified owner-mode STOP event proves that
the Atlas *dispatcher* has been manually stopped. It does not prove that
every Codex worker or other application has exited.
"""

from __future__ import annotations

import json
from contextlib import closing
import sqlite3
import stat
from pathlib import Path

from codex_stop_attestation import ATLAS_POLICY, verify_codex_stop

ATLAS_DB = Path("/var/lib/twt-roadmap-atlas/roadmap.sqlite")
TERMINAL_ATTEMPT_STATES = ("COMPLETE", "FAILED", "INTERRUPTED", "QUOTA", "STALE")
VALID_MODES = frozenset(("RUN", "STOP"))
EXPLICIT_STOP_REASON = "Explicit owner stop requested"

UNKNOWN = {
    "status": "unavailable",
    "scheduler_mode": "unknown",
    "dispatch_armed": None,
    "owner_stop_verified": False,
    "codex_user_stop_verified": False,
    "codex_stop": {"status": "unavailable", "expected_workers": None,
                   "acknowledged_workers": 0, "dispatch_frozen": False,
                   "evidence_age_seconds": None},
    "inflight_attempts": None,
    "running_packages": None,
    "ready_packages": None,
    "dispatch_stop_reason": "not_verified",
    "atlas_power_gate_clear": False,
}


def _validate_owner_stop(details: str) -> bool:
    if not isinstance(details, str) or len(details) > 4096:
        return False

    def no_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate event field")
            result[key] = value
        return result

    try:
        event = json.loads(details, object_pairs_hook=no_duplicate_keys)
    except (TypeError, ValueError, RecursionError):
        return False
    return (
        isinstance(event, dict)
        and event.get("after") == "STOP"
        and event.get("reason") == EXPLICIT_STOP_REASON
    )


def classify_snapshot(mode, event_details, active_attempts, legacy_attempts,
                      running_packages, ready_packages):
    """Separate scheduler readiness from a confirmed human stop.

    Even a manually stopped dispatcher is NOT proof that every Codex worker
    is fully drained: a future owner-stop acknowledgement interface must
    attest to all independent execution lanes. Never authorize power here.
    """
    if mode not in VALID_MODES:
        return dict(UNKNOWN)
    counts = (active_attempts, legacy_attempts, running_packages, ready_packages)
    if any(type(value) is not int or not 0 <= value <= 100000 for value in counts):
        return dict(UNKNOWN)
    inflight = active_attempts + legacy_attempts
    explicit = mode == "STOP" and _validate_owner_stop(event_details)
    if mode == "RUN":
        state = "running" if inflight or running_packages else "armed_idle"
    elif not explicit:
        state = "unverified_stop"
    elif inflight or running_packages:
        state = "owner_stop_draining"
    else:
        state = "owner_stop_no_active_attempts"

    return {
        "status": state,
        "scheduler_mode": mode,
        "dispatch_armed": mode == "RUN",
        "owner_stop_verified": explicit,
        # Separate from owner-mode STOP: future Codex stop control must attest
        # each physical worker and prevent new claims across all lanes.
        "codex_user_stop_verified": False,
        "inflight_attempts": inflight,
        "running_packages": running_packages,
        "ready_packages": ready_packages,
        "dispatch_stop_reason": "explicit_owner_action" if explicit else "not_verified",
        "atlas_power_gate_clear": False,
    }


def read_atlas_dispatch_state(database: Path = ATLAS_DB, *, policy_path: Path = ATLAS_POLICY) -> dict:
    """Short, bounded SQLite snapshot from the existing Atlas database.

    The source path and SQL are fixed. No Atlas imports, commands, writes,
    owner-mode changes, signals, job cancellations or PID disclosure.
    """
    try:
        source = Path(database)
        info = source.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size == 0:
            return dict(UNKNOWN)
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=1.0)) as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("PRAGMA busy_timeout=750")
            conn.execute("BEGIN")
            row = conn.execute("SELECT value FROM meta WHERE key='mode'").fetchone()
            if not row:
                return dict(UNKNOWN)
            mode = row[0]
            event = conn.execute(
                "SELECT details FROM events WHERE kind='owner_mode' ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            active_attempts = conn.execute(
                "SELECT count(*) FROM attempts WHERE state NOT IN (?,?,?,?,?)",
                TERMINAL_ATTEMPT_STATES,
            ).fetchone()[0]
            legacy_attempts = conn.execute(
                "SELECT count(*) FROM legacy_atomicity_attempts WHERE state NOT IN (?,?,?,?,?)",
                TERMINAL_ATTEMPT_STATES,
            ).fetchone()[0]
            running_packages = conn.execute(
                "SELECT count(*) FROM packages WHERE state='RUNNING'"
            ).fetchone()[0]
            ready_packages = conn.execute(
                "SELECT count(*) FROM packages WHERE state='READY'"
            ).fetchone()[0]
            summary = classify_snapshot(
                mode, event[0] if event else None, active_attempts,
                legacy_attempts, running_packages, ready_packages,
            )
            if summary["status"] == "unavailable":
                return summary
            receipt = verify_codex_stop(
                conn,
                mode=mode,
                in_flight_attempts=summary["inflight_attempts"],
                running_packages=running_packages,
                policy_path=policy_path,
            )
            verified = receipt["status"] == "verified"
            return {
                **summary,
                "codex_stop": receipt,
                "codex_user_stop_verified": verified,
                # This clears only the Atlas-specific gate. It never grants
                # permission for shutdown: CPUWM, unsaved work, inhibitors
                # and owner confirmation remain separate.
                "atlas_power_gate_clear": verified,
            }
    except (OSError, ValueError, sqlite3.Error, TypeError):
        return dict(UNKNOWN)
