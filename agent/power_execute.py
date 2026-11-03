#!/usr/bin/python3
"""Root-owned fixed power executor; never call --execute in smoke tests.

Read-only gate is re-evaluated seconds before requesting normal systemd
shutdown/reboot. No shell, --force, model operations, account changes or
arbitrary path arguments are supported.
"""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys


def _trusted_file(path):
    try:
        info=Path(path).lstat()
        return (stat.S_ISREG(info.st_mode) and info.st_uid==0
                and stat.S_IMODE(info.st_mode)&0o022==0)
    except OSError:
        return False


def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    own=Path(__file__).resolve(strict=True)
    gate=own.parent/"power_gate.py"
    # The root-owned systemd unit is the sole intended invocation context.
    # NoNewPrivileges remains enabled in the unprivileged outbound Agent.
    if (os.geteuid()!=0
            or not _trusted_file(own) or not _trusted_file(gate)):
        raise RuntimeError("Privileged power helper identity invalid")
    sys.path.insert(0,str(own.parent))
    from power_gate import inspect_power
    result=inspect_power()
    if argv==["--check"]:
        print(json.dumps(result,separators=(",",":")))
        return 0 if result["eligible"] else 4
    if (len(argv)!=3 or argv[0]!="--execute"
            or argv[1] not in ("shutdown","restart") or argv[2]!="unsaved-loss-accepted"):
        raise ValueError("Unsupported root power action")
    if not result["eligible"]:
        raise RuntimeError("Live workstation power gate blocked")
    action="poweroff" if argv[1]=="shutdown" else "reboot"
    # The owner explicitly accepts LOSS of unsaved work. Saving and closing
    # files are optional and will be managed in a separate application section.
    # GNOME's session shutdown block can be bypassed with no --force:
    # use ordinary systemd shutdown, never forcefully kill processes here.
    argv_systemctl=[
        "/usr/bin/systemctl","--check-inhibitors=no",
        "--no-block","--no-wall",action,
    ]
    finished=subprocess.run(argv_systemctl,check=False,capture_output=True,
                            timeout=12,shell=False)
    if finished.returncode!=0:
        raise RuntimeError("Normal systemd power request was rejected")
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        print("Ubuntu Control power refused: "+type(error).__name__,file=sys.stderr)
        raise SystemExit(1)
