"""Floodlight support for the Netatmo Presence."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NetatmoPresenceConfigEntry
from .api import NetatmoLocalError
from .const import (
    ATTR_INTENSITY,
    ATTR_MODE,
    CAP_FLOODLIGHT,
    FLOODLIGHT_MODE_ON,
    FLOODLIGHT_MODES,
    NIGHT_TRIGGERS,
    SERVICE_SET_FLOODLIGHT,
    SERVICE_SET_NIGHT_TRIGGERS,
)
from .entity import NetatmoPresenceEntity
from .helpers import merge_floodlight_config


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NetatmoPresenceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the floodlight."""
    coordinator = entry.runtime_data
    if not coordinator.supports(CAP_FLOODLIGHT):
        return

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SET_FLOODLIGHT,
        {
            vol.Optional(ATTR_MODE): vol.In(FLOODLIGHT_MODES),
            vol.Optional(ATTR_INTENSITY): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=100)
            ),
        },
        "async_set_floodlight",
    )
    platform.async_register_entity_service(
        SERVICE_SET_NIGHT_TRIGGERS,
        {vol.Optional(trigger): cv.boolean for trigger in NIGHT_TRIGGERS},
        "async_set_night_triggers",
    )

    async_add_entities([NetatmoPresenceFloodlight(coordinator)])


class NetatmoPresenceFloodlight(NetatmoPresenceEntity, LightEntity):
    """The camera's floodlight.

    ``is_on`` reflects the *configured* mode, not the physical lamp: in
    ``auto`` the camera decides on its own and reports no feedback, so the
    entity is considered off until the mode is forced to ``on``.
    """

    _attr_translation_key = "floodlight"
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, coordinator) -> None:
        """Initialise the floodlight entity."""
        super().__init__(coordinator, "floodlight")

    @property
    def is_on(self) -> bool | None:
        """Return whether the floodlight is forced on."""
        mode = self.data.floodlight_mode
        return None if mode is None else mode == FLOODLIGHT_MODE_ON

    @property
    def brightness(self) -> int | None:
        """Return the floodlight intensity scaled to 0-255."""
        intensity = self.data.floodlight_intensity
        return None if intensity is None else round(intensity * 255 / 100)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the mode and the night triggers alongside the state."""
        attributes: dict[str, Any] = {
            ATTR_MODE: self.data.floodlight_mode,
            "restores_to": self.coordinator.restore_mode,
        }
        if (intensity := self.data.floodlight_intensity) is not None:
            attributes[ATTR_INTENSITY] = intensity
        for trigger in NIGHT_TRIGGERS:
            value = self.data.night_trigger(trigger)
            if value is not None:
                attributes[f"night_{trigger}"] = value
        return attributes

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Force the floodlight on, optionally at a given brightness."""
        # Capture where the floodlight was resting, in case no poll has seen
        # it since it last changed.
        self.coordinator.remember_passive_mode(self.data.floodlight_mode)

        config: dict[str, Any] = {ATTR_MODE: FLOODLIGHT_MODE_ON}
        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            config[ATTR_INTENSITY] = max(1, round(brightness * 100 / 255))
        await self._async_push(config)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Return the floodlight to the mode it was resting in.

        Turning the light on and off again therefore leaves an automatic
        floodlight automatic, rather than disabling it.
        """
        await self._async_push({ATTR_MODE: self.coordinator.restore_mode})

    async def async_set_floodlight(
        self, mode: str | None = None, intensity: int | None = None
    ) -> None:
        """Service target: set the mode and/or the intensity in one call."""
        config: dict[str, Any] = {}
        if mode is not None:
            config[ATTR_MODE] = mode
        if intensity is not None:
            config[ATTR_INTENSITY] = intensity
        if not config:
            raise HomeAssistantError("Provide at least one of: mode, intensity")
        await self._async_push(config)

    async def async_set_night_triggers(self, **triggers: bool) -> None:
        """Service target: choose what wakes the floodlight at night."""
        night = {
            key: bool(value) for key, value in triggers.items() if value is not None
        }
        if not night:
            raise HomeAssistantError(
                f"Provide at least one of: {', '.join(NIGHT_TRIGGERS)}"
            )
        await self._async_push({"night": night})

    async def _async_push(self, config: dict[str, Any]) -> None:
        """Merge ``config`` into the current one and send it to the camera."""
        merged = merge_floodlight_config(self.data.floodlight, config)
        try:
            await self.coordinator.async_write_floodlight(merged)
        except (NetatmoLocalError, ValueError) as err:
            raise HomeAssistantError(f"Setting the floodlight failed: {err}") from err
