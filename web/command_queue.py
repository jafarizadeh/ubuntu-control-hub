"""Durable, at-most-once command delivery. No executable text is accepted."""
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time


def validate_action(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid command")
    action = value.get("action")
    expected = {"action", "value", "confirm"} if action == "cpuwm.set_profile" else {"action", "value"}
    if set(value) != expected:
        raise ValueError("Invalid command fields")
    argument = value["value"]
    if action == "audio.set_volume" and type(argument) is int and 0 <= argument <= 100:
        return
    if action == "audio.set_mute" and type(argument) is bool:
        return
    if (action == "cpuwm.set_profile" and type(argument) is str
            and argument in {"quiet", "balanced", "performance"} and value["confirm"] is True):
        return
    raise ValueError("Command not allowed")


class CommandQueue:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Refuse symlinks and create the database privately before SQLite opens it.
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.fchmod(fd, 0o600)
        os.close(fd)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, payload TEXT, created INTEGER, expires INTEGER, status TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS nonces (nonce TEXT PRIMARY KEY, seen REAL)")
        self.db.commit()

    def _expire(self):
        self.db.execute("UPDATE commands SET status='expired' WHERE expires<=? AND status IN ('queued','delivered')", (int(time.time()),))

    def remember_nonce(self, nonce, now):
        with self.lock, self.db:
            self.db.execute("DELETE FROM nonces WHERE seen<?", (now - 150,))
            try:
                self.db.execute("INSERT INTO nonces VALUES (?,?)", (nonce, now))
            except sqlite3.IntegrityError:
                return False
            return True

    def enqueue(self, payload):
        validate_action(payload)
        with self.lock, self.db:
            self._expire()
            count = self.db.execute("SELECT count(*) FROM commands WHERE status IN ('queued','delivered')").fetchone()[0]
            if count >= 16:
                raise OverflowError("Command queue full")
            ident, now = secrets.token_hex(16), int(time.time())
            self.db.execute("INSERT INTO commands VALUES (?,?,?,?,?)", (ident, json.dumps(payload), now, now + 45, "queued"))
            return {"id": ident, "status": "queued"}

    def enqueue_power(self, payload):
        """Internal-only delivery for an owner-armed Pi timer, never API input.

        /api/commands deliberately rejects power actions. This method is
        called only after the timer deadline and fresh signed safety checks.
        """
        if (not isinstance(payload, dict) or set(payload) !=
                {"action", "value", "confirm", "ack_unsaved_loss"}
                or payload["action"] not in {"power.shutdown", "power.restart"}
                or payload["value"] is not None or payload["confirm"] is not True
                or payload["ack_unsaved_loss"] is not True):
            raise ValueError("Invalid internal power command")
        with self.lock, self.db:
            self._expire()
            if self.db.execute(
                "SELECT count(*) FROM commands WHERE status IN ('queued','delivered')"
            ).fetchone()[0]:
                raise OverflowError("Other commands must finish before powering down")
            ident, now=secrets.token_hex(16),int(time.time())
            self.db.execute(
                "INSERT INTO commands VALUES(?,?,?,?,?)",
                (ident,json.dumps(payload),now,now+45,"queued"),
            )
            return {"id":ident,"status":"queued"}

    def status(self, ident):
        with self.lock, self.db:
            self._expire()
            row = self.db.execute("SELECT status FROM commands WHERE id=?", (ident,)).fetchone()
            return row[0] if row else None

    def report_response(self, ack=None):
        with self.lock, self.db:
            self._expire()
            if ack is not None:
                self.db.execute("UPDATE commands SET status=? WHERE id=? AND status='delivered'",
                                (ack["status"], ack["id"]))
            row = self.db.execute("SELECT id,payload,created,expires FROM commands WHERE status='queued' ORDER BY created,rowid LIMIT 1").fetchone()
            if row is None:
                return {"ok": True}
            self.db.execute("UPDATE commands SET status='delivered' WHERE id=?", (row[0],))
            return {"ok": True, "command": {"id": row[0], **json.loads(row[1]), "created_at": row[2], "expires_at": row[3]}}
