"""Offline coordinator behavior using real Home Assistant refresh methods."""

import asyncio
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.axiell_libraries.const import DOMAIN
from custom_components.axiell_libraries.coordinator import AxiellCoordinator
from custom_components.axiell_libraries.solus import (
    SolusAuthError,
    SolusConnectionError,
    SolusProtocolError,
    SolusSecurityError,
    SolusSessionExpired,
)

CARD = "TEST-CARD-0000"
PIN = "TEST_PIN_NOT_VALID"
DEVICE = "0123456789abcdef"
NOW = datetime(2026, 11, 13, tzinfo=UTC)


def loan(record="record-a", loan_id="loan-a", source="ILS", **updates):
    """Build synthetic protocol rows, never real account responses."""
    return {
        "recordID": record,
        "loanID": loan_id,
        "Source": source,
        "title": "Example book",
        "subtitle": "Fallback author",
        "dueObject": "/Date(1795046400000)/",
        "canRenew": True,
        "Overdue": False,
        "RenewalsRemaining": -1,
        **updates,
    }


def record(record_id="record-a", **updates):
    return {
        "RecordID": record_id,
        "Author": "Catalogue author",
        "ImageUrl": "https://images.example.org/cover.jpg",
        **updates,
    }


@pytest.fixture
def setup_coordinator(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "app_id": "TEST-APP",
            "server_url": "https://process-test.sol.us",
            "location_id": "Test",
            "library_name": "Synthetic Library",
            "card": CARD,
            "pin": PIN,
            "device_id": DEVICE,
        },
    )
    entry.add_to_hass(hass)
    entry._async_set_state(hass, ConfigEntryState.SETUP_IN_PROGRESS, None)
    client = Mock()
    client.device_id = DEVICE
    client.async_login = AsyncMock(return_value=[{"UserID": CARD}])
    client.async_get_loans = AsyncMock(return_value=[loan()])
    client.async_get_record = AsyncMock(return_value=record())
    return AxiellCoordinator(hass, entry, client), entry, client


async def test_first_refresh_logs_in_once_then_refreshes_loans_with_same_identity(
    setup_coordinator,
):
    coordinator, entry, client = setup_coordinator
    original = deepcopy(dict(entry.data))
    with patch("secrets.token_hex", side_effect=AssertionError("new device")):
        await coordinator.async_config_entry_first_refresh()
        client.async_get_loans.return_value = [loan(dueObject="/Date(1795651200000)/")]
        await coordinator.async_refresh()
    client.async_login.assert_awaited_once_with(CARD, PIN)
    assert client.async_get_loans.await_args_list[0].args == (CARD,)
    assert client.async_get_loans.await_args_list[1].args == (CARD,)
    assert dict(entry.data) == original
    assert client.device_id == DEVICE
    assert coordinator.data.loans[0].due_date == date(2026, 11, 26)
    assert isinstance(coordinator.data.loans, tuple)
    assert coordinator.data.fetched_at.tzinfo is not None
    assert coordinator.update_interval == timedelta(hours=6)


async def test_distinct_copies_share_catalogue_but_keep_loan_identity(
    setup_coordinator,
):
    coordinator, _, client = setup_coordinator
    client.async_get_loans.return_value = [loan(), loan(loan_id="loan-b")]
    await coordinator.async_config_entry_first_refresh()
    await coordinator.async_refresh()
    assert [item.loan_id for item in coordinator.data.loans] == ["loan-a", "loan-b"]
    assert all(item.author == "Catalogue author" for item in coordinator.data.loans)
    client.async_get_record.assert_awaited_once_with("record-a", "ILS")


@pytest.mark.parametrize("due", [None, "invalid"])
async def test_unknown_due_date_keeps_loan(setup_coordinator, due):
    coordinator, _, client = setup_coordinator
    client.async_get_loans.return_value = [loan(dueObject=due)]
    await coordinator.async_config_entry_first_refresh()
    assert len(coordinator.data.loans) == 1
    assert coordinator.data.loans[0].due_date is None


@pytest.mark.parametrize(
    "error", [SolusConnectionError, SolusProtocolError, SolusSecurityError]
)
async def test_loans_failure_retains_previous_snapshot(
    setup_coordinator, error, caplog
):
    coordinator, _, client = setup_coordinator
    await coordinator.async_config_entry_first_refresh()
    previous = coordinator.data
    client.async_get_loans.side_effect = error("SYNTHETIC_PRIVATE_DETAIL")
    await coordinator.async_refresh()
    assert coordinator.data is previous
    assert not coordinator.last_update_success
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert "SYNTHETIC_PRIVATE_DETAIL" not in caplog.text
    assert "SYNTHETIC_PRIVATE_DETAIL" not in str(coordinator.last_exception)
    assert coordinator.last_exception.__suppress_context__
    client.async_login.assert_awaited_once()


async def test_explicit_empty_loans_replaces_previous_data(setup_coordinator):
    coordinator, _, client = setup_coordinator
    await coordinator.async_config_entry_first_refresh()
    client.async_get_loans.return_value = []
    await coordinator.async_refresh()
    assert coordinator.data.loans == ()
    assert coordinator.last_update_success


@pytest.mark.parametrize("stage", ["login", "loans", "record"])
async def test_invalid_auth_requests_reauth_without_retry(setup_coordinator, stage):
    coordinator, _, client = setup_coordinator
    getattr(
        client, f"async_{'get_' if stage != 'login' else ''}{stage}"
    ).side_effect = SolusAuthError("SYNTHETIC_PRIVATE_DETAIL")
    with pytest.raises(ConfigEntryAuthFailed) as exc:
        await coordinator.async_config_entry_first_refresh()
    assert "SYNTHETIC_PRIVATE_DETAIL" not in str(exc.value)
    assert exc.value.__suppress_context__
    client.async_login.assert_awaited_once()


async def test_initial_transport_failure_is_retryable_setup_failure(setup_coordinator):
    coordinator, _, client = setup_coordinator
    client.async_login.side_effect = SolusConnectionError("synthetic")
    with pytest.raises(ConfigEntryNotReady):
        await coordinator.async_config_entry_first_refresh()
    assert isinstance(coordinator.last_exception, UpdateFailed)
    client.async_get_loans.assert_not_awaited()


@pytest.mark.parametrize("stage", ["loans", "record"])
async def test_session_expiry_recovers_once_with_persisted_identity(
    setup_coordinator, stage
):
    coordinator, entry, client = setup_coordinator
    target = client.async_get_loans if stage == "loans" else client.async_get_record
    target.side_effect = [
        SolusSessionExpired("expired"),
        [loan()] if stage == "loans" else record(),
    ]
    await coordinator.async_config_entry_first_refresh()
    assert coordinator.last_update_success
    assert coordinator.data.loans[0].author == "Catalogue author"
    assert client.async_login.await_count == 2
    assert all(call.args == (CARD, PIN) for call in client.async_login.await_args_list)
    assert entry.data["device_id"] == DEVICE


@pytest.mark.parametrize("stage", ["loans", "record"])
async def test_repeated_session_expiry_stops_after_one_recovery(
    setup_coordinator, stage
):
    coordinator, _, client = setup_coordinator
    target = client.async_get_loans if stage == "loans" else client.async_get_record
    target.side_effect = SolusSessionExpired("expired")
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator.async_config_entry_first_refresh()
    assert client.async_login.await_count == 2
    assert target.await_count == 2


async def test_invalid_credentials_during_recovery_do_not_retry(setup_coordinator):
    coordinator, _, client = setup_coordinator
    client.async_get_loans.side_effect = SolusSessionExpired("expired")
    client.async_login.side_effect = [[{"UserID": CARD}], SolusAuthError("invalid")]
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator.async_config_entry_first_refresh()
    assert client.async_login.await_count == 2
    assert client.async_get_loans.await_count == 1


async def test_partial_catalogue_failure_keeps_all_loans(setup_coordinator):
    coordinator, _, client = setup_coordinator
    client.async_get_loans.return_value = [loan(), loan("record-b", "loan-b")]
    client.async_get_record.side_effect = [record(), SolusProtocolError("private")]
    await coordinator.async_config_entry_first_refresh()
    assert [item.author for item in coordinator.data.loans] == [
        "Catalogue author",
        "Fallback author",
    ]
    assert coordinator.last_update_success


@pytest.mark.parametrize(
    "metadata", [None, record("different"), record(Source="OTHER")]
)
async def test_missing_or_mismatched_catalogue_is_ignored(setup_coordinator, metadata):
    coordinator, _, client = setup_coordinator
    client.async_get_record.return_value = metadata
    await coordinator.async_config_entry_first_refresh()
    assert coordinator.data.loans[0].author == "Fallback author"
    assert coordinator.data.loans[0].image_url is None


async def test_unsafe_catalogue_cover_is_optional(setup_coordinator):
    coordinator, _, client = setup_coordinator
    client.async_get_record.return_value = record(
        ImageUrl="http://images.example.org/a"
    )
    await coordinator.async_config_entry_first_refresh()
    assert coordinator.data.loans[0].author == "Catalogue author"
    assert coordinator.data.loans[0].image_url is None


async def test_cache_ttl_refreshes_metadata_and_retains_stale_on_failure(
    setup_coordinator, freezer
):
    coordinator, _, client = setup_coordinator
    freezer.move_to(NOW)
    await coordinator.async_config_entry_first_refresh()
    freezer.tick(timedelta(hours=23))
    await coordinator.async_refresh()
    assert client.async_get_record.await_count == 1
    freezer.tick(timedelta(hours=1))
    client.async_get_record.side_effect = SolusConnectionError("unavailable")
    await coordinator.async_refresh()
    assert client.async_get_record.await_count == 2
    assert coordinator.data.loans[0].author == "Catalogue author"
    client.async_get_record.side_effect = None
    client.async_get_record.return_value = record(Author="Updated author")
    await coordinator.async_refresh()
    assert coordinator.data.loans[0].author == "Updated author"


async def test_same_record_in_different_sources_uses_separate_cache(setup_coordinator):
    coordinator, _, client = setup_coordinator
    client.async_get_loans.return_value = [
        loan(),
        loan(loan_id="loan-b", source="OTHER"),
    ]
    await coordinator.async_config_entry_first_refresh()
    assert client.async_get_record.await_count == 2
    assert {call.args for call in client.async_get_record.await_args_list} == {
        ("record-a", "ILS"),
        ("record-a", "OTHER"),
    }


async def test_cache_is_bounded_to_256_records(setup_coordinator):
    coordinator, _, client = setup_coordinator
    for index in range(257):
        client.async_get_loans.return_value = [loan(f"record-{index}")]
        client.async_get_record.return_value = record(f"record-{index}")
        if index == 0:
            await coordinator.async_config_entry_first_refresh()
        else:
            await coordinator.async_refresh()
    client.async_get_loans.return_value = [loan("record-256")]
    await coordinator.async_refresh()
    assert client.async_get_record.await_count == 257
    client.async_get_loans.return_value = [loan("record-0")]
    await coordinator.async_refresh()
    assert client.async_get_record.await_count == 258


async def test_catalogue_cache_is_private_to_each_entry(setup_coordinator, hass):
    coordinator, entry, client = setup_coordinator
    await coordinator.async_config_entry_first_refresh()
    other_entry = MockConfigEntry(
        domain=DOMAIN, data={**entry.data, "device_id": "fedcba9876543210"}
    )
    other_entry.add_to_hass(hass)
    other_entry._async_set_state(hass, ConfigEntryState.SETUP_IN_PROGRESS, None)
    other_client = Mock(
        async_login=AsyncMock(return_value=[{}]),
        async_get_loans=AsyncMock(return_value=[loan()]),
        async_get_record=AsyncMock(return_value=record(Author="Other account")),
    )
    other = AxiellCoordinator(hass, other_entry, other_client)
    await other.async_config_entry_first_refresh()
    assert other.data.loans[0].author == "Other account"
    assert coordinator.data.loans[0].author == "Catalogue author"


async def test_enrichment_is_bounded_and_settled_before_session_recovery(
    setup_coordinator,
):
    coordinator, _, client = setup_coordinator
    client.async_get_loans.return_value = [
        loan(f"record-{index}") for index in range(12)
    ]
    active = 0
    maximum = 0
    recovery_seen = False

    async def get_record(record_id, source):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        try:
            await asyncio.sleep(0)
            if record_id == "record-0" and not recovery_seen:
                raise SolusSessionExpired("expired")
            return record(record_id)
        finally:
            active -= 1

    async def login(card, pin):
        nonlocal recovery_seen
        assert active == 0
        if client.async_login.await_count == 2:
            recovery_seen = True
        return [{}]

    client.async_login.side_effect = login
    client.async_get_record.side_effect = get_record
    await coordinator.async_config_entry_first_refresh()
    assert 1 < maximum <= 4
    assert active == 0
    assert recovery_seen
    assert len(coordinator.data.loans) == 12
