"""Detection binary sensors derived from the camera's event log."""

from __future__ import annotations

import time
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NetatmoPresenceConfigEntry
from .const import CAP_EVENTS
from .coordinator import PresenceData
from .entity import NetatmoPresenceEntity

# The camera is polled, so a detection is reported for a short window after
# its event timestamp. Kept comfortably above the poll interval so an event
# cannot slip between two polls unnoticed.
DETECTION_WINDOW = 90


@dataclass(frozen=True, kw_only=True)
class NetatmoDetectionDescription(BinarySensorEntityDescription):
    """Describes a detection sensor backed by one or more event types."""

    event_types: tuple[str, ...]


DETECTIONS: tuple[NetatmoDetectionDescription, ...] = (
    NetatmoDetectionDescription(
        key="motion",
        translation_key="motion",
        device_class=BinarySensorDeviceClass.MOTION,
        event_types=("movement", "motion"),
    ),
    NetatmoDetectionDescription(
        key="person",
        translation_key="person",
        device_class=BinarySensorDeviceClass.OCCUPANCY,
        event_types=("human", "person"),
    ),
    NetatmoDetectionDescription(
        key="vehicle",
        translation_key="vehicle",
        device_class=BinarySensorDeviceClass.MOTION,
        event_types=("vehicle", "car"),
    ),
    NetatmoDetectionDescription(
        key="animal",
        translation_key="animal",
        device_class=BinarySensorDeviceClass.MOTION,
        event_types=("animal",),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NetatmoPresenceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the detection sensors."""
    coordinator = entry.runtime_data
    if not coordinator.supports(CAP_EVENTS):
        return
    async_add_entities(
        NetatmoDetectionSensor(coordinator, description) for description in DETECTIONS
    )


class NetatmoDetectionSensor(NetatmoPresenceEntity, BinarySensorEntity):
    """On while the camera reported a matching event very recently."""

    entity_description: NetatmoDetectionDescription

    def __init__(self, coordinator, description: NetatmoDetectionDescription) -> None:
        """Initialise the detection sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        """Return whether a matching event happened within the window."""
        return _recent(self.data, self.entity_description.event_types)


def _recent(data: PresenceData, event_types: tuple[str, ...]) -> bool:
    """Return True when an event of one of ``event_types`` is fresh enough."""
    cutoff = time.time() - DETECTION_WINDOW
    for event in data.events:
        timestamp = event.get("time")
        if not isinstance(timestamp, int | float) or timestamp < cutoff:
            # Events are sorted newest first, so the rest is older still.
            break
        if str(event.get("type", "")).lower() in event_types:
            return True
    return False
