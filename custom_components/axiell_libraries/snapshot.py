"""Private, account-bound persistence of normalized public loan snapshots.

Limits are deliberately generous: 1,000 loans, 32 KiB per text value and 2 MiB
of JSON overall. No transport data or renewal authorization is reconstructed.
"""

import hashlib
import json
import logging
import math
from datetime import date, datetime
from types import MappingProxyType

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .models import LibrarySnapshot, Loan, _cover_url

_LOGGER = logging.getLogger(__name__)
_MAX_BYTES = 2 * 1024 * 1024
_MAX_LOANS = 1000
_MAX_TEXT = 32768
_WITHHELD = frozenset({"credentials", "security"})
_TEXT_FIELDS = (
    "loan_id",
    "record_id",
    "title",
    "source",
    "subtitle",
    "item_id",
    "author",
    "image_url",
    "isbn",
    "description",
    "format",
)
_COUNT_FIELDS = ("renewal_count", "renewals_remaining")
_LOAN_FIELDS = frozenset(
    (
        *_TEXT_FIELDS,
        *_COUNT_FIELDS,
        "due_date",
        "can_renew",
        "overdue",
        "overdue_specified",
        "renewal_cost",
        "main_metadata",
    )
)
_ROOT_FIELDS = frozenset({"schema", "identity", "fetched_at", "loans", "withheld"})
_STORAGE_ERRORS = (OSError, HomeAssistantError, ValueError, TypeError, OverflowError)


def _identity(entry: ConfigEntry) -> str:
    """Use the config flow's card normalization; preserve case and leading zeros."""
    canonical = [
        entry.entry_id,
        entry.data["app_id"],
        "".join(entry.data["card"].split()),
    ]
    return hashlib.sha256(json.dumps(canonical, ensure_ascii=True).encode()).hexdigest()


def _text(value: object, *, required: bool = False) -> None:
    if value is None and not required:
        return
    if not isinstance(value, str) or len(value) > _MAX_TEXT:
        raise ValueError
    if required and not value.strip():
        raise ValueError


def _decode(payload: object, identity: str) -> tuple[LibrarySnapshot, str | None]:
    if not isinstance(payload, dict) or payload.keys() != _ROOT_FIELDS:
        raise ValueError
    if type(payload["schema"]) is not int or payload["schema"] != 1:
        raise ValueError
    if payload["identity"] != identity or payload["withheld"] not in (*_WITHHELD, None):
        raise ValueError
    # Bound the complete public payload and reject non-finite JSON scalars.
    if len(json.dumps(payload, allow_nan=False).encode()) > _MAX_BYTES:
        raise ValueError
    if not isinstance(payload["fetched_at"], str):
        raise ValueError
    timestamp = datetime.fromisoformat(payload["fetched_at"])
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError
    rows = payload["loans"]
    if not isinstance(rows, list) or len(rows) > _MAX_LOANS:
        raise ValueError
    loans = []
    identifiers = set()
    for row in rows:
        if not isinstance(row, dict) or row.keys() != _LOAN_FIELDS:
            raise ValueError
        for key in _TEXT_FIELDS:
            _text(row[key], required=key in {"loan_id", "title"})
        if not all(isinstance(row[key], str) for key in ("record_id", "source")):
            raise ValueError
        # Record/source may legitimately be unknown; loan IDs and titles may not.
        if row["loan_id"] in identifiers:
            raise ValueError
        identifiers.add(row["loan_id"])
        for key in ("can_renew", "overdue"):
            if type(row[key]) is not bool:
                raise ValueError
        if (
            row["overdue_specified"] is not None
            and type(row["overdue_specified"]) is not bool
        ):
            raise ValueError
        for key in _COUNT_FIELDS:
            if row[key] is not None and (type(row[key]) is not int or row[key] < 0):
                raise ValueError
        cost = row["renewal_cost"]
        if cost is not None and (
            type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0
        ):
            raise ValueError
        if row["image_url"] is not None and _cover_url(row["image_url"]) is None:
            raise ValueError
        due = row["due_date"]
        if due is not None:
            if not isinstance(due, str):
                raise ValueError
            due = date.fromisoformat(due)
            if due.isoformat() != row["due_date"]:
                raise ValueError
        metadata = row["main_metadata"]
        if not isinstance(metadata, dict) or len(metadata) > 32:
            raise ValueError
        for key, value in metadata.items():
            _text(key, required=True)
            _text(value, required=True)
        loan = Loan(
            **{**row, "due_date": due, "main_metadata": MappingProxyType(metadata)}
        )
        if dict(loan.bibliographic_metadata) != metadata:
            raise ValueError
        loans.append(loan)
    return LibrarySnapshot(tuple(loans), timestamp), payload["withheld"]


class SnapshotStore:
    """Use supported atomic Store methods, with finite sticky withholding state."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry_id = entry.entry_id
        self._identity = _identity(entry)
        self._key = f"{DOMAIN}.{entry.entry_id}.snapshot"
        self._warned = False
        # At most one finite category per configured entry; removal clears it.
        self._blocks: dict[str, tuple[str, str]] = hass.data.setdefault(
            f"{DOMAIN}_snapshot_blocks", {}
        )

    def _store(self) -> Store[dict]:
        return Store(self._hass, 1, self._key, private=True, atomic_writes=True)

    def matches_identity(self, entry: ConfigEntry) -> bool:
        """Compare against the identity captured before any live entry updates."""
        return self._identity == _identity(entry)

    @property
    def withheld(self) -> str | None:
        """Return only a block belonging to this account and entry."""
        block = self._blocks.get(self._entry_id)
        return block[1] if block and block[0] == self._identity else None

    def _warn(self) -> None:
        if not self._warned:
            self._warned = True
            _LOGGER.warning("Unable to persist or restore private library snapshot")

    def _encode(self, snapshot: LibrarySnapshot, withheld: str | None = None) -> dict:
        rows = []
        for loan in snapshot.loans:
            row = {
                key: getattr(loan, key)
                for key in _LOAN_FIELDS - {"main_metadata", "due_date"}
            }
            row["main_metadata"] = dict(loan.bibliographic_metadata)
            row["due_date"] = loan.due_date.isoformat() if loan.due_date else None
            rows.append(row)
        payload = {
            "schema": 1,
            "identity": self._identity,
            "fetched_at": snapshot.fetched_at.isoformat(),
            "loans": rows,
            "withheld": withheld,
        }
        _decode(payload, self._identity)
        return payload

    async def async_load(self) -> tuple[LibrarySnapshot, str | None] | None:
        """Reject the entire invalid account file, retaining only safe diagnostics."""
        try:
            if (payload := await self._store().async_load()) is None:
                return None
            snapshot, category = _decode(payload, self._identity)
        except _STORAGE_ERRORS:
            self._warn()
            await self._async_delete()
            return None
        if category is not None:
            self._blocks[self._entry_id] = (self._identity, category)
        return snapshot, self.withheld

    async def async_save(self, snapshot: LibrarySnapshot) -> None:
        """An authoritative success clears policy even when caching is unavailable."""
        self._blocks.pop(self._entry_id, None)
        # Core defers saves while stopping and attaches final-write callbacks to
        # the individual Store. Never create one: a removed/reloaded account
        # must not be recreated later by an old wrapper's callback.
        if self._hass.state is CoreState.stopping:
            return
        try:
            await self._store().async_save(self._encode(snapshot))
        except _STORAGE_ERRORS:
            self._warn()

    async def async_mark_withheld(
        self, snapshot: LibrarySnapshot | None, category: str
    ) -> None:
        """Verify durable policy; Store can swallow disk write errors internally."""
        if category not in _WITHHELD:
            raise ValueError
        self._blocks[self._entry_id] = (self._identity, category)
        # A deferred marker cannot be verified on disk. Remove the old cache
        # instead, retaining the in-process block if disk removal also fails.
        if snapshot is None or self._hass.state is CoreState.stopping:
            await self._async_delete()
            return
        try:
            payload = self._encode(snapshot, category)
            await self._store().async_save(payload)
            if await self._store().async_load() == payload:
                return
        except _STORAGE_ERRORS:
            pass
        self._warn()
        await self._async_delete()

    async def _async_delete(self) -> None:
        try:
            await self._store().async_remove()
        except _STORAGE_ERRORS:
            self._warn()

    async def async_remove(self) -> None:
        """Remove private account data and its in-process policy on removal."""
        await self._async_delete()
        self._blocks.pop(self._entry_id, None)
