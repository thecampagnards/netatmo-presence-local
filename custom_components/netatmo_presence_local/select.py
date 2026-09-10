"""Floodlight mode selector."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NetatmoPresenceConfigEntry
from .api import NetatmoLocalError
from .const import CAP_FLOODLIGHT, FLOODLIGHT_MODES
from .entity import NetatmoPresenceEntity
from .helpers import merge_floodlight_config


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NetatmoPresenceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the floodlight mode selector."""
    coordinator = entry.runtime_data
    if coordinator.supports(CAP_FLOODLIGHT):
        async_add_entities([NetatmoFloodlightMode(coordinator)])


class NetatmoFloodlightMode(NetatmoPresenceEntity, SelectEntity):
    """Expose on / off / auto as a first-class choice."""

    _attr_translation_key = "floodlight_mode"
    _attr_options = list(FLOODLIGHT_MODES)

    def __init__(self, coordinator) -> None:
        """Initialise the selector."""
        super().__init__(coordinator, "floodlight_mode")

    @property
    def current_option(self) -> str | None:
        """Return the configured floodlight mode."""
        return self.data.floodlight_mode

    async def async_select_option(self, option: str) -> None:
        """Switch the floodlight to ``option``."""
        config = merge_floodlight_config(self.data.floodlight, {"mode": option})
        try:
            await self.coordinator.async_write_floodlight(config)
        except (NetatmoLocalError, ValueError) as err:
            raise HomeAssistantError(
                f"Setting the floodlight mode failed: {err}"
            ) from err
