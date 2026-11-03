#!/usr/bin/env python3
"""Local read-only checks for the Ubuntu Control hub."""
import json
import pathlib
import shutil
import socket
import subprocess
import sys
import time


BASE = pathlib.Path(__file__).resolve().parent.parent
DEVICES = json.loads((BASE / "config/devices.json").read_text())

def ping(ip):
    try:
        return subprocess.run(["ping", "-n", "-c", "1", "-W", "2", ip], capture_output=True, timeout=3).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False

def tcp(ip, port):
    try:
        with socket.create_connection((ip, int(port)), timeout=1):
            return True
    except OSError:
        return False

def cpu_temp():
    try:
        return round(int(pathlib.Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000, 1)
    except (OSError, ValueError):
        return None

def mem_mib():
    try:
        entries = {}
        for line in pathlib.Path("/proc/meminfo").read_text().splitlines():
            key, val = line.split(":", 1)
            entries[key] = int(val.strip().split()[0]) // 1024
        return {"total_mib": entries["MemTotal"], "available_mib": entries["MemAvailable"]}
    except (OSError, ValueError, KeyError):
        return None

def cmd(command, timeout=2):
    try:
        r = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None

disk = shutil.disk_usage("/")
ts = cmd(["tailscale", "status", "--json"], timeout=4)
try:
    tailscale_state = json.loads(ts)["BackendState"] if ts else "unknown"
except (ValueError, KeyError):
    tailscale_state = "unknown"

report = {
    "checked_at_unix": int(time.time()),
    "controller": {
        "hostname": socket.gethostname(),
        "ethernet_ip": DEVICES["controller"]["ethernet_ip"],
        "wifi_ip": DEVICES["controller"]["wifi_ip"],
        "temperature_c": cpu_temp(),
        "uptime_s": int(float(pathlib.Path("/proc/uptime").read_text().split()[0])),
        "memory": mem_mib(),
        "storage": {"free_gib": round(disk.free / 2**30, 1), "total_gib": round(disk.total / 2**30, 1)},
        "tailscale_state": tailscale_state,
        "throttling": cmd(["vcgencmd", "get_throttled"])
    },
    "desktop": {
        "ip": DEVICES["desktop"]["ip"],
        "ping_reachable": ping(DEVICES["desktop"]["ip"]),
        "mac_configured": bool(DEVICES["desktop"].get("mac"))
    },
    "tv": {
        "ip": DEVICES["tv"]["ip"],
        "model": DEVICES["tv"]["model"],
        "ping_reachable": ping(DEVICES["tv"]["ip"]),
        "webos_api_reachable": tcp(DEVICES["tv"]["ip"], DEVICES["tv"]["control_port"]),
        "power_state": "unknown",
        "mac_configured": bool(DEVICES["tv"].get("mac"))
    }
}
print(json.dumps(report, indent=2, ensure_ascii=False))
