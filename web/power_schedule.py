"""Durable, cancelable Raspberry Pi power scheduling; no local power calls.

The owner arms a timer, receives a 30-second minimum grace period and may
cancel until an Ubuntu Agent report reaches the deadline. At-most-once dispatch
uses the existing signed outbound Agent command queue. No overdue timer can
replay after a long Pi outage or an Ubuntu offline period.
"""

import os
from contextlib import closing
from pathlib import Path
import secrets
import sqlite3
import threading
import time


class PowerSchedule:
    def __init__(self,path):
        self.path=Path(path)
        self.lock=threading.RLock()

    def _connect(self):
        self.path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        os.fchmod(fd,0o600)
        os.close(fd)
        db=sqlite3.connect(self.path,timeout=4,isolation_level=None)
        db.execute("""CREATE TABLE IF NOT EXISTS power_schedule (
            slot INTEGER PRIMARY KEY CHECK(slot=1),
            token TEXT NOT NULL,action TEXT NOT NULL,created INTEGER NOT NULL,
            deadline INTEGER NOT NULL,state TEXT NOT NULL,detail TEXT
        )""")
        return db

    def _expire(self,db,now):
        # A failed readiness probe at the exact timer boundary must not
        # irreversibly reject a request while fresh signed telemetry is about
        # to arrive (default Agent interval: 10 seconds). Keep a strictly
        # bounded 30-second verification grace, then fail closed.
        db.execute("UPDATE power_schedule SET state='blocked',detail="
                   "'Fresh Ubuntu safety could not be confirmed within the 30-second final verification window' "
                   "WHERE state='armed' AND deadline<?",(now-30,))
        # Delivery does not prove the machine actually powered off. After
        # a bounded observation window, expose the unverified outcome and
        # release the UI lock for an independent future owner request.
        db.execute("UPDATE power_schedule SET state='completed_unverified',detail="
                   "'Power request was dispatched; verify device state separately' "
                   "WHERE state='sent' AND deadline<?",(now-120,))

    def _status(self,db,now):
        self._expire(db,now)
        row=db.execute("SELECT token,action,created,deadline,state,detail "
                       "FROM power_schedule WHERE slot=1").fetchone()
        return {
            "schedule_id":row[0] if row else None,
            "state":row[4] if row else "absent",
            "action":row[1] if row else None,
            "created_at":row[2] if row else None,
            "deadline":row[3] if row else None,
            "remaining_seconds":max(0,row[3]-now) if row and row[4]=="armed" else 0,
            "can_cancel":bool(row and row[4]=="armed"),
            "detail":row[5] if row else None,
            "will_execute_if_safe":bool(row and row[4]=="armed"),
            "server_time":now,
        }

    def status(self):
        with self.lock, closing(self._connect()) as db, db:
            return self._status(db,int(time.time()))

    def arm(self,payload):
        if (not isinstance(payload,dict) or set(payload)!=
                {"action","delay_minutes","ack_unsaved_loss","confirm"}):
            raise ValueError("Unexpected power request fields")
        if (payload["action"] not in ("shutdown","restart")
                or type(payload["delay_minutes"]) is not int
                or not 0<=payload["delay_minutes"]<=240
                or payload["ack_unsaved_loss"] is not True
                or payload["confirm"] is not True):
            raise ValueError("Explicit owner confirmation, explicit unsaved data-loss acceptance and valid delay required")
        now=int(time.time())
        seconds=30 if payload["delay_minutes"]==0 else payload["delay_minutes"]*60
        with self.lock, closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            self._expire(db,now)
            running=db.execute("SELECT state FROM power_schedule WHERE slot=1").fetchone()
            if running and running[0] in ("armed","dispatching","sent"):
                raise FileExistsError("An existing timer or dispatched power request is still unresolved")
            db.execute("INSERT OR REPLACE INTO power_schedule "
                       "(slot,token,action,created,deadline,state,detail) "
                       "VALUES(1,?,?,?,?,?,'Owner-confirmed and awaiting safety recheck')",
                       (secrets.token_hex(16),payload["action"],now,now+seconds,"armed"))
            return self._status(db,now)

    def cancel(self,body):
        if not isinstance(body,dict) or set(body) not in (set(),{"schedule_id"}):
            raise ValueError("Cancellation requires the observed schedule identifier")
        expected=body.get("schedule_id")
        if expected is not None and (type(expected) is not str or len(expected)!=32
                or any(ch not in "0123456789abcdef" for ch in expected)):
            raise ValueError("Invalid schedule identifier")
        with self.lock, closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            self._expire(db,int(time.time()))
            row=db.execute("SELECT state,token FROM power_schedule WHERE slot=1").fetchone()
            if row is None:
                return self._status(db,int(time.time()))
            if expected!=row[1]:
                raise FileExistsError("Timer changed; refresh before canceling")
            if row[0]=="dispatching":
                raise FileExistsError("Power command is already being dispatched")
            if row[0]=="sent":
                raise FileExistsError("Power command was already sent to Ubuntu; cannot cancel")
            db.execute("UPDATE power_schedule SET state='canceled',detail='Canceled by owner' "
                       "WHERE slot=1 AND token=? AND state='armed'",(expected,))
            return self._status(db,int(time.time()))

    def dispatch_due(self,ready,enqueue,*,definitive_block=False):
        """Called only by the Pi after a valid signed Ubuntu Agent report.

        At the deadline, a transient unready observation waits at most 30s
        for the next fresh signed report; a positive Atlas/job hard blocker
        aborts immediately. No report can dispatch past the grace deadline.
        A crash after 'dispatching' will never retry.
        """
        now=int(time.time())
        with self.lock, closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            self._expire(db,now)
            row=db.execute(
                "SELECT token,action,deadline,state FROM power_schedule WHERE slot=1"
            ).fetchone()
            if row is None or row[3]!="armed" or row[2]>now:
                return None
            if row[2] < now-30:
                return self._status(db,now)
            if ready is not True:
                if definitive_block is True:
                    db.execute("UPDATE power_schedule SET state='blocked',detail="
                               "'Atlas resumed or active work was reported; shutdown canceled' "
                               "WHERE slot=1 AND token=?",(row[0],))
                else:
                    db.execute("UPDATE power_schedule SET detail="
                               "'Waiting for fresh signed Ubuntu safety evidence (max 30 seconds after deadline)' "
                               "WHERE slot=1 AND token=?",(row[0],))
                return self._status(db,now)
            db.execute("UPDATE power_schedule SET state='dispatching',detail="
                       "'Atomic at-most-once delivery reservation' WHERE slot=1 AND token=?",
                       (row[0],))
        # Never keep an open SQLite transaction across command queue I/O.
        try:
            ident=enqueue({
                "action":"power.shutdown" if row[1]=="shutdown" else "power.restart",
                "value":None, "confirm":True, "ack_unsaved_loss":True,
            })
            if not isinstance(ident,dict) or ident.get("status")!="queued":
                raise ValueError("Signed Ubuntu dispatch was not queued")
        except (OSError,ValueError,OverflowError,sqlite3.Error):
            with self.lock, closing(self._connect()) as db, db:
                db.execute("UPDATE power_schedule SET state='blocked',detail="
                           "'Unable to enqueue safely; will not retry' "
                           "WHERE slot=1 AND state='dispatching' AND token=?",(row[0],))
            return self.status()
        with self.lock, closing(self._connect()) as db, db:
            db.execute("UPDATE power_schedule SET state='sent',detail="
                       "'Sent through signed Ubuntu channel; awaiting power transition' "
                       "WHERE slot=1 AND state='dispatching' AND token=?",(row[0],))
        return self.status()
