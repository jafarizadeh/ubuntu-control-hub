"""Desktop action security and behavior — never close a real window in tests."""

from contextlib import closing
import json
import os
from pathlib import Path
import signal
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"agent"))
sys.path.insert(0,str(ROOT/"web"))

import desktop_actions as actions
from command_executor import CommandExecutor, valid_command
from command_queue import CommandQueue, validate_action


class FakeWindow:
    def __init__(self, actions_allowed):
        self.actions=list(actions_allowed)
        self.invoked=[]

    def get_n_actions(self):
        return len(self.actions)

    def get_action_name(self,index):
        return self.actions[index]

    def do_action(self,index):
        self.invoked.append(index)
        return True


class GUIClassificationTests(unittest.TestCase):
    def test_only_allowlisted_documents_browsers_and_terminals(self):
        for name,expected in (("Google Chrome","browser"),("firefox","browser"),
                              ("papers","document"),("org.gnome.nautilus","document"),
                              ("LibreOffice Writer","document"),("ptyxis","terminal"),
                              ("gnome-terminal","terminal")):
            self.assertEqual(actions.classify(name),expected)
        for name in ("gnome-shell","systemd","codex","ubuntu-control-agent",
                     "npm","telegram-desktop","Unknown App",None):
            self.assertIsNone(actions.classify(name))

    def test_close_uses_accessible_application_close_action_only(self):
        win=FakeWindow(["win.open","page.close","window.close"])
        self.assertTrue(actions._close_accessible(win))
        self.assertEqual(win.invoked,[2])
        unknown=FakeWindow(["doDefault"])
        self.assertFalse(actions._close_accessible(unknown))
        self.assertEqual(unknown.invoked,[])

    def test_readonly_summary_contains_counts_not_document_names(self):
        fake=[("browser",object())]*6+[("document",object())]+[("terminal",object())]
        with mock.patch.object(actions,"_windows",return_value=fake),\
             mock.patch.object(actions,"_gpt_remote_running",return_value=True),\
             mock.patch.object(actions,"_last_result",return_value=None):
            result=actions.inspect()
        self.assertTrue(result["available"])
        self.assertEqual(result["browser_windows"],6)
        self.assertEqual(result["document_windows"],1)
        self.assertEqual(result["terminal_windows"],1)
        self.assertTrue(result["gpt_remote_running"])
        self.assertNotIn("window_titles",result)
        self.assertNotIn("window_names",result)
        self.assertNotIn("pids",result)
        with mock.patch.object(actions,"_windows",return_value=None),\
             mock.patch.object(actions,"_gpt_remote_running",return_value=False),\
             mock.patch.object(actions,"_last_result",return_value=None):
            self.assertIsNone(actions.inspect()["browser_windows"])

    def test_browser_main_detection_does_not_select_renderer_children(self):
        with tempfile.TemporaryDirectory() as temporary:
            proc=Path(temporary)
            basename=Path("/opt/google/chrome/chrome")
            if not basename.exists():
                self.skipTest("Browser executable unavailable in this environment")
            uid=os.getuid()
            for pid, parent in ((1001,100),(1002,1001),(1003,1001)):
                folder=proc/str(pid);folder.mkdir()
                (folder/"status").write_text(
                    f"Name:\tchrome\nPPid:\t{parent}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
                (folder/"exe").symlink_to(basename)
            (proc/"1004").mkdir()
            (proc/"1004"/"status").write_text(
                "Name:\tchrome\nPPid:\t100\nUid:\t999999\t999999\t999999\t999999\n")
            (proc/"1004"/"exe").symlink_to(basename)
            self.assertEqual(actions._known_browser_mains(proc),[1001])

    def test_browser_fallback_only_sends_sigterm_to_verified_main_process(self):
        with mock.patch.object(actions,"_known_browser_mains",side_effect=[[34,35],[34,35],[34,35]]),\
             mock.patch.object(actions.os,"kill") as killing:
            self.assertEqual(actions._close_browsers(),2)
            self.assertEqual([c.args for c in killing.call_args_list],
                             [(34,signal.SIGTERM),(35,signal.SIGTERM)])
        self.assertNotIn("SIGKILL",(ROOT/"agent/desktop_actions.py").read_text().split("os.kill(")[-1])

    def test_model_jobs_protect_desktop_closure(self):
        from power_gate import inspect_atlas,inspect_cpuwm,inspect_processes
        safe={"errors":[],"atlas_owner_paused":True,
              "codex_owner_paused_count":3,"active_jobs":0}
        with mock.patch("power_gate.inspect_atlas",return_value=safe),\
             mock.patch("power_gate.inspect_cpuwm",return_value=True),\
             mock.patch("power_gate.inspect_processes",return_value=(True,False)):
            actions._safe_to_close()
        for changed in ({**safe,"atlas_owner_paused":False},
                        {**safe,"active_jobs":1},
                        {**safe,"codex_owner_paused_count":2}):
            with mock.patch("power_gate.inspect_atlas",return_value=changed),\
                 mock.patch("power_gate.inspect_cpuwm",return_value=True),\
                 mock.patch("power_gate.inspect_processes",return_value=(True,False)),\
                 self.assertRaises(PermissionError):
                actions._safe_to_close()
        with mock.patch("power_gate.inspect_atlas",return_value=safe),\
             mock.patch("power_gate.inspect_cpuwm",return_value=True),\
             mock.patch("power_gate.inspect_processes",return_value=(True,True)),\
             self.assertRaises(PermissionError):
            actions._safe_to_close()

    def test_document_close_request_not_deletion_and_partial_is_honest(self):
        document=FakeWindow(["win.close"])
        with mock.patch.object(actions,"_safe_to_close"),\
             mock.patch.object(actions,"_windows",side_effect=[
                 [("document",document),("browser",object())],
                 [("browser",object())],
             ]),\
             mock.patch.object(actions,"_close_browsers",return_value=1),\
             mock.patch.object(actions.time,"sleep"),\
             mock.patch.object(actions,"_write_receipt") as record:
            result=actions.run("close-documents")
        self.assertEqual(result,{"requested":2,"remaining":1,"completed":False})
        record.assert_called_once_with("close-documents",2,1,False)
        self.assertEqual(document.invoked,[0])

    def test_terminal_close_uses_window_close_never_kill_shell(self):
        terminal=FakeWindow(["window.close"])
        with mock.patch.object(actions,"_safe_to_close"),\
             mock.patch.object(actions,"_windows",side_effect=[
                 [("terminal",terminal)],[]
             ]),\
             mock.patch.object(actions.time,"sleep"),\
             mock.patch.object(actions,"_write_receipt") as record,\
             mock.patch.object(actions.os,"kill") as kill:
            result=actions.run("close-terminals")
        self.assertTrue(result["completed"])
        self.assertEqual(result["remaining"],0)
        kill.assert_not_called()
        record.assert_called_once_with("close-terminals",1,0,True)

    def test_open_gpt_remote_is_fixed_ptyxis_launch_not_shell(self):
        with mock.patch.object(actions,"_terminal_executable",
             return_value=Path("/usr/bin/ptyxis")),\
             mock.patch.object(actions.subprocess,"Popen",
             return_value=mock.Mock(pid=4400)) as popen,\
             mock.patch.object(actions,"_write_receipt"):
            result=actions.run("start-gpt-remote")
        argv=popen.call_args.args[0]
        self.assertEqual(argv[:3],["/usr/bin/ptyxis","--new-window","--"])
        self.assertEqual(argv[3],sys.executable)
        self.assertTrue(argv[4].endswith("/gpt_remote_console.py"))
        self.assertTrue(result["requested"])
        self.assertFalse(result["completed"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertNotIn("bash",repr(argv))

    def test_gpt_remote_console_reuses_existing_connector(self):
        code=(ROOT/"agent/gpt_remote_console.py").read_text()
        self.assertIn("if _gpt_remote_running()",code)
        self.assertIn("The existing ChatGPT connection will not be restarted",code)
        self.assertIn("@wonderwhy-er/desktop-commander@latest",code)
        self.assertNotIn("shell=True",code)


class SignedCommandTests(unittest.TestCase):
    def test_rejected_unconfirmed_or_arbitrary_commands(self):
        close={"action":"desktop.close_documents","value":None,
               "confirm":True,"ack_unsaved_loss":True}
        open_term={"action":"desktop.start_gpt_remote","value":None,"confirm":True}
        for req in (close,open_term):
            validate_action(req)
        for rejected in (
            {**close,"ack_unsaved_loss":False},
            {**close,"confirm":False},
            {**close,"value":"rm -rf /"},
            {**close,"action":"desktop.delete_files"},
            {**open_term,"value":"cat /etc/shadow"},
            {**open_term,"command":"rm -rf /"},
            {**open_term,"confirm":False},
        ):
            with self.subTest(data=rejected),self.assertRaises(ValueError):
                validate_action(rejected)

    def test_agent_rejects_unsigned_confirmation_or_modified_actions(self):
        now=int(time.time())
        command={"id":"a"*32,"created_at":now,"expires_at":now+45,
                 "action":"desktop.close_terminals","value":None,
                 "confirm":True,"ack_unsaved_loss":True}
        self.assertTrue(valid_command(command))
        self.assertFalse(valid_command({**command,"ack_unsaved_loss":False}))
        self.assertFalse(valid_command({**command,"action":"desktop.system_shell"}))
        self.assertTrue(valid_command({**command,"action":"desktop.close_documents"}))
        opened={k:v for k,v in command.items() if k!="ack_unsaved_loss"}
        opened["action"]="desktop.open_terminal"
        self.assertTrue(valid_command(opened))
        opened["action"]="desktop.start_gpt_remote"
        self.assertTrue(valid_command(opened))

    def test_queue_desktop_command_routes_via_signed_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue=CommandQueue(Path(tmp)/"queue.sqlite")
            self.addCleanup(queue.db.close)
            command={"action":"desktop.close_terminals","value":None,
                     "confirm":True,"ack_unsaved_loss":True}
            result=queue.enqueue(command)
            self.assertEqual(result["status"],"queued")
            issued=queue.report_response()
            self.assertEqual(issued["command"]["action"],"desktop.close_terminals")
            self.assertIs(issued["command"]["ack_unsaved_loss"],True)

    def test_agent_routes_known_helper_with_fixed_argument_and_receipt(self):
        now=int(time.time())
        with tempfile.TemporaryDirectory() as tmp:
            agent=CommandExecutor(Path(tmp)/"state.json")
            command={"id":"a"*32,"created_at":now,"expires_at":now+45,
                     "action":"desktop.close_documents","value":None,
                     "confirm":True,"ack_unsaved_loss":True}
            with mock.patch("command_executor.subprocess.run",
                            return_value=mock.Mock(returncode=0)) as run:
                agent.execute(command)
            argv=run.call_args.args[0]
            self.assertEqual(argv[:1],[sys.executable])
            self.assertTrue(argv[1].endswith("/desktop_actions.py"))
            self.assertEqual(argv[-1],"--close-documents")
            self.assertFalse(run.call_args.kwargs["shell"])
            self.assertEqual(agent.ack["status"],"succeeded")


if __name__=="__main__":
    unittest.main()
