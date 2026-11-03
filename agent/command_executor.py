"""Fixed unprivileged commands with durable execution reservations."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time

DEFAULT_STATE = Path.home() / ".config/ubuntu-control-agent/command-state.json"


def valid_command(command):
    if not isinstance(command, dict):
        return False
    action = command.get("action")
    fields = {"id", "action", "value", "created_at", "expires_at"}
    if action == "cpuwm.set_profile":
        fields.add("confirm")
    if set(command) != fields:
        return False
    if not isinstance(command["id"], str) or not re.fullmatch(r"[a-f0-9]{32}", command["id"]):
        return False
    start, end = command["created_at"], command["expires_at"]
    if type(start) is not int or type(end) is not int or not start <= time.time() < end or end - start != 45:
        return False
    value = command["value"]
    return ((action == "audio.set_volume" and type(value) is int and 0 <= value <= 100)
            or (action == "audio.set_mute" and type(value) is bool)
            or (action == "cpuwm.set_profile" and type(value) is str
                and value in {"quiet", "balanced", "performance"} and command["confirm"] is True))


class CommandExecutor:
    def __init__(self, state_file=DEFAULT_STATE):
        self.path = Path(state_file)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._locked():
            self._load()
            if not self.path.exists():
                self._save()

    @contextmanager
    def _locked(self):
        fd = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _load(self):
        self.state = {"seen": {}, "ack": None}
        if self.path.is_symlink():
            raise ValueError("Unsafe command state")
        if self.path.exists():
            info = self.path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError("Unsafe command state")
            self.state = json.loads(self.path.read_text())
            if (not isinstance(self.state, dict) or set(self.state) != {"seen", "ack"}
                    or not isinstance(self.state["seen"], dict)
                    or any(not isinstance(k, str) or not re.fullmatch(r"[a-f0-9]{32}", k)
                           or v not in ("succeeded", "failed") for k, v in self.state["seen"].items())
                    or (self.state["ack"] is not None and self.state["ack"] not in
                        [{"id": k, "status": v} for k, v in self.state["seen"].items()])):
                raise ValueError("Invalid command state")

    def _save(self):
        fd, name = tempfile.mkstemp(prefix=".command-state-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(self.state, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    @property
    def ack(self):
        return self.state["ack"]

    def acknowledged(self):
        with self._locked():
            self._load()
            self.state["ack"] = None
            self._save()

    def execute(self, command):
        with self._locked():
            self._load()
            self._execute(command)

    def _execute(self, command):
        if not valid_command(command):
            raise ValueError("Invalid or expired command")
        ident = command["id"]
        if ident in self.state["seen"]:
            self.state["ack"] = {"id": ident, "status": self.state["seen"][ident]}
            self._save()
            return
        # Persist a failure reservation before any side effect. A crash cannot retry it.
        self.state["seen"][ident] = "failed"
        self.state["ack"] = {"id": ident, "status": "failed"}
        self._save()
        try:
            action, value = command["action"], command["value"]
            if action == "audio.set_volume":
                argv = ["/usr/bin/wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{value}%"]
            elif action == "audio.set_mute":
                argv = ["/usr/bin/wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if value else "0"]
            else:
                manager = Path.home() / "cpu-workload-manager/cpuwm.py"
                if not manager.is_file() or manager.is_symlink():
                    raise ValueError("Workload manager unavailable")
                argv = [sys.executable, str(manager), "profile", value]
            if not valid_command(command):
                raise ValueError("Command expired before execution")
            result = subprocess.run(argv, shell=False, timeout=15, capture_output=True, check=False)
            outcome = "succeeded" if result.returncode == 0 else "failed"
        except (OSError, ValueError, subprocess.SubprocessError):
            outcome = "failed"
        self.state["seen"][ident] = outcome
        self.state["ack"] = {"id": ident, "status": outcome}
        self._save()
