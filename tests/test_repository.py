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
        self.assertFalse(example["desktop"]["agent_ssh"]["enabled"])

    def test_backend_localhost_and_csrf(self):
        src = (ROOT / "web/server.py").read_text()
        self.assertIn('ThreadingHTTPServer(("127.0.0.1", PORT)', src)
        self.assertIn("X-UC-CSRF", src)
        self.assertIn("check_origin(", src)

    def test_dynamic_device_addresses(self):
        html = (ROOT / "web/static/index.html").read_text()
        js = (ROOT / "web/static/app.js").read_text()
        for key in ("pi-ethernet-ip", "desktop-ip", "tv-ip"):
            self.assertIn('id="' + key + '"', html)
            self.assertIn('text("' + key + '"', js)
        self.assertNotIn("192" + ".168.", html)


if __name__ == "__main__":
    unittest.main()
