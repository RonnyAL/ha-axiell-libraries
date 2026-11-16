"""Offline recovery schedules, freshness, and serialization contracts."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant.common import async_fire_time_changed

from custom_components.axiell_libraries import AxiellEntity
from custom_components.axiell_libraries.renewal import RenewalError
from custom_components.axiell_libraries.solus import (
    SolusAuthError,
    SolusConnectionError,
    SolusProtocolError,
    SolusSecurityError,
    SolusSessionExpired,
)
from tests.test_coordinator import loan
from tests.test_coordinator import setup_coordinator as setup_coordinator


async def advance(hass, freezer, seconds):
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, datetime.now(UTC))
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.mark.parametrize("error", [SolusConnectionError, SolusProtocolError])
async def test_failed_poll_automatically_recovers_without_reload(
    setup_coordinator, hass, freezer, error
):
    coordinator, entry, client = setup_coordinator
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entity = AxiellEntity(entry, "loans")
    previous = coordinator.data
    unsubscribe = coordinator.async_add_listener(Mock())
    try:
        client.async_get_loans.side_effect = [error("PRIVATE"), []]
        await coordinator.async_refresh()
        assert entity.available
        assert entity.extra_state_attributes["data_stale"] is True
        assert coordinator.data is previous
        assert coordinator.last_update_error
        await advance(hass, freezer, 80)
        assert coordinator.last_update_success
        assert coordinator.data.loans == ()
        assert entity.extra_state_attributes["data_stale"] is False
        assert entity.extra_state_attributes["last_update_error"] is None
        assert coordinator.data.fetched_at > previous.fetched_at
        client.async_login.assert_awaited_once()
    finally:
        unsubscribe()


async def test_only_three_early_recovery_cycles_then_normal_interval(
    setup_coordinator, hass, freezer, caplog
):
    coordinator, _, client = setup_coordinator
    await coordinator.async_config_entry_first_refresh()
    unsubscribe = coordinator.async_add_listener(Mock())
    client.async_get_loans.side_effect = SolusConnectionError("PRIVATE")
    try:
        with patch(
            "custom_components.axiell_libraries.coordinator.random.uniform",
            return_value=0,
        ):
            await coordinator.async_refresh()
            for delay in (62, 122, 242):
                await advance(hass, freezer, delay)
            assert client.async_get_loans.await_count == 5  # initial + failure + 3
            await advance(hass, freezer, 600)
            assert client.async_get_loans.await_count == 5
            await advance(hass, freezer, 6 * 3600)
            assert client.async_get_loans.await_count == 6
            await advance(hass, freezer, 600)
            assert client.async_get_loans.await_count == 6
        assert caplog.text.count("Error fetching axiell_libraries data") == 1
        assert "PRIVATE" not in caplog.text
    finally:
        unsubscribe()


async def test_retry_after_blocks_manual_reads_options_and_renewal_preflight(
    setup_coordinator, hass, freezer
):
    coordinator, entry, client = setup_coordinator
    await coordinator.async_config_entry_first_refresh()
    client.async_renew_loan = AsyncMock()
    unsubscribe = coordinator.async_add_listener(Mock())
    try:
        client.async_get_loans.side_effect = [
            SolusConnectionError("PRIVATE", reason="http", status=429, retry_after=900),
            [],
        ]
        await coordinator.async_refresh()
        assert "429" in str(coordinator.last_exception)
        await coordinator.async_refresh()
        hass.config_entries.async_update_entry(entry, options={"update_interval": 30})
        await coordinator.async_update_options()
        with pytest.raises(RenewalError, match="Library renewal failed"):
            await coordinator.async_renew_loan("loan-a")
        client.async_renew_loan.assert_not_awaited()
        assert client.async_get_loans.await_count == 2
        await advance(hass, freezer, 899)
        assert client.async_get_loans.await_count == 2
        await advance(hass, freezer, 3)
        assert coordinator.last_update_success
        assert coordinator.update_interval == timedelta(minutes=30)
        assert client.async_get_loans.await_count == 3
    finally:
        unsubscribe()


@pytest.mark.parametrize("error", [SolusAuthError, SolusSecurityError])
async def test_unsafe_or_rejected_account_is_unavailable_and_not_fast_retried(
    setup_coordinator, hass, freezer, error
):
    coordinator, entry, client = setup_coordinator
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entity = AxiellEntity(entry, "loans")
    unsubscribe = coordinator.async_add_listener(Mock())
    try:
        client.async_get_loans.side_effect = error("PRIVATE")
        with patch.object(entry, "async_start_reauth_if_available") as reauth:
            await coordinator.async_refresh()
        assert not entity.available
        assert bool(reauth.call_count) == (error is SolusAuthError)
        await advance(hass, freezer, 600)
        assert client.async_get_loans.await_count == 2
    finally:
        unsubscribe()


async def test_repeated_session_expiry_does_not_request_new_credentials(
    setup_coordinator,
):
    coordinator, entry, client = setup_coordinator
    await coordinator.async_config_entry_first_refresh()
    client.async_get_loans.side_effect = SolusSessionExpired("expired")
    with patch.object(entry, "async_start_reauth_if_available") as reauth:
        await coordinator.async_refresh()
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert not isinstance(coordinator.last_exception, ConfigEntryAuthFailed)
    reauth.assert_not_called()
    assert client.async_login.await_count == 2
    client.async_get_loans.side_effect = None
    await coordinator.async_refresh()
    assert coordinator.last_update_success


async def test_changed_failure_category_updates_listener_without_log_spam(
    setup_coordinator, caplog
):
    coordinator, _, client = setup_coordinator
    await coordinator.async_config_entry_first_refresh()
    updates = []
    unsubscribe = coordinator.async_add_listener(
        lambda: updates.append(coordinator.last_update_error)
    )
    try:
        for error in (SolusConnectionError("PRIVATE"), SolusProtocolError("PRIVATE")):
            client.async_get_loans.side_effect = error
            await coordinator.async_refresh()
        assert updates[-1].startswith("protocol/")
        assert any(item.startswith("transport/") for item in updates)
        assert caplog.text.count("Error fetching axiell_libraries data") == 1
    finally:
        unsubscribe()


async def test_recovery_timer_serializes_with_write_and_does_not_repeat_it(
    setup_coordinator, hass, freezer
):
    coordinator, _, client = setup_coordinator
    await coordinator.async_config_entry_first_refresh()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def renew(*args, **kwargs):
        entered.set()
        await release.wait()
        raise SolusConnectionError("lost reply")

    client.async_renew_loan = AsyncMock(side_effect=renew)
    unsubscribe = coordinator.async_add_listener(Mock())
    client.async_get_loans.side_effect = SolusConnectionError("temporary")
    await coordinator.async_refresh()
    client.async_get_loans.side_effect = None
    task = asyncio.create_task(coordinator.async_renew_loan("loan-a"))
    try:
        await entered.wait()
        reads = client.async_get_loans.await_count
        # A scheduled poll queues behind the write's operation lock.
        freezer.tick(timedelta(hours=6, seconds=2))
        async_fire_time_changed(hass, datetime.now(UTC))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert client.async_get_loans.await_count == reads
        release.set()
        with pytest.raises(RenewalError) as exc:
            await task
        assert exc.value.code == "outcome_unknown"
        await hass.async_block_till_done(wait_background_tasks=True)
        client.async_renew_loan.assert_awaited_once()
        assert coordinator.last_update_success
    finally:
        release.set()
        unsubscribe()


async def test_write_rate_limit_defers_reconciliation_without_replaying_write(
    setup_coordinator,
):
    coordinator, _, client = setup_coordinator
    await coordinator.async_config_entry_first_refresh()
    client.async_renew_loan = AsyncMock(
        side_effect=SolusConnectionError(
            "PRIVATE", reason="http", status=429, retry_after=600
        )
    )
    with pytest.raises(RenewalError) as exc:
        await coordinator.async_renew_loan("loan-a")
    assert exc.value.code == "outcome_unknown"
    client.async_renew_loan.assert_awaited_once()
    assert client.async_get_loans.await_count == 2  # setup and preflight only
    assert not coordinator.last_update_success


async def test_security_error_in_catalogue_is_not_hidden(setup_coordinator):
    coordinator, _, client = setup_coordinator
    await coordinator.async_config_entry_first_refresh()
    previous = coordinator.data
    client.async_get_loans.return_value = [loan(record="uncached")]
    client.async_get_record.side_effect = SolusSecurityError("PRIVATE")
    await coordinator.async_refresh()
    assert coordinator.data is previous
    assert not coordinator.last_update_success
    assert coordinator.last_update_error.startswith("security/")


async def test_shutdown_cancels_scheduled_recovery(setup_coordinator, hass, freezer):
    coordinator, _, client = setup_coordinator
    await coordinator.async_config_entry_first_refresh()
    coordinator.async_add_listener(Mock())
    client.async_get_loans.side_effect = SolusConnectionError("temporary")
    await coordinator.async_refresh()
    await coordinator.async_shutdown()
    await advance(hass, freezer, 600)
    assert client.async_get_loans.await_count == 2


async def test_catalogue_rate_limit_takes_precedence_over_parallel_session_expiry(
    setup_coordinator, hass, freezer
):
    coordinator, _, client = setup_coordinator
    await coordinator.async_config_entry_first_refresh()
    previous = coordinator.data
    client.async_get_loans.return_value = [
        loan(record="uncached-a", loan_id="a"),
        loan(record="uncached-b", loan_id="b"),
    ]
    both_started = asyncio.Event()
    active = 0

    async def record(record_id, source):
        nonlocal active
        active += 1
        if active == 2:
            both_started.set()
        await both_started.wait()
        if record_id == "uncached-a":
            raise SolusSessionExpired("PRIVATE")
        raise SolusConnectionError(
            "PRIVATE", reason="http", status=429, retry_after=900
        )

    client.async_get_record.side_effect = record
    unsubscribe = coordinator.async_add_listener(Mock())
    try:
        await coordinator.async_refresh()
        client.async_login.assert_awaited_once()  # no relogin during provider cooldown
        assert coordinator.data is previous
        await advance(hass, freezer, 899)
        assert client.async_get_loans.await_count == 2
    finally:
        unsubscribe()


async def test_success_resets_early_recovery_budget(setup_coordinator, hass, freezer):
    coordinator, _, client = setup_coordinator
    await coordinator.async_config_entry_first_refresh()
    unsubscribe = coordinator.async_add_listener(Mock())
    try:
        for _ in range(2):
            client.async_get_loans.side_effect = [SolusConnectionError("offline"), []]
            await coordinator.async_refresh()
            await advance(hass, freezer, 80)
            assert coordinator.last_update_success
        assert client.async_get_loans.await_count == 5
    finally:
        unsubscribe()


async def test_polling_disabled_does_not_schedule_recovery(
    setup_coordinator, hass, freezer
):
    coordinator, entry, client = setup_coordinator
    hass.config_entries.async_update_entry(entry, pref_disable_polling=True)
    await coordinator.async_config_entry_first_refresh()
    unsubscribe = coordinator.async_add_listener(Mock())
    try:
        client.async_get_loans.side_effect = SolusConnectionError("offline")
        await coordinator.async_refresh()
        await advance(hass, freezer, 600)
        assert client.async_get_loans.await_count == 2
    finally:
        unsubscribe()


@pytest.mark.parametrize("stage", ["loans", "catalogue"])
async def test_session_retry_after_prevents_immediate_relogin(
    setup_coordinator, hass, freezer, stage
):
    coordinator, _, client = setup_coordinator
    await coordinator.async_config_entry_first_refresh()
    target = client.async_get_loans
    if stage == "catalogue":
        client.async_get_loans.return_value = [loan(record="uncached")]
        target = client.async_get_record
    target.side_effect = SolusSessionExpired(reason="http", status=401, retry_after=900)
    unsubscribe = coordinator.async_add_listener(Mock())
    try:
        await coordinator.async_refresh()
        client.async_login.assert_awaited_once()
        await advance(hass, freezer, 899)
        client.async_login.assert_awaited_once()
        client.async_get_loans.side_effect = None
        client.async_get_loans.return_value = []
        await advance(hass, freezer, 3)
        assert coordinator.last_update_success
        assert client.async_login.await_count == 2
    finally:
        unsubscribe()


async def test_setup_retry_preserves_provider_cooldown(
    setup_coordinator, hass, freezer
):
    from homeassistant.exceptions import ConfigEntryNotReady

    from custom_components.axiell_libraries.coordinator import AxiellCoordinator

    coordinator, entry, client = setup_coordinator
    client.async_login.side_effect = SolusConnectionError(
        reason="http", status=429, retry_after=900
    )
    with pytest.raises(ConfigEntryNotReady):
        await coordinator.async_config_entry_first_refresh()
    await coordinator.async_shutdown()
    replacement = AxiellCoordinator(hass, entry, client)
    with pytest.raises(ConfigEntryNotReady):
        await replacement.async_config_entry_first_refresh()
    client.async_login.assert_awaited_once()
    await advance(hass, freezer, 901)
    client.async_login.side_effect = None
    await replacement.async_config_entry_first_refresh()
    assert replacement.last_update_success
    assert client.async_login.await_count == 2


async def test_setup_outage_leaves_backoff_to_core_without_resetting_retry_hint(
    setup_coordinator,
):
    from homeassistant.exceptions import ConfigEntryNotReady

    coordinator, _, client = setup_coordinator
    client.async_login.side_effect = SolusConnectionError("offline")
    with pytest.raises(ConfigEntryNotReady):
        await coordinator.async_config_entry_first_refresh()
    # A constant hint on each new coordinator would defeat Core's setup backoff.
    assert coordinator.last_exception.retry_after is None
