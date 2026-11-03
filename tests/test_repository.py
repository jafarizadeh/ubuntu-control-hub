import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


class RepositorySmokeTests(unittest.TestCase):
    def test_english_ltr_manifest(self):
        page = (ROOT / "web/static/index.html").read_text(encoding="utf-8")
        self.assertIn('<html lang="en" dir="ltr">', page)
        manifest = json.loads((ROOT / "web/static/manifest.webmanifest").read_text())
        self.assertEqual(manifest["lang"], "en")
        self.assertEqual(manifest["dir"], "ltr")
        self.assertEqual(manifest["display"], "standalone")

    def test_light_mode(self):
        css = (ROOT / "web/static/style.css").read_text(encoding="utf-8")
        self.assertIn("color-scheme: light", css)
        self.assertNotIn("@media(prefers-color-scheme:dark)", css)

    def test_no_persian_ui(self):
        for name in ("index.html", "app.js", "style.css", "sw.js"):
            src = (ROOT / "web/static" / name).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"[\u0600-\u06ff]", src), name)

    def test_no_real_private_configuration(self):
        ignore = (ROOT / ".gitignore").read_text()
        self.assertIn("/config/devices.json", ignore)
        self.assertIn("/data/", ignore)
        self.assertIn(".venv/", ignore)
        for private in ("config/devices.json", "config/.aiopylgtv.sqlite", "data/history.jsonl"):
            self.assertFalse((ROOT / private).exists())

    def test_example_uses_documentation_addresses(self):
        example = json.loads((ROOT / "config/devices.example.json").read_text())
        self.assertTrue(example["controller"]["broadcast_ip"].startswith("192.0.2."))
        for key in ("ethernet_ip", "wifi_ip"):
            self.assertTrue(example["controller"][key].startswith("192.0.2."))
        for key in ("desktop", "tv"):
            self.assertTrue(example[key]["ip"].startswith("192.0.2."))
            self.assertIn("mac", example[key])
        self.assertNotIn("agent_ssh", example["desktop"])

    def test_backend_localhost_and_csrf(self):
        src = (ROOT / "web/server.py").read_text()
        self.assertIn('ThreadingHTTPServer(("127.0.0.1", PORT)', src)
        self.assertIn("X-UC-CSRF", src)
        self.assertIn("check_origin(", src)

    def test_cpu_details_from_signed_ubuntu_telemetry(self):
        html = (ROOT / "web/static/index.html").read_text()
        js = (ROOT / "web/static/app.js").read_text()
        cpu_js = (ROOT / "web/static/cpu-details.js").read_text()
        css = (ROOT / "web/static/cpu-details.css").read_text()
        worker = (ROOT / "web/static/sw.js").read_text()
        self.assertIn('id="open-cpu-details"',html)
        self.assertIn('id="view-cpu" hidden',html)
        self.assertIn('id="cpu-back-button"',html)
        self.assertIn('id="cpu-core-grid"',html)
        self.assertIn('id="cpu-history-canvas"',html)
        self.assertIn('id="cpu-detail-gpu-temp"',html)
        self.assertIn('id="cpu-info-physical"',html)
        self.assertIn('id="cpu-info-clock"',html)
        self.assertIn('window.UbuntuCPU.update(report)',js)
        self.assertIn('window.UbuntuCPU.stale()',js)
        self.assertIn('switchTab("cpu")',js)
        self.assertIn('HISTORY_LIMIT = 90',cpu_js)
        self.assertIn('HOT_THRESHOLD = 90',cpu_js)
        self.assertIn('validCoreList(cpu.per_core)',cpu_js)
        self.assertIn('ctx.strokeStyle="#ff4960"',cpu_js)
        self.assertIn('4,minmax(0,1fr)',css)
        self.assertIn('/cpu-details.js',worker)
        self.assertIn('/cpu-details.css',worker)
        self.assertNotIn("setInterval(() => Math.random()",cpu_js)
        self.assertNotIn("/api/pi/",cpu_js)

    def test_ubuntu_only_dashboard_and_power_controls(self):
        html = (ROOT / "web/static/index.html").read_text()
        dashboard = html.split('id="view-dashboard"', 1)[1].split('id="view-control"', 1)[0]
        self.assertNotIn('id="pi-temperature"', dashboard)
        self.assertNotIn('id="pi-memory"', dashboard)
        self.assertIn('id="hero-cpu"', dashboard)
        self.assertIn('id="hero-memory"', dashboard)
        self.assertIn('id="hero-gpu"', dashboard)
        self.assertEqual(dashboard.count('class="btn power-toggle"'), 2)
        self.assertIn('id="desktop-power-button" disabled', dashboard)
        self.assertIn('id="tv-power-button" disabled', dashboard)
        self.assertIn('id="desktop-power-badge"', dashboard)
        self.assertIn('id="tv-power-badge"', dashboard)
        self.assertNotIn('id="desktop-on"', dashboard)
        self.assertNotIn('id="tv-on"', dashboard)
        self.assertNotIn('id="tv-off"', dashboard)
        self.assertLess(dashboard.index('class="power-grid"'), dashboard.index('id="metrics-grid"'))
        self.assertNotIn("192" + ".168.", html)

    def test_metric_preferences_and_agent_freshness(self):
        html = (ROOT / "web/static/index.html").read_text()
        js = (ROOT / "web/static/app.js").read_text()
        self.assertIn('id="metric-options"', html)
        self.assertIn('id="customize-btn"', html)
        self.assertIn('window.localStorage', js)
        self.assertIn('desktop.last_agent_report_unix', js)
        self.assertIn('desktop.control_agent === "online"', js)
        self.assertIn('paintWithoutUbuntu()', js)

    def test_control_panel_is_honest_about_unsupported_actions(self):
        html = (ROOT / "web/static/index.html").read_text()
        for button in ("desktop-power-button", "volume-slider", "mute-toggle", "apply-profile"):
            self.assertIn('id="' + button + '"', html)
        self.assertIn("Manage GPT remote access", html)
        self.assertIn("CPU & GPU Workload Manager", html)


    def test_remote_commands_require_capabilities_and_leave_power_locked(self):
        html = (ROOT / "web/static/index.html").read_text()
        js = (ROOT / "web/static/app.js").read_text()
        self.assertIn('id="control-access"', html)
        self.assertIn('id="command-feedback"', html)
        self.assertIn('id="apply-volume" type="button" disabled', html)
        self.assertIn('id="apply-profile" type="button" disabled', html)
        self.assertIn('id="desktop-power-button" disabled', html)
        self.assertIn('/api/control/capabilities', js)
        self.assertIn('/api/commands', js)
        self.assertIn('commandAuthorizedAndReady()', js)
        self.assertIn('cpuwm.set_profile', js)
        self.assertIn('window.UbuntuIOS.confirm(', js)


    def test_ios_timer_profile_and_custom_dialogs(self):
        html=(ROOT/"web/static/index.html").read_text()
        ui=(ROOT/"web/static/ios-ui.js").read_text()
        css=(ROOT/"web/static/ios-controls.css").read_text()
        js=(ROOT/"web/static/app.js").read_text()
        worker=(ROOT/"web/static/sw.js").read_text()
        for name in ("ios-picker-sheet", "ios-confirm-dialog", "ios-hours-wheel",
                     "ios-minutes-wheel", "ios-sheet-done", "ios-confirm-submit",
                     "duration-picker-open", "profile-picker-open", "ios-ring-progress",
                     "ios-timer-readout", "power-preview-delay", "power-preview-action"):
            self.assertIn('id="'+name+'"', html)
        self.assertIn('data-duration="240"', html)
        self.assertIn('data-profile-option="performance"', html)
        self.assertNotIn('<select id="profile-selector"', html)
        self.assertNotIn('<select id="power-preview-action"', html)
        self.assertNotIn('type="number" id="power-preview-delay"', html)
        self.assertNotIn("window.confirm(", js)
        self.assertIn('dialog.showModal()', ui)
        self.assertIn('preview_only !== true', ui)
        self.assertIn('will_execute !== false', ui)
        self.assertIn('performance.now()', ui)
        self.assertIn('Raspberry Pi remains authoritative', ui)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn(".ios-picker-sheet::backdrop", css)
        self.assertIn("/ios-controls.css", worker)
        self.assertIn("/ios-ui.js", worker)
        self.assertIn('method: "POST"', js)
        self.assertIn('cancel ? "/api/power/cancel" : "/api/power/preview"', js)

    def test_user_supplied_svg_assets_are_local_and_inert(self):
        import xml.etree.ElementTree as ET
        names = ("ubuntu-logo.svg", "monitor.svg", "wifi.svg", "wifi-off.svg", "cpu.svg",
                 "power.svg", "ubuntu-on.svg", "ubuntu-off.svg",
                 "monitor-on.svg", "monitor-off.svg")
        html = (ROOT / "web/static/index.html").read_text()
        js = (ROOT / "web/static/app.js").read_text()
        worker = (ROOT / "web/static/sw.js").read_text()
        allowed = {"svg", "g", "path", "rect", "circle", "ellipse",
                   "line", "polyline", "polygon", "defs", "linearGradient", "stop"}
        for name in names:
            svg = ROOT / "web/static/assets" / name
            self.assertTrue(svg.is_file(), name)
            body = svg.read_text()
            self.assertNotIn("<!DOCTYPE", body)
            self.assertNotIn("<script", body)
            self.assertNotIn("javascript:", body)
            self.assertNotIn("foreignObject", body)
            node = ET.fromstring(body)
            for item in node.iter():
                self.assertIn(item.tag.rsplit("}",1)[-1],allowed)
                for attr in item.attrib:
                    self.assertFalse(attr.startswith("on"))
                    self.assertNotIn("href",attr.lower())
            self.assertIn("/assets/" + name, worker)
        self.assertIn("/assets/ubuntu-logo.svg", html)
        self.assertIn("/assets/monitor.svg", html)
        self.assertIn("/assets/cpu.svg", html)
        self.assertIn('id="network-control-icon"', html)
        self.assertIn("/assets/wifi-off.svg", js)

    def test_one_power_button_per_device_and_independent_state_icons(self):
        html = (ROOT / "web/static/index.html").read_text()
        js = (ROOT / "web/static/app.js").read_text()
        css = (ROOT / "web/static/style.css").read_text()
        dashboard = html.split('id="view-dashboard"', 1)[1].split('id="view-control"', 1)[0]
        self.assertEqual(dashboard.count('class="btn power-toggle"'), 2)
        self.assertIn('id="desktop-power-icon"', dashboard)
        self.assertIn('id="tv-power-icon"', dashboard)
        self.assertIn('/assets/power.svg', dashboard)
        self.assertIn('function renderDevicePower(', js)
        self.assertIn('function renderPowerUnavailable(', js)
        self.assertIn('function setPowerCard(', js)
        self.assertIn('tv.power_state', js)
        self.assertIn('"tv-screen-on"', js)
        self.assertIn('Wake-on-LAN sends a signal', js)
        self.assertIn('Network reachability is not enough', js)
        self.assertIn('.power-toggle.is-standby', css)
        self.assertIn('.power-symbol.is-unknown', css)
        self.assertNotIn('id="desktop-off"', dashboard)
        self.assertNotIn('id="tv-off"', dashboard)

    def test_real_codex_stop_bridge_is_read_only_and_expires(self):
        code = (ROOT / "agent/codex_stop_attestation.py").read_text()
        html = (ROOT / "web/static/index.html").read_text()
        js = (ROOT / "web/static/app.js").read_text()
        backend = (ROOT / "web/server.py").read_text()
        doc = (ROOT / "docs/ATLAS_CODEX_STOP_BRIDGE.md").read_text()
        self.assertIn("codex_owner_stop_control", code)
        self.assertIn("codex_owner_stop_acks", code)
        self.assertIn("interactive_owner", code)
        self.assertIn("boot_id", code)
        self.assertIn("LEASE_SECONDS = 15", code)
        self.assertIn("codex_user_stop_verified", backend)
        self.assertIn("evidence_age_seconds", backend)
        self.assertIn("lease_age > 15", backend)
        self.assertIn('id="guard-stop-acks"', html)
        self.assertIn('id="guard-stop-barrier"', html)
        self.assertIn("Awaiting Atlas support", js)
        self.assertIn("Not requested", js)
        self.assertIn("Waiting for workers", js)
        self.assertIn("Verified owner stop", js)
        self.assertIn("Codex resumed", js)
        self.assertIn("DO NOT apply manually", doc)
        self.assertIn("not yet implemented", doc)
        self.assertNotIn("subprocess.run(", code)

    def test_atlas_owner_stop_is_separate_from_idle_and_quota(self):
        html = (ROOT / "web/static/index.html").read_text()
        js = (ROOT / "web/static/app.js").read_text()
        py = (ROOT / "agent/atlas_guard.py").read_text()
        for identifier in ("guard-atlas-dispatch","guard-atlas-attempts","guard-codex-stop"):
            self.assertIn('id="' + identifier + '"',html)
            self.assertIn('put("' + identifier + '"',js)
        self.assertIn("Atlas scheduler",html)
        self.assertIn("Codex user stop",html)
        self.assertIn("Worker acknowledgements",html)
        self.assertIn("Dispatch barrier",html)
        self.assertIn('id="guard-stop-acks"',html)
        self.assertIn('id="guard-stop-barrier"',html)
        self.assertIn('put("guard-stop-acks"',js)
        self.assertIn('put("guard-stop-barrier"',js)
        self.assertIn("owner_stop_no_active_attempts",js)
        self.assertIn("armed_idle",py)
        self.assertIn("Explicit owner stop requested",py)
        self.assertIn("mode=ro",py)
        self.assertIn("atlas_power_gate_clear",py)
        self.assertNotIn("shutdown -h",py)

    def test_power_safety_summaries_are_read_only(self):
        html = (ROOT / "web/static/index.html").read_text()
        js = (ROOT / "web/static/app.js").read_text()
        for item in ("guard-atlas", "guard-cpuwm", "guard-desktop"):
            self.assertIn('id="' + item + '"', html)
            self.assertIn('put("' + item + '"', js)
        self.assertIn("Unverified", html)
        self.assertIn("Zero CPUWM scopes does not prove", html)
        self.assertIn('id="power-safety-more"', html)
        self.assertIn('id="power-safety-count"', html)
        self.assertIn('put("power-safety-count"', js)

        self.assertIn('id="desktop-power-button" disabled', html)


if __name__ == "__main__":
    unittest.main()
