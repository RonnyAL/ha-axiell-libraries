"""Offline model contracts based only on synthetic API responses."""

import json
from datetime import date
from pathlib import Path

import pytest

from custom_components.axiell_libraries.models import (
    CatalogueRecord,
    Loan,
    parse_due_date,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def loan_payload():
    """Return a fresh synthetic loan for each test."""
    return json.loads((FIXTURES / "loans_get.json").read_text())["d"]["Detail"][0]


@pytest.fixture
def record_payload():
    """Return a synthetic catalogue record, never live account data."""
    return json.loads((FIXTURES / "record_get.json").read_text())["d"]["Detail"]


def test_due_date_dotnet_utc():
    assert parse_due_date("/Date(1795046400000)/") == date(2026, 11, 19)


@pytest.mark.parametrize("raw", [None, ""])
def test_missing_date_returns_none(raw):
    assert parse_due_date(raw) is None


@pytest.mark.parametrize(
    "raw",
    [
        "19.11.2026<br />Example Library",
        "2026-11-19",
        "/Date(nope)/",
        "/Date(1795046400000.0)/",
        "/Date(1795046400000+2400)/",
        "/Date(1795046400000+0060)/",
        "/Date(1795046400000+010)/",
        "/Date(1795046400000)/junk",
        "/Date(1795046400000)/\n",
        "/Date(99999999999999999999999999)/",
        1795046400000,
    ],
)
def test_bad_date_returns_none(raw):
    assert parse_due_date(raw) is None


@pytest.mark.parametrize("suffix", ["+0100", "-1200", "+0000", "+2359"])
def test_date_suffix_does_not_change_utc_date(suffix):
    assert parse_due_date(f"/Date(1795046400000{suffix})/") == date(2026, 11, 19)


def test_date_before_unix_epoch():
    assert parse_due_date("/Date(-1)/") == date(1969, 12, 31)


def test_loan_fields_from_synthetic_fixture(loan_payload):
    loan = Loan.from_api(loan_payload)
    assert loan.loan_id == "11111111-1111-4111-8111-111111111111"
    assert loan.record_id == "00000000-0000-4000-8000-000000000001"
    assert loan.title == "Example book A"
    assert loan.due_date == date(2026, 11, 19)
    assert loan.can_renew is True
    assert loan.overdue is False
    assert loan.source == "ILS"
    assert loan.author == "Sample, Alex"
    assert loan.image_url is None
    assert loan.isbn is None
    assert loan.description is None


def test_missing_due_object_does_not_parse_due_display(loan_payload):
    del loan_payload["dueObject"]
    assert Loan.from_api(loan_payload).due_date is None


def test_renewals_minus_one_is_unknown(loan_payload):
    assert Loan.from_api(loan_payload).renewals_remaining is None


@pytest.mark.parametrize("raw, expected", [(0, 0), (2, 2), (None, None)])
def test_renewal_counts(loan_payload, raw, expected):
    loan_payload["RenewalsRemaining"] = raw
    assert Loan.from_api(loan_payload).renewals_remaining == expected


def test_loan_ids_distinguish_same_title(loan_payload):
    first = Loan.from_api(loan_payload)
    second = Loan.from_api({**loan_payload, "loanID": "another-synthetic-loan"})
    assert first.title == second.title
    assert first.loan_id != second.loan_id


def test_loan_author_precedes_subtitle(loan_payload):
    loan_payload["author"] = "Loan author"
    assert Loan.from_api(loan_payload).author == "Loan author"


def test_optional_loan_metadata_can_be_absent(loan_payload):
    for field in ("author", "subtitle", "ISBN", "imageUrl"):
        loan_payload.pop(field)
    loan = Loan.from_api(loan_payload)
    assert loan.author is None
    assert loan.isbn is None
    assert loan.image_url is None


def test_catalogue_fields_from_synthetic_fixture(record_payload):
    record = CatalogueRecord.from_api(record_payload)
    assert record.record_id == "00000000-0000-4000-8000-000000000001"
    assert record.title == "Example book A"
    assert record.author == "Sample, Alex"
    assert record.description == "Synthetic example for offline tests."
    assert record.isbn == "9780000000002"
    assert record.image_url == "https://images.example.org/covers/sample-a.jpg"
    assert record.format == "Bok"
    assert record.main_metadata == {"Utgiver": "Sample Press", "Utgitt": "2026"}


def test_optional_catalogue_metadata_can_be_absent():
    record = CatalogueRecord.from_api({"RecordID": "synthetic-record"})
    assert record.title is None
    assert record.author is None
    assert record.description is None
    assert record.isbn is None
    assert record.image_url is None
    assert record.format is None
    assert record.main_metadata == {}


def test_catalogue_uses_large_cover_if_normal_cover_missing(record_payload):
    record_payload["ImageUrl"] = ""
    assert CatalogueRecord.from_api(record_payload).image_url == (
        "https://images.example.org/covers/sample-a-large.jpg"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://images.example.org/cover.jpg",
        "javascript:alert(1)",
        "/cover.jpg",
        "https://user:password@images.example.org/cover.jpg",
        "https://images.example.org/\ncover.jpg",
        "https://[bad/cover.jpg",
        "https://m.solus.co.uk/catalogue/ItemImage.aspx?id=example",
    ],
)
def test_unsafe_or_placeholder_cover_is_absent(url):
    assert CatalogueRecord.from_api({"ImageUrl": url}).image_url is None
    assert Loan.from_api({"imageUrl": url}).image_url is None


def test_malformed_optional_metadata_is_ignored(record_payload):
    record_payload.update(
        Author=[],
        Description={},
        ISBN=None,
        Format=42,
        MainMetadata=[None, {}, {"Key": "Utgiver", "Value": None}],
    )
    record = CatalogueRecord.from_api(record_payload)
    assert record.author is None
    assert record.description is None
    assert record.isbn is None
    assert record.format is None
    assert record.main_metadata == {}


def test_catalogue_author_precedes_loan_subtitle(loan_payload, record_payload):
    record_payload["Author"] = "Catalogue author"
    loan = Loan.from_api(loan_payload)
    enriched = loan.with_catalogue(CatalogueRecord.from_api(record_payload))
    assert enriched.author == "Catalogue author"
    assert enriched.image_url == "https://images.example.org/covers/sample-a.jpg"
    assert enriched.isbn == "9780000000002"
    assert enriched.description == "Synthetic example for offline tests."
    assert enriched.loan_id == loan.loan_id
    assert enriched.due_date == date(2026, 11, 19)
    assert loan.author == "Sample, Alex"


def test_missing_catalogue_fields_keep_loan_fallback(loan_payload):
    loan = Loan.from_api(loan_payload)
    enriched = loan.with_catalogue(CatalogueRecord.from_api({}))
    assert enriched.author == "Sample, Alex"
    assert enriched.title == "Example book A"
    assert enriched.image_url is None


def test_catalogue_format_and_immutable_publisher_metadata_reach_loan(
    loan_payload, record_payload
):
    record = CatalogueRecord.from_api(record_payload)
    enriched = Loan.from_api(loan_payload).with_catalogue(record)
    assert enriched.format == "Bok"
    assert enriched.main_metadata == {"Utgiver": "Sample Press", "Utgitt": "2026"}
    with pytest.raises(TypeError):
        enriched.main_metadata["Utgiver"] = "Changed"
    unchanged = enriched.with_catalogue(CatalogueRecord.from_api({}))
    assert unchanged.format == "Bok"
    assert unchanged.main_metadata == {"Utgiver": "Sample Press", "Utgitt": "2026"}
