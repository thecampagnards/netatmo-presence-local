"""Tests for the payload-shaping helpers."""

from __future__ import annotations

import unittest

from _loader import load

helpers = load("helpers")


class MergeFloodlightConfigTest(unittest.TestCase):
    """merge_floodlight_config rebases a partial update on the live config."""

    CURRENT = {
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

    def test_scalar_change_keeps_every_other_key(self):
        merged = helpers.merge_floodlight_config(self.CURRENT, {"mode": "on"})
        self.assertEqual(merged["mode"], "on")
        self.assertEqual(merged["intensity"], 100)
        self.assertEqual(merged["night"], self.CURRENT["night"])

    def test_night_is_merged_key_by_key_not_replaced(self):
        merged = helpers.merge_floodlight_config(
            self.CURRENT, {"night": {"animal": True}}
        )
        self.assertEqual(
            merged["night"],
            {
                "always": False,
                "person": True,
                "vehicle": True,
                "animal": True,
                "movement": False,
            },
        )

    def test_source_config_is_not_mutated(self):
        current = {"mode": "auto", "night": {"person": True}}
        helpers.merge_floodlight_config(current, {"night": {"person": False}})
        self.assertEqual(current, {"mode": "auto", "night": {"person": True}})

    def test_missing_mode_defaults_to_auto(self):
        merged = helpers.merge_floodlight_config({}, {"intensity": 40})
        self.assertEqual(merged, {"intensity": 40, "mode": "auto"})

    def test_night_survives_when_current_has_none(self):
        merged = helpers.merge_floodlight_config(
            {"mode": "on"}, {"night": {"person": True}}
        )
        self.assertEqual(merged["night"], {"person": True})


class ExtractEventsTest(unittest.TestCase):
    """extract_events copes with the shapes the firmware may return."""

    def test_wrapped_list_is_sorted_newest_first(self):
        payload = {"events": [{"time": 10}, {"time": 30}, {"time": 20}]}
        self.assertEqual(
            [event["time"] for event in helpers.extract_events(payload)], [30, 20, 10]
        )

    def test_bare_list_is_accepted(self):
        self.assertEqual(len(helpers.extract_events([{"time": 1}, {"time": 2}])), 2)

    def test_events_list_alias_is_accepted(self):
        self.assertEqual(len(helpers.extract_events({"events_list": [{"time": 1}]})), 1)

    def test_events_without_time_do_not_crash_the_sort(self):
        events = helpers.extract_events([{"type": "human"}, {"time": 5}])
        self.assertEqual(events[0]["time"], 5)

    def test_non_dict_entries_are_dropped(self):
        self.assertEqual(helpers.extract_events(["nope", {"time": 1}]), [{"time": 1}])

    def test_unexpected_payloads_yield_no_events(self):
        for payload in (None, "text", 42, {"other": 1}, {"events": "nope"}):
            with self.subTest(payload=payload):
                self.assertEqual(helpers.extract_events(payload), [])


class ConfigLookupTest(unittest.TestCase):
    """config_lookup searches the known nestings of get_config."""

    def test_flat_payload(self):
        self.assertEqual(helpers.config_lookup({"status": "on"}, ("status",)), "on")

    def test_nested_module_payload(self):
        config = {"module": {"sd_status": 3}}
        self.assertEqual(helpers.config_lookup(config, ("sd_status",)), 3)

    def test_modules_list_payload(self):
        config = {"modules": [{"type": "NOC", "firmware": 176}]}
        self.assertEqual(helpers.config_lookup(config, ("firmware",)), 176)

    def test_first_matching_key_wins(self):
        config = {"monitoring": "off", "status": "on"}
        self.assertEqual(helpers.config_lookup(config, ("status", "monitoring")), "on")

    def test_absent_key_returns_none(self):
        self.assertIsNone(helpers.config_lookup({"a": 1}, ("b",)))

    def test_non_dict_payload_returns_none(self):
        self.assertIsNone(helpers.config_lookup("nope", ("b",)))


class ParseOnOffTest(unittest.TestCase):
    """parse_on_off understands the camera's several boolean spellings."""

    def test_truthy_spellings(self):
        for value in (True, "on", "ON", " true ", "enabled", "1", 1):
            with self.subTest(value=value):
                self.assertIs(helpers.parse_on_off(value), True)

    def test_falsy_spellings(self):
        for value in (False, "off", "false", "disabled", "0", 0):
            with self.subTest(value=value):
                self.assertIs(helpers.parse_on_off(value), False)

    def test_unknown_values_are_none(self):
        for value in (None, "maybe", [], {}):
            with self.subTest(value=value):
                self.assertIsNone(helpers.parse_on_off(value))


class ModelNameTest(unittest.TestCase):
    """model_name maps a module type onto a readable model."""

    def test_known_types(self):
        self.assertEqual(helpers.model_name("NOC"), "Smart Outdoor Camera (Presence)")
        self.assertEqual(
            helpers.model_name("NACamera"), "Smart Indoor Camera (Welcome)"
        )

    def test_unknown_or_missing_type_falls_back_to_presence(self):
        for value in (None, "", "NXX", 42):
            with self.subTest(value=value):
                self.assertEqual(
                    helpers.model_name(value), "Smart Outdoor Camera (Presence)"
                )

    def test_the_misleading_ping_product_name_is_never_used(self):
        # ping reports "Welcome Netatmo" on a Presence too.
        self.assertNotIn("Welcome Netatmo", helpers.model_name("NOC"))


class StableUniqueIdTest(unittest.TestCase):
    """Deciding whether a reconfiguration points at a different camera."""

    def test_a_mac_identifies_the_hardware(self):
        for value in ("70:ee:50:11:22:33", "AA:BB:CC:DD:EE:FF"):
            with self.subTest(value=value):
                self.assertTrue(helpers.is_stable_unique_id(value))

    def test_a_host_fallback_is_not_stable(self):
        # These change when the camera moves, so they must not block a
        # reconfiguration that only updates the address.
        for value in ("camera-parking.home", "192.168.1.20", "169.254.91.84"):
            with self.subTest(value=value):
                self.assertFalse(helpers.is_stable_unique_id(value))

    def test_malformed_values_are_not_stable(self):
        for value in (
            None,
            "",
            "70:ee:50:11:22",
            "70:ee:50:11:22:zz",
            42,
            "70-ee-50-11-22-33",
        ):
            with self.subTest(value=value):
                self.assertFalse(helpers.is_stable_unique_id(value))


class RestingModeTest(unittest.TestCase):
    """Turning the floodlight off puts it back where it was resting."""

    def test_auto_is_remembered_over_a_forced_on(self):
        remembered = helpers.remembered_passive_mode(None, "auto")
        # The camera now reports "on"; the resting mode must survive that.
        remembered = helpers.remembered_passive_mode(remembered, "on")
        self.assertEqual(remembered, "auto")
        self.assertEqual(helpers.restore_target(remembered), "auto")

    def test_off_is_remembered_the_same_way(self):
        remembered = helpers.remembered_passive_mode(None, "off")
        remembered = helpers.remembered_passive_mode(remembered, "on")
        self.assertEqual(helpers.restore_target(remembered), "off")

    def test_switching_between_resting_modes_tracks_the_latest(self):
        remembered = helpers.remembered_passive_mode(None, "auto")
        remembered = helpers.remembered_passive_mode(remembered, "off")
        self.assertEqual(helpers.restore_target(remembered), "off")

    def test_starting_up_on_a_forced_light_falls_back_to_off(self):
        # Home Assistant restarted while the light was held on: nothing was
        # ever observed at rest, so turning it off must really turn it off.
        remembered = helpers.remembered_passive_mode(None, "on")
        self.assertIsNone(remembered)
        self.assertEqual(helpers.restore_target(remembered), "off")

    def test_an_unreadable_mode_does_not_erase_what_is_known(self):
        remembered = helpers.remembered_passive_mode(None, "auto")
        for junk in (None, 42, ""):
            with self.subTest(junk=junk):
                self.assertEqual(
                    helpers.remembered_passive_mode(remembered, junk), "auto"
                )

    def test_the_full_cycle_the_user_asked_for(self):
        # auto -> turn on -> turn off -> auto
        remembered = helpers.remembered_passive_mode(None, "auto")
        self.assertEqual(helpers.restore_target(remembered), "auto")
        remembered = helpers.remembered_passive_mode(remembered, "on")
        self.assertEqual(helpers.restore_target(remembered), "auto")


if __name__ == "__main__":
    unittest.main()
