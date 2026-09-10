"""Tests for the local HTTP client."""

from __future__ import annotations

import asyncio
import json
import unittest

import _aiohttp_stub
from _aiohttp_stub import FakeSession
from _loader import load

_aiohttp_stub.install()
api = load("api")

HOST = "camera-parking.home"
VKEY = "s3cr3t-key"

FLOODLIGHT = {
    "intensity": 100,
    "mode": "auto",
    "night": {
        "always": False,
        "person": True,
        "vehicle": True,
        "animal": False,
        "movement": False,
    },
}


def run(coro):
    """Run a coroutine to completion."""
    return asyncio.run(coro)


class ApiTestCase(unittest.TestCase):
    """Base class wiring a client onto a fake session."""

    def setUp(self) -> None:
        self.session = FakeSession()
        self.client = api.NetatmoPresenceLocalApi(self.session, HOST, VKEY)


class UrlBuildingTest(ApiTestCase):
    """URLs are scoped by the device key."""

    def test_commands_are_vkey_scoped(self):
        self.session.queue(body=json.dumps(FLOODLIGHT))
        run(self.client.async_get_floodlight_config())
        self.assertEqual(
            self.session.last_url,
            f"http://{HOST}/{VKEY}/command/floodlight_get_config",
        )

    def test_ping_is_not_vkey_scoped(self):
        self.session.queue(body='{"product_name":"Netatmo Presence"}')
        run(self.client.async_ping())
        self.assertEqual(self.session.last_url, f"http://{HOST}/command/ping")

    def test_snapshot_and_stream_urls(self):
        self.assertEqual(
            self.client.snapshot_url, f"http://{HOST}/{VKEY}/live/snapshot_720.jpg"
        )
        self.assertEqual(
            self.client.stream_url(), f"http://{HOST}/{VKEY}/live/index_local.m3u8"
        )
        self.assertEqual(
            self.client.stream_url("live/index.m3u8"),
            f"http://{HOST}/{VKEY}/live/index.m3u8",
        )

    def test_host_given_with_a_scheme_is_not_doubled(self):
        client = api.NetatmoPresenceLocalApi(self.session, f"http://{HOST}", VKEY)
        self.assertEqual(client.base_url, f"http://{HOST}")


class FloodlightWriteTest(ApiTestCase):
    """Writes go out as a JSON ``config`` query parameter."""

    def test_config_is_sent_as_json(self):
        self.session.queue(body='{"status":"ok"}')
        run(self.client.async_set_floodlight_config({"mode": "on", "intensity": 80}))
        self.assertEqual(
            self.session.last_url,
            f"http://{HOST}/{VKEY}/command/floodlight_set_config",
        )
        sent = json.loads(self.session.last_params["config"])
        self.assertEqual(sent, {"mode": "on", "intensity": 80})

    def test_unknown_mode_is_rejected_before_any_request(self):
        with self.assertRaises(ValueError):
            run(self.client.async_set_floodlight_config({"mode": "strobe"}))
        self.assertEqual(self.session.requests, [])

    def test_out_of_range_intensity_is_rejected(self):
        with self.assertRaises(ValueError):
            run(self.client.async_set_floodlight_config({"intensity": 150}))
        self.assertEqual(self.session.requests, [])

    def test_unknown_night_trigger_is_rejected(self):
        with self.assertRaises(ValueError):
            run(self.client.async_set_floodlight_config({"night": {"drone": True}}))
        self.assertEqual(self.session.requests, [])

    def test_valid_night_triggers_are_accepted(self):
        self.session.queue(body='{"status":"ok"}')
        run(self.client.async_set_floodlight_config({"night": {"animal": True}}))
        self.assertEqual(
            json.loads(self.session.last_params["config"]), {"night": {"animal": True}}
        )


class MonitoringTest(ApiTestCase):
    """changestatus maps a boolean onto the camera's on/off wording."""

    def test_turning_monitoring_on(self):
        self.session.queue(body='{"status":"ok"}')
        run(self.client.async_set_monitoring(True))
        self.assertEqual(self.session.last_params, {"status": "on"})

    def test_turning_monitoring_off(self):
        self.session.queue(body='{"status":"ok"}')
        run(self.client.async_set_monitoring(False))
        self.assertEqual(self.session.last_params, {"status": "off"})


class ErrorHandlingTest(ApiTestCase):
    """HTTP and in-band failures map onto the client's exception types."""

    def test_404_means_the_command_does_not_exist(self):
        self.session.queue(status=404, body=b"Not Found")
        with self.assertRaises(api.NetatmoLocalNotSupportedError):
            run(self.client.async_get_floodlight_config())

    def test_403_means_a_bad_device_key(self):
        self.session.queue(status=403, body=b"Forbidden")
        with self.assertRaises(api.NetatmoLocalAuthError):
            run(self.client.async_get_floodlight_config())

    def test_server_error_is_a_generic_failure(self):
        self.session.queue(status=500, body=b"boom")
        with self.assertRaises(api.NetatmoLocalError):
            run(self.client.async_get_floodlight_config())

    def test_in_band_error_on_http_200_is_raised(self):
        self.session.queue(body='{"error":{"code":9,"message":"invalid param"}}')
        with self.assertRaisesRegex(api.NetatmoLocalError, "invalid param"):
            run(self.client.async_get_floodlight_config())

    def test_malformed_json_is_reported(self):
        self.session.queue(body=b"<html>nope</html>")
        with self.assertRaises(api.NetatmoLocalError):
            run(self.client.async_get_floodlight_config())

    def test_timeout_becomes_a_connection_error(self):
        self.session.queue_exception(TimeoutError())
        with self.assertRaises(api.NetatmoLocalConnectionError):
            run(self.client.async_get_floodlight_config())

    def test_transport_failure_becomes_a_connection_error(self):
        self.session.queue_exception(_aiohttp_stub.ClientError("refused"))
        with self.assertRaises(api.NetatmoLocalConnectionError):
            run(self.client.async_get_floodlight_config())

    def test_the_device_key_never_leaks_into_error_messages(self):
        self.session.queue(status=404, body=b"Not Found")
        with self.assertRaises(api.NetatmoLocalError) as caught:
            run(self.client.async_get_floodlight_config())
        self.assertNotIn(VKEY, str(caught.exception))
        self.assertIn("***", str(caught.exception))


class ProbeTest(ApiTestCase):
    """Capability probing distinguishes a missing route from a failing one."""

    def test_missing_route_is_unsupported(self):
        self.session.queue(status=404, body=b"Not Found")
        self.assertFalse(run(self.client.probe("command/whatever")))

    def test_successful_call_is_supported(self):
        self.session.queue(body="{}")
        self.assertTrue(run(self.client.probe("command/get_config")))

    def test_parameter_error_still_proves_the_route_exists(self):
        self.session.queue(body='{"error":{"message":"missing status"}}')
        self.assertTrue(run(self.client.probe("command/changestatus")))

    def test_unreachable_camera_propagates(self):
        self.session.queue_exception(TimeoutError())
        with self.assertRaises(api.NetatmoLocalConnectionError):
            run(self.client.probe("command/get_config"))

    def test_bad_key_propagates_rather_than_disabling_the_feature(self):
        self.session.queue(status=401, body=b"")
        with self.assertRaises(api.NetatmoLocalAuthError):
            run(self.client.probe("command/get_config"))


class RawTest(ApiTestCase):
    """Snapshots and arbitrary commands."""

    def test_snapshot_returns_raw_bytes(self):
        self.session.queue(body=b"\xff\xd8\xff-jpeg-data")
        self.assertEqual(
            run(self.client.async_get_snapshot()), b"\xff\xd8\xff-jpeg-data"
        )

    def test_raw_command_targets_the_command_namespace(self):
        self.session.queue(body="{}")
        run(self.client.async_raw_command("get_events_until", {"offset": "5"}))
        self.assertEqual(
            self.session.last_url,
            f"http://{HOST}/{VKEY}/command/get_events_until",
        )
        self.assertEqual(self.session.last_params, {"offset": "5"})

    def test_raw_command_tolerates_a_leading_slash(self):
        self.session.queue(body="{}")
        run(self.client.async_raw_command("/get_config"))
        self.assertEqual(
            self.session.last_url, f"http://{HOST}/{VKEY}/command/get_config"
        )


if __name__ == "__main__":
    unittest.main()
