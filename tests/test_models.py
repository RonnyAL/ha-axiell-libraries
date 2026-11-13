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
    assert loan.author is None
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
    assert record.image_url == "https://images.example.org/covers/sample-a-large.jpg"
    assert record.format == "Bok"
    assert record.main_metadata == {
        "Utgiver": "Sample Press",
        "Utgitt": "2026",
        "Språk": "Norsk",
    }


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


def test_catalogue_author_precedes_loan_author(loan_payload, record_payload):
    loan_payload["author"] = "Loan author"
    record_payload["Author"] = "Catalogue author"
    loan = Loan.from_api(loan_payload)
    enriched = loan.with_catalogue(CatalogueRecord.from_api(record_payload))
    assert enriched.author == "Catalogue author"
    assert enriched.image_url == "https://images.example.org/covers/sample-a-large.jpg"
    assert enriched.isbn == "9780000000002"
    assert enriched.description == "Synthetic example for offline tests."
    assert enriched.loan_id == loan.loan_id
    assert enriched.due_date == date(2026, 11, 19)
    assert loan.author == "Loan author"


def test_missing_catalogue_fields_keep_loan_fallback(loan_payload):
    loan = Loan.from_api(loan_payload)
    enriched = loan.with_catalogue(CatalogueRecord.from_api({}))
    assert enriched.author is None
    assert enriched.title == "Example book A"
    assert enriched.image_url is None


def test_catalogue_format_and_immutable_publisher_metadata_reach_loan(
    loan_payload, record_payload
):
    record = CatalogueRecord.from_api(record_payload)
    enriched = Loan.from_api(loan_payload).with_catalogue(record)
    assert enriched.format == "Bok"
    assert enriched.main_metadata == {
        "Utgiver": "Sample Press",
        "Utgitt": "2026",
        "Språk": "Norsk",
    }
    with pytest.raises(TypeError):
        enriched.main_metadata["Utgiver"] = "Changed"
    unchanged = enriched.with_catalogue(CatalogueRecord.from_api({}))
    assert unchanged.format == "Bok"
    assert unchanged.main_metadata == {
        "Utgiver": "Sample Press",
        "Utgitt": "2026",
        "Språk": "Norsk",
    }


def test_subtitle_is_preserved_without_inventing_an_author(loan_payload):
    loan_payload["subtitle"] = "Example series, volume 2"
    loan = Loan.from_api(loan_payload)
    assert loan.subtitle == "Example series, volume 2"
    assert loan.author is None


def test_missing_catalogue_author_keeps_explicit_loan_author(loan_payload):
    loan_payload["author"] = "Loan author"
    loan = Loan.from_api(loan_payload).with_catalogue(CatalogueRecord.from_api({}))
    assert loan.author == "Loan author"


def test_enrichment_preserves_current_circulation_and_title(
    loan_payload, record_payload
):
    loan_payload.update(
        itemID="copy-a",
        RenewalCount=2,
        renewalCost=1.5,
        OverdueSpecified=True,
        Overdue=True,
        canRenew=False,
    )
    record_payload.update(RecordID="different-record", Title="Catalogue title")
    enriched = Loan.from_api(loan_payload).with_catalogue(
        CatalogueRecord.from_api(record_payload)
    )
    assert enriched.loan_id == "11111111-1111-4111-8111-111111111111"
    assert enriched.record_id == "00000000-0000-4000-8000-000000000001"
    assert enriched.item_id == "copy-a"
    assert enriched.title == "Example book A"
    assert enriched.due_date == date(2026, 11, 19)
    assert enriched.source == "ILS"
    assert enriched.can_renew is False
    assert enriched.overdue is True
    assert enriched.overdue_specified is True
    assert enriched.renewal_count == 2
    assert enriched.renewal_cost == 1.5
    assert enriched.renewals_remaining is None


@pytest.mark.parametrize(
    "key, attribute",
    [("RenewalCount", "renewal_count"), ("RenewalsRemaining", "renewals_remaining")],
)
@pytest.mark.parametrize(
    "value, expected",
    [
        (0, 0),
        (2, 2),
        (-1, None),
        (-2, None),
        (True, None),
        (False, None),
        (1.5, None),
        ("2", None),
        ([], None),
        (None, None),
    ],
)
def test_counts_accept_only_nonnegative_integers(key, attribute, value, expected):
    assert getattr(Loan.from_api({key: value}), attribute) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        (0, 0),
        (2, 2),
        (1.5, 1.5),
        (-1, None),
        (True, None),
        (False, None),
        (float("inf"), None),
        (float("-inf"), None),
        (float("nan"), None),
        ("2", None),
        ({}, None),
        (None, None),
    ],
)
def test_cost_is_finite_nonnegative_number(value, expected):
    assert Loan.from_api({"renewalCost": value}).renewal_cost == expected


@pytest.mark.parametrize(
    "value, expected",
    [(True, True), (False, False), (None, None), (1, None), ("true", None)],
)
def test_overdue_specified_is_optional_boolean(value, expected):
    assert Loan.from_api({"OverdueSpecified": value}).overdue_specified is expected


@pytest.mark.parametrize(
    "value, expected", [(" copy-a ", "copy-a"), (42, None), ("", None)]
)
def test_item_id_is_optional_string(value, expected):
    assert Loan.from_api({"itemID": value}).item_id == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://images.example.org:invalid/cover.jpg",
        "https://images.example.org:65536/cover.jpg",
        "https://images.example.org:/cover.jpg",
        "https://images.example.org/cover name.jpg",
        " https://images.example.org/cover.jpg",
        "https://images.example.org/cover.jpg\t",
        "https://images.example.org\\cover.jpg",
    ],
)
def test_malformed_covers_are_absent_and_allow_valid_fallback(url):
    assert Loan.from_api({"imageUrl": url}).image_url is None
    record = CatalogueRecord.from_api(
        {"ImageUrlLarge": url, "ImageUrl": "https://images.example.org/normal.jpg"}
    )
    assert record.image_url == "https://images.example.org/normal.jpg"


def test_loan_cover_survives_missing_catalogue_cover():
    loan = Loan.from_api({"imageUrl": "https://images.example.org/loan.jpg"})
    assert loan.with_catalogue(CatalogueRecord.from_api({})).image_url == (
        "https://images.example.org/loan.jpg"
    )


def test_selected_original_fields_are_immutable_and_do_not_keep_unknowns(
    loan_payload, record_payload
):
    loan_payload.update(
        itemID=" copy-a ",
        RenewalCount=-1,
        OverdueSpecified=False,
        description="Loan description",
        unknown="DROP",
        dueDisplay="PRESENTATION_ONLY",
        unrelated={"nested": "DROP"},
    )
    record_payload.update(unknown="DROP", Title={"malformed": "DROP"})
    loan = Loan.from_api(loan_payload)
    record = CatalogueRecord.from_api(record_payload)
    assert dict(loan.api_fields) == {
        "loanID": "11111111-1111-4111-8111-111111111111",
        "recordID": "00000000-0000-4000-8000-000000000001",
        "itemID": " copy-a ",
        "title": "Example book A",
        "author": "",
        "subtitle": "Sample, Alex",
        "dueObject": "/Date(1795046400000)/",
        "canRenew": True,
        "renewalCost": 0,
        "RenewalCount": -1,
        "RenewalsRemaining": -1,
        "OverdueSpecified": False,
        "Overdue": False,
        "Source": "ILS",
        "ISBN": "",
        "imageUrl": "",
        "description": "Loan description",
    }
    assert dict(record.api_fields) == {
        "RecordID": "00000000-0000-4000-8000-000000000001",
        "Author": "Sample, Alex",
        "ISBN": "9780000000002",
        "Description": "Synthetic example for offline tests.",
        "Format": "Bok",
        "ImageUrl": "https://images.example.org/covers/sample-a.jpg",
        "ImageUrlLarge": "https://images.example.org/covers/sample-a-large.jpg",
    }
    loan_payload["itemID"] = "changed"
    record_payload["Author"] = "changed"
    assert loan.api_fields["itemID"] == " copy-a "
    assert record.api_fields["Author"] == "Sample, Alex"
    with pytest.raises(TypeError):
        loan.api_fields["title"] = "changed"
    with pytest.raises(TypeError):
        record.api_fields["Author"] = "changed"
    with pytest.raises(TypeError):
        record.main_metadata["Utgiver"] = "changed"
    assert loan.with_catalogue(record).api_fields == loan.api_fields


@pytest.mark.parametrize(
    "labels",
    [
        ("Utgiver", "Utgitt", "Språk", "Emne"),
        ("Publisher", "Year", "Language", "Subject"),
        ("PUBLISHER", "Publication year", "LANGUAGE", "Subjects"),
        ("utgiver", "utgitt", "språk", "Emner"),
    ],
)
def test_supported_bibliographic_labels_are_normalized_without_splitting(labels):
    publisher, year, language, subjects = labels
    metadata = [
        {"Key": publisher, "Value": " Sample Press "},
        {"Key": year, "Value": "c2026"},
        {"Key": language, "Value": "Norsk"},
        {"Key": subjects, "Value": "One; two / three"},
        {"Key": "Unknown", "Value": "DO_NOT_EXPORT"},
        {"Key": "Malformed", "Value": {"nested": "DO_NOT_EXPORT"}},
    ]
    loan = Loan.from_api({}).with_catalogue(
        CatalogueRecord.from_api({"MainMetadata": metadata})
    )
    assert loan.publisher == "Sample Press"
    assert loan.publication_year == "c2026"
    assert loan.language == "Norsk"
    assert loan.subjects == "One; two / three"
    assert dict(loan.bibliographic_metadata) == {
        publisher: "Sample Press",
        year: "c2026",
        language: "Norsk",
        subjects: "One; two / three",
    }
    assert loan.main_metadata["Unknown"] == "DO_NOT_EXPORT"
    assert "DO_NOT_EXPORT" not in json.dumps(loan.as_dict())
    with pytest.raises(TypeError):
        loan.bibliographic_metadata[publisher] = "changed"


def test_public_dictionary_has_stable_keys_and_iso_date(loan_payload, record_payload):
    loan_payload.update(
        itemID="copy-a", RenewalCount=1, renewalCost=0.5, OverdueSpecified=True
    )
    record_payload["MainMetadata"].append({"Key": "Unknown", "Value": "DO_NOT_EXPORT"})
    loan = Loan.from_api(loan_payload).with_catalogue(
        CatalogueRecord.from_api(record_payload)
    )
    assert loan.as_dict() == {
        "loan_id": "11111111-1111-4111-8111-111111111111",
        "record_id": "00000000-0000-4000-8000-000000000001",
        "item_id": "copy-a",
        "title": "Example book A",
        "subtitle": "Sample, Alex",
        "author": "Sample, Alex",
        "due_date": "2026-11-19",
        "overdue": False,
        "overdue_specified": True,
        "can_renew": True,
        "renewal_count": 1,
        "renewals_remaining": None,
        "renewal_cost": 0.5,
        "source": "ILS",
        "isbn": "9780000000002",
        "image_url": "https://images.example.org/covers/sample-a-large.jpg",
        "description": "Synthetic example for offline tests.",
        "format": "Bok",
        "publisher": "Sample Press",
        "publication_year": "2026",
        "language": "Norsk",
        "subjects": None,
        "main_metadata": {
            "Utgiver": "Sample Press",
            "Utgitt": "2026",
            "Språk": "Norsk",
        },
    }
    exported = loan.as_dict()
    exported["main_metadata"]["Utgiver"] = "changed"
    assert loan.publisher == "Sample Press"
    assert loan.due_date == date(2026, 11, 19)


def test_public_dictionary_uses_null_for_absent_optional_values():
    assert Loan.from_api({}).as_dict() == {
        "loan_id": "",
        "record_id": "",
        "item_id": None,
        "title": "",
        "subtitle": None,
        "author": None,
        "due_date": None,
        "overdue": False,
        "overdue_specified": None,
        "can_renew": False,
        "renewal_count": None,
        "renewals_remaining": None,
        "renewal_cost": None,
        "source": "",
        "isbn": None,
        "image_url": None,
        "description": None,
        "format": None,
        "publisher": None,
        "publication_year": None,
        "language": None,
        "subjects": None,
        "main_metadata": {},
    }


@pytest.mark.parametrize("value", [None, 2026, True, [], {}, "", "   "])
def test_malformed_recognized_metadata_is_absent(value):
    loan = Loan.from_api({}).with_catalogue(
        CatalogueRecord.from_api(
            {
                "MainMetadata": [
                    {"Key": label, "Value": value}
                    for label in ("Publisher", "Year", "Language", "Subjects")
                ]
            }
        )
    )
    assert loan.publisher is None
    assert loan.publication_year is None
    assert loan.language is None
    assert loan.subjects is None
    assert loan.as_dict()["main_metadata"] == {}
