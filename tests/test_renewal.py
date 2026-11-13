"""Offline consent and serialized writes against the real account coordinator."""

import asyncio
from datetime import date
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant.common import MockConfigEntry

from custom_components.axiell_libraries.coordinator import AxiellCoordinator
from custom_components.axiell_libraries.renewal import RenewalError
from custom_components.axiell_libraries.solus import (
    RenewalReply,
    SolusAuthError,
    SolusConnectionError,
    SolusProtocolError,
    SolusSessionExpired,
)
from tests.test_coordinator import CARD, DEVICE, PIN, loan
from tests.test_coordinator import setup_coordinator as setup_coordinator


async def test_explicit_renewal_reads_current_account_then_publishes(setup_coordinator):
    coordinator, entry, client = setup_coordinator
    await coordinator.async_config_entry_first_refresh()
    client.async_get_loans.side_effect = [
        [loan(source="CURRENT"), loan(loan_id="other-copy")],
        [loan(source="CURRENT", dueObject="/Date(1795651200000)/")],
    ]
    client.async_renew_loan = AsyncMock(return_value=RenewalReply("success", "Renewed"))
    result = await coordinator.async_renew_loan("loan-a")
    assert result.as_dict() == {
        "status": "renewed",
        "loan_id": "loan-a",
        "message": "Renewed",
        "refreshed": True,
    }
    assert coordinator.data.loans[0].due_date == date(2026, 11, 26)
    client.async_renew_loan.assert_awaited_once_with(
        CARD,
        "loan-a",
        "CURRENT",
        acknowledged_codes=(),
        sensitive_values=(CARD, PIN, DEVICE),
    )
    assert client.async_get_loans.await_count == 3
    client.async_login.assert_awaited_once()
    assert entry.data["device_id"] == DEVICE


@pytest.fixture
async def ready(setup_coordinator):
    coordinator, entry, client = setup_coordinator
    client.async_renew_loan = AsyncMock(return_value=RenewalReply("success", "Renewed"))
    await coordinator.async_config_entry_first_refresh()
    return coordinator, entry, client


async def assert_error(coordinator, code, **kwargs):
    with pytest.raises(RenewalError) as exc:
        await coordinator.async_renew_loan("loan-a", **kwargs)
    assert exc.value.code == code
    assert str(exc.value) == "Library renewal failed"
    return exc.value


async def prompt(coordinator, client, cost=2.5):
    client.async_get_loans.return_value = [loan(renewalCost=cost)]
    result = await coordinator.async_renew_loan("loan-a")
    assert result.status == "confirmation_required"
    assert result.expires_in == 600
    assert result.confirmation_id
    return result.confirmation_id


@pytest.mark.parametrize(
    "kwargs",
    [
        {"confirm": True},
        {"confirmation_id": "invalid"},
        {"confirm": True, "confirmation_id": ""},
        {"confirm": "true"},
    ],
)
async def test_confirmation_fields_must_be_paired_before_reads(ready, kwargs):
    coordinator, _, client = ready
    client.async_get_loans.reset_mock()
    await assert_error(coordinator, "invalid_confirmation", **kwargs)
    client.async_get_loans.assert_not_awaited()
    client.async_renew_loan.assert_not_awaited()


@pytest.mark.parametrize(
    "rows,code",
    [
        ([], "loan_not_found"),
        ([loan(canRenew=False)], "not_renewable"),
        ([loan(Source="")], "missing_source"),
    ],
)
async def test_current_authoritative_loan_is_required(ready, rows, code):
    coordinator, _, client = ready
    client.async_get_loans.return_value = rows
    await assert_error(coordinator, code)
    client.async_renew_loan.assert_not_awaited()


async def test_local_cost_consent_never_invents_a_provider_code(ready):
    coordinator, _, client = ready
    token = await prompt(coordinator, client)
    client.async_renew_loan.assert_not_awaited()
    result = await coordinator.async_renew_loan(
        "loan-a", confirm=True, confirmation_id=token
    )
    assert result.status == "renewed"
    assert client.async_renew_loan.await_args.kwargs["acknowledged_codes"] == ()
    await assert_error(
        coordinator, "invalid_confirmation", confirm=True, confirmation_id=token
    )
    assert client.async_renew_loan.await_count == 1


@pytest.mark.parametrize(
    "change",
    [
        {"dueObject": "/Date(1795046400001)/"},
        {"Source": "OTHER"},
        {"renewalCost": 3},
        {"renewalCost": "malformed"},
        {"itemID": "new"},
        {"recordID": "new"},
        {"RenewalCount": 2},
        {"RenewalsRemaining": 0},
        {"OverdueSpecified": True},
        {"Overdue": True},
        {"canRenew": False},
    ],
)
async def test_changed_original_circulation_rejects_consumed_consent(ready, change):
    coordinator, _, client = ready
    token = await prompt(coordinator, client)
    client.async_get_loans.return_value = [loan(renewalCost=2.5) | change]
    await assert_error(coordinator, "loan_changed", confirm=True, confirmation_id=token)
    client.async_renew_loan.assert_not_awaited()
    await assert_error(
        coordinator, "invalid_confirmation", confirm=True, confirmation_id=token
    )


async def test_metadata_changes_do_not_invalidate_consent(ready):
    coordinator, _, client = ready
    token = await prompt(coordinator, client)
    client.async_get_loans.return_value = [loan(renewalCost=2.5, title="New title")]
    result = await coordinator.async_renew_loan(
        "loan-a", confirm=True, confirmation_id=token
    )
    assert result.status == "renewed"


async def test_expired_token_rejected_before_read_or_write(ready):
    coordinator, _, client = ready
    with patch(
        "custom_components.axiell_libraries.renewal.time.monotonic", return_value=0
    ):
        token = await prompt(coordinator, client)
    client.async_get_loans.reset_mock()
    with patch(
        "custom_components.axiell_libraries.renewal.time.monotonic", return_value=600
    ):
        await assert_error(
            coordinator, "invalid_confirmation", confirm=True, confirmation_id=token
        )
    client.async_get_loans.assert_not_awaited()
    client.async_renew_loan.assert_not_awaited()


async def test_wrong_token_does_not_consume_valid_consent(ready):
    coordinator, _, client = ready
    token = await prompt(coordinator, client)
    await assert_error(
        coordinator, "invalid_confirmation", confirm=True, confirmation_id="wrong"
    )
    assert (
        await coordinator.async_renew_loan(
            "loan-a", confirm=True, confirmation_id=token
        )
    ).status == "renewed"


async def test_confirmation_is_private_to_account_even_with_same_loan_id(ready, hass):
    coordinator, entry, client = ready
    token = await prompt(coordinator, client)
    other_entry = MockConfigEntry(
        domain=entry.domain, data={**entry.data, "card": "OTHER"}
    )
    other_entry.add_to_hass(hass)
    other_entry._async_set_state(hass, ConfigEntryState.SETUP_IN_PROGRESS, None)
    other_client = Mock(
        async_login=AsyncMock(),
        async_get_loans=AsyncMock(return_value=[loan(source="OTHER-ILS")]),
        async_get_record=AsyncMock(return_value=None),
        async_renew_loan=AsyncMock(return_value=RenewalReply("success", "Renewed")),
    )
    other = AxiellCoordinator(hass, other_entry, other_client)
    await other.async_config_entry_first_refresh()
    await assert_error(
        other, "invalid_confirmation", confirm=True, confirmation_id=token
    )
    other_client.async_renew_loan.assert_not_awaited()
    assert (await other.async_renew_loan("loan-a")).status == "renewed"
    assert other_client.async_renew_loan.await_args.args == (
        "OTHER",
        "loan-a",
        "OTHER-ILS",
    )
    client.async_renew_loan.assert_not_awaited()


async def test_each_provider_challenge_requires_new_consent_preserving_codes(ready):
    coordinator, _, client = ready
    token = await prompt(coordinator, client)
    client.async_renew_loan.side_effect = [
        RenewalReply("confirmation_required", "First prompt", "first"),
        RenewalReply("confirmation_required", "Second prompt", "Second"),
        RenewalReply("success", "Renewed"),
    ]
    for expected, status in [
        ((), "confirmation_required"),
        (("first",), "confirmation_required"),
        (("first", "Second"), "renewed"),
    ]:
        result = await coordinator.async_renew_loan(
            "loan-a", confirm=True, confirmation_id=token
        )
        assert result.status == status
        assert (
            client.async_renew_loan.await_args.kwargs["acknowledged_codes"] == expected
        )
        assert "acknowledgement_code" not in result.as_dict()
        assert "First prompt" not in repr(result)
        token = result.confirmation_id
    assert client.async_renew_loan.await_count == 3


@pytest.mark.parametrize("repeated", [True, False])
async def test_repeated_or_more_than_five_challenges_stop(ready, repeated):
    coordinator, _, client = ready
    client.async_renew_loan.side_effect = [
        RenewalReply("confirmation_required", "Consent", str(0 if repeated else index))
        for index in range(6)
    ]
    result = await coordinator.async_renew_loan("loan-a")
    for _ in range(0 if repeated else 4):
        result = await coordinator.async_renew_loan(
            "loan-a", confirm=True, confirmation_id=result.confirmation_id
        )
    await assert_error(
        coordinator,
        "confirmation_limit",
        confirm=True,
        confirmation_id=result.confirmation_id,
    )
    assert client.async_renew_loan.await_count == (2 if repeated else 6)


async def test_new_prompt_replaces_same_loan_token_and_pending_map_is_bounded(ready):
    coordinator, _, client = ready
    first = await prompt(coordinator, client)
    second = await prompt(coordinator, client)
    assert first != second
    await assert_error(
        coordinator, "invalid_confirmation", confirm=True, confirmation_id=first
    )
    for index in range(32):
        client.async_get_loans.return_value = [
            loan(loan_id=f"loan-{index}", renewalCost=1)
        ]
        await coordinator.async_renew_loan(f"loan-{index}")
    await assert_error(
        coordinator, "invalid_confirmation", confirm=True, confirmation_id=second
    )
    client.async_renew_loan.assert_not_awaited()


async def test_concurrent_submissions_consume_token_before_preflight_await(ready):
    coordinator, _, client = ready
    token = await prompt(coordinator, client)
    entered, release = asyncio.Event(), asyncio.Event()

    async def read(*args):
        entered.set()
        await release.wait()
        return [loan(renewalCost=2.5)]

    client.async_get_loans.side_effect = read
    first = asyncio.create_task(
        coordinator.async_renew_loan("loan-a", confirm=True, confirmation_id=token)
    )
    await entered.wait()
    second = asyncio.create_task(
        coordinator.async_renew_loan("loan-a", confirm=True, confirmation_id=token)
    )
    release.set()
    results = await asyncio.gather(first, second, return_exceptions=True)
    assert results[0].status == "renewed"
    assert results[1].code == "invalid_confirmation"
    client.async_renew_loan.assert_awaited_once()


@pytest.mark.parametrize(
    "error",
    [SolusConnectionError, SolusSessionExpired, SolusProtocolError, SolusAuthError],
)
async def test_uncertain_write_is_never_repeated_and_reconciles(ready, error):
    coordinator, _, client = ready
    client.async_renew_loan.side_effect = error("PRIVATE")
    client.async_get_loans.side_effect = [
        [loan()],
        [loan(dueObject="/Date(1795651200000)/")],
    ]
    result = await assert_error(coordinator, "outcome_unknown")
    assert "PRIVATE" not in repr(result) + result.message
    client.async_renew_loan.assert_awaited_once()
    assert coordinator.data.loans[0].due_date == date(2026, 11, 26)
    client.async_renew_loan.side_effect = None
    client.async_get_loans.side_effect = [[loan(canRenew=False)]]
    await assert_error(coordinator, "not_renewable")
    assert client.async_renew_loan.await_count == 1


async def test_provider_rejection_has_static_exception_and_safe_message(ready, caplog):
    coordinator, _, client = ready
    client.async_renew_loan.return_value = RenewalReply("error", "Provider denied")
    result = await assert_error(coordinator, "provider_rejected")
    assert result.message == "Provider denied"
    assert "Provider denied" not in str(result) + repr(result) + caplog.text
    client.async_renew_loan.assert_awaited_once()


@pytest.mark.parametrize("known_success", [True, False])
async def test_postwrite_refresh_failure_retains_known_vs_unknown_outcome(
    ready, known_success
):
    coordinator, _, client = ready
    if not known_success:
        client.async_renew_loan.side_effect = SolusConnectionError("PRIVATE")
    client.async_get_loans.side_effect = [[loan()], SolusConnectionError("PRIVATE")]
    if known_success:
        result = await coordinator.async_renew_loan("loan-a")
        assert result.status == "renewed"
        assert result.refreshed is False
    else:
        await assert_error(coordinator, "outcome_unknown")
    assert coordinator.last_update_success is False
    assert "PRIVATE" not in str(coordinator.last_exception)
    client.async_renew_loan.assert_awaited_once()


@pytest.mark.parametrize("authentication", [True, False])
async def test_failed_preflight_consumes_consent_without_write(
    ready, authentication, caplog
):
    coordinator, entry, client = ready
    token = await prompt(coordinator, client)
    error = SolusAuthError if authentication else SolusConnectionError
    client.async_get_loans.side_effect = error("PRIVATE")
    with patch.object(type(entry), "async_start_reauth") as reauth:
        await assert_error(
            coordinator,
            "authentication_failed" if authentication else "refresh_failed",
            confirm=True,
            confirmation_id=token,
        )
        assert reauth.call_count == int(authentication)
    assert not coordinator.last_update_success
    assert "PRIVATE" not in caplog.text
    await assert_error(
        coordinator, "invalid_confirmation", confirm=True, confirmation_id=token
    )
    client.async_renew_loan.assert_not_awaited()


async def test_reconciliation_recovers_expired_session_once_without_write_retry(ready):
    coordinator, entry, client = ready
    client.async_renew_loan.side_effect = SolusSessionExpired("PRIVATE")
    client.async_get_loans.side_effect = [
        [loan()],
        SolusSessionExpired("PRIVATE"),
        [loan()],
    ]
    await assert_error(coordinator, "outcome_unknown")
    assert client.async_login.await_count == 2
    assert client.async_get_loans.await_count == 4
    assert entry.data["device_id"] == DEVICE
    client.async_renew_loan.assert_awaited_once()


async def test_reconciliation_auth_failure_starts_reauth_without_leaking(ready, caplog):
    coordinator, entry, client = ready
    client.async_renew_loan.side_effect = SolusSessionExpired("PRIVATE")
    client.async_get_loans.side_effect = [
        [loan()],
        SolusSessionExpired("PRIVATE"),
        SolusSessionExpired("PRIVATE"),
    ]
    with patch.object(type(entry), "async_start_reauth") as reauth:
        await assert_error(coordinator, "outcome_unknown")
        reauth.assert_called_once()
    assert not coordinator.last_update_success
    assert "PRIVATE" not in caplog.text
    client.async_renew_loan.assert_awaited_once()


async def checkpoint():
    """Let already scheduled callbacks run, without a wall-clock race."""
    reached = asyncio.Event()
    asyncio.get_running_loop().call_soon(reached.set)
    await reached.wait()


@pytest.mark.parametrize("write_first", [True, False])
async def test_poll_and_write_share_one_operation_lock(ready, write_first):
    coordinator, _, client = ready
    entered, release, second_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    events = []

    async def read(*args):
        events.append("read")
        if not write_first and len(events) == 1:
            entered.set()
            await release.wait()
        return [loan()]

    async def write(*args, **kwargs):
        events.append("write")
        if write_first:
            entered.set()
            await release.wait()
        return RenewalReply("success", "Renewed")

    async def second_operation():
        second_started.set()
        if write_first:
            await coordinator.async_refresh()
        else:
            await coordinator.async_renew_loan("loan-a")

    client.async_get_loans.side_effect = read
    client.async_renew_loan.side_effect = write
    first = asyncio.create_task(
        coordinator.async_renew_loan("loan-a")
        if write_first
        else coordinator.async_refresh()
    )
    await entered.wait()
    second = asyncio.create_task(second_operation())
    await second_started.wait()
    try:
        assert events == (["read", "write"] if write_first else ["read"])
    finally:
        release.set()
        await asyncio.gather(first, second)
    assert events == (
        ["read", "write", "read", "read"]
        if write_first
        else ["read", "read", "write", "read"]
    )


@pytest.mark.parametrize("failure", [False, True])
async def test_caller_cancel_after_dispatch_drains_reconciliation_before_poll(
    ready, failure
):
    coordinator, _, client = ready
    dispatched, release, poll_started = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    events = []

    async def write(*args, **kwargs):
        events.append("write")
        dispatched.set()
        await release.wait()
        events.append("reply")
        if failure:
            raise SolusConnectionError("PRIVATE")
        return RenewalReply("success", "Renewed")

    async def read(*args):
        events.append("read")
        return [loan()]

    async def poll():
        poll_started.set()
        await coordinator.async_refresh()

    client.async_get_loans.side_effect = read
    client.async_renew_loan.side_effect = write
    caller = asyncio.create_task(coordinator.async_renew_loan("loan-a"))
    await dispatched.wait()
    caller.cancel()
    polling = asyncio.create_task(poll())
    await poll_started.wait()
    try:
        await checkpoint()
        assert not caller.done()
        assert events == ["read", "write"]
    finally:
        release.set()
        outcomes = await asyncio.gather(caller, polling, return_exceptions=True)
    assert isinstance(outcomes[0], asyncio.CancelledError)
    assert events == ["read", "write", "reply", "read", "read"]
    client.async_renew_loan.assert_awaited_once()


async def test_shutdown_rejects_queued_actions_and_clears_consent(ready):
    coordinator, _, client = ready
    token = await prompt(coordinator, client)
    dispatched, release, queued_started = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )

    async def write(*args, **kwargs):
        dispatched.set()
        await release.wait()
        return RenewalReply("success", "Renewed")

    client.async_renew_loan.side_effect = write
    active = asyncio.create_task(
        coordinator.async_renew_loan("loan-a", confirm=True, confirmation_id=token)
    )
    await dispatched.wait()

    async def queued():
        queued_started.set()
        return await coordinator.async_renew_loan("loan-a")

    queued_task = asyncio.create_task(queued())
    await queued_started.wait()
    shutdown = asyncio.create_task(coordinator.async_shutdown())
    await checkpoint()
    try:
        assert not shutdown.done()
    finally:
        release.set()
        results = await asyncio.gather(
            active, queued_task, shutdown, return_exceptions=True
        )
    assert results[0].status == "renewed"
    assert results[1].code == "entry_closing"
    await assert_error(coordinator, "entry_closing")
    client.async_renew_loan.assert_awaited_once()


@pytest.mark.parametrize(
    "initial,changed",
    [
        ({"renewalCost": {"malformed": 1}}, {"renewalCost": {"malformed": 2}}),
        ({"renewalCost": "bad-a"}, {"renewalCost": "bad-b"}),
        ({"dueObject": "bad-a"}, {"dueObject": "bad-b"}),
        ({}, {"itemID": None}),
        ({"Source": "ILS"}, {"Source": " ILS "}),
        ({"RenewalCount": 1}, {"RenewalCount": True}),
    ],
)
async def test_fingerprint_preserves_malformed_raw_values_and_types(
    ready, initial, changed
):
    coordinator, _, client = ready
    client.async_get_loans.return_value = [loan() | initial]
    client.async_renew_loan.return_value = RenewalReply(
        "confirmation_required", "Consent", "Code"
    )
    result = await coordinator.async_renew_loan("loan-a")
    client.async_get_loans.return_value = [loan() | changed]
    await assert_error(
        coordinator,
        "loan_changed",
        confirm=True,
        confirmation_id=result.confirmation_id,
    )
    client.async_renew_loan.assert_awaited_once()


async def test_same_record_different_copy_cannot_reuse_consent(ready):
    coordinator, _, client = ready
    token = await prompt(coordinator, client)
    client.async_get_loans.return_value = [loan(loan_id="loan-b", renewalCost=2.5)]
    with pytest.raises(RenewalError) as exc:
        await coordinator.async_renew_loan(
            "loan-b", confirm=True, confirmation_id=token
        )
    assert exc.value.code == "invalid_confirmation"
    client.async_renew_loan.assert_not_awaited()


async def test_cancelled_shutdown_still_drains_and_clears_pending_consent(ready):
    coordinator, _, client = ready
    await prompt(coordinator, client)
    client.async_get_loans.return_value = [loan(loan_id="loan-b")]
    dispatched, release = asyncio.Event(), asyncio.Event()
    closed = Mock()
    coordinator._close_session = closed

    async def write(*args, **kwargs):
        dispatched.set()
        await release.wait()
        return RenewalReply("confirmation_required", "Consent", "code")

    client.async_renew_loan.side_effect = write
    active = asyncio.create_task(coordinator.async_renew_loan("loan-b"))
    await dispatched.wait()
    shutdown = asyncio.create_task(coordinator.async_shutdown())
    await checkpoint()
    shutdown.cancel()
    await checkpoint()
    try:
        assert not shutdown.done()
        closed.assert_not_called()
    finally:
        release.set()
        results = await asyncio.gather(active, shutdown, return_exceptions=True)
    assert results[0].status == "confirmation_required"
    assert isinstance(results[1], asyncio.CancelledError)
    closed.assert_called_once()
    assert not coordinator._renewal._pending
    assert coordinator._renewal_task is None


@pytest.mark.parametrize(
    "injected",
    [{"source": "OTHER"}, {"user_id": "OTHER"}, {"acknowledged_codes": ("code",)}],
)
async def test_callers_cannot_inject_source_account_or_acknowledgements(
    ready, injected
):
    coordinator, _, client = ready
    with pytest.raises(TypeError):
        await coordinator.async_renew_loan("loan-a", **injected)
    client.async_renew_loan.assert_not_awaited()


async def test_confirmation_result_exposes_only_small_safe_fields(ready):
    coordinator, _, client = ready
    client.async_get_loans.return_value = [loan(renewalCost=2.5)]
    result = await coordinator.async_renew_loan("loan-a")
    assert result.as_dict() == {
        "status": "confirmation_required",
        "loan_id": "loan-a",
        "message": "Renewal costs 2.5. Confirm to continue.",
        "refreshed": True,
        "confirmation_id": result.confirmation_id,
        "expires_in": 600,
    }
    client.async_renew_loan.assert_not_awaited()
