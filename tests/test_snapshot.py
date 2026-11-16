"""Offline storage and startup contracts for coherent account snapshots."""

import asyncio
import importlib.util
import json
from copy import deepcopy
from datetime import UTC, date, datetime
from types import MappingProxyType
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.helpers.storage import Store

from custom_components.axiell_libraries import async_setup_entry
from custom_components.axiell_libraries.const import DOMAIN
from custom_components.axiell_libraries.coordinator import AxiellCoordinator
from custom_components.axiell_libraries.models import LibrarySnapshot, Loan
from custom_components.axiell_libraries.solus import (
    SolusAuthError,
    SolusConnectionError,
    SolusSecurityError,
)
from tests.test_coordinator import setup_coordinator as setup_coordinator

REAL_STORE_LOAD = Store._async_load
REAL_STORE_WRITE = Store._async_write_data
REAL_STORE_REMOVE = Store.async_remove

NOW = datetime(2026, 11, 13, tzinfo=UTC)


def snapshot():
    return LibrarySnapshot(
        loans=(
            Loan(
                loan_id="copy-a",
                record_id="record-a",
                title="Synthetic book",
                due_date=date(2026, 11, 19),
                can_renew=True,
                overdue=False,
                source="ILS",
                renewal_count=2,
                renewal_cost=3.5,
                image_url="https://images.example.org/cover.jpg",
                main_metadata=MappingProxyType(
                    {"Publisher": "Example", "Token": "secret"}
                ),
                api_fields=MappingProxyType({"title": "RAW-NEVER-SAVE"}),
            ),
        ),
        fetched_at=NOW,
    )


def store_for(hass, entry):
    name = "custom_components.axiell_libraries.snapshot"
    assert importlib.util.find_spec(name) is not None, (
        "account snapshot storage missing"
    )
    module = __import__(name, fromlist=["SnapshotStore"])
    return module.SnapshotStore(hass, entry)


async def raw_store(hass, entry):
    return Store(
        hass, 1, f"{DOMAIN}.{entry.entry_id}.snapshot", private=True, atomic_writes=True
    )


async def test_snapshot_roundtrip_allowlists_public_fields_and_empty(
    setup_coordinator, hass
):
    _, entry, _ = setup_coordinator
    store = store_for(hass, entry)
    await store.async_save(snapshot())
    restored, withheld = await store_for(hass, entry).async_load()
    assert restored.fetched_at == NOW
    assert restored.loans[0].due_date == date(2026, 11, 19)
    assert restored.loans[0].renewal_cost == 3.5
    assert dict(restored.loans[0].main_metadata) == {"Publisher": "Example"}
    assert not restored.loans[0].api_fields
    assert withheld is None
    payload = await (await raw_store(hass, entry)).async_load()
    encoded = json.dumps(payload)
    for forbidden in (
        "RAW-NEVER-SAVE",
        "secret",
        entry.data["card"],
        entry.data["pin"],
        entry.data["device_id"],
        "api_fields",
        "confirmation",
    ):
        assert forbidden not in encoded
    await store.async_save(LibrarySnapshot((), NOW))
    restored, _ = await store.async_load()
    assert restored.loans == ()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(schema=999),
        lambda p: p.update(fetched_at="2026-11-13T00:00:00"),
        lambda p: p.update(fetched_at="invalid"),
        lambda p: p.update(withheld="unknown"),
        lambda p: p.update(identity="wrong"),
        lambda p: p["loans"].append(deepcopy(p["loans"][0])),
        lambda p: p["loans"][0].update(loan_id=""),
        lambda p: p["loans"][0].update(title=""),
        lambda p: p["loans"][0].update(due_date="2026-02-30"),
        lambda p: p["loans"][0].update(can_renew=1),
        lambda p: p["loans"][0].update(overdue_specified="false"),
        lambda p: p["loans"][0].update(renewal_count=True),
        lambda p: p["loans"][0].update(renewals_remaining=-1),
        lambda p: p["loans"][0].update(renewal_cost=float("inf")),
        lambda p: p["loans"][0].update(image_url="https://user:pass@example.org/x"),
        lambda p: p["loans"][0].update(main_metadata={"AuthToken": "private"}),
        lambda p: p["loans"][0].update(api_fields={}),
        lambda p: p["loans"][0].update(description="x" * 32769),
    ],
)
async def test_malformed_cache_is_rejected_whole_and_removed(
    setup_coordinator, hass, hass_storage, mutation
):
    _, entry, _ = setup_coordinator
    store = store_for(hass, entry)
    await store.async_save(snapshot())
    raw = await raw_store(hass, entry)
    payload = await raw.async_load()
    mutation(payload)
    hass_storage[f"{DOMAIN}.{entry.entry_id}.snapshot"]["data"] = payload
    assert await store_for(hass, entry).async_load() is None
    assert await (await raw_store(hass, entry)).async_load() is None


async def test_identity_preserves_pin_but_isolates_account_and_entry(
    setup_coordinator, hass
):
    _, entry, _ = setup_coordinator
    store = store_for(hass, entry)
    await store.async_save(snapshot())
    hass.config_entries.async_update_entry(entry, data={**entry.data, "pin": "new-pin"})
    assert store.matches_identity(entry)
    hass.config_entries.async_update_entry(entry, data={**entry.data, "card": "OTHER"})
    assert not store.matches_identity(entry)
    assert await store_for(hass, entry).async_load() is None


async def test_coordinator_restores_stale_then_replaces_with_empty(
    setup_coordinator, hass
):
    coordinator, entry, client = setup_coordinator
    await store_for(hass, entry).async_save(snapshot())
    assert await coordinator.async_restore_snapshot()
    assert coordinator.data_freshness == "stale"
    assert coordinator.data.fetched_at == NOW
    client.async_login.assert_not_awaited()
    client.async_get_loans.return_value = []
    await coordinator.async_refresh()
    assert coordinator.data_freshness == "fresh"
    assert coordinator.data.loans == ()
    restored, _ = await store_for(hass, entry).async_load()
    assert restored.loans == ()


@pytest.mark.parametrize("error_type", [SolusAuthError, SolusSecurityError])
async def test_withholding_survives_transient_failure_and_reload(
    setup_coordinator, hass, error_type
):
    coordinator, entry, client = setup_coordinator
    await coordinator.async_config_entry_first_refresh()
    historical = coordinator.data.fetched_at
    client.async_get_loans.side_effect = error_type()
    await coordinator.async_refresh()
    assert not coordinator.snapshot_available
    client.async_get_loans.side_effect = SolusConnectionError()
    await coordinator.async_refresh()
    assert not coordinator.snapshot_available
    reloaded = AxiellCoordinator(hass, entry, client)
    assert await reloaded.async_restore_snapshot()
    assert not reloaded.snapshot_available
    assert reloaded.data.fetched_at == historical
    client.async_get_loans.side_effect = None
    await reloaded.async_refresh()
    assert reloaded.snapshot_available
    assert reloaded.data_freshness == "fresh"
    await coordinator.async_shutdown()
    await reloaded.async_shutdown()


async def test_cached_setup_forwards_before_blocked_provider_read(
    setup_coordinator, hass
):
    _, entry, client = setup_coordinator
    await store_for(hass, entry).async_save(snapshot())
    started, release = asyncio.Event(), asyncio.Event()

    async def blocked_read(*_):
        started.set()
        await release.wait()
        return []

    client.async_get_loans.side_effect = blocked_read
    forwarded = []

    async def forward(config, _platforms):
        forwarded.append(config.runtime_data.data_freshness)

    with (
        patch("custom_components.axiell_libraries.SolusClient", return_value=client),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", side_effect=forward
        ),
    ):
        assert await async_setup_entry(hass, entry)
        assert forwarded == ["stale"]
        await asyncio.wait_for(started.wait(), 2)
        assert entry.runtime_data.data_freshness == "stale"
        release.set()
        await hass.async_block_till_done(wait_background_tasks=True)
        assert entry.runtime_data.data_freshness == "fresh"
        await entry.runtime_data.async_shutdown()


async def test_successful_read_survives_disk_save_failure(setup_coordinator):
    coordinator, _, _ = setup_coordinator
    with patch("homeassistant.helpers.storage.Store.async_save", side_effect=OSError):
        await coordinator.async_config_entry_first_refresh()
    assert coordinator.data_freshness == "fresh"
    await coordinator.async_shutdown()


async def test_incompatible_store_envelope_is_removed(
    setup_coordinator, hass, hass_storage
):
    _, entry, _ = setup_coordinator
    key = f"{DOMAIN}.{entry.entry_id}.snapshot"
    hass_storage[key] = {"version": 999, "minor_version": 1, "data": {}}
    assert await store_for(hass, entry).async_load() is None
    assert key not in hass_storage


async def test_private_atomic_disk_roundtrip_and_remove(
    setup_coordinator, hass, tmp_path
):
    from homeassistant.util.file import write_utf8_file_atomic

    _, entry, _ = setup_coordinator
    hass.config.config_dir = str(tmp_path)
    with (
        patch(
            "homeassistant.helpers.storage.write_utf8_file_atomic",
            wraps=write_utf8_file_atomic,
        ) as atomic_write,
        patch.object(Store, "_async_load", REAL_STORE_LOAD),
        patch.object(Store, "_async_write_data", REAL_STORE_WRITE),
        patch.object(Store, "async_remove", REAL_STORE_REMOVE),
    ):
        store = store_for(hass, entry)
        await store.async_save(snapshot())
        path = tmp_path / ".storage" / f"{DOMAIN}.{entry.entry_id}.snapshot"
        stat = await hass.async_add_executor_job(path.stat)
        atomic_write.assert_called_once()
        assert stat.st_mode & 0o777 == 0o600
        restored, _ = await store_for(hass, entry).async_load()
        assert restored.loans[0].title == "Synthetic book"
        await store.async_remove()
        assert not await hass.async_add_executor_job(path.exists)


@pytest.mark.parametrize("delete_fails", [False, True])
async def test_swallowed_marker_write_falls_back_to_delete_and_process_block(
    setup_coordinator, hass, delete_fails
):
    coordinator, entry, client = setup_coordinator
    await coordinator.async_config_entry_first_refresh()
    client.async_get_loans.side_effect = SolusSecurityError()
    original_remove = Store.async_remove
    deletion_attempts = []

    async def delete(store):
        deletion_attempts.append(True)
        if delete_fails:
            raise OSError
        await original_remove(store)

    # A no-op save mirrors Store swallowing a failed disk write.
    with (
        patch.object(Store, "async_save", new=AsyncMock()),
        patch.object(Store, "async_remove", new=delete),
    ):
        await coordinator.async_refresh()
        assert deletion_attempts == [True]
        reloaded = AxiellCoordinator(hass, entry, client)
        assert await reloaded.async_restore_snapshot() is delete_fails
        assert not reloaded.snapshot_available
        client.async_get_loans.side_effect = SolusConnectionError()
        await reloaded.async_refresh()
        assert not reloaded.snapshot_available
        await reloaded.async_shutdown()
    await coordinator.async_shutdown()


@pytest.mark.parametrize("security_failure", [False, True])
async def test_cancelled_refresh_keeps_save_owned_until_remove(
    setup_coordinator, hass, security_failure
):
    coordinator, entry, client = setup_coordinator
    if security_failure:
        await coordinator.async_config_entry_first_refresh()
        client.async_get_loans.side_effect = SolusSecurityError()
    started, release = asyncio.Event(), asyncio.Event()
    original_save = Store.async_save

    async def blocked_save(store, payload):
        started.set()
        await release.wait()
        await original_save(store, payload)

    with patch.object(Store, "async_save", blocked_save):
        refresh = asyncio.create_task(coordinator.async_refresh())
        await started.wait()
        refresh.cancel()
        removal = asyncio.create_task(coordinator.async_remove_snapshot())
        await asyncio.sleep(0)
        assert not refresh.done()
        assert not removal.done()
        assert coordinator.closing
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await refresh
        await removal
    assert await store_for(hass, entry).async_load() is None


async def test_loaded_identity_change_removes_cache_before_reload(
    setup_coordinator, hass
):
    from custom_components.axiell_libraries import _async_update_options

    coordinator, entry, _ = setup_coordinator
    entry.runtime_data = coordinator
    await coordinator.async_config_entry_first_refresh()
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "app_id": "NEW-APP"}
    )
    observed = []

    async def reload(_):
        observed.append(await store_for(hass, entry).async_load())

    with patch.object(hass.config_entries, "async_reload", side_effect=reload):
        await _async_update_options(hass, entry)
    assert observed == [None]
    assert coordinator.closing


async def test_removal_of_unloaded_account_cleans_cache_and_cooldown(
    setup_coordinator, hass
):
    from custom_components.axiell_libraries import async_remove_entry

    coordinator, entry, _ = setup_coordinator
    await store_for(hass, entry).async_save(snapshot())
    hass.data.setdefault(f"{DOMAIN}_cooldowns", {})[entry.entry_id] = object()
    await async_remove_entry(hass, entry)
    assert await store_for(hass, entry).async_load() is None
    assert entry.entry_id not in hass.data[f"{DOMAIN}_cooldowns"]
    await coordinator.async_shutdown()


async def test_real_entities_restore_before_provider_then_recover_transient_startup(
    hass, freezer
):
    from datetime import timedelta

    from pytest_homeassistant.common import async_fire_time_changed

    from tests.test_entities import entities, entry

    config = entry(hass)
    await store_for(hass, config).async_save(snapshot())
    started, release = asyncio.Event(), asyncio.Event()
    attempts = 0

    async def read(*_):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            started.set()
            await release.wait()
            raise SolusConnectionError()
        return []

    with (
        patch(
            "custom_components.axiell_libraries.solus.SolusClient.async_login",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.axiell_libraries.solus.SolusClient.async_get_loans",
            side_effect=read,
        ),
    ):
        assert await hass.config_entries.async_setup(config.entry_id)
        await hass.async_block_till_done()
        await started.wait()
        ids = entities(hass, config)
        assert hass.states.get(ids["active_loans"]).state == "1"
        assert hass.states.get(ids["data_freshness"]).state == "stale"
        todo = hass.data["todo"].get_entity(ids["loans"])
        assert todo.todo_items[0].uid == "copy-a"
        release.set()
        await hass.async_block_till_done(wait_background_tasks=True)
        assert hass.states.get(ids["data_freshness"]).state == "stale"
        freezer.tick(timedelta(seconds=80))
        async_fire_time_changed(hass, datetime.now(UTC))
        await hass.async_block_till_done(wait_background_tasks=True)
        assert hass.states.get(ids["active_loans"]).state == "0"
        assert hass.states.get(ids["data_freshness"]).state == "fresh"
        assert await hass.config_entries.async_reload(config.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert hass.states.get(ids["active_loans"]).state == "0"
        assert config.runtime_data.data_freshness == "fresh"


async def test_entry_scoping_prevents_copying_another_accounts_cache(
    setup_coordinator, hass, hass_storage
):
    from tests.test_entities import entry as create_entry

    _, original, _ = setup_coordinator
    await store_for(hass, original).async_save(snapshot())
    other = create_entry(hass, "1")
    original_key = f"{DOMAIN}.{original.entry_id}.snapshot"
    other_key = f"{DOMAIN}.{other.entry_id}.snapshot"
    hass_storage[other_key] = deepcopy(hass_storage[original_key])
    hass_storage[other_key]["key"] = other_key
    assert await store_for(hass, other).async_load() is None
    restored, _ = await store_for(hass, original).async_load()
    assert restored.loans[0].loan_id == "copy-a"


async def test_restore_never_reuses_renewal_consent_and_always_fresh_preflights(
    setup_coordinator, hass
):
    from custom_components.axiell_libraries.renewal import RenewalError
    from tests.test_coordinator import loan

    coordinator, entry, client = setup_coordinator
    client.async_get_loans.return_value = [loan(renewalCost=3.5)]
    client.async_renew_loan = AsyncMock()
    await coordinator.async_config_entry_first_refresh()
    prompt = await coordinator.async_renew_loan("loan-a")
    assert prompt.status == "confirmation_required"
    reloaded = AxiellCoordinator(hass, entry, client)
    assert await reloaded.async_restore_snapshot()
    with pytest.raises(RenewalError) as error:
        await reloaded.async_renew_loan(
            "loan-a", confirm=True, confirmation_id=prompt.confirmation_id
        )
    assert error.value.code == "invalid_confirmation"
    started, release = asyncio.Event(), asyncio.Event()

    async def read(*_):
        started.set()
        await release.wait()
        return []

    client.async_get_loans.side_effect = read
    renewing = asyncio.create_task(reloaded.async_renew_loan("loan-a"))
    await started.wait()
    client.async_renew_loan.assert_not_awaited()
    release.set()
    with pytest.raises(RenewalError) as error:
        await renewing
    assert error.value.code == "loan_not_found"
    client.async_renew_loan.assert_not_awaited()
    restored, _ = await store_for(hass, entry).async_load()
    assert restored.loans == ()
    await coordinator.async_shutdown()
    await reloaded.async_shutdown()


@pytest.mark.parametrize("final_action", ["remove", "withhold"])
async def test_stopping_old_store_wrappers_cannot_resurrect_removed_cache(
    setup_coordinator, hass, tmp_path, final_action
):
    from homeassistant.const import EVENT_HOMEASSISTANT_FINAL_WRITE
    from homeassistant.core import CoreState

    _, entry, _ = setup_coordinator
    hass.config.config_dir = str(tmp_path)
    old_state = hass.state
    with (
        patch.object(Store, "_async_load", REAL_STORE_LOAD),
        patch.object(Store, "_async_write_data", REAL_STORE_WRITE),
        patch.object(Store, "async_remove", REAL_STORE_REMOVE),
    ):
        old_wrapper = store_for(hass, entry)
        await old_wrapper.async_save(snapshot())
        try:
            hass.set_state(CoreState.stopping)
            # A wrapper retained by an unloaded coordinator must not leave a
            # callback that a later wrapper's removal cannot cancel.
            await old_wrapper.async_save(snapshot())
            later_wrapper = store_for(hass, entry)
            if final_action == "withhold":
                await later_wrapper.async_mark_withheld(snapshot(), "security")
            else:
                await later_wrapper.async_save(snapshot())
                await store_for(hass, entry).async_remove()
            hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)
            await hass.async_block_till_done(wait_background_tasks=True)
            path = tmp_path / ".storage" / f"{DOMAIN}.{entry.entry_id}.snapshot"
            assert not await hass.async_add_executor_job(path.exists)
        finally:
            hass.set_state(old_state)
