"""Real HA config flows with only the external client boundary replaced."""

import hashlib
import re
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.axiell_libraries.const import DOMAIN
from custom_components.axiell_libraries.solus import (
    Library,
    SolusAuthError,
    SolusConnectionError,
)

LIBRARY = Library(
    "Test", "Synthetic Library", "TEST-APP", "https://process-test.sol.us"
)
CARD = "TEST-CARD-0000"
PIN = "TEST_PIN_NOT_VALID"
DEVICE = "0123456789abcdef"


def entry_data():
    return {
        "location_id": "Test",
        "library_name": "Synthetic Library",
        "app_id": "TEST-APP",
        "server_url": "https://process-test.sol.us",
        "card": CARD,
        "pin": PIN,
        "device_id": DEVICE,
    }


@pytest.fixture
def api():
    """Replace Solus I/O; real managed sessions and flow lifecycle remain intact."""
    with (
        patch(
            "custom_components.axiell_libraries.solus.async_find_nearby",
            new_callable=AsyncMock,
            return_value=[LIBRARY],
        ) as nearby,
        patch(
            "custom_components.axiell_libraries.solus.async_lookup_location",
            new_callable=AsyncMock,
            return_value=LIBRARY,
        ) as lookup,
        patch(
            "custom_components.axiell_libraries.solus.SolusClient.async_login",
            autospec=True,
            return_value=[{"UserID": CARD}],
        ) as login,
    ):
        yield nearby, lookup, login


async def start(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


async def credentials(hass, result):
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"library": "Test"}
    )


@pytest.mark.asyncio
async def test_two_accounts_have_distinct_entries_and_private_sessions(hass, api):
    sessions = []
    ids = []
    for card in (CARD, "TEST-CARD-0001"):
        result = await credentials(hass, await start(hass))
        assert result["step_id"] == "credentials"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"card": card, "pin": PIN}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert re.fullmatch(r"[0-9a-f]{16}", result["data"]["device_id"])
        assert card not in result["title"]
        assert (
            result["result"].unique_id
            == hashlib.sha256(f"TEST-APP:{card}".encode()).hexdigest()
        )
        ids.append(result["data"]["device_id"])
        sessions.append(api[2].call_args.args[0]._session)
    assert len(hass.config_entries.async_entries(DOMAIN)) == 2
    assert ids[0] != ids[1]
    assert sessions[0] is not sessions[1]
    assert sessions[0].cookie_jar is not sessions[1].cookie_jar
    assert all(session.closed for session in sessions)
    assert all(call.args[0].closed for call in api[0].call_args_list)
    assert sessions[0] is not api[0].call_args_list[0].args[0]


@pytest.mark.asyncio
async def test_duplicate_normalizes_whitespace_and_aborts_before_login(hass, api):
    existing = MockConfigEntry(
        domain=DOMAIN,
        data=entry_data(),
        unique_id=hashlib.sha256(b"TEST-APP:TEST-CARD-0000").hexdigest(),
    )
    existing.add_to_hass(hass)
    result = await credentials(hass, await start(hass))
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"card": " TEST-CARD- 0000\t", "pin": PIN}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    api[2].assert_not_called()


@pytest.mark.asyncio
async def test_retries_reuse_one_generated_device_and_sanitize_errors(
    hass, api, caplog
):
    api[2].side_effect = [SolusAuthError(f"{CARD} {PIN} {DEVICE}"), None]
    with patch("secrets.token_hex", return_value=DEVICE) as token_hex:
        result = await credentials(hass, await start(hass))
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"card": CARD, "pin": PIN}
        )
        assert result["errors"] == {"base": "invalid_auth"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"card": CARD, "pin": "TEST_NEW_PIN"}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["device_id"] == DEVICE
        token_hex.assert_called_once_with(8)
    assert [call.args[0]._device_id for call in api[2].call_args_list] == [
        DEVICE,
        DEVICE,
    ]
    assert all(call.args[0]._session.closed for call in api[2].call_args_list)
    assert all(secret not in caplog.text for secret in (CARD, PIN, DEVICE))


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [SOURCE_REAUTH, SOURCE_RECONFIGURE])
async def test_existing_account_pin_update_preserves_identity(hass, api, source):
    entry = MockConfigEntry(
        domain=DOMAIN, title=LIBRARY.name, data=entry_data(), unique_id="fixed-account"
    )
    entry.add_to_hass(hass)
    with patch("secrets.token_hex") as token_hex:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": source, "entry_id": entry.entry_id},
            data=entry.data if source == SOURCE_REAUTH else None,
        )
        assert result["step_id"] == (
            "reauth_confirm" if source == SOURCE_REAUTH else "reconfigure"
        )
        assert list(result["data_schema"].schema) == ["pin"]
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"pin": "TEST_NEW_PIN"}
        )
        assert result["reason"] == f"{source}_successful"
        token_hex.assert_not_called()
    assert dict(entry.data) == {**entry_data(), "pin": "TEST_NEW_PIN"}
    assert entry.unique_id == "fixed-account"
    client, card, pin = api[2].call_args.args
    assert (client._device_id, card, pin) == (DEVICE, CARD, "TEST_NEW_PIN")
    api[0].assert_not_called()
    api[1].assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("discovery", ["failure", "empty", "no_coordinates", "manual"])
async def test_manual_location_remains_available_when_nearby_is_unusable(
    hass, api, discovery
):
    if discovery == "failure":
        api[0].side_effect = SolusConnectionError("TEST_PROVIDER_FAILURE")
    elif discovery == "empty":
        api[0].return_value = []
    elif discovery == "no_coordinates":
        hass.config.latitude = None
        hass.config.longitude = None
    with patch("secrets.token_hex", return_value=DEVICE) as token_hex:
        result = await start(hass)
        if discovery == "manual":
            selector = next(iter(result["data_schema"].schema.values()))
            assert selector.config["custom_value"] is False
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"library": "__manual__"}
            )
        assert result["step_id"] == "library_manual"
        api[1].side_effect = [SolusConnectionError("TEST_PROVIDER_FAILURE"), LIBRARY]
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"location_id": "Test"}
        )
        assert result["errors"] == {"base": "cannot_connect"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"location_id": "Test"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"card": CARD, "pin": PIN}
        )
        assert result["data"]["device_id"] == DEVICE
        token_hex.assert_called_once_with(8)
    assert all(call.args[0].closed for call in api[1].call_args_list)
    assert api[1].call_args.args[1] == "Test"


@pytest.mark.asyncio
async def test_credential_provider_failure_preserves_candidate_and_ha_connector(
    hass, api
):
    """A provider outage must not allocate another device or close HA's connector."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    shared_session = async_get_clientsession(hass)
    connector = shared_session.connector
    api[2].side_effect = [SolusConnectionError("TEST_PROVIDER_FAILURE"), None]
    with patch("secrets.token_hex", return_value=DEVICE) as token_hex:
        result = await credentials(hass, await start(hass))
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"card": CARD, "pin": PIN}
        )
        assert result["errors"] == {"base": "cannot_connect"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"card": " TEST-CARD-0001 ", "pin": PIN}
        )
        assert result["data"]["card"] == "TEST-CARD-0001"
        assert result["data"]["device_id"] == DEVICE
        token_hex.assert_called_once_with(8)
    assert all(call.args[0]._device_id == DEVICE for call in api[2].call_args_list)
    assert all(call.args[0]._session.closed for call in api[2].call_args_list)
    assert connector is shared_session.connector
    assert not connector.closed
