"""End-to-end tests of the API client against a real HTTP server."""

from __future__ import annotations

import asyncio
import unittest

import _aiohttp_stub
from _fake_camera import VKEY, FakeCamera
from _loader import COMPONENT_DIR, load
from _urllib_session import UrllibSession

_aiohttp_stub.install()
api = load("api")
const = load("const")
helpers = load("helpers")


class LiveCameraTest(unittest.TestCase):
    """Drive the client against an in-process stand-in camera."""

    def setUp(self) -> None:
        self.camera = FakeCamera().__enter__()
        self.addCleanup(self.camera.__exit__, None, None, None)
        self.client = api.NetatmoPresenceLocalApi(
            UrllibSession(), self.camera.host, VKEY
        )

    def run_async(self, coro):
        """Run a coroutine to completion."""
        return asyncio.run(coro)

    def test_ping_is_served_under_the_device_key(self):
        identity = self.run_async(self.client.async_ping_scoped())
        self.assertEqual(identity["product_name"], "noc")
        self.assertEqual(
            helpers.model_name(None, identity["product_name"]),
            "Smart Outdoor Camera (Presence)",
        )

    def test_the_unscoped_ping_may_not_exist(self):
        # This firmware only routes ping under the key. Setup must not depend
        # on the unscoped one: requiring it rejected a working camera.
        with self.assertRaises(api.NetatmoLocalNotSupportedError):
            self.run_async(self.client.async_ping())

        self.camera.serves_unscoped_ping = True
        self.assertEqual(
            self.run_async(self.client.async_ping())["product_name"], "noc"
        )

    def test_an_unknown_command_reads_as_unsupported_not_as_a_bad_answer(self):
        # The camera serves its HTML error page instead of a JSON error.
        with self.assertRaises(api.NetatmoLocalNotSupportedError):
            self.run_async(self.client.async_get_config())
        self.assertFalse(self.run_async(self.client.probe("command/get_config")))

    def test_an_html_error_page_under_http_200_is_still_unsupported(self):
        self.camera.missing_status = 200
        with self.assertRaises(api.NetatmoLocalNotSupportedError):
            self.run_async(self.client.async_get_config())
        self.assertFalse(self.run_async(self.client.probe("command/get_config")))

    def test_ping_leaks_the_device_key_so_it_must_stay_redacted(self):
        # Guards the diagnostics redaction list: the firmware puts the key
        # inside local_url, so that field can never be reported as-is.
        identity = self.run_async(self.client.async_ping_scoped())
        self.assertIn(VKEY, identity["local_url"])
        diagnostics_redactions = (COMPONENT_DIR / "diagnostics.py").read_text()
        self.assertIn('"local_url"', diagnostics_redactions)

    def test_floodlight_round_trip(self):
        config = self.run_async(self.client.async_get_floodlight_config())
        self.assertEqual(config["mode"], "auto")
        self.assertEqual(config["intensity"], 100)
        self.assertTrue(config["night"]["person"])

    def test_turning_the_floodlight_on_preserves_the_night_triggers(self):
        current = self.run_async(self.client.async_get_floodlight_config())
        merged = helpers.merge_floodlight_config(
            current, {"mode": "on", "intensity": 60}
        )
        self.run_async(self.client.async_set_floodlight_config(merged))

        updated = self.run_async(self.client.async_get_floodlight_config())
        self.assertEqual(updated["mode"], "on")
        self.assertEqual(updated["intensity"], 60)
        self.assertEqual(updated["night"], current["night"])

    def test_flipping_one_night_trigger_leaves_the_others_alone(self):
        current = self.run_async(self.client.async_get_floodlight_config())
        merged = helpers.merge_floodlight_config(current, {"night": {"animal": True}})
        self.run_async(self.client.async_set_floodlight_config(merged))

        updated = self.run_async(self.client.async_get_floodlight_config())
        self.assertTrue(updated["night"]["animal"])
        self.assertTrue(updated["night"]["person"])
        self.assertFalse(updated["night"]["always"])
        self.assertEqual(updated["mode"], "auto")
        self.assertEqual(updated["intensity"], 100)

    def test_monitoring_can_be_switched_and_read_back(self):
        self.camera.serves_get_config = True
        self.run_async(self.client.async_set_monitoring(False))
        config = self.run_async(self.client.async_get_config())
        self.assertIs(helpers.parse_on_off(config["status"]), False)

        self.run_async(self.client.async_set_monitoring(True))
        config = self.run_async(self.client.async_get_config())
        self.assertIs(helpers.parse_on_off(config["status"]), True)

    def test_events_are_returned_newest_first(self):
        self.camera.serves_events = True
        payload = self.run_async(self.client.async_get_events())
        events = helpers.extract_events(payload)
        self.assertEqual([event["type"] for event in events], ["human", "vehicle"])

    def test_snapshot_returns_jpeg_bytes(self):
        image = self.run_async(self.client.async_get_snapshot())
        self.assertTrue(image.startswith(b"\xff\xd8\xff"))

    def test_a_wrong_device_key_is_rejected(self):
        client = api.NetatmoPresenceLocalApi(
            UrllibSession(), self.camera.host, "wrong-key"
        )
        with self.assertRaises(api.NetatmoLocalAuthError):
            self.run_async(client.async_get_floodlight_config())

    def test_probing_reports_what_this_firmware_answers(self):
        self.camera.serves_get_config = True
        self.camera.serves_events = True
        supported = {
            path: self.run_async(self.client.probe(path, params))
            for path, params in (
                ("command/floodlight_get_config", None),
                ("command/get_config", None),
                ("command/get_events_until", {"offset": 1}),
                ("live/snapshot_720.jpg", None),
                ("command/get_zones", None),
            )
        }
        self.assertTrue(supported["command/floodlight_get_config"])
        self.assertTrue(supported["command/get_config"])
        self.assertTrue(supported["command/get_events_until"])
        self.assertTrue(supported["live/snapshot_720.jpg"])
        self.assertFalse(supported["command/get_zones"])

    def test_probing_the_observed_firmware_finds_only_the_floodlight(self):
        # get_config and get_events_until are both absent on the hardware
        # this was tested against; only the floodlight answers.
        for path, params in (
            ("command/get_config", None),
            ("command/get_events_until", {"offset": 1}),
        ):
            with self.subTest(path=path):
                self.assertFalse(self.run_async(self.client.probe(path, params)))
        self.assertTrue(
            self.run_async(self.client.probe("command/floodlight_get_config"))
        )

    def test_media_probing_does_not_download_the_body(self):
        # A snapshot is ~240 kB on real hardware; discovery must not pull it.
        self.assertTrue(
            self.run_async(self.client.probe("live/snapshot_720.jpg", read_body=False))
        )
        self.assertFalse(
            self.run_async(self.client.probe("live/nope.jpg", read_body=False))
        )

    def test_media_probing_still_reports_a_rejected_key(self):
        client = api.NetatmoPresenceLocalApi(
            UrllibSession(), self.camera.host, "wrong-key"
        )
        with self.assertRaises(api.NetatmoLocalAuthError):
            self.run_async(client.probe("live/snapshot_720.jpg", read_body=False))


class MonitoringTest(unittest.TestCase):
    """changestatus routes only with its parameter, and 409s a no-op."""

    def setUp(self) -> None:
        self.camera = FakeCamera().__enter__()
        self.addCleanup(self.camera.__exit__, None, None, None)
        self.client = api.NetatmoPresenceLocalApi(
            UrllibSession(), self.camera.host, VKEY
        )

    def run_async(self, coro):
        """Run a coroutine to completion."""
        return asyncio.run(coro)

    def test_probing_it_without_the_parameter_finds_nothing(self):
        # This is why the integration cannot discover the command by probing,
        # and why probing it leaves monitoring untouched.
        self.assertFalse(self.run_async(self.client.probe("command/changestatus")))
        self.assertTrue(self.camera.monitoring)

    def test_turning_monitoring_off_then_on(self):
        self.run_async(self.client.async_set_monitoring(False))
        self.assertFalse(self.camera.monitoring)
        self.run_async(self.client.async_set_monitoring(True))
        self.assertTrue(self.camera.monitoring)

    def test_a_no_op_is_reported_as_success_not_as_an_error(self):
        # The camera answers HTTP 409 {"code": 7, "message": "Already on"}.
        self.assertTrue(self.camera.monitoring)
        result = self.run_async(self.client.async_set_monitoring(True))
        self.assertEqual(result.get("status"), "ok")
        self.assertTrue(result.get("already_in_state"))
        self.assertTrue(self.camera.monitoring)

    def test_a_genuine_command_error_still_raises(self):
        # An in-band error that is not "already in state" must not be
        # swallowed the way the 409 no-op is.
        with self.assertRaises(api.NetatmoLocalCommandError) as caught:
            self.run_async(
                self.client.async_raw_command(
                    "floodlight_set_config", {"config": "not-json"}
                )
            )
        self.assertFalse(caught.exception.is_already_in_state)


class StreamDiscoveryTest(unittest.TestCase):
    """The playlist path is picked from what the firmware actually serves."""

    def setUp(self) -> None:
        self.camera = FakeCamera().__enter__()
        self.addCleanup(self.camera.__exit__, None, None, None)
        self.client = api.NetatmoPresenceLocalApi(
            UrllibSession(), self.camera.host, VKEY
        )

    def first_served(self) -> str | None:
        """Mirror the coordinator's preference order over the real server."""
        for path in const.STREAM_PATHS:
            if asyncio.run(self.client.probe(path)):
                return path
        return None

    def test_local_playlist_is_preferred_when_served(self):
        self.camera.stream_paths = {"live/index_local.m3u8", "live/index.m3u8"}
        self.assertEqual(self.first_served(), "live/index_local.m3u8")

    def test_documented_playlist_is_used_when_local_is_absent(self):
        self.camera.stream_paths = {"live/index.m3u8"}
        self.assertEqual(self.first_served(), "live/index.m3u8")

    def test_no_playlist_at_all_means_no_stream(self):
        self.camera.stream_paths = set()
        self.assertIsNone(self.first_served())


class SetupSequenceTest(unittest.TestCase):
    """The order the config flow validates a camera in.

    The flow itself needs Home Assistant to run, so this exercises the same
    sequence directly against the client: what it asks, in what order, and
    what each outcome means.
    """

    def setUp(self) -> None:
        self.camera = FakeCamera().__enter__()
        self.addCleanup(self.camera.__exit__, None, None, None)

    def _client(self, key: str = VKEY):
        return api.NetatmoPresenceLocalApi(UrllibSession(), self.camera.host, key)

    def _key_accepted(self, client) -> bool:
        """Mirror the flow: anything answering under the key validates it."""
        for probe in (client.async_ping_scoped, client.async_get_floodlight_config):
            try:
                asyncio.run(probe())
            except api.NetatmoLocalNotSupportedError:
                continue
            return True
        return False

    def test_the_observed_firmware_validates(self):
        # No unscoped ping, no get_config: the scoped ping alone must do it.
        self.assertTrue(self._key_accepted(self._client()))

    def test_a_firmware_without_scoped_ping_validates_on_the_floodlight(self):
        self.camera.serves_scoped_ping = False
        self.assertTrue(self._key_accepted(self._client()))

    def test_a_wrong_key_is_an_auth_error_not_an_unknown_one(self):
        with self.assertRaises(api.NetatmoLocalAuthError):
            self._key_accepted(self._client("wrong-key"))


if __name__ == "__main__":
    unittest.main()
