#!/usr/bin/env python3
"""Read-only Ubuntu Desktop telemetry. No daemon, sudo, or listening port."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time

SCHEMA_VERSION = 1


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def parse_cpu_times(stat: str) -> tuple[int, int]:
    first = next((line for line in stat.splitlines() if line.startswith("cpu ")), "")
    fields = first.split()
    if len(fields) < 5:
        raise ValueError("CPU counters unavailable")
    values = [int(v) for v in fields[1:]]
    idle = values[3] + (values[4] if len(values) >= 5 else 0)
    return sum(values), idle


def usage_percent(before: tuple[int, int], after: tuple[int, int]) -> float | None:
    elapsed = after[0] - before[0]
    idle = after[1] - before[1]
    if elapsed <= 0:
        return None
    return round(max(0.0, min(100.0, (elapsed - idle) * 100.0 / elapsed)), 1)


def cpu_usage(sample_seconds: float = 0.2) -> float | None:
    try:
        before = parse_cpu_times(read_text(Path("/proc/stat")) or "")
        time.sleep(sample_seconds)
        after = parse_cpu_times(read_text(Path("/proc/stat")) or "")
        return usage_percent(before, after)
    except (ValueError, OSError):
        return None


def parse_meminfo(text: str) -> dict[str, int] | None:
    values: dict[str, int] = {}
    for line in text.splitlines():
        match = re.match(r"^(\w+):\s+(\d+)\s+kB$", line)
        if match:
            values[match.group(1)] = int(match.group(2))
    if not all(key in values for key in ("MemTotal", "MemAvailable")):
        return None
    total = values["MemTotal"]
    free = values["MemAvailable"]
    if not (0 <= free <= total):
        return None
    return {
        "total_mib": round(total / 1024),
        "available_mib": round(free / 1024),
        "used_percent": round((total - free) * 100 / total, 1) if total else 0,
    }


def memory() -> dict[str, int] | None:
    return parse_meminfo(read_text(Path("/proc/meminfo")) or "")


def temperature_c(value: str | None) -> float | None:
    try:
        celsius = int((value or "").strip()) / 1000.0
        return round(celsius, 1) if -20 <= celsius <= 150 else None
    except (ValueError, TypeError):
        return None


def cpu_temperature() -> float | None:
    preferred = {"coretemp", "k10temp", "zenpower", "cpu_thermal"}
    temps: list[float] = []
    for hwmon in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
        name = (read_text(hwmon / "name") or "").strip().lower()
        if name not in preferred:
            continue
        for file in hwmon.glob("temp*_input"):
            temp = temperature_c(read_text(file))
            if temp is not None:
                temps.append(temp)
    if temps:
        return max(temps)
    for zone in Path("/sys/class/thermal").glob("thermal_zone*"):
        sensor_type = (read_text(zone / "type") or "").strip().lower()
        if "cpu" in sensor_type or "x86_pkg_temp" in sensor_type:
            temp = temperature_c(read_text(zone / "temp"))
            if temp is not None:
                temps.append(temp)
    return max(temps) if temps else None


def fan_speeds() -> list[dict[str, int | str]]:
    result: list[dict[str, int | str]] = []
    for hwmon in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
        chip = (read_text(hwmon / "name") or "unknown").strip()
        for file in sorted(hwmon.glob("fan*_input")):
            raw = read_text(file)
            try:
                rpm = int((raw or "").strip())
            except ValueError:
                continue
            if not (0 <= rpm <= 100000):
                continue
            label = read_text(file.with_name(file.name.replace("_input", "_label")))
            key = (label or file.stem).strip()
            result.append({"sensor": f"{chip}/{key}", "rpm": rpm})
    return result[:32]


def gpu_status() -> list[dict[str, str | int | None]]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return []
    try:
        run = subprocess.run(
            [executable, "--query-gpu=name,utilization.gpu,temperature.gpu,"
             "memory.total,memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=False, timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if run.returncode != 0:
        return []

    def number(s: str) -> int | None:
        s = s.strip()
        return int(s) if s.isdecimal() else None

    devices: list[dict[str, str | int | None]] = []
    for line in run.stdout.splitlines()[:8]:
        parts = [s.strip() for s in line.split(",")]
        if len(parts) != 5:
            continue
        devices.append({
            "name": parts[0][:100],
            "usage_percent": number(parts[1]),
            "temperature_c": number(parts[2]),
            "memory_total_mib": number(parts[3]),
            "memory_used_mib": number(parts[4]),
        })
    return devices


def os_name() -> str:
    os_release = read_text(Path("/etc/os-release")) or ""
    for line in os_release.splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')[:120]
    return "Linux"


def collect_status() -> dict:
    disk = shutil.disk_usage("/")
    try:
        uptime = int(float((read_text(Path("/proc/uptime")) or "0").split()[0]))
    except (ValueError, IndexError):
        uptime = None
    return {
        "schema_version": SCHEMA_VERSION,
        "checked_at_unix": int(time.time()),
        "hostname": socket.gethostname(),
        "os": os_name(),
        "uptime_s": uptime,
        "cpu": {
            "logical_cores": os.cpu_count(),
            "usage_percent": cpu_usage(),
            "temperature_c": cpu_temperature(),
        },
        "memory": memory(),
        "storage": {
            "total_gib": round(disk.total / 2**30, 1),
            "free_gib": round(disk.free / 2**30, 1),
            "used_percent": round(disk.used * 100 / disk.total, 1) if disk.total else 0,
        },
        "fans": fan_speeds(),
        "gpus": gpu_status(),
    }


def main() -> int:
    if len(sys.argv) > 1:
        print("Usage: desktop_status.py", file=sys.stderr)
        return 2
    print(json.dumps(collect_status(), ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
