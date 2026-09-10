"""Maintenance buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NetatmoPresenceConfigEntry
from .entity import NetatmoPresenceEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NetatmoPresenceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the maintenance buttons."""
    async_add_entities([NetatmoRediscoverButton(entry.runtime_data)])


class NetatmoRediscoverButton(NetatmoPresenceEntity, ButtonEntity):
    """Re-probe the firmware, e.g. after a camera update added commands."""

    _attr_translation_key = "rediscover"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        """Initialise the button."""
        super().__init__(coordinator, "rediscover")

    async def async_press(self) -> None:
        """Reload the entry, which re-runs capability discovery."""
        entry = self.coordinator.config_entry
        self.hass.async_create_task(
            self.hass.config_entries.async_reload(entry.entry_id)
        )
