"""Read-only per-core CPU counters, bounded history and full system telemetry."""

from pathlib import Path
import importlib.util
import json
import sys
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
import cpu_monitor
import desktop_status


def line(tag, user=10, nice=0, system=2, idle=80, iowait=0, irq=0, softirq=0, steal=0):
    return f"{tag} {user} {nice} {system} {idle} {iowait} {irq} {softirq} {steal} 0 0"


class CounterParsingTests(unittest.TestCase):
    def test_core_count_and_cpu_labels(self):
        raw = "\n".join([line("cpu"), line("cpu0"), line("cpu1"), line("cpu10"), "intr 500 120", "ctxt 111"])
        data = cpu_monitor.parse_cpu_counters(raw)
        self.assertEqual(list(data), [-1, 0, 1, 10])
        self.assertEqual(data[-1], (92, 80))

    def test_busy_and_idle_calculation(self):
        before = cpu_monitor.parse_cpu_counters("\n".join([
            line("cpu", user=10, idle=90), line("cpu0", user=0, idle=100),
            line("cpu1", user=20, idle=80)]))
        after = cpu_monitor.parse_cpu_counters("\n".join([
            line("cpu", user=40, idle=110), line("cpu0", user=50, idle=110),
            line("cpu1", user=30, idle=120)]))
        data = cpu_monitor.calculate_usage(before, after)
        self.assertEqual(data["usage_percent"], 60.0)
        self.assertEqual(data["per_core"], [
            {"index": 0, "usage_percent": 83.3},
            {"index": 1, "usage_percent": 20.0},
        ])

    def test_counter_wrap_idle_overflow_and_missing_cpu(self):
        self.assertIsNone(cpu_monitor.counter_usage((100,80), (100,80)))
        self.assertIsNone(cpu_monitor.counter_usage((100,80), (110,100)))
        self.assertIsNone(cpu_monitor.counter_usage((100,80), (110,70)))
        with self.assertRaises(ValueError):
            cpu_monitor.parse_cpu_counters("cpu 1 2")
        with self.assertRaises(ValueError):
            cpu_monitor.parse_cpu_counters("cpu nonnumeric 0 0 10 0 0 0 0")
        with self.assertRaises(ValueError):
            cpu_monitor.parse_cpu_counters("intr 42")

    def test_guests_not_double_counted(self):
        original = line("cpu") + " 9 4"
        same = line("cpu")
        self.assertEqual(cpu_monitor.parse_cpu_counters(original),
                         cpu_monitor.parse_cpu_counters(same))

    def test_sample_once_is_read_only_and_has_failure_fallback(self):
        before=cpu_monitor.parse_cpu_counters(line("cpu")+"\n"+line("cpu0"))
        after=cpu_monitor.parse_cpu_counters(line("cpu",user=20,idle=90)+"\n"+line("cpu0",user=20,idle=90))
        with mock.patch.object(cpu_monitor,"read_counters",side_effect=[before,after]),mock.patch.object(cpu_monitor.time,"sleep") as sleep:
            got=cpu_monitor.sample_once(0.2)
        self.assertEqual(got["usage_percent"],50.0)
        self.assertEqual(got["per_core"][0]["index"],0)
        sleep.assert_called_once_with(0.2)
        with mock.patch.object(cpu_monitor,"read_counters",side_effect=OSError):
            self.assertEqual(cpu_monitor.sample_once(),{"usage_percent":None,"per_core":[]})


class HistoryTests(unittest.TestCase):
    def test_history_is_bounded_and_detached(self):
        sampler=cpu_monitor.CPUActivitySampler(interval=1,history_size=5)
        for timepoint in range(12):
            sampler._record({"usage_percent":timepoint/2,
                             "per_core":[{"index":0,"usage_percent":timepoint/2}]},
                            1000+timepoint)
        report=sampler.snapshot()
        self.assertEqual(len(report["history"]),5)
        self.assertEqual([p["time_unix"] for p in report["history"]],list(range(1007,1012)))
        self.assertEqual(report["per_core"][0]["usage_percent"],5.5)
        report["per_core"][0]["usage_percent"]=99
        report["history"][0]["usage_percent"]=99
        again=sampler.snapshot()
        self.assertEqual(again["per_core"][0]["usage_percent"],5.5)
        self.assertNotEqual(again["history"][0]["usage_percent"],99)

    def test_invalid_values_never_recorded(self):
        sampler=cpu_monitor.CPUActivitySampler()
        for val in (None,-1,101,"50",True,float("nan")):
            sampler._record({"usage_percent":val,"per_core":[]},171, )
        self.assertEqual(sampler.snapshot()["history"],[])

    def test_stops_background_sampler(self):
        sampler=cpu_monitor.CPUActivitySampler(interval=.2,history_size=5)
        sampler.start()
        time.sleep(.45)
        snapshot=sampler.snapshot()
        self.assertTrue(0<len(snapshot["history"])<=5)
        self.assertIsInstance(snapshot["per_core"],list)
        sampler.stop()
        self.assertFalse(sampler._thread.is_alive())

    def test_report_under_signed_16_kib_limit(self):
        sampler=cpu_monitor.CPUActivitySampler(interval=1,history_size=90)
        for second in range(90):
            sampler._record({"usage_percent":10.0,
                "per_core":[{"index":i,"usage_percent":float(i % 100)} for i in range(32)]},
                1762192800+second)
        snapshot=sampler.snapshot()
        status={"schema_version":1,"status":{"schema_version":1,"cpu":snapshot,
                "hostname":"desktop","memory":{},"storage":{},"gpus":[],"fans":[]}}
        body=json.dumps(status,separators=(",",":")).encode()
        self.assertLess(len(body),16384)
        self.assertEqual(len(snapshot["history"]),90)
        self.assertEqual(len(snapshot["per_core"]),32)


class SystemReadingsTests(unittest.TestCase):
    def test_cpu_metadata_parsing(self):
        cpuinfo="processor : 0\nphysical id : 0\ncore id : 0\n\nprocessor : 1\nphysical id : 0\ncore id : 0\n\nprocessor : 2\nphysical id : 0\ncore id : 1\n"
        with mock.patch.object(desktop_status,"read_text",return_value=cpuinfo):
            self.assertEqual(desktop_status.physical_core_count(),2)

    def test_missing_core_ids_is_unknown(self):
        with mock.patch.object(desktop_status,"read_text",return_value="processor : 0\n"):
            self.assertIsNone(desktop_status.physical_core_count())

    def test_full_report_uses_same_per_core_sampling(self):
        readings={"usage_percent":17.5,"per_core":[{"index":0,"usage_percent":18.0}]}
        with mock.patch.object(desktop_status,"sample_once",return_value=readings),\
             mock.patch.object(desktop_status,"power_safety",create=True) if False else mock.patch.object(desktop_status,"collect_power_safety",return_value={}):
            report=desktop_status.collect_status()
        self.assertEqual(report["cpu"]["usage_percent"],17.5)
        self.assertEqual(report["cpu"]["per_core"],readings["per_core"])

    def test_background_sampler_history_propagates(self):
        sampler=cpu_monitor.CPUActivitySampler()
        sampler._record({"usage_percent":20.0,"per_core":[{"index":2,"usage_percent":100.0}]},int(time.time()))
        with mock.patch.object(desktop_status,"collect_power_safety",return_value={}):
            report=desktop_status.collect_status(cpu_sampler=sampler)
        self.assertEqual(report["cpu"]["usage_percent"],20.0)
        self.assertEqual(report["cpu"]["per_core"][0]["index"],2)
        self.assertEqual(len(report["cpu"]["history"]),1)


if __name__=="__main__":
    unittest.main()
