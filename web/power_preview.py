"""Durable simulation only. No command transport or execution dependencies."""
import os
from pathlib import Path
import sqlite3
import time


class PreviewStore:
    def __init__(self, path):
        # Construction/import does not create files. Open only on an authorized request.
        self.path = Path(path)

    def _connect(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.fchmod(fd, 0o600)
        os.close(fd)
        db = sqlite3.connect(self.path, timeout=3)
        db.execute("CREATE TABLE IF NOT EXISTS preview (id INTEGER PRIMARY KEY CHECK(id=1), action TEXT, created INTEGER, deadline INTEGER, state TEXT)")
        db.commit()
        return db

    def _operate(self, operation, payload=None):
        db = self._connect()
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                now = int(time.time())  # UTC epoch; lazy expiry, including after a hub restart.
                db.execute("UPDATE preview SET state='elapsed' WHERE state='draft' AND deadline<=?", (now,))
                row = db.execute("SELECT action,created,deadline,state FROM preview WHERE id=1").fetchone()
                if operation == "create":
                    if row and row[3] == "draft":
                        raise FileExistsError("Cancel the existing preview first")
                    db.execute("INSERT OR REPLACE INTO preview VALUES (1,?,?,?,'draft')",
                               (payload["action"], now, now + payload["delay_minutes"] * 60))
                elif operation == "cancel":
                    db.execute("UPDATE preview SET state='canceled' WHERE state='draft'")
                row = db.execute("SELECT action,created,deadline,state FROM preview WHERE id=1").fetchone()
                return {"preview_only": True, "will_execute": False,
                        "message": "Simulation only — no power action will be performed.",
                        "state": row[3] if row else "absent", "action": row[0] if row else None,
                        "created_at": row[1] if row else None, "expires_at": row[2] if row else None,
                        "remaining_seconds": max(0, row[2] - now) if row and row[3] == "draft" else 0,
                        "server_time": now}
        finally:
            db.close()

    def get(self):
        return self._operate("get")

    def create(self, payload):
        if (not isinstance(payload, dict) or set(payload) != {"action", "delay_minutes"}
                or type(payload["action"]) is not str or payload["action"] not in {"shutdown", "restart"}
                or type(payload["delay_minutes"]) is not int or not 1 <= payload["delay_minutes"] <= 240):
            raise ValueError("Use shutdown/restart and an integer delay from 1 to 240 minutes")
        return self._operate("create", payload)

    def cancel(self, payload):
        if payload != {}:
            raise ValueError("Cancellation requires an empty object")
        return self._operate("cancel")
