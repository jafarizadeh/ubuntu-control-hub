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

    def test_ubuntu_only_dashboard_and_power_controls(self):
        html = (ROOT / "web/static/index.html").read_text()
        dashboard = html.split('id="view-dashboard"', 1)[1].split('id="view-control"', 1)[0]
        self.assertNotIn('id="pi-temperature"', dashboard)
        self.assertNotIn('id="pi-memory"', dashboard)
        self.assertIn('id="hero-cpu"', dashboard)
        self.assertIn('id="hero-memory"', dashboard)
        self.assertIn('id="hero-gpu"', dashboard)
        self.assertIn('id="desktop-on"', dashboard)
        self.assertIn('id="desktop-off" disabled', dashboard)
        self.assertIn('id="tv-on"', dashboard)
        self.assertIn('id="tv-off" disabled', dashboard)
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
        for button in ("desktop-off", "volume-slider", "mute-toggle", "apply-profile"):
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
        self.assertIn('id="desktop-off" disabled', html)
        self.assertIn('/api/control/capabilities', js)
        self.assertIn('/api/commands', js)
        self.assertIn('commandAuthorizedAndReady()', js)
        self.assertIn('cpuwm.set_profile', js)
        self.assertIn('window.confirm(', js)


    def test_user_supplied_svg_assets_are_local_and_inert(self):
        import xml.etree.ElementTree as ET
        names = ("ubuntu-logo.svg", "monitor.svg", "wifi.svg", "wifi-off.svg", "cpu.svg")
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

        self.assertIn('id="desktop-off" disabled', html)


if __name__ == "__main__":
    unittest.main()
