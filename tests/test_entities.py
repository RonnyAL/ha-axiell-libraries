"""Offline HA entity, service and per-account lifecycle contracts."""

from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.axiell_libraries.const import DOMAIN
from custom_components.axiell_libraries.solus import (
    SolusAuthError,
    SolusConnectionError,
)

DEVICE = "0123456789abcdef"
CARD = "TEST-CARD-0000"
PIN = "TEST_PIN_NOT_VALID"


def rows():
    """Distinct copies and dates, including a provider-overdue unknown date."""
    return [
        {
            "loanID": "loan-a",
            "recordID": "record-a",
            "Source": "ILS",
            "title": "Same title",
            "dueObject": "/Date(1795046400000)/",
            "Overdue": False,
        },
        {
            "loanID": "loan-b",
            "recordID": "record-b",
            "Source": "ILS",
            "title": "Same title",
            "dueObject": "/Date(1795651200000)/",
            "Overdue": False,
        },
        {
            "loanID": "loan-c",
            "recordID": "",
            "Source": "ILS",
            "title": "Unknown date",
            "dueObject": "invalid",
            "Overdue": True,
        },
    ]


def entry(hass, suffix="0"):
    config = MockConfigEntry(
        domain=DOMAIN,
        title="Synthetic Library",
        unique_id=f"account-{suffix}",
        data={
            "location_id": "Test",
            "library_name": "Synthetic Library",
            "app_id": "TEST-APP",
            "server_url": "https://process-test.sol.us",
            "card": CARD if suffix == "0" else "TEST-CARD-0001",
            "pin": PIN,
            "device_id": DEVICE if suffix == "0" else "fedcba9876543210",
        },
    )
    config.add_to_hass(hass)
    return config


@pytest.fixture
def api():
    """Replace only upstream I/O, retaining HA sessions and the real coordinator."""
    state = SimpleNamespace(
        clients=[], logins=[], rows=rows(), login_error=None, loans_error=None
    )

    async def login(client, card, pin):
        state.clients.append(client)
        state.logins.append((client._device_id, card, pin))
        if state.login_error:
            raise state.login_error("SYNTHETIC_PRIVATE_DETAIL")
        return []

    async def loans(client, card):
        if state.loans_error:
            raise state.loans_error("SYNTHETIC_PRIVATE_DETAIL")
        return deepcopy(state.rows)

    async def record(client, record_id, source):
        return {
            "RecordID": record_id,
            "Author": "Sample Author",
            "ISBN": "9780000000002",
            "Description": "A synthetic catalogue description.",
            "Format": "Bok",
            "ImageUrl": "https://images.example.org/cover.jpg",
            "MainMetadata": [
                {"Key": "Utgiver", "Value": "Sample Press"},
                {"Key": "Utgitt", "Value": "2026"},
                {"Key": "Card", "Value": "SYNTHETIC_PRIVATE_DETAIL"},
            ],
        }

    with (
        patch(
            "custom_components.axiell_libraries.solus.SolusClient.async_login", login
        ),
        patch(
            "custom_components.axiell_libraries.solus.SolusClient.async_get_loans",
            loans,
        ),
        patch(
            "custom_components.axiell_libraries.solus.SolusClient.async_get_record",
            record,
        ),
    ):
        yield state


def entities(hass, config):
    return {
        item.unique_id.removeprefix(f"{config.entry_id}_"): item.entity_id
        for item in er.async_entries_for_config_entry(
            er.async_get(hass), config.entry_id
        )
    }


async def setup(hass, config):
    assert await hass.config_entries.async_setup(config.entry_id)
    await hass.async_block_till_done()
    assert config.state is ConfigEntryState.LOADED
    return entities(hass, config)


async def get_items(hass, entity_id):
    response = await hass.services.async_call(
        "todo",
        "get_items",
        {"entity_id": entity_id},
        blocking=True,
        return_response=True,
    )
    return response[entity_id]["items"]


async def test_native_entities_have_independent_dates_safe_metadata_and_device(
    hass, api
):
    config = entry(hass)
    ids = await setup(hass, config)
    assert set(ids) == {"active_loans", "next_due_date", "overdue_loans", "loans"}
    assert hass.states.get(ids["active_loans"]).state == "3"
    assert hass.states.get(ids["overdue_loans"]).state == "1"
    due = hass.states.get(ids["next_due_date"])
    assert due.state == "2026-11-19"
    assert due.attributes["device_class"] == "date"
    sensor = hass.data["sensor"].get_entity(ids["next_due_date"])
    assert sensor.native_value == date(2026, 11, 19)
    assert type(sensor.native_value) is date
    items = await get_items(hass, ids["loans"])
    assert [item["uid"] for item in items] == ["loan-a", "loan-b", "loan-c"]
    assert [item.get("due") for item in items] == ["2026-11-19", "2026-11-26", None]
    todo = hass.data["todo"].get_entity(ids["loans"])
    assert [item.due for item in todo.todo_items] == [
        date(2026, 11, 19),
        date(2026, 11, 26),
        None,
    ]
    assert [item["summary"] for item in items[:2]] == ["Same title", "Same title"]
    assert all(item["status"] == "needs_action" for item in items)
    for expected in (
        "Sample Author",
        "9780000000002",
        "Bok",
        "Utgiver",
        "Sample Press",
        "Utgitt",
        "2026",
        "https://images.example.org/cover.jpg",
    ):
        assert expected in items[0]["description"]
    exposed = str(items) + str(
        [hass.states.get(entity_id).attributes for entity_id in ids.values()]
    )
    assert all(
        secret not in exposed
        for secret in (CARD, PIN, DEVICE, "SYNTHETIC_PRIVATE_DETAIL")
    )
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), config.entry_id)
    assert len(devices) == 1
    assert all(
        er.async_get(hass).async_get(entity_id).device_id == devices[0].id
        for entity_id in ids.values()
    )
    assert api.logins == [(DEVICE, CARD, PIN)]


@pytest.mark.parametrize(
    "service,data",
    [
        ("add_item", {"item": "New loan"}),
        ("update_item", {"item": "loan-a", "status": "completed"}),
        ("remove_item", {"item": "loan-a"}),
    ],
)
async def test_todo_services_cannot_mutate_library(hass, api, service, data):
    config = entry(hass)
    ids = await setup(hass, config)
    assert hass.states.get(ids["loans"]).attributes["supported_features"] == 0
    before = await get_items(hass, ids["loans"])
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "todo", service, {"entity_id": ids["loans"], **data}, blocking=True
        )
    assert await get_items(hass, ids["loans"]) == before


async def test_two_entries_reload_and_unload_keep_identity_and_sessions_isolated(
    hass, api
):
    shared = async_get_clientsession(hass)
    first = entry(hass)
    ids_first = await setup(hass, first)
    second = entry(hass, "1")
    with patch("secrets.token_hex", side_effect=AssertionError("DeviceID regenerated")):
        ids_second = await setup(hass, second)
        initial_clients = api.clients[:]
        assert initial_clients[0]._session is not initial_clients[1]._session
        assert (
            initial_clients[0]._session.cookie_jar
            is not initial_clients[1]._session.cookie_jar
        )
        assert set(ids_first.values()).isdisjoint(ids_second.values())
        assert await hass.config_entries.async_reload(first.entry_id)
        await hass.async_block_till_done()
        assert entities(hass, first) == ids_first
        assert api.clients[-1]._device_id == DEVICE
        assert initial_clients[0]._session.closed
        assert not initial_clients[1]._session.closed
        assert not shared.connector.closed
        assert await hass.config_entries.async_unload(first.entry_id)
        assert api.clients[-1]._session.closed
        assert hass.data["sensor"].get_entity(ids_first["active_loans"]) is None
        assert hass.data["todo"].get_entity(ids_first["loans"]) is None
        assert hass.states.get(ids_second["active_loans"]).state == "3"
        assert not initial_clients[1]._session.closed
        assert await hass.config_entries.async_unload(second.entry_id)
        assert initial_clients[1]._session.closed
        assert not shared.connector.closed
    assert first.data["device_id"] == DEVICE


async def test_reauth_reload_preserves_device_and_entities(hass, api):
    config = entry(hass)
    ids = await setup(hass, config)
    original = api.clients[0]
    with patch("secrets.token_hex", side_effect=AssertionError("DeviceID regenerated")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_REAUTH, "entry_id": config.entry_id},
            data=config.data,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"pin": "TEST_NEW_PIN"}
        )
        assert result["reason"] == "reauth_successful"
        await hass.async_block_till_done()
    assert config.data["device_id"] == DEVICE
    assert config.data["pin"] == "TEST_NEW_PIN"
    assert original._session.closed
    assert api.logins[-1] == (DEVICE, CARD, "TEST_NEW_PIN")
    assert entities(hass, config) == ids
    assert hass.states.get(ids["active_loans"]).state == "3"


@pytest.mark.parametrize(
    "error,state",
    [
        (SolusAuthError, ConfigEntryState.SETUP_ERROR),
        (SolusConnectionError, ConfigEntryState.SETUP_RETRY),
    ],
)
@pytest.mark.parametrize("stage", ["login", "loans"])
async def test_setup_failure_detaches_account_session_without_closing_shared_connector(
    hass, api, error, state, stage, caplog
):
    shared = async_get_clientsession(hass)
    config = entry(hass)
    setattr(api, f"{stage}_error", error)
    assert not await hass.config_entries.async_setup(config.entry_id)
    await hass.async_block_till_done()
    assert config.state is state
    assert api.clients[0]._session.closed
    assert not shared.connector.closed
    assert not entities(hass, config)
    assert "SYNTHETIC_PRIVATE_DETAIL" not in caplog.text


async def test_refresh_failure_is_unavailable_then_real_empty_list_is_zero(hass, api):
    config = entry(hass)
    ids = await setup(hass, config)
    api.loans_error = SolusConnectionError
    await config.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert all(
        hass.states.get(entity_id).state == "unavailable" for entity_id in ids.values()
    )
    api.loans_error = None
    api.rows = []
    await config.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ids["active_loans"]).state == "0"
    assert hass.states.get(ids["overdue_loans"]).state == "0"
    assert hass.states.get(ids["next_due_date"]).state == "unknown"
    assert await get_items(hass, ids["loans"]) == []


async def test_all_unknown_dates_keep_loans_without_fabricating_metadata(hass, api):
    api.rows = [rows()[2]]
    config = entry(hass)
    ids = await setup(hass, config)
    assert hass.states.get(ids["active_loans"]).state == "1"
    assert hass.states.get(ids["overdue_loans"]).state == "1"
    assert hass.states.get(ids["next_due_date"]).state == "unknown"
    items = await get_items(hass, ids["loans"])
    assert items == [
        {"summary": "Unknown date", "uid": "loan-c", "status": "needs_action"}
    ]
