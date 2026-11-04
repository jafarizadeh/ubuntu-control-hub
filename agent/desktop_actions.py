"""Limited, consent-based GNOME Wayland desktop management for Ubuntu Control.

NO arbitrary remote shell, window titles, file contents or user-provided
commands. Close via AT-SPI application actions where possible; only known
browser MAIN processes have a bounded SIGTERM fallback. No SIGKILL,
gnome-session-quit, pkill-all, system service or Atlas worker termination.

Actions run solely in the signed, unprivileged Ubuntu Agent after the user
confirmed data-loss risk in the private iPhone PWA.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time

RESULT_FILE = Path.home() / ".local/state/ubuntu-control/desktop-actions.json"
MAX_WINDOWS = 180
BROWSERS = frozenset((
    "google chrome", "chromium", "chromium-browser", "firefox",
    "brave browser", "microsoft edge", "vivaldi",
))
DOCUMENTS = frozenset((
    "papers", "evince", "org.gnome.nautilus", "nautilus",
    "gnome text editor", "text editor", "gedit", "libreoffice",
    "libreoffice writer", "libreoffice calc", "libreoffice impress",
    "visual studio code", "code", "mousepad", "kate", "okular",
))
TERMINALS = frozenset((
    "ptyxis", "gnome terminal", "gnome-terminal", "console",
    "kgx", "konsole", "xterm", "tilix", "alacritty", "kitty",
))
BROWSER_EXE = frozenset((
    "chrome", "chromium", "chromium-browser", "firefox", "firefox-bin",
    "brave", "brave-browser", "msedge", "vivaldi-bin",
))
ACTIONS = frozenset((
    "inspect", "close-documents", "close-terminals",
    "open-terminal", "start-gpt-remote",
))


def classify(app_name: str) -> str | None:
    if not isinstance(app_name, str):
        return None
    name = app_name.strip().lower()
    if name in BROWSERS:
        return "browser"
    if name in DOCUMENTS or name.startswith("libreoffice "):
        return "document"
    if name in TERMINALS:
        return "terminal"
    return None


def _windows():
    try:
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
        desktop = Atspi.get_desktop(0)
        if desktop is None:
            return None
        windows = []
        for i in range(min(desktop.get_child_count(), 90)):
            app = desktop.get_child_at_index(i)
            if app is None:
                continue
            category = classify(app.get_name())
            if category is None:
                continue
            for j in range(min(app.get_child_count(), 64)):
                win = app.get_child_at_index(j)
                if win is None or win.get_role_name() not in ("frame", "window"):
                    continue
                windows.append((category, win))
                if len(windows) >= MAX_WINDOWS:
                    return None
        return windows
    except (OSError, ValueError, TypeError, RuntimeError, ImportError):
        return None


def _known_browser_mains(proc_root: Path = Path("/proc")) -> list[int]:
    """Return only same-UID *main* browser PIDs, never renderer children."""
    data = {}
    for item in proc_root.iterdir():
        if not item.name.isdecimal():
            continue
        try:
            pid = int(item.name)
            status = (item / "status").read_text(encoding="utf-8")
            uid = int(next(line.split()[1] for line in status.splitlines()
                           if line.startswith("Uid:")))
            parent = int(next(line.split()[1] for line in status.splitlines()
                              if line.startswith("PPid:")))
            if uid != os.geteuid() or pid <= 2:
                continue
            executable = os.readlink(item / "exe")
            basename = Path(executable).name
            if basename not in BROWSER_EXE:
                continue
            if executable.startswith(("/tmp/", "/dev/shm/", "/run/user/")):
                continue
            data[pid] = (basename, parent)
        except (OSError, ValueError, StopIteration, UnicodeError):
            continue
    return sorted(pid for pid, (name, parent) in data.items()
                  if parent not in data or data[parent][0] != name)[:12]


def _gpt_remote_running(proc_root: Path = Path("/proc")) -> bool:
    """Recognize the installed Desktop Commander Remote connector by argv."""
    for item in proc_root.iterdir():
        if not item.name.isdecimal():
            continue
        try:
            uid = int(next(line.split()[1] for line in
                           (item / "status").read_text().splitlines()
                           if line.startswith("Uid:")))
            if uid != os.geteuid():
                continue
            args = (item / "cmdline").read_bytes().split(b"\0")
            if any(b"desktop-commander" in a.lower() for a in args) and (
                    any(b"remote" == a.strip().lower() for a in args) or
                    any(b"remote" in a.lower() for a in args if b"desktop-commander" in a.lower())):
                return True
        except (OSError, StopIteration, ValueError):
            continue
    return False


def _last_result():
    try:
        p = RESULT_FILE
        info = p.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
            return None
        value = json.loads(p.read_text(encoding="utf-8"))
        allowed = ("close-documents", "close-terminals", "open-terminal", "start-gpt-remote")
        if (not isinstance(value, dict) or value.get("action") not in allowed
                or type(value.get("timestamp")) is not int
                or type(value.get("requested")) is not int
                or type(value.get("remaining")) is not int
                or type(value.get("completed")) is not bool):
            return None
        return {key: value[key] for key in
                ("action", "timestamp", "requested", "remaining", "completed")}
    except (OSError, ValueError, TypeError, KeyError):
        return None


def inspect():
    windows = _windows()
    if windows is None:
        counts = {"available": False, "browser_windows": None,
                  "document_windows": None, "terminal_windows": None}
    else:
        counts = {
            "available": True,
            "browser_windows": sum(k == "browser" for k, _ in windows),
            "document_windows": sum(k == "document" for k, _ in windows),
            "terminal_windows": sum(k == "terminal" for k, _ in windows),
        }
    return {
        **counts, "gpt_remote_running": _gpt_remote_running(),
        "last_action": _last_result(),
        "backend": "GNOME Wayland accessibility (no window titles disclosed)",
    }


def _safe_to_close():
    # Closing browser windows or terminal tabs may destroy work. Atlas stays
    # protected even if the owner clicked the iPhone confirmation.
    from power_gate import inspect_atlas, inspect_processes, inspect_cpuwm
    atlas = inspect_atlas()
    processes_ok, heavy = inspect_processes()
    if (atlas["errors"] or not atlas["atlas_owner_paused"] or
            atlas["codex_owner_paused_count"] != 3 or atlas["active_jobs"] != 0
            or not processes_ok or heavy or not inspect_cpuwm()):
        raise PermissionError("Atlas, Codex or active workloads are not confirmed stopped")


def _close_accessible(window) -> bool:
    """Ask the *application* to close; this permits any native unsaved prompt."""
    try:
        names = [window.get_action_name(i) for i in range(min(window.get_n_actions(), 70))]
        for action in ("window.close", "win.close", "close"):
            if action in names:
                return bool(window.do_action(names.index(action)))
    except (OSError, ValueError, TypeError, RuntimeError):
        pass
    return False


def _close_browsers():
    """Browser Wayland windows do not publish a close action via AT-SPI.

    SIGTERM targets only validated, same-owner main browser processes.
    Never signal renderer/zygote children, shells, other apps or services.
    """
    requested = 0
    for pid in _known_browser_mains():
        try:
            # Reconfirm same PID, UID and executable before sending a signal.
            current = _known_browser_mains()
            if pid not in current:
                continue
            os.kill(pid, signal.SIGTERM)
            requested += 1
        except (OSError, ValueError):
            pass
    return requested


def _write_receipt(action, requested, remaining, completed):
    data = {
        "action": action,
        "timestamp": int(time.time()),
        "requested": requested,
        "remaining": remaining,
        "completed": completed,
    }
    RESULT_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".desktop-action-", dir=RESULT_FILE.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, RESULT_FILE)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _terminal_executable():
    """Allow only the installed fixed GNOME Ptyxis binary."""
    terminal=Path("/usr/bin/ptyxis")
    if not terminal.is_file() or terminal.is_symlink():
        raise RuntimeError("Ptyxis terminal is not available")
    return terminal


def run(action):
    if action not in ACTIONS:
        raise ValueError("Unsupported desktop action")
    if action == "inspect":
        return inspect()

    if action in ("close-documents", "close-terminals"):
        _safe_to_close()
        windows = _windows()
        if windows is None:
            raise RuntimeError("Cannot inspect native desktop windows")
        categories = {"browser", "document"} if action == "close-documents" else {"terminal"}
        selected = [item for item in windows if item[0] in categories]
        requested = sum(_close_accessible(win) for category, win in selected
                        if category != "browser")
        if action == "close-documents":
            requested += _close_browsers()
        # Closing GUI windows is asynchronous; don't claim full completion
        # until the post-action scan confirms they are no longer present.
        time.sleep(0.4)
        current = _windows()
        remaining = -1 if current is None else sum(kind in categories for kind, _ in current)
        completed = remaining == 0
        _write_receipt(action, requested, remaining, completed)
        return {"requested": requested, "remaining": remaining, "completed": completed}

    # Only a fixed, local, installed terminal is launched. No commands from
    # the phone are passed through to a shell.
    terminal = _terminal_executable()
    if action == "open-terminal":
        args = [str(terminal), "--new-window"]
    elif action == "start-gpt-remote":
        launcher = Path(__file__).resolve().with_name("gpt_remote_console.py")
        if not launcher.is_file() or launcher.is_symlink():
            raise RuntimeError("GPT Remote terminal launcher unavailable")
        args = [str(terminal), "--new-window", "--", sys.executable, str(launcher)]
    else:
        raise ValueError("Invalid launcher")
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            close_fds=True, start_new_session=True)
    # Popen returning doesn't establish that the GUI appeared. Report the
    # start request accurately; a subsequent window scan confirms it.
    _write_receipt(action, 1, 0, False)
    return {"requested": 1, "remaining": 0, "completed": False,
            "launch_pid": proc.pid}


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].startswith("--"):
        raise SystemExit(2)
    operation = sys.argv[1][2:]
    try:
        response = run(operation)
        print(json.dumps(response, separators=(",", ":")))
    except (OSError, PermissionError, RuntimeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__}))
        raise SystemExit(1)
