"""Floodlight intensity control."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NetatmoPresenceConfigEntry
from .api import NetatmoLocalError
from .const import CAP_FLOODLIGHT
from .entity import NetatmoPresenceEntity
from .helpers import merge_floodlight_config


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NetatmoPresenceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the intensity number."""
    coordinator = entry.runtime_data
    if coordinator.supports(CAP_FLOODLIGHT):
        async_add_entities([NetatmoFloodlightIntensity(coordinator)])


class NetatmoFloodlightIntensity(NetatmoPresenceEntity, NumberEntity):
    """The floodlight intensity, in percent.

    Separate from the light's brightness so the level can be tuned (and
    automated) while the lamp sits in ``auto``.
    """

    _attr_translation_key = "floodlight_intensity"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator) -> None:
        """Initialise the intensity control."""
        super().__init__(coordinator, "floodlight_intensity")

    @property
    def native_value(self) -> float | None:
        """Return the configured intensity."""
        return self.data.floodlight_intensity

    async def async_set_native_value(self, value: float) -> None:
        """Set the floodlight intensity."""
        config = merge_floodlight_config(
            self.data.floodlight, {"intensity": int(value)}
        )
        try:
            await self.coordinator.async_write_floodlight(config)
        except (NetatmoLocalError, ValueError) as err:
            raise HomeAssistantError(f"Setting the intensity failed: {err}") from err
