"""Atlas owner-stop policy tests: explicit user stop != idle or quota pause."""

from pathlib import Path
from contextlib import closing, contextmanager
import json
import sqlite3
import tempfile
import unittest
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "web"))

import atlas_guard
import power_safety
from test_command_channel import server


@contextmanager
def writable_database(path):
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            yield connection



class AtlasStopClassificationTests(unittest.TestCase):
    owner = json.dumps({
        "before": "RUN", "after": "STOP",
        "reason": atlas_guard.EXPLICIT_STOP_REASON,
    })

    def check(self, mode="RUN", event=None, in_flight=0, legacy=0,
              running_packages=0, ready_packages=0):
        return atlas_guard.classify_snapshot(
            mode, event, in_flight, legacy, running_packages, ready_packages,
        )

    def test_idle_when_scheduler_run_must_still_block(self):
        for ready in (0,1,150):
            result=self.check(ready_packages=ready)
            self.assertEqual(result["status"],"armed_idle")
            self.assertTrue(result["dispatch_armed"])
            self.assertFalse(result["owner_stop_verified"])
            self.assertFalse(result["codex_user_stop_verified"])
            self.assertFalse(result["atlas_power_gate_clear"])

    def test_actual_running_attempts(self):
        for current,legacy,packages in ((1,0,0),(0,1,0),(0,0,1)):
            result=self.check(in_flight=current,legacy=legacy,running_packages=packages)
            self.assertEqual(result["status"],"running")
            self.assertFalse(result["atlas_power_gate_clear"])

    def test_user_stop_with_inflight_requires_drain(self):
        current=self.check("STOP",self.owner,in_flight=2)
        self.assertEqual(current["status"],"owner_stop_draining")
        self.assertTrue(current["owner_stop_verified"])
        self.assertEqual(current["inflight_attempts"],2)
        self.assertFalse(current["atlas_power_gate_clear"])

    def test_explicit_owner_stop_with_zero_attempts_not_power_approval(self):
        result=self.check("STOP",self.owner,ready_packages=125)
        self.assertEqual(result["status"],"owner_stop_no_active_attempts")
        self.assertTrue(result["owner_stop_verified"])
        self.assertFalse(result["dispatch_armed"])
        self.assertEqual(result["ready_packages"],125)
        self.assertFalse(result["codex_user_stop_verified"])
        self.assertFalse(result["atlas_power_gate_clear"])

    def test_unverified_stop_never_counts_as_human_codex_stop(self):
        events=(None, "{}", '{"after":"STOP"}',
                '{"after":"STOP","reason":"QUOTA_LIMIT"}',
                '{"after":"STOP","reason":"Automatic completion"}',
                '{"after":"STOP","reason":"Explicit owner stop requested","after":"STOP"}',
                '{"after":"RUN","reason":"Explicit owner stop requested"}')
        for event in events:
            with self.subTest(event=event):
                result=self.check("STOP",event)
                self.assertEqual(result["status"],"unverified_stop")
                self.assertFalse(result["owner_stop_verified"])
                self.assertFalse(result["codex_user_stop_verified"])

    def test_restart_after_manual_stop_rearms_scheduler(self):
        result=self.check("RUN",self.owner,ready_packages=0)
        self.assertEqual(result["status"],"armed_idle")
        self.assertTrue(result["dispatch_armed"])
        self.assertFalse(result["owner_stop_verified"])

    def test_missing_corrupt_counts_fail_closed(self):
        for count in (None,-1,1.4,"0",True,100001):
            with self.subTest(count=count):
                self.assertEqual(
                    self.check(in_flight=count)["status"],"unavailable"
                )
        self.assertEqual(self.check(mode="PAUSED")["status"],"unavailable")


class AtlasReadOnlyDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path=Path(self.directory.name)/"roadmap.sqlite"
        with writable_database(self.path) as db:
            db.executescript("""
                CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE events(seq INTEGER PRIMARY KEY, kind TEXT, details TEXT);
                CREATE TABLE attempts(id TEXT, state TEXT);
                CREATE TABLE legacy_atomicity_attempts(id TEXT, state TEXT);
                CREATE TABLE packages(id TEXT, state TEXT);
                INSERT INTO meta VALUES ('mode','RUN');
                INSERT INTO packages VALUES ('pkg-one','READY');
                INSERT INTO attempts VALUES ('old','COMPLETE');
            """)
        self.original=self.path.read_bytes()

    def test_read_only_run_with_zero_active_and_ready_queue(self):
        report=atlas_guard.read_atlas_dispatch_state(self.path)
        self.assertEqual(report["status"],"armed_idle")
        self.assertEqual(report["ready_packages"],1)
        self.assertEqual(report["inflight_attempts"],0)
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_explicit_owner_stop_event_required_from_database(self):
        with writable_database(self.path) as db:
            db.execute("UPDATE meta SET value='STOP' WHERE key='mode'")
        self.assertEqual(atlas_guard.read_atlas_dispatch_state(self.path)["status"],"unverified_stop")
        with writable_database(self.path) as db:
            db.execute(
                "INSERT INTO events VALUES (1,'owner_mode',?)",
                (AtlasStopClassificationTests.owner,),
            )
        state=atlas_guard.read_atlas_dispatch_state(self.path)
        self.assertEqual(state["status"],"owner_stop_no_active_attempts")
        self.assertTrue(state["owner_stop_verified"])
        with writable_database(self.path) as db:
            db.execute("INSERT INTO attempts VALUES ('current','RUNNING')")
        self.assertEqual(atlas_guard.read_atlas_dispatch_state(self.path)["status"],"owner_stop_draining")

    def test_last_owner_control_event_wins(self):
        with writable_database(self.path) as db:
            db.execute("UPDATE meta SET value='STOP' WHERE key='mode'")
            db.execute(
                "INSERT INTO events VALUES (1,'owner_mode',?)",
                (AtlasStopClassificationTests.owner,),
            )
            db.execute(
                "INSERT INTO events VALUES (2,'owner_mode',?)",
                (json.dumps({"after":"RUN","reason":"Owner resumed"}),),
            )
        self.assertEqual(atlas_guard.read_atlas_dispatch_state(self.path)["status"],"unverified_stop")

    def test_missing_database_and_symlink_fail_closed(self):
        missing=Path(self.directory.name)/"missing.sqlite"
        self.assertEqual(atlas_guard.read_atlas_dispatch_state(missing)["status"],"unavailable")
        link=Path(self.directory.name)/"link.sqlite"
        link.symlink_to(self.path)
        self.assertEqual(atlas_guard.read_atlas_dispatch_state(link)["status"],"unavailable")

    def test_unsettled_new_states_are_conservatively_inflight(self):
        with writable_database(self.path) as db:
            db.execute("UPDATE meta SET value='STOP' WHERE key='mode'")
            db.execute("INSERT INTO events VALUES (1,'owner_mode',?)",(AtlasStopClassificationTests.owner,))
            db.execute("INSERT INTO legacy_atomicity_attempts VALUES ('a','FINALIZING')")
        state=atlas_guard.read_atlas_dispatch_state(self.path)
        self.assertEqual(state["status"],"owner_stop_draining")
        self.assertEqual(state["inflight_attempts"],1)


class AtlasPowerSafetyIntegrationTests(unittest.TestCase):
    def test_atlas_service_running_and_idle_mode_run_is_blocked(self):
        evidence=atlas_guard.classify_snapshot("RUN",None,0,0,0,0)
        with mock.patch.object(power_safety,"read_atlas_dispatch_state",return_value=evidence),\
             mock.patch.object(power_safety,"read_command",return_value=None):
            result=power_safety.collect_power_safety()
        self.assertFalse(result["safe_to_request"])
        self.assertEqual(result["atlas_control"]["status"],"armed_idle")
        self.assertIn("can start new Codex tasks", " ".join(result["blocked_reasons"]))
        self.assertNotIn("owner_stopped",result["atlas_control"]["status"])

    def test_verified_stop_no_attempts_does_not_clear_codex_or_desktop_gates(self):
        evidence=atlas_guard.classify_snapshot(
            "STOP", AtlasStopClassificationTests.owner, 0,0,0,75
        )
        with mock.patch.object(power_safety,"read_atlas_dispatch_state",return_value=evidence),\
             mock.patch.object(power_safety,"read_command",return_value=None):
            state=power_safety.collect_power_safety()
        self.assertFalse(state["safe_to_request"])
        self.assertTrue(state["atlas_control"]["owner_stop_verified"])
        self.assertFalse(state["atlas_control"]["codex_user_stop_verified"])
        self.assertIn("not yet independently verified", " ".join(state["blocked_reasons"]))

    def test_pi_never_exposes_claimed_unverified_worker_ack(self):
        valid=atlas_guard.classify_snapshot("RUN",None,0,0,0,0)
        valid["private_path"]="/secret/data"
        result=server.safe_atlas_control_summary(valid)
        self.assertEqual(result["status"],"armed_idle")
        self.assertFalse(result["codex_user_stop_verified"])
        self.assertNotIn("private_path",result)
        forged={**valid,"codex_user_stop_verified":True,"atlas_power_gate_clear":True}
        rejected=server.safe_atlas_control_summary(forged)
        self.assertEqual(rejected["status"],"unavailable")
        self.assertFalse(rejected["atlas_power_gate_clear"])


if __name__=="__main__":
    unittest.main()
