"""Atlas per-Codex owner stop verification against synthetic, disposable DBs.

No tests modify the user's real Atlas, launch a model, stop an agent or power
off Ubuntu. The future Atlas producer is NOT deployed by these tests.
"""
from contextlib import closing, contextmanager
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"agent"))
sys.path.insert(0, str(ROOT/"web"))
from codex_stop_attestation import (
    verify_codex_stop, _roster, _event_is_exact_owner_stop, _empty,
)
from atlas_guard import read_atlas_dispatch_state
from test_command_channel import server

GEN = "1234567890abcdef1234567890abcdef"
BOOT = "12345678-1234-1234-1234-1234567890ab"
ACCOUNTS = {"primary": "architect", "secondary": "validator", "codex3": "auditor"}


@contextmanager
def dbwrite(path):
    with closing(sqlite3.connect(path)) as c:
        with c:
            yield c


class StopReceiptFixtures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root/"roadmap.sqlite"
        self.policy = self.root/"policy.json"
        self.boot = self.root/"boot_id"
        self.boot.write_text(BOOT+"\n")
        self.policy.write_text(json.dumps({
            "agents": {role: {"account": account} for role,account in ACCOUNTS.items()},
            "permanent_role_roster": {"enabled": True},
            "parallel_final_auditor": {"enabled": False}
        }))
        self.now = time.time()
        with dbwrite(self.db) as c:
            c.executescript("""
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE events (seq INTEGER PRIMARY KEY, kind TEXT, created REAL, details TEXT);
            CREATE TABLE attempts(id TEXT, state TEXT);
            CREATE TABLE legacy_atomicity_attempts(id TEXT, state TEXT);
            CREATE TABLE packages(id TEXT, state TEXT);
            CREATE TABLE codex_owner_stop_control (
              id INTEGER PRIMARY KEY, generation TEXT, state TEXT, event_seq INTEGER,
              dispatch_barrier_active INTEGER, barrier_checked_at REAL, roster_sha256 TEXT,
              active_worker_processes INTEGER, all_lanes_drained INTEGER, boot_id TEXT
            );
            CREATE TABLE codex_owner_stop_acks (
              role TEXT PRIMARY KEY, account TEXT, state TEXT,
              generation TEXT, acknowledged_at REAL
            );
            INSERT INTO meta VALUES('mode','RUN');
            INSERT INTO packages VALUES('p1','READY');
            """)
            proof = {"generation":GEN,"initiator":"interactive_owner",
                     "confirmed":True,"action":"stop_all_codex_workers"}
            c.execute("INSERT INTO events VALUES(?,?,?,?)",(
                10,"codex_owner_stop_request",self.now-2,json.dumps(proof)))
            digest = _roster(self.policy)[1]
            c.execute("INSERT INTO codex_owner_stop_control VALUES(1,?,?,?,?,?,?,?,?,?)",(
                GEN,"STOPPED",10,1,self.now-1,digest,0,1,BOOT))
            for role, account in ACCOUNTS.items():
                c.execute("INSERT INTO codex_owner_stop_acks VALUES(?,?,?,?,?)",
                          (role,account,"STOPPED",GEN,self.now-1))

    def read(self):
        with closing(sqlite3.connect("file:"+str(self.db)+"?mode=ro",uri=True)) as c:
            c.execute("PRAGMA query_only=ON")
            return verify_codex_stop(
                c,mode="RUN",in_flight_attempts=0,running_packages=0,
                policy_path=self.policy,now=self.now,boot_id_path=self.boot
            )

    def test_strict_verified_stop_requires_three_distinct_receipts(self):
        result=self.read()
        self.assertEqual(result["status"],"verified")
        self.assertEqual(result["expected_workers"],3)
        self.assertEqual(result["acknowledged_workers"],3)
        self.assertTrue(result["dispatch_frozen"])
        self.assertFalse("account" in json.dumps(result))
        self.assertFalse("architect" in json.dumps(result))
        self.assertFalse("validator" in json.dumps(result))
        self.assertNotIn(GEN,json.dumps(result))

    def test_verified_proof_frees_only_atlas_gate_in_single_db_snapshot(self):
        # For this integration test, use the real host boot ID in the fake
        # receipt; the reader still never writes to the actual Atlas DB.
        real_boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        with dbwrite(self.db) as c:
            c.execute("UPDATE codex_owner_stop_control SET boot_id=?",(real_boot,))
        original=self.db.read_bytes()
        result=read_atlas_dispatch_state(self.db,policy_path=self.policy)
        self.assertEqual(result["scheduler_mode"],"RUN")
        self.assertEqual(result["status"],"armed_idle")
        self.assertTrue(result["dispatch_armed"])
        self.assertTrue(result["codex_user_stop_verified"])
        self.assertTrue(result["atlas_power_gate_clear"])
        self.assertTrue(result["codex_stop"]["dispatch_frozen"])
        self.assertEqual(self.db.read_bytes(),original)
        pi=server.safe_atlas_control_summary(result)
        self.assertTrue(pi["codex_user_stop_verified"])
        self.assertTrue(pi["atlas_power_gate_clear"])
        self.assertNotIn("architect",json.dumps(pi))

    def test_existing_atlas_without_tables_is_unsupported_not_idle(self):
        with dbwrite(self.db) as c:
            c.execute("DROP TABLE codex_owner_stop_control")
            c.execute("DROP TABLE codex_owner_stop_acks")
        r=read_atlas_dispatch_state(self.db,policy_path=self.policy)
        self.assertEqual(r["codex_stop"]["status"],"unsupported")
        self.assertFalse(r["atlas_power_gate_clear"])
        self.assertFalse(r["codex_user_stop_verified"])

    def test_incomplete_tables_fail_closed(self):
        with dbwrite(self.db) as c:
            c.execute("DROP TABLE codex_owner_stop_acks")
        self.assertEqual(self.read()["status"],"invalid")

    def test_missing_or_resumed_receipt_never_qualifies(self):
        with dbwrite(self.db) as c:
            c.execute("UPDATE codex_owner_stop_control SET state='RESUMED'")
        self.assertEqual(self.read()["status"],"resumed")
        with dbwrite(self.db) as c:
            c.execute("DELETE FROM codex_owner_stop_control")
        self.assertEqual(self.read()["status"],"not_requested")

    def test_quota_idle_or_missing_one_ack_do_not_verify_user_stop(self):
        with dbwrite(self.db) as c:
            c.execute("DELETE FROM codex_owner_stop_acks WHERE role='secondary'")
        result=self.read()
        self.assertEqual(result["status"],"draining")
        self.assertEqual(result["expected_workers"],3)
        self.assertFalse(server.safe_atlas_control_summary(
            {**read_atlas_dispatch_state(self.db,policy_path=self.policy),
             "codex_user_stop_verified": True,
             "atlas_power_gate_clear": True})["codex_user_stop_verified"])

    def test_owner_event_provenance_requires_explicit_interactive_action(self):
        for changes in (
            {"initiator":"quota_recovery"}, {"confirmed":False},
            {"action":"automatic_stop"}, {"generation":"0"*32}
        ):
            event={"generation":GEN,"initiator":"interactive_owner",
                   "confirmed":True,"action":"stop_all_codex_workers"}
            event.update(changes)
            with dbwrite(self.db) as c:
                c.execute("UPDATE events SET details=? WHERE seq=10",(json.dumps(event),))
            self.assertEqual(self.read()["status"],"invalid",changes)
        self.assertFalse(_event_is_exact_owner_stop("{}",GEN))
        self.assertFalse(_event_is_exact_owner_stop(
            '{"generation":"%s","confirmed":true,"confirmed":true}'%GEN,GEN))

    def test_newer_owner_resume_invalidates_old_receipt(self):
        with dbwrite(self.db) as c:
            c.execute("INSERT INTO events VALUES(11,'codex_owner_resume',?,'{}')",(self.now,))
        self.assertEqual(self.read()["status"],"invalid")
        with dbwrite(self.db) as c:
            c.execute("DELETE FROM events WHERE seq=11")
            c.execute("INSERT INTO events VALUES(11,'owner_mode',?,'{}')",(self.now,))
        self.assertEqual(self.read()["status"],"invalid")

    def test_stale_or_future_heartbeat_and_worker_ack_never_pass(self):
        with dbwrite(self.db) as c:
            c.execute("UPDATE codex_owner_stop_control SET barrier_checked_at=?",(self.now-16,))
        self.assertEqual(self.read()["status"],"stale")
        with dbwrite(self.db) as c:
            c.execute("UPDATE codex_owner_stop_control SET barrier_checked_at=?",(self.now+5,))
        self.assertEqual(self.read()["status"],"stale")
        with dbwrite(self.db) as c:
            c.execute("UPDATE codex_owner_stop_control SET barrier_checked_at=?",(self.now-1,))
            c.execute("UPDATE codex_owner_stop_acks SET acknowledged_at=? WHERE role='primary'",(self.now-16,))
        self.assertEqual(self.read()["status"],"invalid")

    def test_barrier_or_worker_drain_unverified(self):
        for field,value in (("dispatch_barrier_active",0),("active_worker_processes",1),
                            ("all_lanes_drained",0)):
            with dbwrite(self.db) as c:
                c.execute("UPDATE codex_owner_stop_control SET "+field+"=?",(value,))
            self.assertEqual(self.read()["status"],"draining")
            with dbwrite(self.db) as c:
                c.execute("UPDATE codex_owner_stop_control SET "+field+"=?",(1 if field!="active_worker_processes" else 0,))

    def test_running_task_cannot_be_overridden_by_stop_receipt(self):
        with closing(sqlite3.connect("file:"+str(self.db)+"?mode=ro",uri=True)) as c:
            self.assertEqual(verify_codex_stop(
                c,mode="RUN",in_flight_attempts=1,running_packages=0,
                policy_path=self.policy,now=self.now,boot_id_path=self.boot)["status"],"draining")
            self.assertEqual(verify_codex_stop(
                c,mode="RUN",in_flight_attempts=0,running_packages=1,
                policy_path=self.policy,now=self.now,boot_id_path=self.boot)["status"],"draining")

    def test_boot_id_mismatch_rejects_reboot_replay(self):
        with dbwrite(self.db) as c:
            c.execute("UPDATE codex_owner_stop_control SET boot_id='00000000-0000-0000-0000-000000000000'")
        self.assertEqual(self.read()["status"],"invalid")
        self.boot.write_text("not-a-real-uuid")
        self.assertEqual(self.read()["status"],"unavailable")

    def test_policy_roster_must_match_exact_signed_identity_set(self):
        with dbwrite(self.db) as c:
            c.execute("UPDATE codex_owner_stop_acks SET account='attacker' WHERE role='primary'")
        self.assertEqual(self.read()["status"],"invalid")
        with dbwrite(self.db) as c:
            c.execute("UPDATE codex_owner_stop_acks SET account='architect' WHERE role='primary'")
            c.execute("UPDATE codex_owner_stop_control SET roster_sha256='0'")
        self.assertEqual(self.read()["status"],"invalid")

    def test_extra_acked_account_is_not_ignored(self):
        with dbwrite(self.db) as c:
            c.execute("INSERT INTO codex_owner_stop_acks VALUES(?,?,?,?,?)",
                      ("fake-extra","fake","STOPPED",GEN,self.now))
        self.assertEqual(self.read()["status"],"invalid")

    def test_private_hub_recomputes_lease_age_after_signed_report(self):
        from atlas_guard import classify_snapshot
        valid = classify_snapshot("RUN", None, 0, 0, 0, 0)
        valid.update({
            "codex_user_stop_verified": True,
            "atlas_power_gate_clear": True,
            "codex_stop": {"status": "verified", "expected_workers": 3,
                           "acknowledged_workers": 3, "dispatch_frozen": True,
                           "evidence_age_seconds": 1.0},
        })
        now = time.time()
        def case(report_age):
            safety = {
                "checked_at": datetime.fromtimestamp(now-report_age, timezone.utc).isoformat(),
                "safe_to_request": False, "atlas_state": "active",
                "inhibitors": {"shutdown_block": False, "session_block": False,
                               "shutdown_delay": False, "unknown": False},
                "workload_categories": [], "unknowns": [],
                "blocked_reasons": ["Unsaved desktop work unverified"], "warnings": [],
                "atlas_control": valid,
            }
            fake = {"control_agent":"online","metrics":{"power_safety":safety}}
            with mock.patch.object(server.BROKER,"desktop_state",return_value=fake),\
                 mock.patch.object(server.time,"time",return_value=now):
                return server.power_safety()
        fresh = case(2)
        self.assertEqual(fresh["status"], "fresh")
        self.assertTrue(fresh["atlas_control"]["codex_user_stop_verified"])
        self.assertFalse(fresh["safe_to_request"])
        expired = case(20)
        self.assertEqual(expired["status"], "fresh")
        self.assertFalse(expired["atlas_control"]["codex_user_stop_verified"])
        self.assertFalse(expired["atlas_control"]["atlas_power_gate_clear"])
        self.assertEqual(expired["atlas_control"]["codex_stop"]["status"], "stale")
        self.assertTrue(any("expired" in item for item in expired["blocked_reasons"]))

    def test_no_actual_stop_operations_exist_in_verifier(self):
        source=(ROOT/"agent/codex_stop_attestation.py").read_text()
        for forbidden in ("subprocess.run(","subprocess.Popen(","owner-stop --confirm",
                          "systemctl stop","os.kill(","INSERT INTO","UPDATE codex_owner_stop"):
            self.assertNotIn(forbidden,source)


if __name__=="__main__":
    unittest.main()
