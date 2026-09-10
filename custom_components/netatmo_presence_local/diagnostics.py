"""Diagnostics support, with the device secret redacted."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import NetatmoPresenceConfigEntry
from .const import CONF_VKEY

TO_REDACT = {CONF_VKEY, "vpn_url", "local_url", "id", "mac", "wifi_mac", "ssid"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NetatmoPresenceConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "capabilities": sorted(coordinator.capabilities),
        "ping": async_redact_data(coordinator.device_info_payload, TO_REDACT),
        "floodlight": data.floodlight,
        "config": async_redact_data(data.config, TO_REDACT),
        "event_count": len(data.events),
        "last_event": async_redact_data(data.last_event or {}, TO_REDACT),
    }
