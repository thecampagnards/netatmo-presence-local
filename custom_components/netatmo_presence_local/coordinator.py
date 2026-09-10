"""Polling coordinator and capability discovery."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    NetatmoLocalAuthError,
    NetatmoLocalConnectionError,
    NetatmoLocalError,
    NetatmoPresenceLocalApi,
)
from .const import (
    CAP_CONFIG,
    CAP_EVENTS,
    CAP_FLOODLIGHT,
    CAP_MONITORING,
    CAP_SNAPSHOT,
    CAP_STREAM,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    STREAM_PATHS,
)
from .helpers import (
    config_lookup,
    extract_events,
    parse_on_off,
    remembered_passive_mode,
    restore_target,
)

_LOGGER = logging.getLogger(__name__)

# Endpoints probed once at setup. All of them are read-only: ``changestatus``
# is probed without its ``status`` parameter so the camera answers with an
# in-band parameter error rather than actually toggling monitoring.
_PROBES: dict[str, tuple[str, dict[str, Any] | None]] = {
    CAP_FLOODLIGHT: ("command/floodlight_get_config", None),
    CAP_CONFIG: ("command/get_config", None),
    CAP_EVENTS: ("command/get_events_until", {"offset": 1}),
    CAP_SNAPSHOT: ("live/snapshot_720.jpg", None),
}


@dataclass
class PresenceData:
    """Snapshot of everything read from the camera in one poll."""

    floodlight: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def floodlight_mode(self) -> str | None:
        """Return the floodlight mode, if known."""
        mode = self.floodlight.get("mode")
        return mode if isinstance(mode, str) else None

    @property
    def floodlight_intensity(self) -> int | None:
        """Return the floodlight intensity in percent, if known."""
        value = self.floodlight.get("intensity")
        return int(value) if isinstance(value, int | float) else None

    def night_trigger(self, name: str) -> bool | None:
        """Return the state of one night trigger, if known."""
        night = self.floodlight.get("night")
        if not isinstance(night, dict) or name not in night:
            return None
        return bool(night[name])

    def config_value(self, *keys: str) -> Any:
        """Return the first of ``keys`` found in the config payload."""
        return config_lookup(self.config, keys)

    @property
    def monitoring(self) -> bool | None:
        """Return whether video monitoring is enabled, if known."""
        return parse_on_off(self.config_value("status", "monitoring"))

    @property
    def last_event(self) -> dict[str, Any] | None:
        """Return the most recent event, if any."""
        return self.events[0] if self.events else None


class NetatmoPresenceCoordinator(DataUpdateCoordinator[PresenceData]):
    """Poll the camera and expose which commands it supports."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: NetatmoPresenceLocalApi,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {api.host}",
            update_interval=DEFAULT_SCAN_INTERVAL,
            config_entry=entry,
        )
        self.api = api
        self.capabilities: set[str] = set()
        self.device_info_payload: dict[str, Any] = {}
        self.stream_path: str | None = None
        # Firmwares without get_config cannot report whether monitoring is on,
        # so it is tracked from the commands this integration itself sends.
        self.assumed_monitoring: bool | None = None
        # The mode the floodlight rests in, so turning the light off can put
        # it back rather than always disabling it.
        self.passive_mode: str | None = None

    async def async_discover(self) -> None:
        """Probe the firmware once and record what it supports."""
        # ``ping`` is normally served under the device key. Some firmwares also
        # answer it unscoped; neither is guaranteed, so a failure here is not
        # fatal -- the capability probes below decide whether setup succeeds.
        for ping in (self.api.async_ping_scoped, self.api.async_ping):
            try:
                payload = await ping()
            except NetatmoLocalError as err:
                _LOGGER.debug("Ping via %s failed: %s", ping.__name__, err)
                continue
            if isinstance(payload, dict):
                self.device_info_payload = payload
                break

        for capability, (path, params) in _PROBES.items():
            try:
                supported = await self.api.probe(
                    path, params, read_body=capability != CAP_SNAPSHOT
                )
            except NetatmoLocalAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            if supported:
                self.capabilities.add(capability)

        # Firmwares disagree on the playlist path, so try each in turn and
        # keep the first that answers.
        for path in STREAM_PATHS:
            if await self.api.probe(path, read_body=False):
                self.stream_path = path
                self.capabilities.add(CAP_STREAM)
                break

        # ``changestatus`` only routes when its ``status`` parameter is present,
        # so it cannot be probed without actually switching monitoring. It is
        # part of the documented command set and was verified on hardware, so
        # it is taken as available once anything else answered.
        if self.capabilities:
            self.capabilities.add(CAP_MONITORING)

        if not self.capabilities:
            # Every command 404s: the camera is reachable but the device key
            # does not open anything, so ask the user for a new one.
            raise ConfigEntryAuthFailed(
                "The camera answered but exposes no command under this device key"
            )

        _LOGGER.debug(
            "Discovered capabilities on %s: %s",
            self.api.host,
            sorted(self.capabilities),
        )

    def remember_passive_mode(self, observed: str | None) -> None:
        """Record ``observed`` if it is a resting mode rather than forced on."""
        self.passive_mode = remembered_passive_mode(self.passive_mode, observed)

    @property
    def restore_mode(self) -> str:
        """Return the mode to fall back to when the floodlight is turned off."""
        return restore_target(self.passive_mode)

    async def async_set_monitoring(self, enabled: bool) -> None:
        """Switch video monitoring and remember the state we put it in."""
        await self.api.async_set_monitoring(enabled)
        self.assumed_monitoring = enabled
        await self.async_request_refresh()

    def monitoring_state(self) -> bool | None:
        """Return monitoring as reported, falling back to what we last set."""
        reported = self.data.monitoring if self.data else None
        return reported if reported is not None else self.assumed_monitoring

    def supports(self, capability: str) -> bool:
        """Return whether the camera implements ``capability``."""
        return capability in self.capabilities

    async def _async_update_data(self) -> PresenceData:
        """Fetch the current state of the camera."""
        data = PresenceData()
        try:
            if self.supports(CAP_FLOODLIGHT):
                payload = await self.api.async_get_floodlight_config()
                if isinstance(payload, dict):
                    data.floodlight = payload
                    self.remember_passive_mode(data.floodlight_mode)

            if self.supports(CAP_CONFIG):
                payload = await self.api.async_get_config()
                if isinstance(payload, dict):
                    data.config = payload

            if self.supports(CAP_EVENTS):
                payload = await self.api.async_get_events()
                data.events = extract_events(payload)
        except NetatmoLocalAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (NetatmoLocalConnectionError, NetatmoLocalError) as err:
            raise UpdateFailed(str(err)) from err

        return data
