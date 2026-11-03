"""Conservative, read-only power preflight. Never authorizes execution."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pwd
import selectors
import stat
import subprocess
import time

from atlas_guard import read_atlas_dispatch_state
from power_gate import inspect_power

ATLAS = ["/usr/bin/systemctl", "--user", "show", "twt-roadmap-atlas.service",
         "--property=LoadState,ActiveState,SubState", "--no-pager"]
INHIBITORS = ["/usr/bin/systemd-inhibit", "--list", "--no-pager"]
PROCESSES = ["/usr/bin/ps", "-e", "-o", "comm="]
CPUWM_SCRIPT = Path(pwd.getpwuid(os.getuid()).pw_dir) / "cpu-workload-manager" / "cpuwm.py"
CPUWM = ["/usr/bin/python3", "-B", str(CPUWM_SCRIPT), "status"]
PROFILES = {"quiet", "balanced", "performance"}
LIMIT = 32768


def read_command(args):
    """Fixed readers only; bound bytes in memory and wall time, discard stderr."""
    if args not in (ATLAS, INHIBITORS, PROCESSES, CPUWM):
        raise ValueError("Reader not allowed")
    try:
        if args == CPUWM:
            # lstat rejects symlinks, directories and special files. Also reject
            # a redirected manager directory; never discover an alternate script.
            if (not stat.S_ISREG(CPUWM_SCRIPT.lstat().st_mode)
                    or not stat.S_ISDIR(CPUWM_SCRIPT.parent.lstat().st_mode)):
                return None
        with subprocess.Popen(args, shell=False, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL,
                              env={**os.environ, "LC_ALL": "C", "SYSTEMD_COLORS": "0"}) as child:
            try:
                output = bytearray()
                deadline = time.monotonic() + 3
                with selectors.DefaultSelector() as selector:
                    selector.register(child.stdout, selectors.EVENT_READ)
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not selector.select(remaining):
                            return None
                        chunk = os.read(child.stdout.fileno(), min(4096, LIMIT + 1 - len(output)))
                        if not chunk:
                            break
                        output.extend(chunk)
                        if len(output) > LIMIT:
                            return None
                if child.wait(timeout=max(0.01, deadline - time.monotonic())) != 0:
                    return None
                return output.decode("utf-8", errors="strict")
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        return None


def parse_atlas(text):
    if text is None:
        return "unknown"
    fields = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if not sep or key in fields or key not in {"LoadState", "ActiveState", "SubState"}:
            return "unknown"
        fields[key] = value
    if fields.get("LoadState") != "loaded":
        return "unknown"
    if fields.get("ActiveState") == "active" and fields.get("SubState") in {"running", "exited"}:
        return "active"
    if fields.get("ActiveState") == "inactive" and fields.get("SubState") == "dead":
        return "inactive"
    return "unknown"


def parse_inhibitors(text):
    """Parse C-locale systemd table from the right; never return private columns."""
    result = {"shutdown_block": False, "session_block": False, "shutdown_delay": False,
              "unknown": False}
    if text is None:
        return {**result, "unknown": True}
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines == ["No inhibitors listed."]:
        return result
    if not lines or lines[0].split() != ["WHO", "UID", "USER", "PID", "COMM", "WHAT", "WHY", "MODE"]:
        return {**result, "unknown": True}
    import re
    footer = re.fullmatch(r"(\d+) inhibitors? listed\.", lines[-1])
    rows = lines[1:-1]
    if not footer or int(footer[1]) != len(rows):
        return {**result, "unknown": True}
    for row in rows:
        # UID/PID delimit the identity columns; WHAT has a fixed vocabulary.
        match = re.fullmatch(r".+?\s+\d+\s+\S+\s+\d+\s+(\S+)\s+([a-z:-]+)\s+.+?\s+(block|delay)", row)
        if not match:
            result["unknown"] = True
            continue
        comm, what, mode = match.groups()
        parts = what.split(":")
        if any(p not in {"shutdown", "sleep", "idle", "handle-power-key", "handle-suspend-key",
                         "handle-hibernate-key", "handle-lid-switch", "handle-reboot-key"} for p in parts):
            result["unknown"] = True
        if "shutdown" in parts:
            result["shutdown_" + mode] = True
            if mode == "block" and ("session" in comm or comm.startswith("gnome-")):
                result["session_block"] = True
    return result


def parse_cpuwm(text, now):
    """Only fresh, schema-checked status supplies counts/enforcement indicators.

    Enforcement is resource policy, not evidence that jobs have drained. Neither
    roles nor scopes are returned, including in errors. No receipt is consulted.
    """
    empty = {"status": "unavailable", "managed_scopes": None, "managed_roles": None,
             "primary_active": None, "secondary_active": None,
             "enforcement_ok": None, "monitor_age_seconds": None}

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate status key")
            result[key] = value
        return result

    try:
        if not isinstance(text, str) or len(text.encode("utf-8")) > LIMIT:
            return empty
        data = json.loads(text, object_pairs_hook=unique_object)
        if not isinstance(data, dict) or data.get("profile") not in PROFILES:
            return empty
        for key in ("active_managed_scopes", "active_roles"):
            values = data.get(key)
            if (not isinstance(values, list) or len(values) > 128
                    or any(not isinstance(value, str) or not value.strip() for value in values)):
                return empty
        monitor = data.get("last_monitor")
        if (not isinstance(monitor, dict) or monitor.get("profile") != data["profile"]
                or not isinstance(monitor.get("timestamp"), str)):
            return empty
        enforcement = monitor.get("twt_enforcement")
        if (not isinstance(enforcement, dict)
                or any(type(enforcement.get(key)) is not bool
                       for key in ("primary_active", "secondary_active", "ok"))):
            return empty
        timestamp = datetime.fromisoformat(monitor["timestamp"])
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            return empty
        age = (now - timestamp).total_seconds()
        if not -5 <= age <= 60:
            return {**empty, "status": "stale", "monitor_age_seconds": round(age, 3)}
        trusted = enforcement["ok"]
        return {"status": "fresh", "managed_scopes": len(data["active_managed_scopes"]),
                "managed_roles": len(data["active_roles"]),
                "primary_active": enforcement["primary_active"] if trusted else None,
                "secondary_active": enforcement["secondary_active"] if trusted else None,
                "enforcement_ok": trusted, "monitor_age_seconds": round(age, 3)}
    except (ValueError, TypeError, OverflowError, RecursionError):
        return empty


def collect_power_safety():
    atlas = parse_atlas(read_command(ATLAS))
    atlas_control = read_atlas_dispatch_state()
    inhibitors = parse_inhibitors(read_command(INHIBITORS))
    processes = read_command(PROCESSES)
    cpuwm = parse_cpuwm(read_command(CPUWM), datetime.now(timezone.utc))
    categories = []
    desktop_categories = []
    if processes is not None:
        names = processes.lower().splitlines()
        for category, tokens in {"Atlas": ("atlas",), "ns-3": ("ns3", "ns-3"),
                                 "Codex": ("codex",), "CPUWM": ("cpuwm",)}.items():
            if any(any(token in name for token in tokens) for name in names):
                categories.append(category)
        for category, tokens in {
                "Browser": ("firefox", "chrome", "chromium", "brave", "epiphany"),
                "Editor": ("code", "gedit", "gnome-text-edit", "kate", "emacs", "vim"),
                "Document tools": ("libreoffice", "soffice", "evince", "okular")}.items():
            if any(any(token in name for token in tokens) for name in names):
                desktop_categories.append(category)
    desktop_work = {"status": "unverifiable", "app_categories": desktop_categories,
                    "process_observation": "available" if processes is not None else "unavailable",
                    "session_shutdown_blocked": inhibitors["session_block"]}
    unknowns = ["CPUWM active-job state is not verified; the manager must not be bypassed.",
                "Unsaved desktop work and other long-running jobs cannot be ruled out."]
    reasons = []
    warnings = ["Process categories are best-effort and cannot prove that work is idle."]
    warnings.append("CPUWM scopes describe extra managed resources, not system idleness; zero scopes cannot prove idle.")
    warnings.append("CPUWM enforcement indicators describe resource policy, not job drain confirmation.")
    warnings.append("Desktop app presence cannot detect unsaved files; external session/save acknowledgements are required.")
    if cpuwm["status"] != "fresh":
        unknowns.append("CPUWM status is " + cpuwm["status"] + "; active work cannot be verified.")
    else:
        if not cpuwm["enforcement_ok"]:
            reasons.append("CPUWM resource enforcement is not confirmed; protect running work.")
        if cpuwm["managed_scopes"] or cpuwm["managed_roles"]:
            reasons.append("CPUWM reports managed scopes or roles; job drain must be confirmed.")
        if cpuwm["primary_active"] or cpuwm["secondary_active"]:
            reasons.append("CPUWM reports active enforcement groups; protect running work.")
    if desktop_categories:
        reasons.append("Desktop applications may contain unsaved work: " + ", ".join(desktop_categories) + ".")
    # Never infer explicit owner stop from idle agents, empty queues,
    # quota exhaustion or a non-running service. Atlas may dispatch at any
    # moment while the authoritative scheduler mode remains RUN.
    dispatch = atlas_control.get("status", "unavailable")
    if atlas_control.get("codex_user_stop_verified") is True and atlas_control.get("atlas_power_gate_clear") is True:
        warnings.append("Verified fresh owner stop receipts cover all Codex workers and the dispatch barrier; Atlas-specific protection is clear.")
    elif dispatch in ("running", "armed_idle"):
        reasons.append("Atlas scheduler is in RUN mode; it can start new Codex tasks even when agents are idle or queues are empty.")
    elif dispatch == "owner_stop_draining":
        reasons.append("Atlas owner STOP was requested, but model attempts are still in flight.")
    elif dispatch == "owner_stop_no_active_attempts":
        warnings.append("Atlas scheduler STOP is explicitly recorded by the owner; no active database attempts were found.")
        unknowns.append("Codex user-stop and complete worker drain are not yet independently verified.")
    elif dispatch == "unverified_stop":
        reasons.append("Atlas scheduler appears STOPPED without a verified explicit owner stop; inactivity cannot authorize shutdown.")
    else:
        unknowns.append("Atlas owner-stop evidence is unavailable; idle Codex agents do not authorize shutdown.")
    if atlas == "unknown":
        unknowns.append("Atlas service state is unknown.")
    elif (atlas == "active" and not atlas_control.get("atlas_power_gate_clear")
          and dispatch not in ("owner_stop_no_active_attempts", "owner_stop_draining")):
        reasons.append("Atlas service is active and no verified drained owner stop exists.")
    if inhibitors["unknown"]:
        unknowns.append("Shutdown inhibitor data is missing or ambiguous.")
    if inhibitors["shutdown_block"]:
        reasons.append("A systemd shutdown/block inhibitor prevents power requests.")
    if inhibitors["session_block"]:
        reasons.append("The desktop session blocks shutdown; protect unsaved work.")
    if inhibitors["shutdown_delay"]:
        warnings.append("Shutdown delay inhibitors are present; applications or updates need time.")
    if processes is None:
        unknowns.append("Workload process categories are unavailable.")
    if categories:
        reasons.append("Known workload categories are present: " + ", ".join(categories) + ".")
    real_power = inspect_power()
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "safe_to_request": False,
            "atlas_state": atlas, "atlas_control": atlas_control,
            "inhibitors": inhibitors, "workload_categories": categories,
            "cpuwm": cpuwm, "desktop_work": desktop_work,
            "real_power": real_power,
            "unknowns": unknowns, "blocked_reasons": reasons + unknowns, "warnings": warnings}
