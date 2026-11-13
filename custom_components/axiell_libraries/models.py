"""Pure data models for Solus responses; no Home Assistant dependencies."""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from types import MappingProxyType
from typing import Any, Self
from urllib.parse import urlsplit

_DOTNET_DATE = re.compile(r"/Date\((-?[0-9]+)(?:([+-])([0-9]{2})([0-9]{2}))?\)/")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_LOAN_FIELDS = frozenset(
    {
        "loanID",
        "recordID",
        "itemID",
        "title",
        "author",
        "subtitle",
        "dueObject",
        "canRenew",
        "renewalCost",
        "RenewalCount",
        "RenewalsRemaining",
        "OverdueSpecified",
        "Overdue",
        "Source",
        "ISBN",
        "imageUrl",
        "description",
    }
)
_CATALOGUE_FIELDS = frozenset(
    {
        "RecordID",
        "Title",
        "Author",
        "ISBN",
        "Description",
        "Format",
        "ImageUrl",
        "ImageUrlLarge",
    }
)
_BIBLIOGRAPHIC_LABELS = {
    "publisher": frozenset({"utgiver", "publisher"}),
    "publication_year": frozenset({"utgitt", "year", "publication year"}),
    "language": frozenset({"språk", "language"}),
    "subjects": frozenset({"emne", "emner", "subject", "subjects"}),
}
_PUBLIC_METADATA_LABELS = frozenset().union(*_BIBLIOGRAPHIC_LABELS.values())


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
    except ValueError, OverflowError:
        return None


def _text(value: Any) -> str | None:
    """Normalize optional strings without coercing malformed objects."""
    return value.strip() or None if isinstance(value, str) else None


def _cover_url(value: Any) -> str | None:
    """Accept optional direct HTTPS covers without embedded credentials."""
    if (
        not isinstance(value, str)
        or not value
        or any(
            char.isspace() or ord(char) < 32 or ord(char) == 127 or char == "\\"
            for char in value
        )
    ):
        return None
    url = value
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.netloc.endswith(":")
            or (parsed.port is not None and parsed.port == 0)
            or parsed.path.lower().endswith("/itemimage.aspx")
        ):
            return None
    except ValueError:
        return None
    return url


def _count(value: Any) -> int | None:
    """Negative or malformed circulation counts are unknown, including booleans."""
    return value if type(value) is int and value >= 0 else None


def _cost(value: Any) -> int | float | None:
    """Keep only finite nonnegative amounts without inferring a currency."""
    if type(value) is int:
        return value if value >= 0 else None
    if type(value) is float and math.isfinite(value) and value >= 0:
        return value
    return None


def _api_fields(
    payload: Mapping[str, Any], allowed: frozenset[str]
) -> Mapping[str, Any]:
    """Snapshot selected original scalars without nested responses or credentials."""
    return MappingProxyType(
        {
            key: value
            for key, value in payload.items()
            if key in allowed
            and (value is None or type(value) in (str, int, float, bool))
        }
    )


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
    main_metadata: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )
    api_fields: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

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
                _cover_url(payload.get("ImageUrlLarge"))
                or _cover_url(payload.get("ImageUrl"))
            ),
            isbn=_text(payload.get("ISBN")),
            description=_text(payload.get("Description")),
            format=_text(payload.get("Format")),
            main_metadata=MappingProxyType(metadata),
            api_fields=_api_fields(payload, _CATALOGUE_FIELDS),
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
    subtitle: str | None = None
    item_id: str | None = None
    renewal_count: int | None = None
    renewal_cost: int | float | None = None
    overdue_specified: bool | None = None
    renewals_remaining: int | None = None
    author: str | None = None
    image_url: str | None = None
    isbn: str | None = None
    description: str | None = None
    format: str | None = None
    main_metadata: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )
    api_fields: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> Self:
        """Parse LoansGet detail without consulting presentation HTML."""
        return cls(
            loan_id=_text(payload.get("loanID")) or "",
            record_id=_text(payload.get("recordID")) or "",
            title=_text(payload.get("title")) or "",
            due_date=parse_due_date(payload.get("dueObject")),
            can_renew=payload.get("canRenew") is True,
            overdue=payload.get("Overdue") is True,
            source=_text(payload.get("Source")) or "",
            subtitle=_text(payload.get("subtitle")),
            item_id=_text(payload.get("itemID")),
            renewal_count=_count(payload.get("RenewalCount")),
            renewal_cost=_cost(payload.get("renewalCost")),
            overdue_specified=(
                payload["OverdueSpecified"]
                if type(payload.get("OverdueSpecified")) is bool
                else None
            ),
            renewals_remaining=_count(payload.get("RenewalsRemaining")),
            author=_text(payload.get("author")),
            image_url=_cover_url(payload.get("imageUrl")),
            isbn=_text(payload.get("ISBN")),
            description=_text(payload.get("description")),
            api_fields=_api_fields(payload, _LOAN_FIELDS),
        )

    def with_catalogue(self, record: CatalogueRecord) -> Self:
        """Prefer catalogue enrichment while preserving available loan fallbacks."""
        return replace(
            self,
            author=record.author or self.author,
            image_url=record.image_url or self.image_url,
            isbn=record.isbn or self.isbn,
            description=record.description or self.description,
            format=record.format or self.format,
            main_metadata=MappingProxyType(
                {**self.main_metadata, **record.main_metadata}
            ),
        )

    @property
    def bibliographic_metadata(self) -> Mapping[str, str]:
        """Expose only known bibliographic labels, retaining their original strings."""
        return MappingProxyType(
            {
                key: value
                for key, value in self.main_metadata.items()
                if key.casefold() in _PUBLIC_METADATA_LABELS
            }
        )

    def _bibliographic_value(self, field_name: str) -> str | None:
        return next(
            (
                value
                for key, value in self.main_metadata.items()
                if key.casefold() in _BIBLIOGRAPHIC_LABELS[field_name]
            ),
            None,
        )

    @property
    def publisher(self) -> str | None:
        """Return an optional publisher under a supported provider label."""
        return self._bibliographic_value("publisher")

    @property
    def publication_year(self) -> str | None:
        """Keep the publication value as supplied without inferring a date."""
        return self._bibliographic_value("publication_year")

    @property
    def language(self) -> str | None:
        """Return an optional language under a supported provider label."""
        return self._bibliographic_value("language")

    @property
    def subjects(self) -> str | None:
        """Keep subject text intact without assuming delimiters."""
        return self._bibliographic_value("subjects")

    def as_dict(self) -> dict[str, Any]:
        """Serialize the public loan contract without internal original fields."""
        return {
            "loan_id": self.loan_id,
            "record_id": self.record_id,
            "item_id": self.item_id,
            "title": self.title,
            "subtitle": self.subtitle,
            "author": self.author,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "overdue": self.overdue,
            "overdue_specified": self.overdue_specified,
            "can_renew": self.can_renew,
            "renewal_count": self.renewal_count,
            "renewals_remaining": self.renewals_remaining,
            "renewal_cost": self.renewal_cost,
            "source": self.source,
            "isbn": self.isbn,
            "image_url": self.image_url,
            "description": self.description,
            "format": self.format,
            "publisher": self.publisher,
            "publication_year": self.publication_year,
            "language": self.language,
            "subjects": self.subjects,
            "main_metadata": dict(self.bibliographic_metadata),
        }


@dataclass(frozen=True, slots=True)
class LibrarySnapshot:
    """One successful loan refresh, including any available enrichment."""

    loans: tuple[Loan, ...]
    fetched_at: datetime
