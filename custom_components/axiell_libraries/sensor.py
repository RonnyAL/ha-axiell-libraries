"""Read-only loan counts and next due date for each library account."""

from datetime import date

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AxiellConfigEntry, AxiellEntity

_DESCRIPTIONS = (
    SensorEntityDescription(
        key="active_loans", translation_key="active_loans", icon="mdi:book-multiple"
    ),
    SensorEntityDescription(
        key="next_due_date",
        translation_key="next_due_date",
        device_class=SensorDeviceClass.DATE,
    ),
    SensorEntityDescription(
        key="overdue_loans", translation_key="overdue_loans", icon="mdi:book-alert"
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AxiellConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the three account sensors."""
    async_add_entities(
        AxiellSensor(entry, description) for description in _DESCRIPTIONS
    )


class AxiellSensor(AxiellEntity, SensorEntity):
    """Derive values from a successful snapshot; failed refreshes are unavailable."""

    def __init__(self, entry: AxiellConfigEntry, description: SensorEntityDescription):
        super().__init__(entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | date | None:
        loans = self.coordinator.data.loans
        if self.entity_description.key == "active_loans":
            return len(loans)
        if self.entity_description.key == "overdue_loans":
            # The provider remains authoritative, even for missing due dates.
            return sum(item.overdue for item in loans)
        return min((item.due_date for item in loans if item.due_date), default=None)
