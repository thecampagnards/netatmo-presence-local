"""Constants for the Netatmo Presence (local) integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "netatmo_presence_local"

MANUFACTURER: Final = "Netatmo"
DEFAULT_MODEL: Final = "Smart Outdoor Camera (Presence)"

# Netatmo module types, as reported by get_config's ``type`` or by ping's
# ``product_name``. Firmwares differ on case -- a Presence answers "noc" to
# ping and "NOC" to get_config -- so lookups are case-insensitive.
MODEL_BY_TYPE: Final = {
    "noc": "Smart Outdoor Camera (Presence)",
    "nacamera": "Smart Indoor Camera (Welcome)",
    "ndb": "Smart Video Doorbell",
}

CONF_VKEY: Final = "vkey"
CONF_VERIFY_SSL: Final = "verify_ssl"

DEFAULT_SCAN_INTERVAL: Final = timedelta(seconds=30)
DEFAULT_TIMEOUT: Final = 10

# --- Floodlight -------------------------------------------------------------
FLOODLIGHT_MODE_ON: Final = "on"
FLOODLIGHT_MODE_OFF: Final = "off"
FLOODLIGHT_MODE_AUTO: Final = "auto"
FLOODLIGHT_MODES: Final = [
    FLOODLIGHT_MODE_ON,
    FLOODLIGHT_MODE_OFF,
    FLOODLIGHT_MODE_AUTO,
]

# Keys of the "night" sub-object returned by floodlight_get_config. Each one
# tells the camera which night-time trigger should switch the floodlight on
# while it is in "auto" mode.
NIGHT_TRIGGERS: Final = ("always", "person", "vehicle", "animal", "movement")

# HLS playlists, in preference order. Firmwares differ: the documented path
# is ``index.m3u8``, while some builds also serve a LAN-only ``index_local``
# variant that avoids the relay. The first one that answers is used.
STREAM_PATHS: Final = ("live/index_local.m3u8", "live/index.m3u8")

# In-band error code returned when the camera is already in the state a
# command asks for -- observed as HTTP 409 {"code": 7, "message": "Already on"}.
ALREADY_IN_STATE_CODE: Final = 7

# --- Capabilities -----------------------------------------------------------
# Probed once at setup: an entity is only created when its backing endpoint
# actually answers on this firmware.
CAP_FLOODLIGHT: Final = "floodlight"
CAP_CONFIG: Final = "config"
CAP_SNAPSHOT: Final = "snapshot"
CAP_STREAM: Final = "stream"
CAP_EVENTS: Final = "events"
CAP_MONITORING: Final = "monitoring"

# --- Services ---------------------------------------------------------------
SERVICE_SET_FLOODLIGHT: Final = "set_floodlight"
SERVICE_SET_NIGHT_TRIGGERS: Final = "set_night_triggers"
SERVICE_RAW_COMMAND: Final = "raw_command"

ATTR_MODE: Final = "mode"
ATTR_INTENSITY: Final = "intensity"
ATTR_COMMAND: Final = "command"
ATTR_PARAMS: Final = "params"
