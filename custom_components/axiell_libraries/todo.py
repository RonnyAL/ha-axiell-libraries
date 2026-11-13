"""Read-only loan lists using Home Assistant's standard to-do presentation."""

from homeassistant.components.todo import TodoItem, TodoItemStatus, TodoListEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AxiellConfigEntry, AxiellEntity
from .models import Loan

# Catalogue metadata uses provider-localized keys. Only bibliographic fields
# belong in descriptions; account-shaped or unknown keys must not leak through.
_BIBLIOGRAPHIC_KEYS = {"Utgiver", "Utgitt", "Publisher", "Year", "Publication year"}


def _description(loan: Loan) -> str | None:
    """Render optional safe catalogue fields without fetching or proxying covers."""
    lines = [
        f"{label}: {value}"
        for label, value in (
            ("Author", loan.author),
            ("ISBN", loan.isbn),
            ("Format", loan.format),
        )
        if value
    ]
    lines.extend(
        f"{key}: {value}"
        for key, value in loan.main_metadata.items()
        if key in _BIBLIOGRAPHIC_KEYS
    )
    if loan.description:
        lines.append(loan.description)
    if loan.image_url:
        lines.append(f"[Cover]({loan.image_url})")
    return "\n\n".join(lines) or None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AxiellConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add one read-only list for this account."""
    async_add_entities([AxiellTodo(entry)])


class AxiellTodo(AxiellEntity, TodoListEntity):
    """Display each issued copy independently; do not expose any mutations."""

    _attr_translation_key = "loans"
    _attr_icon = "mdi:bookshelf"
    _attr_supported_features = 0

    def __init__(self, entry: AxiellConfigEntry) -> None:
        super().__init__(entry, "loans")

    @property
    def todo_items(self) -> list[TodoItem]:
        return [
            TodoItem(
                uid=loan.loan_id,
                summary=loan.title,
                status=TodoItemStatus.NEEDS_ACTION,
                due=loan.due_date,
                description=_description(loan),
            )
            for loan in self.coordinator.data.loans
        ]
