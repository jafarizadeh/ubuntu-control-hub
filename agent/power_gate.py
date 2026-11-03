"""Conservative live power readiness checks; never executes power.

The owner's explicit global STOP and each physical Agent OFF must be persisted
in the Atlas database with matching owner events. Idle/limited agents do not
count. The result is advisory until re-checked by a separate root-owned helper.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pwd
import re
import sqlite3
import stat
import subprocess
import time

ATLAS_DB = Path("/var/lib/twt-roadmap-atlas/roadmap.sqlite")
AGENTS = frozenset(("primary", "secondary", "codex3"))
OWNER_STOP_REASON = "Explicit owner stop requested"
TERMINAL = ("COMPLETE", "FAILED", "INTERRUPTED", "QUOTA", "STALE", "CANCELLED", "CANCELED")
CPUWM_STATUS_TIMEOUT = 4
RUNNING_PROCESS_NAMES = frozenset((
    "codex", "codex-cli", "ns3", "ns-3", "waf", "stress", "stress-ng",
    "iperf3", "qemu-system-x86", "qemu-system-x86_64",
))


def failure_result():
    return {
        "eligible": False, "atlas_owner_paused": False,
        "codex_owner_paused_count": 0, "active_jobs": None,
        "cpuwm_verified": False, "processes_verified": False,
        "blockers": ["Workstation power safety has not been verified."],
        "warnings": [
            "Unsaved desktop documents, browser tabs and terminal work may be lost; saving is optional, but the risk must be explicitly acknowledged.",
            "This action closes the desktop session and may interrupt other unknown processes.",
        ],
    }


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate control field")
        result[name] = value
    return result


def inspect_atlas(path=ATLAS_DB):
    """Single, read-only SQLite snapshot, all roles explicitly stopped by owner."""
    result = {"atlas_owner_paused": False, "codex_owner_paused_count": 0,
              "active_jobs": None, "errors": []}
    try:
        p = Path(path)
        if not stat.S_ISREG(p.lstat().st_mode) or p.stat().st_size <= 0:
            return {**result, "errors": ["Atlas authority database is unavailable."]}
        with closing(sqlite3.connect(p.as_uri()+"?mode=ro",uri=True,timeout=1)) as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("PRAGMA busy_timeout=650")
            conn.execute("BEGIN")
            row = conn.execute("SELECT value FROM meta WHERE key='mode'").fetchone()
            if not row or row[0] != "STOP":
                return {**result, "errors": ["Atlas is not explicitly in STOP mode."]}
            owner = conn.execute(
                "SELECT details FROM events WHERE kind='owner_mode' ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            if not owner:
                return {**result, "errors": ["Atlas owner STOP event is missing."]}
            control=json.loads(owner[0],object_pairs_hook=_unique_object)
            if (not isinstance(control,dict)
                    or control.get("after")!="STOP"
                    or control.get("reason")!=OWNER_STOP_REASON):
                return {**result, "errors": ["Atlas STOP does not have explicit owner provenance."]}
            result["atlas_owner_paused"] = True
            role_rows=conn.execute(
                "SELECT role,enabled FROM owner_agent_dispatch_switches"
            ).fetchall()
            if (len(role_rows)!=len(AGENTS)
                    or {role for role,flag in role_rows}!=AGENTS):
                result["errors"].append("Atlas physical account switch roster is incomplete.")
                return result
            for role, enabled in role_rows:
                if type(enabled) is not int or enabled!=0:
                    result["errors"].append("At least one Codex account can start new tasks.")
                    return result
                latest=conn.execute(
                    "SELECT kind,details FROM events "
                    "WHERE kind IN ('owner_agent_stop_requested','owner_agent_resume') "
                    "AND json_extract(details,'$.role')=? ORDER BY seq DESC LIMIT 1",
                    (role,),
                ).fetchone()
                if latest is None or latest[0]!="owner_agent_stop_requested":
                    result["errors"].append("Codex OFF is not backed by the latest user stop event.")
                    return result
                event=json.loads(latest[1],object_pairs_hook=_unique_object)
                if (not isinstance(event,dict) or event.get("role")!=role
                        or event.get("by")!="interactive_owner"
                        or event.get("enabled") is not False):
                    result["errors"].append("Codex stop event failed owner provenance checks.")
                    return result
                result["codex_owner_paused_count"]+=1
            count=0
            for table in ("attempts","legacy_atomicity_attempts","validator_api_runs",
                          "validator_api_continuations"):
                count+=conn.execute(
                    f"SELECT count(*) FROM {table} WHERE state NOT IN (?,?,?,?,?,?,?)",
                    TERMINAL,
                ).fetchone()[0]
            count+=conn.execute("SELECT count(*) FROM packages WHERE state='RUNNING'").fetchone()[0]
            result["active_jobs"]=count
            if count:
                result["errors"].append("Atlas has unfinished model or publication work.")
        return result
    except (OSError,sqlite3.Error,TypeError,ValueError,RecursionError):
        return {**result,"errors":["Atlas status cannot be verified consistently."]}


def inspect_cpuwm(owner=None, owner_home=None, now=None):
    """Read CPUWM as the owner of the authoritative Atlas database.

    Resolve the workstation account from the private Atlas database owner,
    never hardcode a person's username into public source or trust unverified
    browser headers for execution identity.
    """
    try:
        if owner is None:
            info=ATLAS_DB.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid<=0:
                return False
            account=pwd.getpwuid(info.st_uid)
            owner=account.pw_name
            owner_home=owner_home or account.pw_dir
        elif not isinstance(owner,str) or not owner:
            return False
        owner_home=Path(owner_home or pwd.getpwnam(owner).pw_dir)
    except (KeyError,OSError,ValueError):
        return False
    script=owner_home/"cpu-workload-manager"/"cpuwm.py"
    try:
        info=script.lstat()
        if not stat.S_ISREG(info.st_mode) or script.parent.is_symlink():
            return False
        cmd=["/usr/bin/python3","-B",str(script),"status"]
        if os.geteuid()==0:
            cmd=["/usr/sbin/runuser","-u",owner,"--",*cmd]
        completed=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                                 timeout=CPUWM_STATUS_TIMEOUT,check=False,text=True)
        if completed.returncode or len(completed.stdout)>32768:
            return False
        body=json.loads(completed.stdout,object_pairs_hook=_unique_object)
        if not isinstance(body,dict) or body.get("profile") not in ("quiet","balanced","performance"):
            return False
        if (not isinstance(body.get("active_managed_scopes"),list)
                or not isinstance(body.get("active_roles"),list)
                or body["active_managed_scopes"] or body["active_roles"]):
            return False
        monitor=body.get("last_monitor")
        if not isinstance(monitor,dict) or monitor.get("profile")!=body["profile"]:
            return False
        stamp=datetime.fromisoformat(monitor["timestamp"])
        if stamp.tzinfo is None:
            return False
        now=now or datetime.now(timezone.utc)
        if not -5 <= (now-stamp).total_seconds() <= 60:
            return False
        enforcement=monitor.get("twt_enforcement")
        return bool(isinstance(enforcement,dict)
                    and enforcement.get("ok") is True
                    and enforcement.get("primary_active") is False
                    and enforcement.get("secondary_active") is False)
    except (OSError,ValueError,TypeError,subprocess.TimeoutExpired,
            KeyError,RecursionError):
        return False


def inspect_processes():
    """Protect known model/simulation executables, no argv/filenames exported."""
    try:
        result=subprocess.run(["/usr/bin/ps","-e","-o","comm="],
                              capture_output=True,text=True,timeout=3,check=True)
        if not isinstance(result.stdout,str) or len(result.stdout)>65536:
            return False, True
        running=any(line.strip().lower() in RUNNING_PROCESS_NAMES
                    or line.strip().lower().startswith(("ns3-", "ns-3-", "codex-"))
                    for line in result.stdout.splitlines())
        return True, running
    except (OSError,ValueError,TypeError,subprocess.SubprocessError):
        return False, True


def inspect_power():
    atlas=inspect_atlas()
    verified, heavy_process=inspect_processes()
    cpuwm=inspect_cpuwm()
    blockers=list(atlas["errors"])
    if not cpuwm:
        blockers.append("CPUWM cannot certify no managed jobs or fresh enforcement.")
    if not verified:
        blockers.append("Running workstation processes cannot be checked.")
    elif heavy_process:
        blockers.append("A Codex or simulation process is still running.")
    if atlas["active_jobs"] is None and not blockers:
        blockers.append("Atlas work state is unknown.")
    return {
        "eligible": not blockers and atlas["atlas_owner_paused"]
                    and atlas["codex_owner_paused_count"]==len(AGENTS)
                    and atlas["active_jobs"]==0,
        "atlas_owner_paused":atlas["atlas_owner_paused"],
        "codex_owner_paused_count":atlas["codex_owner_paused_count"],
        "active_jobs":atlas["active_jobs"],
        "cpuwm_verified":cpuwm, "processes_verified":verified,
        "blockers":blockers[:16],
        "warnings":[
             "You may shut down WITHOUT saving open documents, tabs, or terminal work, but their unsaved changes may be permanently lost.",
            "GNOME session shutdown inhibitors may be bypassed only after the user explicitly accepts the loss risk.",
            "Other non-Atlas jobs might not be detectable by this automated check.",
            "Wake-on-LAN needs Ethernet power and firmware support while Ubuntu is off.",
        ],
    }


if __name__=="__main__":
    import sys
    if sys.argv[1:]!=["--check"]:
        raise SystemExit(2)
    print(json.dumps(inspect_power()))
