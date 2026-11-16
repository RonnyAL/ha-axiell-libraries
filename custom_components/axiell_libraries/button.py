"""Request native coordinator refreshes for each library account."""

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AxiellConfigEntry, AxiellEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AxiellConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add one refresh control using the existing account coordinator."""
    async_add_entities([AxiellRefreshButton(entry)])


class AxiellRefreshButton(AxiellEntity, ButtonEntity):
    """Request a read; native last-pressed state does not indicate read success."""

    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, entry: AxiellConfigEntry) -> None:
        super().__init__(entry, "refresh")

    @property
    def available(self) -> bool:
        """Allow recovery requests even while loan content is withheld."""
        return not self.coordinator.closing

    async def async_press(self) -> None:
        """Use native debouncing, account serialization and provider cooldown."""
        if not self.coordinator.closing:
            await self.coordinator.async_request_refresh()
