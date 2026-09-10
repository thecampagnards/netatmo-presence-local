"""Shared entity base for the Netatmo Presence (local) integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import NetatmoPresenceCoordinator, PresenceData
from .helpers import model_name


class NetatmoPresenceEntity(CoordinatorEntity[NetatmoPresenceCoordinator]):
    """Base entity bound to a single camera."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NetatmoPresenceCoordinator, key: str) -> None:
        """Initialise the entity for the given description ``key``."""
        super().__init__(coordinator)
        self._key = key
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            manufacturer=MANUFACTURER,
            model=model_name(
                coordinator.data.config_value("type") if coordinator.data else None,
                coordinator.device_info_payload.get("product_name"),
            ),
            name=entry.title,
            configuration_url=coordinator.api.base_url,
            sw_version=_as_str(
                coordinator.data.config_value("firmware", "firmware_name")
                if coordinator.data
                else None
            ),
        )

    @property
    def data(self) -> PresenceData:
        """Return the latest poll result."""
        return self.coordinator.data


def _as_str(value: object) -> str | None:
    """Return ``value`` as a string, or None when absent."""
    return None if value is None else str(value)
