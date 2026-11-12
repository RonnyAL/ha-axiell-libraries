"""Pure data models for Solus responses; no Home Assistant dependencies."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Self
from urllib.parse import urlsplit

_DOTNET_DATE = re.compile(r"/Date\((-?[0-9]+)(?:([+-])([0-9]{2})([0-9]{2}))?\)/")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def parse_due_date(raw: str | None) -> date | None:
    """Read the UTC date of .NET milliseconds, validating any ±HHMM suffix.

    The suffix describes the source offset, not an adjustment to the Unix
    milliseconds. Missing, malformed and out-of-range dates are unknown.
    """
    if not isinstance(raw, str) or (match := _DOTNET_DATE.fullmatch(raw)) is None:
        return None
    if match[2] and (int(match[3]) > 23 or int(match[4]) > 59):
        return None
    try:
        return (_EPOCH + timedelta(milliseconds=int(match[1]))).date()
    except (ValueError, OverflowError):
        return None


def _text(value: Any) -> str | None:
    """Normalize optional strings without coercing malformed objects."""
    return value.strip() or None if isinstance(value, str) else None


def _cover_url(value: Any) -> str | None:
    """Accept optional direct HTTPS covers without embedded credentials."""
    url = _text(value)
    if url is None or any(ord(char) < 32 or ord(char) == 127 for char in url):
        return None
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path.lower().endswith("/itemimage.aspx")
        ):
            return None
    except ValueError:
        return None
    return url


@dataclass(frozen=True, slots=True)
class CatalogueRecord:
    """Optional catalogue enrichment, separate from loan identity."""

    record_id: str
    title: str | None = None
    author: str | None = None
    image_url: str | None = None
    isbn: str | None = None
    description: str | None = None
    format: str | None = None
    main_metadata: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> Self:
        """Parse a decoded RecordGet detail object; all enrichment is optional."""
        metadata = {}
        items = payload.get("MainMetadata")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                key, value = _text(item.get("Key")), _text(item.get("Value"))
                if key and value:
                    metadata[key] = value
        return cls(
            record_id=_text(payload.get("RecordID")) or "",
            title=_text(payload.get("Title")),
            author=_text(payload.get("Author")),
            image_url=(
                _cover_url(payload.get("ImageUrl"))
                or _cover_url(payload.get("ImageUrlLarge"))
            ),
            isbn=_text(payload.get("ISBN")),
            description=_text(payload.get("Description")),
            format=_text(payload.get("Format")),
            main_metadata=metadata,
        )


@dataclass(frozen=True, slots=True)
class Loan:
    """One issued copy, identified by loan ID rather than title or record ID."""

    loan_id: str
    record_id: str
    title: str
    due_date: date | None
    can_renew: bool
    overdue: bool
    source: str
    renewals_remaining: int | None = None
    author: str | None = None
    image_url: str | None = None
    isbn: str | None = None
    description: str | None = None

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> Self:
        """Parse LoansGet detail without consulting presentation HTML."""
        remaining = payload.get("RenewalsRemaining")
        return cls(
            loan_id=_text(payload.get("loanID")) or "",
            record_id=_text(payload.get("recordID")) or "",
            title=_text(payload.get("title")) or "",
            due_date=parse_due_date(payload.get("dueObject")),
            can_renew=payload.get("canRenew") is True,
            overdue=payload.get("Overdue") is True,
            source=_text(payload.get("Source")) or "",
            renewals_remaining=(
                remaining if type(remaining) is int and remaining >= 0 else None
            ),
            author=_text(payload.get("author")) or _text(payload.get("subtitle")),
            image_url=_cover_url(payload.get("imageUrl")),
            isbn=_text(payload.get("ISBN")),
            description=_text(payload.get("description")),
        )

    def with_catalogue(self, record: CatalogueRecord) -> Self:
        """Prefer catalogue enrichment while preserving available loan fallbacks."""
        return replace(
            self,
            author=record.author or self.author,
            image_url=record.image_url or self.image_url,
            isbn=record.isbn or self.isbn,
            description=record.description or self.description,
        )
