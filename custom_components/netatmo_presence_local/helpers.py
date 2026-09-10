"""Pure helpers, free of Home Assistant and aiohttp imports.

Keeping the payload-shaping logic here means it can be unit-tested without a
Home Assistant test harness.
"""

from __future__ import annotations

from typing import Any

from .const import (
    DEFAULT_MODEL,
    FLOODLIGHT_MODE_AUTO,
    FLOODLIGHT_MODE_OFF,
    MODEL_BY_TYPE,
)

_NESTED_CONFIG_KEYS = ("module", "camera", "home")

# The modes the floodlight can rest in. A forced ``on`` is not one of them,
# and neither is an empty or unknown value the camera might report.
PASSIVE_MODES = frozenset({FLOODLIGHT_MODE_OFF, FLOODLIGHT_MODE_AUTO})


def merge_floodlight_config(
    current: dict[str, Any], changes: dict[str, Any]
) -> dict[str, Any]:
    """Return ``current`` overlaid with ``changes``.

    The camera replaces the whole configuration object on every write, so a
    partial update has to be rebased on what it currently reports. The
    ``night`` sub-object is merged key by key rather than replaced.
    """
    merged: dict[str, Any] = {
        key: dict(value) if isinstance(value, dict) else value
        for key, value in current.items()
    }
    for key, value in changes.items():
        if key == "night" and isinstance(value, dict):
            night = merged.get("night")
            merged["night"] = (
                {**night, **value} if isinstance(night, dict) else dict(value)
            )
        else:
            merged[key] = value

    # Writing an intensity while no mode is known would leave the camera in an
    # undefined state; automatic is the neutral choice.
    if merged.get("mode") is None:
        merged["mode"] = FLOODLIGHT_MODE_AUTO
    return merged


def extract_events(payload: Any) -> list[dict[str, Any]]:
    """Normalise the shapes ``get_events_until`` can return, newest first."""
    if isinstance(payload, list):
        events = payload
    elif isinstance(payload, dict):
        events = payload.get("events") or payload.get("events_list") or []
    else:
        return []
    if not isinstance(events, list):
        return []
    cleaned = [event for event in events if isinstance(event, dict)]
    cleaned.sort(key=lambda event: _timestamp(event), reverse=True)
    return cleaned


def _timestamp(event: dict[str, Any]) -> float:
    """Return an event's epoch time, or 0 when it has none."""
    value = event.get("time")
    return float(value) if isinstance(value, int | float) else 0.0


def config_lookup(config: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first of ``keys`` found in a ``get_config`` payload.

    Firmwares nest the module payload differently -- flat, under ``module``,
    or inside a ``modules`` list -- so all the known shapes are searched.
    """
    if not isinstance(config, dict):
        return None

    candidates: list[dict[str, Any]] = [config]
    for nested_key in _NESTED_CONFIG_KEYS:
        nested = config.get(nested_key)
        if isinstance(nested, dict):
            candidates.append(nested)
    modules = config.get("modules")
    if isinstance(modules, list):
        candidates.extend(module for module in modules if isinstance(module, dict))

    for candidate in candidates:
        for key in keys:
            if key in candidate:
                return candidate[key]
    return None


def parse_on_off(value: Any) -> bool | None:
    """Interpret the several ways the camera spells a boolean status."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("on", "true", "enabled", "1"):
            return True
        if lowered in ("off", "false", "disabled", "0"):
            return False
    if isinstance(value, int):
        return bool(value)
    return None


def model_name(*candidates: Any) -> str:
    """Return a human model name from the first recognised candidate.

    Callers pass whatever the camera offered, best source first: get_config's
    ``type`` when available, otherwise ping's ``product_name`` -- a Presence
    answers "noc" there.
    """
    for candidate in candidates:
        if isinstance(candidate, str):
            model = MODEL_BY_TYPE.get(candidate.strip().lower())
            if model is not None:
                return model
    return DEFAULT_MODEL


def is_stable_unique_id(value: Any) -> bool:
    """Return True when a unique id identifies the hardware, not its address.

    Setup uses the camera's MAC when ``get_config`` exposes it, and falls back
    to the host name otherwise. Only the former survives the camera moving to
    a new address, so only the former is worth comparing across a
    reconfiguration.
    """
    if not isinstance(value, str):
        return False
    parts = value.split(":")
    return len(parts) == 6 and all(
        len(part) == 2 and all(c in "0123456789abcdef" for c in part.lower())
        for part in parts
    )


def remembered_passive_mode(previous: Any, observed: Any) -> str | None:
    """Return the floodlight's resting mode, given what was just observed.

    "Resting" means any mode other than a forced ``on``: the state the
    floodlight sits in when nobody is holding the light on. Tracking it on
    every poll means turning the light off can put the camera back where it
    was, no matter how it came to be on -- this integration, the Netatmo app,
    or the mode selector.
    """
    if observed in PASSIVE_MODES:
        return observed
    return previous if previous in PASSIVE_MODES else None


def restore_target(remembered: Any) -> str:
    """Return the mode to switch to when the floodlight is turned off.

    Falls back to ``off`` when no resting mode was ever seen -- that happens
    when Home Assistant starts up with the light already forced on.
    """
    if isinstance(remembered, str) and remembered:
        return remembered
    return FLOODLIGHT_MODE_OFF
