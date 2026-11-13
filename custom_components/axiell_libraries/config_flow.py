"""Configure one library and card with a persistent server-facing DeviceID."""

import hashlib
import secrets
from contextlib import contextmanager
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import solus
from .const import DOMAIN

_MANUAL = "manual"
_PIN = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
_PIN_SCHEMA = vol.Schema({vol.Required("pin"): _PIN})


class AxiellLibrariesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Select a library, then validate the account once per submission."""

    VERSION = 1

    def __init__(self) -> None:
        self._device_id: str | None = None
        self._libraries: dict[str, solus.Library] | None = None
        self._library: solus.Library | None = None

    @contextmanager
    def _session(self):
        """Use HA's connector with an isolated cookie jar for each operation."""
        session = async_create_clientsession(
            self.hass, auto_cleanup=False, cookie_jar=aiohttp.CookieJar()
        )
        try:
            yield session
        finally:
            session.detach()

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Show a searchable selection of nearby results and a manual option."""
        if self._device_id is None:
            self._device_id = secrets.token_hex(8)
        if self._libraries is None:
            self._libraries = {}
            latitude, longitude = self.hass.config.latitude, self.hass.config.longitude
            if latitude is not None and longitude is not None:
                try:
                    with self._session() as session:
                        libraries = await solus.async_find_nearby(
                            session, latitude, longitude
                        )
                    self._libraries = {item.location_id: item for item in libraries}
                except solus.SolusError:
                    pass  # Manual lookup remains available on provider failures.
        if not self._libraries or (user_input and user_input["library"] == _MANUAL):
            return await self.async_step_library_manual()
        if user_input:
            self._library = self._libraries[user_input["library"]]
            return await self.async_step_credentials()
        options = [
            {"value": item.location_id, "label": item.name}
            for item in self._libraries.values()
        ]
        options.append({"value": _MANUAL, "label": "Enter LocationID manually"})
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("library"): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.DROPDOWN,
                            custom_value=False,
                            translation_key="library",
                        )
                    )
                }
            ),
        )

    async def async_step_library_manual(self, user_input=None) -> ConfigFlowResult:
        """Resolve an exact LocationID without inventing global text search."""
        errors = {}
        if user_input:
            try:
                with self._session() as session:
                    self._library = await solus.async_lookup_location(
                        session, user_input["location_id"].strip()
                    )
            except solus.SolusError:
                errors["base"] = "cannot_connect"
            else:
                return await self.async_step_credentials()
        return self.async_show_form(
            step_id="library_manual",
            data_schema=vol.Schema({vol.Required("location_id"): str}),
            errors=errors,
        )

    async def _validate(self, data: dict[str, Any]) -> str | None:
        """Drop transient login cookies and tokens after each validation."""
        try:
            with self._session() as session:
                client = solus.SolusClient(
                    session, data["app_id"], data["server_url"], data["device_id"]
                )
                await client.async_login(data["card"], data["pin"])
        except solus.SolusAuthError:
            return "invalid_auth"
        except solus.SolusError:
            return "cannot_connect"
        return None

    async def async_step_credentials(self, user_input=None) -> ConfigFlowResult:
        """Reject existing accounts before sending credentials upstream."""
        errors = {}
        if user_input:
            # Whitespace is presentation only; preserve case and leading zeros.
            card = "".join(user_input["card"].split())
            library = self._library
            assert library is not None
            unique_id = hashlib.sha256(f"{library.app_id}:{card}".encode()).hexdigest()
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            data = {
                "location_id": library.location_id,
                "library_name": library.name,
                "app_id": library.app_id,
                "server_url": library.server_url,
                "card": card,
                "pin": user_input["pin"],
                "device_id": self._device_id,
            }
            if error := await self._validate(data):
                errors["base"] = error
            else:
                return self.async_create_entry(title=library.name, data=data)
        return self.async_show_form(
            step_id="credentials",
            data_schema=vol.Schema(
                {vol.Required("card"): str, vol.Required("pin"): _PIN}
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data) -> ConfigFlowResult:
        """Use the existing account identity and device, accepting only a new PIN."""
        return await self.async_step_reauth_confirm()

    async def _update_pin(self, entry: ConfigEntry, step_id: str, user_input):
        errors = {}
        if user_input:
            if error := await self._validate({**entry.data, "pin": user_input["pin"]}):
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={"pin": user_input["pin"]}
                )
        return self.async_show_form(
            step_id=step_id, data_schema=_PIN_SCHEMA, errors=errors
        )

    async def async_step_reauth_confirm(self, user_input=None) -> ConfigFlowResult:
        """Validate the new PIN while preserving all stored identity fields."""
        return await self._update_pin(
            self._get_reauth_entry(), "reauth_confirm", user_input
        )

    async def async_step_reconfigure(self, user_input=None) -> ConfigFlowResult:
        """Update the PIN for this entry's fixed library and card pair."""
        return await self._update_pin(
            self._get_reconfigure_entry(), "reconfigure", user_input
        )
