"""Power consolidation regressions: synthetic data only; never real commands."""
from datetime import datetime,timezone
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import io
import json
import sys
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"web"))
from power_schedule import PowerSchedule
from test_command_channel import server, headers


class TimerIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.timer=PowerSchedule(Path(self.tmp.name)/"timer.sqlite")
        self.payload={"action":"shutdown","delay_minutes":0,"confirm":True,"ack_unsaved_loss":True}

    def test_sent_timer_cannot_be_replaced_then_falsely_canceled(self):
        with mock.patch("power_schedule.time.time",return_value=1000):
            first=self.timer.arm(self.payload)
        sender=mock.Mock(return_value={"status":"queued","id":"a"*32})
        with mock.patch("power_schedule.time.time",return_value=1030):
            sent=self.timer.dispatch_due(True,sender)
            self.assertEqual(sent["state"],"sent")
            with self.assertRaises(FileExistsError):self.timer.arm(self.payload)
            with self.assertRaises(FileExistsError):self.timer.cancel({"schedule_id":first["schedule_id"]})
            self.assertEqual(self.timer.status()["schedule_id"],first["schedule_id"])
        sender.assert_called_once()

    def test_stale_client_cannot_cancel_another_devices_replacement(self):
        with mock.patch("power_schedule.time.time",return_value=1000):
            first=self.timer.arm(self.payload)
            self.timer.cancel({"schedule_id":first["schedule_id"]})
            second=self.timer.arm({**self.payload,"action":"restart"})
            self.assertNotEqual(first["schedule_id"],second["schedule_id"])
            with self.assertRaises(FileExistsError):self.timer.cancel({"schedule_id":first["schedule_id"]})
            self.assertEqual(self.timer.status()["state"],"armed")
            self.assertEqual(self.timer.status()["action"],"restart")
            self.assertEqual(self.timer.cancel({"schedule_id":second["schedule_id"]})["state"],"canceled")

    def test_missing_or_malformed_identifier_does_not_cancel(self):
        first=self.timer.arm(self.payload)
        with self.assertRaises(FileExistsError):self.timer.cancel({})
        for body in ({"schedule_id":7},{"schedule_id":"x"*32},{"schedule_id":"a"*33},{"schedule_id":first["schedule_id"],"extra":True}):
            with self.subTest(body=body),self.assertRaises(ValueError):self.timer.cancel(body)
        self.assertEqual(self.timer.status()["state"],"armed")

    def test_no_schedule_cancel_is_harmless_but_never_dispatches(self):
        self.assertEqual(self.timer.cancel({})["state"],"absent")
        with mock.patch.object(self.timer,"dispatch_due") as dispatch:
            self.timer.status();dispatch.assert_not_called()

    def test_resolution_window_is_not_a_completed_shutdown_claim(self):
        with mock.patch("power_schedule.time.time",return_value=1000):self.timer.arm(self.payload)
        with mock.patch("power_schedule.time.time",return_value=1030):
            self.timer.dispatch_due(True,lambda p:{"id":"b"*32,"status":"queued"})
        with mock.patch("power_schedule.time.time",return_value=1151):
            result=self.timer.status()
            self.assertEqual(result["state"],"completed_unverified")
            self.assertIn("verify",result["detail"])


class UnifiedSnapshotTests(unittest.TestCase):
    def make_safety(self,age=2):
        return {"status":"fresh","checked_at":datetime.fromtimestamp(1000-age,timezone.utc).isoformat(),
                "real_power":{"eligible":True,"atlas_owner_paused":True,"codex_owner_paused_count":3,
                              "active_jobs":0,"cpuwm_verified":True,"processes_verified":True,"blockers":[],"warnings":[]},
                "atlas_state":"active","atlas_control":{"scheduler_mode":"STOP"},
                "cpuwm":{"status":"fresh","managed_scopes":0},"desktop_work":{"status":"unverifiable"},
                "private_internal_path":"not-for-api","blocked_reasons":["Legacy proof missing"]}

    def test_one_safety_snapshot_for_controls_and_inspection(self):
        safety=self.make_safety()
        with mock.patch.object(server,"power_safety",return_value=safety) as read,\
             mock.patch.object(server.REAL_POWER,"status",return_value={"state":"absent"}),\
             mock.patch.object(server.time,"time",return_value=1000):
            result=server.live_power_response()
        read.assert_called_once()
        self.assertTrue(result["ready_to_arm"])
        self.assertEqual(result["safety_valid_for_seconds"],13)
        self.assertEqual(result["inspection"]["atlas_control"],safety["atlas_control"])
        self.assertNotIn("private_internal_path",result["inspection"])
        self.assertNotIn("blocked_reasons",result["inspection"])
        self.assertEqual(set(result["inspection"]),{"status","atlas_state","atlas_control","cpuwm","desktop_work"})

    def test_old_35second_eligibility_cannot_become_ready(self):
        with mock.patch.object(server,"power_safety",return_value=self.make_safety(age=20)),\
             mock.patch.object(server.REAL_POWER,"status",return_value={"state":"absent"}),\
             mock.patch.object(server.time,"time",return_value=1000):
            result=server.live_power_response()
        self.assertFalse(result["ready_to_arm"])
        self.assertEqual(result["safety_valid_for_seconds"],0)
        self.assertTrue(result["real_power"]["eligible"])

    def test_absent_report_does_not_gain_permissions_from_inspection(self):
        with mock.patch.object(server,"power_safety",return_value={"status":"absent"}),\
             mock.patch.object(server.REAL_POWER,"status",return_value={"state":"absent"}):
            result=server.live_power_response()
        self.assertFalse(result["ready_to_arm"])
        self.assertEqual(result["safety_valid_for_seconds"],0)

    def test_gates_and_root_helper_unchanged_by_ui_merge(self):
        gate=(ROOT/"agent/power_gate.py").read_text()
        helper=(ROOT/"agent/power_execute.py").read_text()
        self.assertIn('row[0] != "STOP"',gate)
        self.assertIn('codex_owner_paused_count',gate)
        self.assertIn('result["eligible"]',helper)
        self.assertIn('unsaved-loss-accepted',helper)
        self.assertNotIn('danger-full-access',helper)


class CachedClientProtocolTests(unittest.TestCase):
    def handler(self,protocol=None):
        h=server.Handler.__new__(server.Handler)
        h.path="/api/power/live/arm";h.headers=headers();h._json=mock.Mock()
        data=json.dumps({"action":"shutdown","delay_minutes":0,"confirm":True,"ack_unsaved_loss":True}).encode()
        h.headers["Origin"]="https://pi.example.ts.net"
        h.headers["Cookie"]="uc_hub=example"
        h.headers["X-UC-CSRF"]=h._token("example")
        h.headers["Content-Type"]="application/json"
        h.headers["Content-Length"]=str(len(data));h.rfile=io.BytesIO(data)
        if protocol is not None:h.headers["X-UC-Power-Protocol"]=protocol
        return h

    def test_old_cached_pwa_cannot_arm_timer_it_cannot_cancel(self):
        for value in (None,"1","invalid"):
            h=self.handler(value)
            with mock.patch.object(server,"can_control",return_value=True),\
                 mock.patch.object(server,"live_power_ready",return_value=True),\
                 mock.patch.object(server.REAL_POWER,"arm") as arm:
                h.do_POST()
            self.assertEqual(h._json.call_args.args[1],409)
            arm.assert_not_called()

    def test_updated_client_still_requires_real_readiness(self):
        h=self.handler("2")
        with mock.patch.object(server,"can_control",return_value=True),\
             mock.patch.object(server,"live_power_ready",return_value=False),\
             mock.patch.object(server.REAL_POWER,"arm") as arm:
            h.do_POST()
        self.assertEqual(h._json.call_args.args[1],409)
        arm.assert_not_called()


class UnifiedDOMTests(unittest.TestCase):
    def test_unique_ids_one_power_card_no_preview_dependencies(self):
        class IDs(HTMLParser):
            def __init__(self):super().__init__();self.ids=[]
            def handle_starttag(self,tag,attrs):
                self.ids.extend(value for key,value in attrs if key=="id")
        html=(ROOT/"web/static/index.html").read_text();parser=IDs();parser.feed(html)
        self.assertEqual(len(parser.ids),len(set(parser.ids)))
        self.assertEqual(parser.ids.count("real-power-card"),1)
        for old in ("power-preview-card","power-preview-create","ios-timer-readout"):
            self.assertNotIn(old,parser.ids)
        for current in ("live-power-more","live-inspection-age","guard-owner-switches","live-blocking-details"):
            self.assertIn(current,parser.ids)
        js=(ROOT/"web/static/app.js").read_text()+(ROOT/"web/static/ios-ui.js").read_text()+(ROOT/"web/static/power-live.js").read_text()
        self.assertNotIn('/api/power/preview',js)
        self.assertNotIn('power-preview-delay',js)
        self.assertNotIn('Work must be saved',js)
        self.assertIn('ack_unsaved_loss:true',js)
        self.assertIn('schedule_id:schedule.schedule_id',js)
        self.assertIn('AbortController',js)
        self.assertIn('safety_valid_for_seconds',js)


if __name__=="__main__":unittest.main()
