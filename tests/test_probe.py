"""Tests for the standalone probe scripts.

The reports these produce are meant to be pasted into an issue or a chat, so
the device key must never survive into their output: the firmware embeds it in
``local_url``, which ``ping`` returns.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import unittest

from _fake_camera import VKEY, FakeCamera

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
PROBE_PY = REPO_ROOT / "scripts" / "probe.py"
PROBE_SH = REPO_ROOT / "scripts" / "probe.sh"


def _load_probe():
    """Import scripts/probe.py as a module."""
    spec = importlib.util.spec_from_file_location("probe_script", PROBE_PY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = _load_probe()

LEAKY_PING = json.dumps(
    {"local_url": f"http://192.168.1.20/{VKEY}", "product_name": "Welcome Netatmo"}
).encode()


class RedactionTest(unittest.TestCase):
    """describe() blanks the device key out of every response shape."""

    def test_json_response_is_redacted(self):
        line = probe.describe(200, LEAKY_PING, "application/json", VKEY)
        self.assertNotIn(VKEY, line)
        self.assertIn("<KEY>", line)

    def test_plain_text_response_is_redacted(self):
        body = f"redirecting to /{VKEY}/live".encode()
        line = probe.describe(200, body, "text/plain", VKEY)
        self.assertNotIn(VKEY, line)

    def test_binary_bodies_are_summarised_not_dumped(self):
        line = probe.describe(200, b"\xff\xd8\xff" + b"x" * 900, "image/jpeg", VKEY)
        self.assertIn("bytes", line)
        self.assertNotIn("\xff", line)

    def test_missing_endpoints_are_reported_plainly(self):
        self.assertEqual(
            probe.describe(404, b"Not Found", "text/plain", VKEY), "not implemented"
        )


class EndToEndTest(unittest.TestCase):
    """Both scripts run against a live camera without leaking the key."""

    def setUp(self) -> None:
        self.camera = FakeCamera().__enter__()
        self.addCleanup(self.camera.__exit__, None, None, None)

    def _run(self, argv: list[str]) -> str:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=120, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_python_probe_reports_the_supported_endpoints(self):
        output = self._run(
            [sys.executable, str(PROBE_PY), self.camera.host, VKEY, "--timeout", "5"]
        )
        self.assertNotIn(VKEY, output)
        self.assertIn("command/floodlight_get_config", output)
        self.assertIn("command/get_zones", output)  # probed, and reported missing
        self.assertIn("not implemented", output)

    def test_shell_probe_reports_the_supported_endpoints(self):
        output = self._run(["sh", str(PROBE_SH), self.camera.host, VKEY])
        self.assertNotIn(VKEY, output)
        self.assertIn("command/floodlight_get_config", output)
        self.assertIn("<KEY>", output)

    def test_neither_probe_toggles_monitoring(self):
        self.assertTrue(self.camera.monitoring)
        self._run([sys.executable, str(PROBE_PY), self.camera.host, VKEY])
        self._run(["sh", str(PROBE_SH), self.camera.host, VKEY])
        self.assertTrue(self.camera.monitoring)

    def test_neither_probe_writes_to_the_floodlight(self):
        self._run([sys.executable, str(PROBE_PY), self.camera.host, VKEY])
        self._run(["sh", str(PROBE_SH), self.camera.host, VKEY])
        self.assertEqual(self.camera.writes, [])


if __name__ == "__main__":
    unittest.main()
