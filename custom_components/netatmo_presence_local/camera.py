"""Live view and stills from the Netatmo Presence."""

from __future__ import annotations

import logging

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NetatmoPresenceConfigEntry
from .api import NetatmoLocalError
from .const import CAP_MONITORING, CAP_SNAPSHOT, CAP_STREAM
from .coordinator import NetatmoPresenceCoordinator
from .entity import NetatmoPresenceEntity
from .helpers import model_name

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NetatmoPresenceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the camera entity."""
    coordinator = entry.runtime_data
    if coordinator.supports(CAP_SNAPSHOT):
        async_add_entities([NetatmoPresenceCamera(coordinator)])


class NetatmoPresenceCamera(NetatmoPresenceEntity, Camera):
    """Still images over HTTP, live view over the camera's local HLS playlist."""

    # The camera is the device's primary entity, so it carries the device
    # name itself rather than a translated suffix.
    _attr_name = None

    def __init__(self, coordinator: NetatmoPresenceCoordinator) -> None:
        """Initialise the camera entity."""
        super().__init__(coordinator, "camera")
        Camera.__init__(self)

        features = CameraEntityFeature(0)
        if coordinator.supports(CAP_STREAM):
            features |= CameraEntityFeature.STREAM
        if coordinator.supports(CAP_MONITORING):
            features |= CameraEntityFeature.ON_OFF
        self._attr_supported_features = features

    @property
    def is_on(self) -> bool:
        """Return whether video monitoring is enabled."""
        monitoring = self.coordinator.monitoring_state()
        # Firmwares without get_config never report it and we may not have
        # switched it ourselves yet; assume the camera is live rather than
        # showing it as disabled.
        return True if monitoring is None else monitoring

    @property
    def motion_detection_enabled(self) -> bool:
        """Presence detects motion whenever monitoring is on."""
        return self.is_on

    @property
    def brand(self) -> str:
        """Return the camera brand."""
        return "Netatmo"

    @property
    def model(self) -> str | None:
        """Return the camera model."""
        return model_name(
            self.data.config_value("type"),
            self.coordinator.device_info_payload.get("product_name"),
        )

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image from the camera."""
        try:
            return await self.coordinator.api.async_get_snapshot()
        except NetatmoLocalError as err:
            _LOGGER.debug("Snapshot failed: %s", err)
            return None

    async def stream_source(self) -> str | None:
        """Return the local HLS playlist URL."""
        if self.coordinator.stream_path is None:
            return None
        return self.coordinator.api.stream_url(self.coordinator.stream_path)

    async def async_turn_on(self) -> None:
        """Enable video monitoring."""
        await self._async_set_monitoring(True)

    async def async_turn_off(self) -> None:
        """Disable video monitoring."""
        await self._async_set_monitoring(False)

    async def _async_set_monitoring(self, enabled: bool) -> None:
        """Push the monitoring state and refresh."""
        try:
            await self.coordinator.async_set_monitoring(enabled)
        except NetatmoLocalError as err:
            raise HomeAssistantError(f"Switching monitoring failed: {err}") from err
        self.async_write_ha_state()
