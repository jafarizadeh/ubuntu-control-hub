"""Low-cost, read-only per-core CPU sampler for signed Ubuntu telemetry.

The sampler reads /proc/stat once per second in an unprivileged daemon thread.
It never listens on a port, executes a command, or changes system settings.
The history is intentionally bounded so signed reports stay under 16 KiB.
"""

from __future__ import annotations

from collections import deque
import threading
import time
from pathlib import Path

MAX_CORES = 256
HISTORY_POINTS = 90
SAMPLE_SECONDS = 1.0


def parse_cpu_counters(raw: str) -> dict[int, tuple[int, int]]:
    """Map aggregate (-1) and logical CPU indices to (total_jiffies, idle)."""
    if not isinstance(raw, str):
        raise ValueError("CPU counters are not readable")
    result: dict[int, tuple[int, int]] = {}
    for line in raw.splitlines():
        parts = line.split()
        if not parts:
            continue
        tag = parts[0]
        if tag == "cpu":
            index = -1
        elif tag.startswith("cpu") and tag[3:].isdigit():
            index = int(tag[3:])
            if not 0 <= index < MAX_CORES:
                continue
        else:
            continue
        if len(parts) < 9:
            raise ValueError("Incomplete /proc/stat CPU counters")
        try:
            # Linux guest and guest_nice counters are included in user/nice;
            # using first eight fields avoids double-counting guest time.
            counters = [int(value) for value in parts[1:9]]
        except ValueError as exc:
            raise ValueError("Invalid CPU counters") from exc
        if any(value < 0 for value in counters):
            raise ValueError("Negative CPU counters")
        total = sum(counters)
        idle = counters[3] + counters[4]
        result[index] = (total, idle)
    if -1 not in result:
        raise ValueError("Aggregate CPU counters unavailable")
    return result


def counter_usage(before: tuple[int, int], after: tuple[int, int]) -> float | None:
    elapsed = after[0] - before[0]
    idle = after[1] - before[1]
    if elapsed <= 0 or idle < 0 or idle > elapsed:
        return None
    return round(max(0.0, min(100.0, (elapsed - idle) * 100.0 / elapsed)), 1)


def calculate_usage(before: dict, after: dict) -> dict:
    overall = counter_usage(before[-1], after[-1])
    cores = []
    for index in sorted(set(before) & set(after) - {-1}):
        if not isinstance(index, int) or index < 0 or index >= MAX_CORES:
            continue
        cores.append({
            "index": index,
            "usage_percent": counter_usage(before[index], after[index]),
        })
    return {"usage_percent": overall, "per_core": cores[:MAX_CORES]}


def read_counters(path: Path = Path("/proc/stat")) -> dict:
    return parse_cpu_counters(path.read_text(encoding="utf-8"))


def sample_once(seconds: float = 0.2) -> dict:
    """Best-effort single window for direct CLI calls (not continuous)."""
    try:
        before = read_counters()
        time.sleep(seconds)
        return calculate_usage(before, read_counters())
    except (OSError, ValueError, KeyError):
        return {"usage_percent": None, "per_core": []}


class CPUActivitySampler:
    """One background reader with a bounded 90-second rolling history."""

    def __init__(self, interval: float = SAMPLE_SECONDS, history_size: int = HISTORY_POINTS):
        if not 0.2 <= interval <= 10 or not 2 <= history_size <= 120:
            raise ValueError("Unsafe sampling configuration")
        self.interval = interval
        self.history_size = history_size
        self._samples: deque[dict] = deque(maxlen=history_size)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._usage: float | None = None
        self._cores: list[dict] = []
        self._latest_at = 0

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="ubuntu-control-cpu-sampler", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 3) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        try:
            previous = read_counters()
        except (OSError, ValueError):
            previous = None
        while not self._stop.wait(self.interval):
            try:
                current = read_counters()
                if previous is not None:
                    usage = calculate_usage(previous, current)
                    self._record(usage, int(time.time()))
                previous = current
            except (OSError, ValueError, KeyError):
                previous = None

    def _record(self, usage: dict, timestamp: int) -> None:
        value = usage.get("usage_percent")
        cores = usage.get("per_core", [])
        if type(timestamp) is not int or type(value) not in (float, int):
            return
        if not 0 <= value <= 100 or not isinstance(cores, list):
            return
        with self._lock:
            self._usage = float(value)
            self._cores = [dict(item) for item in cores[:MAX_CORES]]
            self._latest_at = timestamp
            self._samples.append({"time_unix": timestamp, "usage_percent": float(value)})

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "usage_percent": self._usage,
                "per_core": [dict(core) for core in self._cores],
                "history": [dict(sample) for sample in self._samples],
                "sampled_at_unix": self._latest_at or None,
                "interval_seconds": self.interval,
            }
