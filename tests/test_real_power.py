"""Non-destructive real-power controls: ONLY fake SQLite and mocked power calls.

NEVER invoke real poweroff, reboot, root execute or actual Wake-on-LAN here.
"""

from contextlib import closing
from pathlib import Path
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"agent"))
sys.path.insert(0,str(ROOT/"web"))
import power_gate
import power_execute
import power_schedule
from command_executor import valid_command
from command_queue import CommandQueue,validate_action
from test_command_channel import server



class PowerGateTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path=Path(self.directory.name)/"atlas.sqlite"
        with closing(sqlite3.connect(self.path)) as c, c:
            c.executescript("""
            CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
            INSERT INTO meta VALUES('mode','STOP');
            CREATE TABLE events(seq INTEGER PRIMARY KEY,kind TEXT,details TEXT);
            CREATE TABLE owner_agent_dispatch_switches(role TEXT PRIMARY KEY,enabled INTEGER);
            CREATE TABLE attempts(state TEXT);
            CREATE TABLE legacy_atomicity_attempts(state TEXT);
            CREATE TABLE validator_api_runs(state TEXT);
            CREATE TABLE validator_api_continuations(state TEXT);
            CREATE TABLE packages(state TEXT);
            """)
            c.execute("INSERT INTO events VALUES(5,'owner_mode',?)",(
                json.dumps({"before":"RUN","after":"STOP","reason":power_gate.OWNER_STOP_REASON}),))
            for number,role in enumerate(sorted(power_gate.AGENTS)):
                c.execute("INSERT INTO owner_agent_dispatch_switches VALUES(?,0)",(role,))
                c.execute("INSERT INTO events VALUES(?,'owner_agent_stop_requested',?)",(
                    number+1,json.dumps({"role":role,"by":"interactive_owner","enabled":False})))

    def inspect(self):
        return power_gate.inspect_atlas(self.path)

    def change(self,sql,params=()):
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute(sql,params)

    def test_manual_owner_stop_plus_three_off_is_distinct_from_idle(self):
        good=self.inspect()
        self.assertTrue(good["atlas_owner_paused"])
        self.assertEqual(good["codex_owner_paused_count"],3)
        self.assertEqual(good["active_jobs"],0)
        self.assertEqual(good["errors"],[])
        self.change("UPDATE meta SET value='RUN' WHERE key='mode'")
        self.assertIn("STOP", " ".join(self.inspect()["errors"]))
        self.change("UPDATE meta SET value='STOP' WHERE key='mode'")
        self.change("UPDATE owner_agent_dispatch_switches SET enabled=1 WHERE role='primary'")
        self.assertTrue(self.inspect()["errors"])
        self.assertNotEqual(self.inspect()["codex_owner_paused_count"],3)

    def test_stopped_without_provenance_not_sufficient(self):
        self.change("DELETE FROM events WHERE kind='owner_agent_stop_requested'")
        self.assertTrue(self.inspect()["errors"])
        self.change("INSERT INTO events VALUES(6,'owner_agent_resume',?)",(
            json.dumps({"role":"primary","by":"interactive_owner","enabled":True}),))
        self.assertTrue(self.inspect()["errors"])

    def test_pending_api_legacy_and_publication_block(self):
        for table in ("attempts","legacy_atomicity_attempts","validator_api_runs",
                      "validator_api_continuations","packages"):
            self.change("INSERT INTO "+table+" VALUES('RUNNING')")
            self.assertGreater(self.inspect()["active_jobs"],0)
            self.change("DELETE FROM "+table)

    def test_root_and_agent_gate_blocks_unknown_cpuwm_or_process(self):
        with mock.patch.object(power_gate,"inspect_atlas",return_value=self.inspect()),\
             mock.patch.object(power_gate,"inspect_cpuwm",return_value=True),\
             mock.patch.object(power_gate,"inspect_processes",return_value=(True,False)):
            state=power_gate.inspect_power()
            self.assertTrue(state["eligible"])
            self.assertEqual(state["codex_owner_paused_count"],3)
        with mock.patch.object(power_gate,"inspect_atlas",return_value=self.inspect()),\
             mock.patch.object(power_gate,"inspect_cpuwm",return_value=False),\
             mock.patch.object(power_gate,"inspect_processes",return_value=(True,False)):
            self.assertFalse(power_gate.inspect_power()["eligible"])
        with mock.patch.object(power_gate,"inspect_atlas",return_value=self.inspect()),\
             mock.patch.object(power_gate,"inspect_cpuwm",return_value=True),\
             mock.patch.object(power_gate,"inspect_processes",return_value=(True,True)):
            self.assertFalse(power_gate.inspect_power()["eligible"])


class PowerScheduleTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path=Path(self.directory.name)/"timer.sqlite"
        self.timer=power_schedule.PowerSchedule(self.path)
        self.arm={"action":"shutdown","delay_minutes":0,
                  "confirm":True,"ack_unsaved_loss":True}

    def test_real_arm_has_30_second_grace_cancel_and_persistence(self):
        state=self.timer.arm(self.arm)
        self.assertEqual(state["state"],"armed")
        self.assertEqual(state["deadline"]-state["created_at"],30)
        self.assertTrue(state["can_cancel"])
        new=power_schedule.PowerSchedule(self.path)
        self.assertEqual(new.status()["state"],"armed")
        self.assertEqual(new.cancel({})["state"],"canceled")
        with mock.patch.object(new,"_connect",wraps=new._connect):
            dispatch=mock.Mock()
            self.assertIsNone(new.dispatch_due(True,dispatch))
            dispatch.assert_not_called()

    def test_unsafe_or_malformed_arm_rejected(self):
        for extra in (
            dict(self.arm,action="install"),
            dict(self.arm,confirm=False),
            dict(self.arm,ack_unsaved_loss=False),
            dict(self.arm,delay_minutes=-1),
            dict(self.arm,delay_minutes=241),
            dict(self.arm,delay_minutes=True),
            {"action":"shutdown"},
        ):
            with self.subTest(extra=extra),self.assertRaises(ValueError):
                self.timer.arm(extra)
        self.assertEqual(self.timer.status()["state"],"absent")

    def test_atomic_due_delivery_is_one_shot_only(self):
        created=self.timer.arm(self.arm)
        deliver=mock.Mock(return_value={"id":"a"*32,"status":"queued"})
        with mock.patch.object(power_schedule.time,"time",return_value=created["deadline"]):
            first=self.timer.dispatch_due(True,deliver)
            self.assertEqual(first["state"],"sent")
            second=self.timer.dispatch_due(True,deliver)
            self.assertIsNone(second)
        deliver.assert_called_once()
        payload=deliver.call_args.args[0]
        self.assertEqual(payload["action"],"power.shutdown")
        self.assertIs(payload["ack_unsaved_loss"],True)
        with self.assertRaises(FileExistsError):
            self.timer.cancel({})

    def test_due_without_fresh_safety_fails_closed(self):
        created=self.timer.arm(self.arm)
        send=mock.Mock()
        with mock.patch.object(power_schedule.time,"time",return_value=created["deadline"]):
            result=self.timer.dispatch_due(False,send)
        self.assertEqual(result["state"],"blocked")
        send.assert_not_called()

    def test_expired_timer_cannot_execute_after_long_disconnection(self):
        created=self.timer.arm(self.arm)
        send=mock.Mock()
        with mock.patch.object(power_schedule.time,"time",return_value=created["deadline"]+31):
            result=self.timer.dispatch_due(True,send)
        self.assertIsNone(result)
        self.assertEqual(self.timer.status()["state"],"expired")
        send.assert_not_called()

    def test_queue_error_does_not_retry(self):
        created=self.timer.arm(self.arm)
        send=mock.Mock(side_effect=OverflowError)
        with mock.patch.object(power_schedule.time,"time",return_value=created["deadline"]):
            first=self.timer.dispatch_due(True,send)
            second=self.timer.dispatch_due(True,send)
        self.assertEqual(first["state"],"blocked")
        self.assertIsNone(second)
        send.assert_called_once()


class UnsavedDataPolicyTests(unittest.TestCase):
    def test_power_card_does_not_require_saved_files(self):
        html=(ROOT/"web/static/index.html").read_text(encoding="utf-8")
        js=(ROOT/"web/static/power-live.js").read_text(encoding="utf-8")
        self.assertIn('id="live-power-loss-accepted"',html)
        self.assertIn("even if documents, browser tabs or terminal work are not saved",html)
        self.assertIn("permanently lost",html)
        self.assertNotIn('id="live-power-saved"',html)
        self.assertNotIn("I saved my documents",html)
        self.assertIn("DATA LOSS WARNING",js)
        self.assertIn("You may proceed WITHOUT saving",js)
        self.assertIn('ack_unsaved_loss:true',js)
        self.assertNotIn("ack_saved_work",js)
        self.assertIn('confirmText:"Confirm "',js)

    def test_unsaved_browser_or_editor_does_not_bypass_atlas_guard(self):
        # Documents are not a blocking power gate; ongoing Atlas work IS.
        trusted={
            "atlas_owner_paused":True, "codex_owner_paused_count":3,
            "active_jobs":0,"errors":[],
        }
        with mock.patch.object(power_gate,"inspect_atlas",return_value=trusted),             mock.patch.object(power_gate,"inspect_cpuwm",return_value=True),             mock.patch.object(power_gate,"inspect_processes",return_value=(True,False)):
            self.assertTrue(power_gate.inspect_power()["eligible"])
        with mock.patch.object(power_gate,"inspect_atlas",return_value={
                **trusted,"atlas_owner_paused":False}),             mock.patch.object(power_gate,"inspect_cpuwm",return_value=True),             mock.patch.object(power_gate,"inspect_processes",return_value=(True,False)):
            self.assertFalse(power_gate.inspect_power()["eligible"])

    def test_old_saved_work_key_cannot_authorize_power(self):
        now=int(time.time())
        payload={"id":"a"*32,"action":"power.shutdown","value":None,
                 "created_at":now,"expires_at":now+45,"confirm":True,
                 "ack_saved_work":True}
        self.assertFalse(valid_command(payload))
        payload["ack_unsaved_loss"]=payload.pop("ack_saved_work")
        self.assertTrue(valid_command(payload))
        with tempfile.TemporaryDirectory() as path:
            schedule=power_schedule.PowerSchedule(Path(path)/"s.sqlite")
            with self.assertRaises(ValueError):
                schedule.arm({"action":"shutdown","delay_minutes":0,
                              "ack_saved_work":True,"confirm":True})
            self.assertEqual(schedule.status()["state"],"absent")


class TrustedPowerRoutingTests(unittest.TestCase):
    def test_owner_direct_commands_never_accept_power(self):
        with tempfile.TemporaryDirectory() as d:
            queue=CommandQueue(Path(d)/"commands.sqlite")
            self.addCleanup(queue.db.close)
            payload={"action":"power.shutdown","value":None,
                     "confirm":True,"ack_unsaved_loss":True}
            with self.assertRaises(ValueError):
                validate_action(payload)
            with self.assertRaises(ValueError):
                queue.enqueue(payload)
            receipt=queue.enqueue_power(payload)
            self.assertEqual(receipt["status"],"queued")
            result=queue.report_response()
            self.assertEqual(result["command"]["action"],"power.shutdown")
            self.assertIs(result["command"]["ack_unsaved_loss"],True)
            with self.assertRaises(ValueError):
                queue.enqueue_power({**payload,"ack_unsaved_loss":False})

    def test_agent_rejects_unconfirmed_or_expired_power_command(self):
        now=int(time.time())
        item={"id":"a"*32,"action":"power.shutdown","value":None,
              "created_at":now,"expires_at":now+45,
              "confirm":True,"ack_unsaved_loss":True}
        self.assertTrue(valid_command(item))
        self.assertTrue(valid_command({**item,"action":"power.restart"}))
        self.assertFalse(valid_command({**item,"ack_unsaved_loss":False}))
        self.assertFalse(valid_command({**item,"expires_at":now-1}))
        self.assertFalse(valid_command({**item,"value":"poweroff"}))

    def test_root_executor_only_allowlisted_systemd_no_force(self):
        good={"eligible":True}
        with mock.patch.object(power_execute.os,"geteuid",return_value=0),\
             mock.patch.dict(os.environ,{"SUDO_USER":"mehdi"}),\
             mock.patch.object(power_execute,"_trusted_file",return_value=True),\
             mock.patch.object(power_gate,"inspect_power",return_value=good),\
             mock.patch.object(power_execute.subprocess,"run",return_value=mock.Mock(returncode=0)) as execute:
            self.assertEqual(power_execute.main(["--check"]),0)
            execute.assert_not_called()
            self.assertEqual(power_execute.main(["--execute","shutdown","unsaved-loss-accepted"]),0)
            args=execute.call_args.args[0]
            self.assertEqual(args[-1],"poweroff")
            self.assertIn("--check-inhibitors=no",args)
            self.assertNotIn("--force",args)
            with self.assertRaises(ValueError):
                power_execute.main(["--execute","shutdown","not-acknowledged"])
            self.assertEqual(execute.call_count,1)

    def test_agent_power_uses_fixed_polkit_systemd_unit_not_sudo(self):
        from command_executor import CommandExecutor
        now=int(time.time())
        command={"id":"a"*32,"action":"power.shutdown","value":None,
                 "created_at":now,"expires_at":now+45,"confirm":True,
                 "ack_unsaved_loss":True}
        with tempfile.TemporaryDirectory() as path:
            executor=CommandExecutor(Path(path)/"cmd.json")
            with mock.patch.object(__import__("subprocess"),"run",
                 return_value=mock.Mock(returncode=0)) as run:
                executor.execute(command)
            argv=run.call_args.args[0]
            self.assertEqual(argv,[
                "/usr/bin/systemctl","--system","--no-block",
                "start","ubuntu-control-power-shutdown.service"
            ])
            self.assertNotIn("sudo",argv)
            self.assertNotIn("--force",argv)
            self.assertEqual(executor.ack["status"],"succeeded")

    def test_root_helper_never_runs_after_safety_changes(self):
        with mock.patch.object(power_execute.os,"geteuid",return_value=0),\
             mock.patch.dict(os.environ,{"SUDO_USER":"mehdi"}),\
             mock.patch.object(power_execute,"_trusted_file",return_value=True),\
             mock.patch.object(power_gate,"inspect_power",return_value={"eligible":False}),\
             mock.patch.object(power_execute.subprocess,"run") as execute:
            with self.assertRaises(RuntimeError):
                power_execute.main(["--execute","restart","unsaved-loss-accepted"])
            execute.assert_not_called()

    def test_signed_report_required_for_real_arm(self):
        fake={
            "status":"fresh",
            "checked_at":__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).isoformat(),
            "real_power":{"eligible":True},
        }
        self.assertTrue(server.live_power_ready(fake))
        self.assertFalse(server.live_power_ready({**fake,"status":"stale"}))
        self.assertFalse(server.live_power_ready({**fake,"real_power":{"eligible":False}}))
        sanitized=server.sanitized_real_power({
            "eligible":True,"atlas_owner_paused":True,
            "codex_owner_paused_count":3,"active_jobs":0,
            "cpuwm_verified":True,"processes_verified":True,
            "blockers":[],"warnings":["Save files before shutdown"],
            "private_path":"/secret",
        })
        self.assertTrue(sanitized["eligible"])
        self.assertNotIn("private_path",sanitized)


if __name__=="__main__":
    unittest.main()
