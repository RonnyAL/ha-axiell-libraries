"""Home Assistant integration for Solus-powered Axiell libraries."""

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AxiellCoordinator
from .solus import SolusClient

PLATFORMS = (Platform.SENSOR, Platform.TODO)
type AxiellConfigEntry = ConfigEntry[AxiellCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: AxiellConfigEntry) -> bool:
    """Create one isolated account session and let the coordinator log in once."""
    session = async_create_clientsession(
        hass, auto_cleanup=False, cookie_jar=aiohttp.CookieJar()
    )
    try:
        client = SolusClient(
            session,
            entry.data["app_id"],
            entry.data["server_url"],
            entry.data["device_id"],
            entry.data.get("locale", "nb-NO"),
        )
        coordinator = AxiellCoordinator(hass, entry, client)
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        # Detach this session, including cancellation; HA owns the connector.
        session.detach()
        raise
    entry.async_on_unload(session.detach)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AxiellConfigEntry) -> bool:
    """Unload this account's entities; its unload callback detaches the session."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


class AxiellEntity(CoordinatorEntity[AxiellCoordinator]):
    """Share the account's coordinator and safe, stable device identity."""

    _attr_has_entity_name = True

    def __init__(self, entry: AxiellConfigEntry, key: str) -> None:
        super().__init__(entry.runtime_data)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data["library_name"],
            manufacturer="Axiell / Solus",
            entry_type=DeviceEntryType.SERVICE,
        )
