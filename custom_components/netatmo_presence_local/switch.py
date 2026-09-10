"""Switches: video monitoring and the floodlight night triggers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NetatmoPresenceConfigEntry
from .api import NetatmoLocalError
from .const import CAP_FLOODLIGHT, CAP_MONITORING, NIGHT_TRIGGERS
from .coordinator import NetatmoPresenceCoordinator
from .entity import NetatmoPresenceEntity
from .helpers import merge_floodlight_config


@dataclass(frozen=True, kw_only=True)
class NetatmoSwitchDescription(SwitchEntityDescription):
    """Describes a Netatmo Presence switch."""

    value_fn: Callable[[NetatmoPresenceCoordinator], bool | None]
    set_fn: Callable[[NetatmoPresenceCoordinator, bool], Awaitable[Any]]
    # True when the camera cannot report this setting back, so Home Assistant
    # should offer explicit on/off buttons instead of a toggle.
    assumed_fn: Callable[[NetatmoPresenceCoordinator], bool] | None = None


def _night_setter(trigger: str) -> Callable[..., Awaitable[Any]]:
    """Return a setter flipping one night trigger of the floodlight."""

    async def _set(coordinator: NetatmoPresenceCoordinator, enabled: bool) -> Any:
        config = merge_floodlight_config(
            coordinator.data.floodlight, {"night": {trigger: enabled}}
        )
        return await coordinator.async_write_floodlight(config)

    return _set


MONITORING_SWITCH = NetatmoSwitchDescription(
    key="monitoring",
    translation_key="monitoring",
    device_class=SwitchDeviceClass.SWITCH,
    value_fn=lambda coordinator: coordinator.monitoring_state(),
    set_fn=lambda coordinator, enabled: coordinator.async_set_monitoring(enabled),
    assumed_fn=lambda coordinator: coordinator.data.monitoring is None,
)

NIGHT_SWITCHES: tuple[NetatmoSwitchDescription, ...] = tuple(
    NetatmoSwitchDescription(
        key=f"night_{trigger}",
        translation_key=f"night_{trigger}",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda coordinator, trigger=trigger: (
            coordinator.data.night_trigger(trigger)
        ),
        set_fn=_night_setter(trigger),
    )
    for trigger in NIGHT_TRIGGERS
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NetatmoPresenceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switches the camera actually supports."""
    coordinator = entry.runtime_data
    entities: list[NetatmoPresenceSwitch] = []

    if coordinator.supports(CAP_MONITORING):
        entities.append(NetatmoPresenceSwitch(coordinator, MONITORING_SWITCH))

    if coordinator.supports(CAP_FLOODLIGHT):
        # Only surface the triggers this firmware reports.
        entities.extend(
            NetatmoPresenceSwitch(coordinator, description)
            for description in NIGHT_SWITCHES
            if description.value_fn(coordinator) is not None
        )

    async_add_entities(entities)


class NetatmoPresenceSwitch(NetatmoPresenceEntity, SwitchEntity):
    """A boolean setting of the camera."""

    entity_description: NetatmoSwitchDescription

    def __init__(
        self,
        coordinator: NetatmoPresenceCoordinator,
        description: NetatmoSwitchDescription,
    ) -> None:
        """Initialise the switch."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the current state of the setting."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def assumed_state(self) -> bool:
        """Return whether the state is inferred rather than read back."""
        assumed_fn = self.entity_description.assumed_fn
        return assumed_fn is not None and assumed_fn(self.coordinator)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the setting."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the setting."""
        await self._async_set(False)

    async def _async_set(self, enabled: bool) -> None:
        """Push the new value and refresh."""
        try:
            await self.entity_description.set_fn(self.coordinator, enabled)
        except (NetatmoLocalError, ValueError) as err:
            raise HomeAssistantError(
                f"Setting {self.entity_description.key} failed: {err}"
            ) from err
        self.async_write_ha_state()
