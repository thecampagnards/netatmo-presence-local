"""Config flow for the Netatmo Presence (local) integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    NetatmoLocalAuthError,
    NetatmoLocalConnectionError,
    NetatmoLocalError,
    NetatmoLocalNotSupportedError,
    NetatmoPresenceLocalApi,
)
from .const import CONF_VKEY, DOMAIN
from .helpers import is_stable_unique_id, model_name

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_VKEY): str,
    }
)


class NetatmoPresenceLocalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the user-driven setup of a camera."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._reauth_entry_data: Mapping[str, Any] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the camera host and its vkey."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"error_detail": ""}

        if user_input is not None:
            host = _normalise_host(user_input[CONF_HOST])
            vkey = user_input[CONF_VKEY].strip().strip("/")
            try:
                identity = await _async_validate(self.hass, host, vkey)
            except NetatmoLocalAuthError as err:
                errors["base"] = "invalid_auth"
                placeholders["error_detail"] = str(err)
            except NetatmoLocalConnectionError as err:
                errors["base"] = "cannot_connect"
                placeholders["error_detail"] = str(err)
            except NetatmoLocalError as err:
                _LOGGER.exception("Unexpected answer from camera at %s", host)
                errors["base"] = "unknown"
                placeholders["error_detail"] = str(err)
            else:
                unique_id = identity.get("unique_id") or host
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: host, CONF_VKEY: vkey}
                )
                return self.async_create_entry(
                    title=identity["name"],
                    data={CONF_HOST: host, CONF_VKEY: vkey},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input or {}
            ),
            description_placeholders=placeholders,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user change the camera's address and device key."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        placeholders: dict[str, str] = {"error_detail": ""}

        if user_input is not None:
            host = _normalise_host(user_input[CONF_HOST])
            vkey = user_input[CONF_VKEY].strip().strip("/")
            try:
                identity = await _async_validate(self.hass, host, vkey)
            except NetatmoLocalAuthError as err:
                errors["base"] = "invalid_auth"
                placeholders["error_detail"] = str(err)
            except NetatmoLocalConnectionError as err:
                errors["base"] = "cannot_connect"
                placeholders["error_detail"] = str(err)
            except NetatmoLocalError as err:
                _LOGGER.exception("Unexpected answer from camera at %s", host)
                errors["base"] = "unknown"
                placeholders["error_detail"] = str(err)
            else:
                unique_id = identity["unique_id"]

                # Only refuse the change when both ids identify hardware and
                # they disagree -- that means a different camera. An id that
                # fell back to the host legitimately changes with the address.
                if is_stable_unique_id(unique_id) and is_stable_unique_id(
                    entry.unique_id
                ):
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_mismatch(reason="another_device")

                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=unique_id,
                    data_updates={CONF_HOST: host, CONF_VKEY: vkey},
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA,
                user_input or {CONF_HOST: entry.data[CONF_HOST]},
            ),
            description_placeholders=placeholders,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle a rejected vkey."""
        self._reauth_entry_data = entry_data
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a fresh vkey."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        host = entry.data[CONF_HOST]
        placeholders: dict[str, str] = {"host": host, "error_detail": ""}

        if user_input is not None:
            vkey = user_input[CONF_VKEY].strip().strip("/")
            try:
                await _async_validate(self.hass, host, vkey)
            except NetatmoLocalAuthError as err:
                errors["base"] = "invalid_auth"
                placeholders["error_detail"] = str(err)
            except NetatmoLocalConnectionError as err:
                errors["base"] = "cannot_connect"
                placeholders["error_detail"] = str(err)
            except NetatmoLocalError as err:
                _LOGGER.exception("Unexpected answer from camera at %s", host)
                errors["base"] = "unknown"
                placeholders["error_detail"] = str(err)
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_VKEY: vkey}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_VKEY): str}),
            description_placeholders=placeholders,
            errors=errors,
        )


async def _async_validate(hass, host: str, vkey: str) -> dict[str, Any]:
    """Check the camera answers and that the device key is accepted.

    ``ping`` lives under the device key on this hardware, so that is the route
    tried first. Firmwares that also expose it unscoped are handled, but the
    unscoped one is never required: demanding it rejected working cameras.
    """
    api = NetatmoPresenceLocalApi(async_get_clientsession(hass), host, vkey)

    identity: dict[str, Any] = {}
    key_accepted = False

    # Scoped ping: proves both that the camera is there and that the key opens
    # it. A firmware without it still validates through the floodlight, which
    # every Presence implements.
    for probe in (api.async_ping_scoped, api.async_get_floodlight_config):
        try:
            payload = await probe()
        except NetatmoLocalNotSupportedError as err:
            _LOGGER.debug("%s is not implemented: %s", probe.__name__, err)
            continue
        key_accepted = True
        if isinstance(payload, dict) and "product_name" in payload:
            identity = payload
        break

    if not key_accepted:
        # Nothing answered under the key. Distinguish "wrong key" from "not a
        # Netatmo camera" using the unscoped ping, where some firmwares reply.
        try:
            await api.async_ping()
        except NetatmoLocalError as err:
            raise NetatmoLocalError(
                "The camera did not answer any known command; check the "
                f"address and that it is a Netatmo camera ({err})"
            ) from err
        raise NetatmoLocalAuthError(
            "The camera answered, but no command is available under this device key"
        )

    if not identity:
        # Best effort: some firmwares only serve ping unscoped.
        try:
            payload = await api.async_ping()
        except NetatmoLocalError as err:
            _LOGGER.debug("Unscoped ping unavailable: %s", err)
        else:
            if isinstance(payload, dict):
                identity = payload

    # Prefer the camera's own id (its MAC) so the entry survives a DHCP lease
    # change; fall back to the host when the firmware does not expose it.
    unique_id: str | None = None
    name: str | None = None
    try:
        config = await api.async_get_config()
    except NetatmoLocalError as err:
        _LOGGER.debug("get_config unavailable during setup: %s", err)
    else:
        if isinstance(config, dict):
            raw_id = config.get("id") or config.get("mac")
            if isinstance(raw_id, str) and raw_id:
                unique_id = dr.format_mac(raw_id)
            raw_name = config.get("name")
            if isinstance(raw_name, str) and raw_name:
                name = raw_name

    return {
        "name": name or model_name(identity.get("product_name")),
        "unique_id": unique_id or host,
    }


def _normalise_host(raw: str) -> str:
    """Strip scheme, trailing slash and whitespace from a user-typed host."""
    host = raw.strip()
    if host.startswith(("http://", "https://")):
        host = urlparse(host).netloc or host
    return host.rstrip("/")
