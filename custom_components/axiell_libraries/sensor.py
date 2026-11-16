"""Read-only loan counts and next due date for each library account."""

from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AxiellConfigEntry, AxiellEntity

_DESCRIPTIONS = (
    SensorEntityDescription(
        key="last_successful_refresh",
        translation_key="last_successful_refresh",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="data_freshness",
        translation_key="data_freshness",
        device_class=SensorDeviceClass.ENUM,
        options=["fresh", "stale", "unavailable"],
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:cloud-check-outline",
    ),
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
    """Add the loan sensors and account freshness diagnostic."""
    async_add_entities(
        AxiellSensor(entry, description) for description in _DESCRIPTIONS
    )


class AxiellSensor(AxiellEntity, SensorEntity):
    """Derive loan values from the last snapshot and expose its freshness."""

    _unrecorded_attributes = frozenset({"loans"})

    def __init__(self, entry: AxiellConfigEntry, description: SensorEntityDescription):
        super().__init__(entry, description.key)
        self.entity_description = description

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the current issued copies only on the active-loan count."""
        attributes = self.coordinator.freshness_attributes
        if (
            self.entity_description.key == "active_loans"
            and self.coordinator.snapshot_available
        ):
            attributes["loans"] = [
                loan.as_dict() for loan in self.coordinator.data.loans
            ]
        return attributes

    @property
    def available(self) -> bool:
        if self.entity_description.key in {"data_freshness", "last_successful_refresh"}:
            return True
        return super().available

    @property
    def native_value(self) -> int | str | date | datetime | None:
        if self.entity_description.key == "data_freshness":
            return self.coordinator.data_freshness
        if self.coordinator.data is None:
            return None
        if self.entity_description.key == "last_successful_refresh":
            return self.coordinator.data.fetched_at
        loans = self.coordinator.data.loans
        if self.entity_description.key == "active_loans":
            return len(loans)
        if self.entity_description.key == "overdue_loans":
            # The provider remains authoritative, even for missing due dates.
            return sum(item.overdue for item in loans)
        return min((item.due_date for item in loans if item.due_date), default=None)
