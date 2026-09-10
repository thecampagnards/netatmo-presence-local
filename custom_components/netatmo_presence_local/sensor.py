"""Diagnostic and event sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NetatmoPresenceConfigEntry
from .const import CAP_CONFIG, CAP_EVENTS
from .coordinator import PresenceData
from .entity import NetatmoPresenceEntity


@dataclass(frozen=True, kw_only=True)
class NetatmoSensorDescription(SensorEntityDescription):
    """Describes a Netatmo Presence sensor."""

    value_fn: Callable[[PresenceData], Any]
    capability: str
    attributes_fn: Callable[[PresenceData], dict[str, Any]] | None = None


def _event_time(data: PresenceData) -> datetime | None:
    """Return the timestamp of the most recent event."""
    event = data.last_event
    if not event or not isinstance(event.get("time"), int | float):
        return None
    return datetime.fromtimestamp(event["time"], tz=UTC)


def _event_attributes(data: PresenceData) -> dict[str, Any]:
    """Return the useful fields of the most recent event."""
    event = data.last_event or {}
    return {
        key: event[key]
        for key in ("id", "type", "message", "video_id", "video_status", "person_id")
        if key in event
    }


SENSORS: tuple[NetatmoSensorDescription, ...] = (
    NetatmoSensorDescription(
        key="last_event",
        translation_key="last_event",
        device_class=SensorDeviceClass.TIMESTAMP,
        capability=CAP_EVENTS,
        value_fn=_event_time,
        attributes_fn=_event_attributes,
    ),
    NetatmoSensorDescription(
        key="last_event_type",
        translation_key="last_event_type",
        capability=CAP_EVENTS,
        value_fn=lambda data: (data.last_event or {}).get("type"),
    ),
    NetatmoSensorDescription(
        key="sd_status",
        translation_key="sd_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        capability=CAP_CONFIG,
        value_fn=lambda data: _as_text(data.config_value("sd_status")),
    ),
    NetatmoSensorDescription(
        key="power_status",
        translation_key="power_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        capability=CAP_CONFIG,
        value_fn=lambda data: _as_text(data.config_value("alim_status")),
    ),
    NetatmoSensorDescription(
        key="firmware",
        translation_key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        capability=CAP_CONFIG,
        value_fn=lambda data: _as_text(data.config_value("firmware", "firmware_name")),
    ),
    NetatmoSensorDescription(
        key="wifi_strength",
        translation_key="wifi_strength",
        entity_category=EntityCategory.DIAGNOSTIC,
        capability=CAP_CONFIG,
        value_fn=lambda data: _as_text(
            data.config_value("wifi_status", "wifi_strength")
        ),
    ),
)


def _as_text(value: Any) -> str | None:
    """Return ``value`` as a string, or None when the camera omits it."""
    return None if value is None else str(value)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NetatmoPresenceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors the camera actually reports."""
    coordinator = entry.runtime_data
    async_add_entities(
        NetatmoPresenceSensor(coordinator, description)
        for description in SENSORS
        if coordinator.supports(description.capability)
        and description.value_fn(coordinator.data) is not None
    )


class NetatmoPresenceSensor(NetatmoPresenceEntity, SensorEntity):
    """A read-only value reported by the camera."""

    entity_description: NetatmoSensorDescription

    def __init__(self, coordinator, description: NetatmoSensorDescription) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the current value."""
        return self.entity_description.value_fn(self.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the extra details attached to this sensor, if any."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.data)
