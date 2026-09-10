"""The Netatmo Presence (local) integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import NetatmoLocalError, NetatmoPresenceLocalApi
from .const import (
    ATTR_COMMAND,
    ATTR_PARAMS,
    CONF_VKEY,
    DOMAIN,
    SERVICE_RAW_COMMAND,
)
from .coordinator import NetatmoPresenceCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CAMERA,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

# Runtime data lives on the entry; HA subscripts ConfigEntry since 2024.8.
NetatmoPresenceConfigEntry = ConfigEntry

RAW_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required(ATTR_COMMAND): cv.string,
        vol.Optional(ATTR_PARAMS, default={}): {cv.string: cv.string},
    }
)


async def async_setup_entry(
    hass: HomeAssistant, entry: NetatmoPresenceConfigEntry
) -> bool:
    """Set up a camera from a config entry."""
    api = NetatmoPresenceLocalApi(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_VKEY],
    )
    coordinator = NetatmoPresenceCoordinator(hass, entry, api)

    try:
        await coordinator.async_discover()
    except NetatmoLocalError as err:
        raise ConfigEntryNotReady(str(err)) from err

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: NetatmoPresenceConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(
    hass: HomeAssistant, entry: NetatmoPresenceConfigEntry
) -> None:
    """Reload a config entry after its options changed."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the domain-level services once."""
    if hass.services.has_service(DOMAIN, SERVICE_RAW_COMMAND):
        return

    async def _handle_raw_command(call: ServiceCall) -> ServiceResponse:
        """Call an arbitrary command on the camera and return its answer."""
        coordinator = _coordinator_for_device(hass, call.data["device_id"])
        try:
            result = await coordinator.api.async_raw_command(
                call.data[ATTR_COMMAND], call.data.get(ATTR_PARAMS) or None
            )
        except NetatmoLocalError as err:
            raise HomeAssistantError(str(err)) from err
        await coordinator.async_request_refresh()
        return {"result": result}

    hass.services.async_register(
        DOMAIN,
        SERVICE_RAW_COMMAND,
        _handle_raw_command,
        schema=RAW_COMMAND_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )


def _coordinator_for_device(
    hass: HomeAssistant, device_id: str
) -> NetatmoPresenceCoordinator:
    """Return the coordinator backing a device registry entry."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise HomeAssistantError(f"Unknown device {device_id}")

    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == DOMAIN and hasattr(entry, "runtime_data"):
            return entry.runtime_data

    raise HomeAssistantError(f"Device {device_id} is not a Netatmo Presence camera")
