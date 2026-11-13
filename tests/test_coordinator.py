"""Offline coordinator behavior using real Home Assistant refresh methods."""

import asyncio
import re
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest
from aioresponses import CallbackResult
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant.common import MockConfigEntry

from custom_components.axiell_libraries.const import DOMAIN
from custom_components.axiell_libraries.coordinator import AxiellCoordinator
from custom_components.axiell_libraries.solus import (
    SolusAuthError,
    SolusClient,
    SolusConnectionError,
    SolusProtocolError,
    SolusSecurityError,
    SolusSessionExpired,
)
from custom_components.axiell_libraries.todo import AxiellTodo
from tests.http import AiohttpResponses as aioresponses

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
        "subtitle": "Example series",
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


@pytest.mark.parametrize(
    "rows",
    [
        [{}, {}],
        [{"loanID": "loan-c"}],
        [loan(loan_id="loan-c"), loan(loan_id="loan-c")],
        [loan(loan_id="loan-c"), loan(loan_id=" \tloan-c\n")],
    ],
    ids=["blank-rows", "missing-title", "duplicate-ids", "normalized-duplicate-ids"],
)
async def test_real_client_malformed_loans_retain_snapshot_and_unavailable_todo(
    setup_coordinator, hass, rows, caplog
):
    """A malformed successful HTTP response cannot replace valid issued copies."""
    _, entry, _ = setup_coordinator
    server = "https://process-test.sol.us"

    def endpoint(method):
        return re.compile(rf"{server}/v4/Cat.asmx/{method}\?rnd=.+")

    with aioresponses() as http:
        http.get("https://repo.sol.us/id/TEST-APP/2026.42", payload={"Server": server})
        http.get(re.compile(rf"{server}/v4/Auth.aspx\?s=.+"), body="")
        for method in ("LoginPreSession", "LoginCheckSession"):
            http.post(
                endpoint(method),
                payload={
                    "d": {
                        "status": "success",
                        "Detail": [{"AuthToken": "TEST_TOKEN"}],
                    }
                },
            )
        for response_rows in (
            [loan(record="", loan_id="loan-a"), loan(record="", loan_id="loan-b")],
            rows,
        ):
            http.post(
                endpoint("LoansGet"),
                payload={"d": {"status": "success", "Detail": response_rows}},
            )
        session = async_create_clientsession(
            hass, cookie_jar=aiohttp.CookieJar(), auto_cleanup=False
        )
        try:
            client = SolusClient(session, "TEST-APP", server, DEVICE)
            coordinator = AxiellCoordinator(hass, entry, client)
            await coordinator.async_config_entry_first_refresh()
            previous = coordinator.data
            entry.runtime_data = coordinator
            todo = AxiellTodo(entry)
            assert todo.available
            assert [item.uid for item in todo.todo_items] == ["loan-a", "loan-b"]

            await coordinator.async_refresh()

            assert coordinator.data is previous
            assert not coordinator.last_update_success
            assert isinstance(coordinator.last_exception, UpdateFailed)
            assert not todo.available
            assert [item.uid for item in todo.todo_items] == ["loan-a", "loan-b"]
            assert [item.summary for item in todo.todo_items] == [
                "Example book",
                "Example book",
            ]
            assert all(
                secret not in str(coordinator.last_exception) + caplog.text
                for secret in (CARD, PIN, DEVICE, "TEST_TOKEN")
            )
        finally:
            session.detach()


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
        None,
    ]
    assert coordinator.last_update_success


@pytest.mark.parametrize(
    "metadata", [None, record("different"), record(Source="OTHER")]
)
async def test_missing_or_mismatched_catalogue_is_ignored(setup_coordinator, metadata):
    coordinator, _, client = setup_coordinator
    client.async_get_record.return_value = metadata
    await coordinator.async_config_entry_first_refresh()
    assert coordinator.data.loans[0].author is None
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


@pytest.mark.parametrize("recovery_outage", [False, True])
async def test_real_client_recovers_expiry_with_queued_catalogue_requests(
    setup_coordinator, hass, recovery_outage
):
    """An expired session must not turn queued requests into credential rejection."""
    _, entry, _ = setup_coordinator
    server = "https://process-test.sol.us"
    login_count = 0
    active = 0
    initial_requests = 0
    repo_requests = 0
    loan_requests = 0
    initial_batch_ready = asyncio.Event()
    devices = []

    def endpoint(method):
        return re.compile(rf"{server}/v4/Cat.asmx/{method}\?rnd=.+")

    def pre_session(url, **kwargs):
        nonlocal login_count
        assert active == 0
        login_count += 1
        devices.append(kwargs["json"]["DeviceID"])
        return CallbackResult(
            payload={
                "d": {"status": "success", "Detail": [{"AuthToken": "TEST_TOKEN"}]}
            }
        )

    def routing(url, **kwargs):
        nonlocal repo_requests
        repo_requests += 1
        if recovery_outage and repo_requests == 2:
            return CallbackResult(status=503)
        return CallbackResult(payload={"Server": server})

    def loans(url, **kwargs):
        nonlocal loan_requests
        loan_requests += 1
        rows = (
            []
            if recovery_outage and loan_requests == 1
            else [loan(f"record-{index}", f"loan-{index}") for index in range(8)]
        )
        return CallbackResult(payload={"d": {"status": "success", "Detail": rows}})

    async def catalogue(url, **kwargs):
        nonlocal active, initial_requests
        active += 1
        devices.append(kwargs["json"]["DeviceID"])
        record_id = kwargs["json"]["Request"]["RecordID"]
        try:
            if login_count == 1:
                initial_requests += 1
                if initial_requests == 4:
                    initial_batch_ready.set()
                await initial_batch_ready.wait()
                if record_id == "record-0":
                    return CallbackResult(status=401)
                # Hold the other real HTTP responses until the client's 401
                # handler invalidates the session; queued calls then see expiry.
                while client._authenticated:
                    await asyncio.sleep(0)
            return CallbackResult(
                payload={"d": {"status": "success", "Detail": record(record_id)}}
            )
        finally:
            active -= 1

    with aioresponses() as http:
        http.get(
            "https://repo.sol.us/id/TEST-APP/2026.42",
            callback=routing,
            repeat=True,
        )
        http.get(re.compile(rf"{server}/v4/Auth.aspx\?s=.+"), body="", repeat=True)
        http.post(endpoint("LoginPreSession"), callback=pre_session, repeat=True)
        http.post(
            endpoint("LoginCheckSession"),
            payload={
                "d": {
                    "status": "success",
                    "Detail": [{"AuthToken": "TEST_TOKEN"}],
                    "Detail2": {"SessionID": "TEST_SESSION", "ServerToUse": server},
                }
            },
            repeat=True,
        )
        http.post(
            endpoint("LoansGet"),
            callback=loans,
            repeat=True,
        )
        http.post(endpoint("RecordGet"), callback=catalogue, repeat=True)
        session = async_create_clientsession(
            hass, cookie_jar=aiohttp.CookieJar(), auto_cleanup=False
        )
        try:
            client = SolusClient(session, "TEST-APP", server, DEVICE)
            coordinator = AxiellCoordinator(hass, entry, client)
            await coordinator.async_config_entry_first_refresh()
            if recovery_outage:
                previous = coordinator.data
                await coordinator.async_refresh()
                assert isinstance(coordinator.last_exception, UpdateFailed)
                assert coordinator.data is previous
                assert login_count == 1
                await coordinator.async_refresh()
        finally:
            session.detach()
    assert coordinator.last_update_success
    assert len(coordinator.data.loans) == 8
    assert all(item.author == "Catalogue author" for item in coordinator.data.loans)
    assert login_count == 2
    assert initial_requests == 4
    assert active == 0
    assert devices and set(devices) == {DEVICE}
    assert entry.data["device_id"] == DEVICE


async def test_cached_record_preserves_each_copys_current_circulation(
    setup_coordinator,
):
    coordinator, _, client = setup_coordinator
    client.async_get_record.return_value = record(
        Title="Catalogue title",
        MainMetadata=[{"Key": "Publisher", "Value": "Cached Press"}],
    )
    client.async_get_loans.return_value = [
        loan(itemID="copy-a", RenewalCount=0, OverdueSpecified=True),
        loan(
            loan_id="loan-b",
            itemID="copy-b",
            title="Second loan title",
            dueObject="/Date(1795651200000)/",
            canRenew=False,
            Overdue=True,
            RenewalCount=2,
            OverdueSpecified=False,
        ),
    ]
    await coordinator.async_config_entry_first_refresh()
    first, second = coordinator.data.loans
    assert (
        first.loan_id,
        first.item_id,
        first.title,
        first.due_date,
        first.can_renew,
        first.overdue,
        first.renewal_count,
        first.overdue_specified,
    ) == (
        "loan-a",
        "copy-a",
        "Example book",
        date(2026, 11, 19),
        True,
        False,
        0,
        True,
    )
    assert (
        second.loan_id,
        second.item_id,
        second.title,
        second.due_date,
        second.can_renew,
        second.overdue,
        second.renewal_count,
        second.overdue_specified,
    ) == (
        "loan-b",
        "copy-b",
        "Second loan title",
        date(2026, 11, 26),
        False,
        True,
        2,
        False,
    )
    assert first.publisher == second.publisher == "Cached Press"
    client.async_get_record.assert_awaited_once_with("record-a", "ILS")

    client.async_get_loans.return_value = [
        loan(
            itemID="copy-a",
            dueObject="/Date(1795651200000)/",
            canRenew=False,
            Overdue=True,
            RenewalCount=1,
            RenewalsRemaining=0,
            renewalCost=1.5,
        ),
    ]
    await coordinator.async_refresh()
    assert len(coordinator.data.loans) == 1  # Returned loan-b disappears.
    renewed = coordinator.data.loans[0]
    assert renewed.loan_id == "loan-a"
    assert renewed.due_date == date(2026, 11, 26)
    assert renewed.can_renew is False
    assert renewed.overdue is True
    assert renewed.renewal_count == 1
    assert renewed.renewals_remaining == 0
    assert renewed.renewal_cost == 1.5
    assert renewed.publisher == "Cached Press"
    client.async_get_record.assert_awaited_once_with("record-a", "ILS")

    client.async_get_loans.return_value.append(loan("record-b", "loan-c"))
    client.async_get_record.return_value = record(
        "record-b", Author="New record author"
    )
    await coordinator.async_refresh()
    assert [item.author for item in coordinator.data.loans] == [
        "Catalogue author",
        "New record author",
    ]
    assert client.async_get_record.await_args.args == ("record-b", "ILS")
    assert client.async_get_record.await_count == 2


async def test_partial_failure_and_stale_retry_preserve_bibliographic_data(
    setup_coordinator, freezer
):
    coordinator, _, client = setup_coordinator
    freezer.move_to(NOW)
    client.async_get_record.return_value = record(
        MainMetadata=[{"Key": "Språk", "Value": "Norsk"}]
    )
    await coordinator.async_config_entry_first_refresh()
    freezer.tick(timedelta(hours=24))
    client.async_get_loans.return_value = [loan(), loan("record-b", "loan-b")]
    client.async_get_record.side_effect = SolusConnectionError("unavailable")
    await coordinator.async_refresh()
    first, second = coordinator.data.loans
    assert first.language == "Norsk"
    assert second.language is None
    assert second.author is None
    assert second.subtitle == "Example series"
    assert coordinator.last_update_success
    assert client.async_get_record.await_count == 3
    client.async_get_record.side_effect = [
        record(MainMetadata=[{"Key": "Language", "Value": "English"}]),
        record("record-b", MainMetadata=[{"Key": "Publisher", "Value": "New Press"}]),
    ]
    await coordinator.async_refresh()
    first, second = coordinator.data.loans
    assert first.language == "English"
    assert second.publisher == "New Press"
    assert client.async_get_record.await_count == 5


async def test_bibliographic_metadata_and_circulation_are_entry_local(
    setup_coordinator, hass
):
    coordinator, entry, client = setup_coordinator
    client.async_get_record.return_value = record(
        MainMetadata=[{"Key": "Publisher", "Value": "First Press"}]
    )
    await coordinator.async_config_entry_first_refresh()
    other_entry = MockConfigEntry(
        domain=DOMAIN,
        data={**entry.data, "card": "TEST-OTHER-CARD", "device_id": "fedcba9876543210"},
    )
    other_entry.add_to_hass(hass)
    other_entry._async_set_state(hass, ConfigEntryState.SETUP_IN_PROGRESS, None)
    other_client = Mock(
        async_login=AsyncMock(return_value=[{}]),
        async_get_loans=AsyncMock(
            return_value=[loan(dueObject="/Date(1795651200000)/", canRenew=False)]
        ),
        async_get_record=AsyncMock(
            return_value=record(
                MainMetadata=[{"Key": "Publisher", "Value": "Second Press"}]
            )
        ),
    )
    other = AxiellCoordinator(hass, other_entry, other_client)
    await other.async_config_entry_first_refresh()
    client.async_get_loans.return_value = [loan(Overdue=True)]
    await coordinator.async_refresh()
    assert coordinator.data.loans[0].publisher == "First Press"
    assert coordinator.data.loans[0].due_date == date(2026, 11, 19)
    assert coordinator.data.loans[0].overdue is True
    assert other.data.loans[0].publisher == "Second Press"
    assert other.data.loans[0].due_date == date(2026, 11, 26)
    assert other.data.loans[0].overdue is False
    assert other.data.loans[0].can_renew is False
    client.async_get_record.assert_awaited_once_with("record-a", "ILS")
    other_client.async_get_record.assert_awaited_once_with("record-a", "ILS")
