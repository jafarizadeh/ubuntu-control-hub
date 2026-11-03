#!/usr/bin/env python3
"""Ubuntu Control Hub. Strictly localhost only; expose through private Tailscale Serve."""
from __future__ import annotations

import functools
import hashlib
import hmac
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import pathlib
import secrets
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

from agent_broker import AgentBroker

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = ROOT / "web" / "static"
CONFIG = ROOT / "config"
EVENTS = ROOT / "data" / "history.jsonl"
COMMAND = ROOT / ".venv" / "bin" / "bscpylgtvcommand"
TV_DATABASE = CONFIG / ".aiopylgtv.sqlite"
STATUS_COMMAND = ROOT / "bin" / "status.py"
BROKER = AgentBroker(CONFIG / "desktop_agent.pub", state_file=ROOT / "data" / "command-state.sqlite")
OPERATOR = CONFIG / "operator.json"
WOL_COMMAND = ROOT / "bin" / "wake.py"
DEVICE_INFO = json.loads((CONFIG / "devices.json").read_text())
COOKIE = "uc_hub"
SECRET = secrets.token_bytes(32)
PORT = 8765
CACHE_SECONDS = 7
_last_report = (0.0, {})
_cache_lock = threading.RLock()
_action_times = {}
_action_lock = threading.RLock()


def paired():
    try:
        with sqlite3.connect(f"file:{TV_DATABASE}?mode=ro", uri=True) as db:
            return db.execute("SELECT count(*) FROM unnamed").fetchone()[0] > 0
    except (sqlite3.Error, OSError):
        return False


def status():
    global _last_report
    with _cache_lock:
        if time.monotonic() - _last_report[0] <= CACHE_SECONDS:
            return _last_report[1]
        r = subprocess.run(
            [sys.executable, str(STATUS_COMMAND)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=18, check=True,
        )
        report = json.loads(r.stdout)
        report["tv"]["paired"] = paired()
        report["desktop"].update(BROKER.desktop_state())
        report["hub"] = {"version": "0.3.0", "control_mode": "private_tailnet", "listen": "localhost"}
        _last_report = (time.monotonic(), report)
        return report


def log_event(action, target, result):
    record = {
        "at": int(time.time()),
        "action": action,
        "target": target,
        "result": result,
    }
    with _action_lock:
        with EVENTS.open("a", encoding="utf-8") as out:
            out.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        EVENTS.chmod(0o600)
    return record


def recent_history():
    if not EVENTS.is_file():
        return []
    try:
        lines = EVENTS.read_text(encoding="utf-8").splitlines()[-30:]
        return list(reversed([json.loads(line) for line in lines]))
    except (ValueError, OSError):
        return []


def call_tv(method, argument=None):
    if not paired():
        raise ValueError("TV is not paired. Approve the pairing prompt on the LG first.")
    if method not in {"volume_up", "volume_down", "set_mute", "get_volume", "get_current_app", "power_off"}:
        raise ValueError("Unsupported TV operation")
    args = [str(COMMAND), "-p", str(TV_DATABASE), "--log", "ERROR",
            DEVICE_INFO["tv"]["ip"], method]
    if argument is not None:
        args.append(str(argument))
    r = subprocess.run(args, cwd=CONFIG, capture_output=True, text=True, timeout=16)
    if r.returncode:
        raise RuntimeError("TV communication failed. Check that the TV is on and paired.")
    return r.stdout.strip()[:450]


def check_origin(host, origin):
    if not origin:
        return False
    try:
        url = urlsplit(origin)
        host_only = host.split(":")[0].lower()
        allowed_host = host_only in {"localhost", "127.0.0.1"} or host_only.endswith(".ts.net")
        acceptable_protocol = "https" if host_only.endswith(".ts.net") else "http"
        return allowed_host and url.netloc.lower() == host.lower() and url.scheme == acceptable_protocol
    except ValueError:
        return False


def can_control(headers):
    # Loopback is the Serve backend, never an authorized browser origin.
    host = headers.get("Host", "").split(":", 1)[0].lower()
    if not host.endswith(".ts.net"):
        return False
    values = headers.get_all("Tailscale-User-Login", [])
    if len(values) != 1:
        return False
    try:
        if OPERATOR.is_symlink():
            return False
        import os
        import stat
        info = OPERATOR.stat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            return False
        cfg = json.loads(OPERATOR.read_text(encoding="utf-8"))
        expected = cfg.get("allowed_login")
        return (isinstance(expected, str) and bool(expected)
                and hmac.compare_digest(values[0].encode(), expected.encode()))
    except (OSError, ValueError, AttributeError, TypeError):
        return False


class Handler(BaseHTTPRequestHandler):
    server_version = "UbuntuControl/0.3"

    def log_message(self, fmt, *args):
        # No cookies or action payloads are included.
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _headers(self, code=200, mime="application/json; charset=utf-8", length=None):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-store" if "json" in mime else "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "connect-src 'self'; img-src 'self' data:; manifest-src 'self'; "
                         "worker-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        if length is not None:
            self.send_header("Content-Length", str(length))

    def _json(self, data, code=200, cookie=None):
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._headers(code, length=len(raw))
        if cookie:
            # Secure cookie when behind Tailscale HTTPS, non-secure only for local HTTP testing.
            host = self.headers.get("Host", "")
            secure = "; Secure" if host.endswith(".ts.net") else ""
            self.send_header("Set-Cookie", f"{COOKIE}={cookie}; HttpOnly; SameSite=Strict; Path=/{secure}")
        self.end_headers()
        self.wfile.write(raw)

    def _host_ok(self):
        h = self.headers.get("Host", "").lower().split(":")[0]
        return h in {"127.0.0.1", "localhost"} or h.endswith(".ts.net")

    def _cookie_token(self):
        try:
            raw = SimpleCookie()
            raw.load(self.headers.get("Cookie", ""))
            value = raw.get(COOKIE)
            if value and len(value.value) <= 128:
                return value.value
        except Exception:
            pass
        return None

    @staticmethod
    def _token(cookie_value):
        return hmac.new(SECRET, cookie_value.encode(), hashlib.sha256).hexdigest()

    def do_GET(self):
        if not self._host_ok():
            return self._json({"error": "Host not allowed"}, 403)
        path = urlsplit(self.path).path
        if path == "/api/control/capabilities":
            return self._json({"can_control": can_control(self.headers)})
        if path.startswith("/api/commands/"):
            if not can_control(self.headers):
                return self._json({"error": "Control denied"}, 403)
            try:
                state = BROKER.commands.status(path.removeprefix("/api/commands/"))
            except sqlite3.Error:
                return self._json({"error": "Command state unavailable"}, 503)
            return self._json({"status": state}, 200 if state else 404)
        if path == "/api/session":
            cookie_value = self._cookie_token() or secrets.token_urlsafe(32)
            return self._json({"csrf": self._token(cookie_value)}, cookie=cookie_value)
        if path == "/api/health":
            return self._json({"ok": True, "version": "0.3", "agent": BROKER.desktop_state()["control_agent"]})
        if path == "/api/status":
            try:
                return self._json(status())
            except Exception:
                return self._json({"error": "Unable to collect hub status"}, 503)
        if path == "/api/history":
            return self._json({"events": recent_history()})
        if path == "/api/tv":
            try:
                if not paired():
                    return self._json({"error": "TV pairing incomplete"}, 409)
                return self._json({"volume": call_tv("get_volume"),
                                   "app": call_tv("get_current_app")})
            except Exception:
                return self._json({"error": "TV is unavailable"}, 503)
        path = "/index.html" if path == "/" else path
        resolved = (STATIC / path.lstrip("/")).resolve()
        if not resolved.is_relative_to(STATIC.resolve()) or not resolved.is_file():
            return self._json({"error": "Not found"}, 404)
        contents = resolved.read_bytes()
        mimetype = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        self._headers(200, mimetype + ("; charset=utf-8" if mimetype.startswith(("text/", "application/javascript")) else ""), len(contents))
        self.end_headers()
        self.wfile.write(contents)

    def do_POST(self):
        if not self._host_ok():
            return self._json({"error": "Host not allowed"}, 403)
        path = urlsplit(self.path).path
        if path == "/api/agent/report":
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                return self._json({"error": "JSON content required"}, 415)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16384:
                    return self._json({"error": "Agent payload size invalid"}, 413)
                raw = self.rfile.read(size)
                if not BROKER.authorized(self.headers, raw):
                    return self._json({"error": "Unauthorized agent"}, 403)
                if not BROKER.accept(raw):
                    return self._json({"error": "Invalid agent report"}, 400)
                result = BROKER.commands.report_response(json.loads(raw).get("ack"))
            except (ValueError, OSError, sqlite3.Error):
                return self._json({"error": "Agent report unavailable"}, 503)
            return self._json(result)
        if path == "/api/commands" and not can_control(self.headers):
            return self._json({"error": "Control denied"}, 403)
        origin = self.headers.get("Origin", "")
        if not check_origin(self.headers.get("Host", ""), origin):
            return self._json({"error": "Invalid request origin"}, 403)
        cookie_value = self._cookie_token()
        supplied = self.headers.get("X-UC-CSRF", "")
        if not cookie_value or not hmac.compare_digest(self._token(cookie_value), supplied):
            return self._json({"error": "Missing or incorrect CSRF token"}, 403)
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._json({"error": "JSON content required"}, 415)
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not (0 < length <= 1024):
                return self._json({"error": "Bad payload size"}, 413)
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict):
                raise ValueError("Bad request")
        except (ValueError, json.JSONDecodeError):
            return self._json({"error": "Invalid JSON"}, 400)
        path = urlsplit(self.path).path
        if path == "/api/commands":
            try:
                return self._json(BROKER.commands.enqueue(request), 202)
            except ValueError:
                return self._json({"error": "Command not allowed"}, 400)
            except OverflowError:
                return self._json({"error": "Command queue full"}, 429)
            except (OSError, sqlite3.Error):
                return self._json({"error": "Command queue unavailable"}, 503)
        if path == "/api/wake":
            target = request.get("target")
            if target not in {"desktop", "tv"}:
                return self._json({"error": "Target not allowed"}, 400)
            with _action_lock:
                now = time.monotonic()
                if now - _action_times.get(("wake", target), 0) < 20:
                    return self._json({"error": "Please wait before sending another wake request"}, 429)
                _action_times[("wake", target)] = now
                try:
                    subprocess.run([sys.executable, str(WOL_COMMAND), target, "--send"],
                                   capture_output=True, text=True, timeout=5, check=True)
                    log_event("wake", target, "packet_sent")
                    return self._json({"ok": True, "message": "Wake packet sent; device wake not yet confirmed"})
                except Exception:
                    log_event("wake", target, "failed")
                    return self._json({"error": "Could not send wake packet"}, 503)
        if path == "/api/tv/pair":
            with _action_lock:
                if paired():
                    return self._json({"ok": True, "message": "TV already paired"})
                now = time.monotonic()
                if now - _action_times.get(("pair", "tv"), 0) < 90:
                    return self._json({"error": "Pairing was requested recently; please try again later"}, 429)
                _action_times[("pair", "tv")] = now
            try:
                process = subprocess.run(
                    [str(COMMAND), "-p", str(TV_DATABASE), "--log", "WARNING",
                     DEVICE_INFO["tv"]["ip"], "get_system_info"],
                    cwd=CONFIG, capture_output=True, text=True, timeout=70
                )
                if process.returncode or not paired():
                    raise RuntimeError("Pairing not confirmed")
                TV_DATABASE.chmod(0o600)
                log_event("pair", "tv", "ok")
                return self._json({"ok": True, "message": "LG pairing completed"})
            except (OSError, subprocess.TimeoutExpired, RuntimeError):
                log_event("pair", "tv", "failed")
                return self._json({"error": "TV did not approve pairing; turn the screen on and accept the connection prompt"}, 503)
        if path == "/api/tv/control":
            action = request.get("action")
            allowed = {"volume_up", "volume_down", "mute", "unmute", "power_off"}
            if action not in allowed:
                return self._json({"error": "Action not allowed"}, 400)
            with _action_lock:
                now = time.monotonic()
                if now - _action_times.get(("tv", action), 0) < 2:
                    return self._json({"error": "Slow down"}, 429)
                _action_times[("tv", action)] = now
                try:
                    if action == "mute":
                        call_tv("set_mute", "true")
                    elif action == "unmute":
                        call_tv("set_mute", "false")
                    elif action == "power_off":
                        call_tv("power_off")
                    else:
                        call_tv(action)
                    log_event(action, "tv", "ok")
                    return self._json({"ok": True, "message": "TV command sent"})
                except Exception:
                    log_event(action, "tv", "failed")
                    return self._json({"error": "TV command failed; check pairing and power"}, 503)
        return self._json({"error": "Not found"}, 404)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.daemon_threads = True
    print(f"Ubuntu Control Hub v0.3 on 127.0.0.1:{PORT} (private only)", flush=True)
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
