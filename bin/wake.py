#!/usr/bin/env python3
"""Wake only the configured devices; explicit --send required."""
import argparse
import json
import ipaddress
import pathlib
import socket

BASE = pathlib.Path(__file__).resolve().parent.parent
devices = json.loads((BASE / "config/devices.json").read_text())
parser = argparse.ArgumentParser(description="Ubuntu Control safe Wake-on-LAN")
parser.add_argument("device", choices=("desktop", "tv"))
parser.add_argument("--send", action="store_true", help="actually send the magic packet")
args = parser.parse_args()
item = devices[args.device]
mac = bytes.fromhex(item["mac"].replace(":", ""))
if len(mac) != 6:
    raise SystemExit("Invalid MAC address")
if not args.send:
    print(f"DRY RUN: {args.device} MAC={item['mac']}. Add --send to transmit.")
else:
    packet = b"\xff" * 6 + mac * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        broadcast = str(ipaddress.IPv4Address(devices["controller"]["broadcast_ip"]))
        sock.sendto(packet, (broadcast, 9))
    print(f"Wake-on-LAN packet sent to {args.device} (delivery/wake not guaranteed)")
