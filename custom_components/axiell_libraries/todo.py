"""Read-only loan lists using Home Assistant's standard to-do presentation."""

from homeassistant.components.todo import TodoItem, TodoItemStatus, TodoListEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AxiellConfigEntry, AxiellEntity
from .models import Loan


def _description(loan: Loan) -> str | None:
    """Render optional safe catalogue fields without fetching or proxying covers."""
    lines = [
        f"{label}: {value}"
        for label, value in (
            ("Subtitle", loan.subtitle),
            ("Author", loan.author),
            ("ISBN", loan.isbn),
            ("Format", loan.format),
            ("Item ID", loan.item_id),
            ("Overdue", "Yes" if loan.overdue else "No"),
            ("Renewable", "Yes" if loan.can_renew else "No"),
            ("Renewal count", loan.renewal_count),
            ("Renewals remaining", loan.renewals_remaining),
            ("Renewal cost", loan.renewal_cost),
            (
                "Overdue specified",
                None
                if loan.overdue_specified is None
                else "Yes"
                if loan.overdue_specified
                else "No",
            ),
        )
        if value is not None
    ]
    lines.extend(
        f"{key}: {value}" for key, value in loan.bibliographic_metadata.items()
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
