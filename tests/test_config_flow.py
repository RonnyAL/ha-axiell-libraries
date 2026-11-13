"""Real HA config flows with only the external client boundary replaced."""

import hashlib
import re
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant.common import MockConfigEntry

from custom_components.axiell_libraries.const import DOMAIN
from custom_components.axiell_libraries.solus import (
    Library,
    SolusAuthError,
    SolusConnectionError,
)
from tests.http import AiohttpResponses as aioresponses

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
        # Successful flows schedule entry setup; lifecycle is exercised separately
        # in test_entities.py, while these assertions cover flow validation only.
        patch(
            "custom_components.axiell_libraries.async_setup_entry", return_value=True
        ),
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
@pytest.mark.parametrize("discovery", ["manual", "nearby"])
async def test_observed_locator_reaches_credentials_with_one_device(hass, discovery):
    """Real discovery parsing must allow setup without Name or uppercase Status."""
    row = {
        "Status": "ok",
        "LocationID": "Test",
        "AppID": "TEST-APP",
        "ServerUrl": "https://m.sol.us/",
        "APIUrl": "https://unused.example/",
    }
    with (
        aioresponses() as mock,
        patch("secrets.token_hex", return_value=DEVICE) as token_hex,
        patch(
            "custom_components.axiell_libraries.solus.SolusClient.async_login"
        ) as login,
    ):
        mock.get(
            "https://repo.sol.us/id/TEST-APP/2026.42",
            payload={"Server": "https://process-test.sol.us/"},
        )
        if discovery == "manual":
            hass.config.latitude = hass.config.longitude = None
            lookup = re.compile(
                r"https://locator.sol.us/v4/Locator.asmx/QueryWithID\?rnd=.+"
            )
            mock.post(lookup, payload={"d": {"Status": "failure"}})
            mock.post(lookup, payload={"d": row})
            result = await start(hass)
            assert result["step_id"] == "library_manual"
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"location_id": "Test"}
            )
            assert result["errors"] == {"base": "cannot_connect"}
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"location_id": "Test"}
            )
        else:
            mock.post(
                re.compile(
                    r"https://locator.sol.us/v4/Locator.asmx/FindWithLocation\?rnd=.+"
                ),
                payload={"d": [row]},
            )
            result = await start(hass)
            assert result["step_id"] == "user"
            selector = next(iter(result["data_schema"].schema.values()))
            assert selector.config["options"][0] == {"value": "Test", "label": "Test"}
            result = await credentials(hass, result)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "credentials"
        flow = hass.config_entries.flow._progress[result["flow_id"]]
        assert flow._library == Library(
            "Test", "Test", "TEST-APP", "https://process-test.sol.us"
        )
        assert flow._device_id == DEVICE
        token_hex.assert_called_once_with(8)
        login.assert_not_called()
        assert all("Cat.asmx" not in str(key[1]) for key in mock.requests)


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
                result["flow_id"], {"library": "manual"}
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


@pytest.mark.asyncio
async def test_probe_responses_create_entry_after_retry_with_one_device(hass):
    """The real client accepts absent CheckSession users and persists flow identity."""
    from tests.test_solus import bootstrap, endpoint, fixture

    with (
        aioresponses() as mock,
        patch("secrets.token_hex", return_value=DEVICE) as token_hex,
        patch(
            "custom_components.axiell_libraries.solus.async_find_nearby",
            return_value=[LIBRARY],
        ),
        patch(
            "custom_components.axiell_libraries.async_setup_entry", return_value=True
        ),
    ):
        result = await credentials(hass, await start(hass))
        bootstrap(mock)
        mock.post(endpoint("LoginPreSession"), payload={"d": {"status": "failure"}})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"card": CARD, "pin": PIN}
        )
        assert result["errors"] == {"base": "invalid_auth"}
        bootstrap(mock)
        mock.post(
            endpoint("LoginPreSession"),
            payload=fixture("login_presession_success.json"),
        )
        mock.post(
            endpoint("LoginCheckSession"),
            payload={
                "d": {
                    "status": "SUCCESS",
                    "Detail": None,
                    "Detail2": {
                        "SessionID": "TEST_SESSION",
                        "ServerToUse": LIBRARY.server_url + "/",
                    },
                }
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"card": CARD, "pin": "TEST_CHANGED_PIN"}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["device_id"] == DEVICE
        assert result["data"]["pin"] == "TEST_CHANGED_PIN"
        token_hex.assert_called_once_with(8)
        pre = [
            row
            for key, rows in mock.requests.items()
            if "LoginPreSession" in str(key[1])
            for row in rows
        ]
        assert [row.kwargs["json"]["DeviceID"] for row in pre] == [DEVICE, DEVICE]


@pytest.mark.parametrize("source", [SOURCE_USER, SOURCE_REAUTH, SOURCE_RECONFIGURE])
@pytest.mark.parametrize(
    "stage,kind,reference,error_key",
    [
        ("routing", "http", "routing/http/403", "cannot_connect"),
        ("bootstrap", "http", "bootstrap/http/403", "cannot_connect"),
        ("login_presession", "http", "login_presession/http/403", "invalid_auth"),
        ("login_checksession", "http", "login_checksession/http/403", "invalid_auth"),
        ("routing", "transport", "routing/transport", "cannot_connect"),
        ("bootstrap", "transport", "bootstrap/transport", "cannot_connect"),
        (
            "login_presession",
            "transport",
            "login_presession/transport",
            "cannot_connect",
        ),
        (
            "login_checksession",
            "transport",
            "login_checksession/transport",
            "cannot_connect",
        ),
        ("routing", "schema", "routing/response_schema", "cannot_connect"),
        (
            "login_presession",
            "schema",
            "login_presession/response_schema",
            "cannot_connect",
        ),
        (
            "login_checksession",
            "schema",
            "login_checksession/response_schema",
            "cannot_connect",
        ),
        ("login_presession", "api", "login_presession/api_rejection", "invalid_auth"),
        (
            "login_checksession",
            "api",
            "login_checksession/api_rejection",
            "invalid_auth",
        ),
        (
            "login_presession",
            "unknown_api",
            "login_presession/api_rejection",
            "cannot_connect",
        ),
        (
            "login_presession",
            "token",
            "login_presession/missing_token",
            "cannot_connect",
        ),
        ("routing", "security", "routing/security", "cannot_connect"),
        (
            "login_checksession",
            "security",
            "login_checksession/security",
            "cannot_connect",
        ),
    ],
)
async def test_real_setup_diagnostics_and_retry_preserve_identity(
    hass, source, stage, kind, reference, error_key, caplog
):
    """Wrong failure stage/classification or raw provider text breaks UI reporting."""
    from homeassistant.helpers.aiohttp_client import async_create_clientsession
    from homeassistant.helpers.translation import async_get_translations

    from tests.test_solus import endpoint, fixture, login

    sessions = []

    def managed_session(*args, **kwargs):
        session = async_create_clientsession(*args, **kwargs)
        sessions.append(session)
        return session

    secret = f"{CARD} {PIN} {DEVICE} TEST_TOKEN TEST_COOKIE https://private.example/"
    if kind == "http":
        response = {"status": 403, "body": secret}
    elif kind == "transport":
        response = {"exception": TimeoutError(secret)}
    elif kind == "schema":
        response = {"body": secret}
    elif kind in ("api", "unknown_api"):
        response = {
            "payload": {
                "d": {
                    "status": "failure" if kind == "api" else "error",
                    "statusmessage": secret,
                }
            }
        }
    elif kind == "token":
        response = {
            "payload": {
                "d": {
                    "status": "success",
                    "Detail": [{"UserID": CARD, "AuthToken": ""}],
                }
            }
        }
    elif stage == "routing":
        response = {"payload": {"Server": "https://private.example/"}}
    else:
        response = {
            "payload": {
                "d": {
                    "status": "success",
                    "Detail2": {"ServerToUse": "https://private.example/"},
                }
            }
        }
    with (
        aioresponses() as mock,
        patch(
            "custom_components.axiell_libraries.config_flow.async_create_clientsession",
            side_effect=managed_session,
        ),
        patch("secrets.token_hex", return_value=DEVICE) as token_hex,
        patch(
            "custom_components.axiell_libraries.solus.async_find_nearby",
            return_value=[LIBRARY],
        ),
        patch(
            "custom_components.axiell_libraries.async_setup_entry", return_value=True
        ),
    ):
        if source == SOURCE_USER:
            result = await credentials(hass, await start(hass))
            submission = {"card": CARD, "pin": PIN}
        else:
            entry = MockConfigEntry(
                domain=DOMAIN, data=entry_data(), unique_id="fixed-account"
            )
            entry.add_to_hass(hass)
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": source, "entry_id": entry.entry_id},
                data=entry.data if source == SOURCE_REAUTH else None,
            )
            submission = {"pin": PIN}
        repo = "https://repo.sol.us/id/TEST-APP/2026.42"
        auth = re.compile(r"https://process-test.sol.us/v4/Auth.aspx\?s=.+")
        if stage == "routing":
            mock.get(repo, **response)
        else:
            mock.get(repo, payload={"Server": LIBRARY.server_url})
            if stage == "bootstrap":
                mock.get(auth, **response)
            else:
                mock.get(auth, body="")
                if stage == "login_presession":
                    mock.post(endpoint("LoginPreSession"), **response)
                else:
                    mock.post(
                        endpoint("LoginPreSession"),
                        payload=fixture("login_presession_success.json"),
                    )
                    mock.post(endpoint("LoginCheckSession"), **response)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], submission
        )
        assert result["errors"] == {"base": error_key}
        assert result["description_placeholders"]["reference"] == reference
        assert set(result["description_placeholders"]) <= {"reference", "name"}
        for language in ("en", "nb"):
            translations = await async_get_translations(
                hass, language, "config", {DOMAIN}
            )
            message = translations[
                f"component.{DOMAIN}.config.error.{error_key}"
            ].format(**result["description_placeholders"])
            assert reference in message
            assert all(marker not in message + caplog.text for marker in secret.split())
        assert sessions and all(session.closed for session in sessions)
        login(mock)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], submission
        )
        if source == SOURCE_USER:
            assert result["type"] is FlowResultType.CREATE_ENTRY
            assert result["data"]["device_id"] == DEVICE
            token_hex.assert_called_once_with(8)
        else:
            assert result["reason"] == f"{source}_successful"
            assert entry.data["device_id"] == DEVICE
            token_hex.assert_not_called()
        assert all(session.closed for session in sessions)
        requests = [
            call
            for key, calls in mock.requests.items()
            if "LoginPreSession" in str(key[1])
            for call in calls
        ]
        assert all(call.kwargs["json"]["DeviceID"] == DEVICE for call in requests)


@pytest.mark.parametrize("operation", ["discovery", "manual_lookup"])
async def test_locator_diagnostics_are_not_credential_errors(hass, operation, caplog):
    """Anonymous locator rejection must retain a safe location-stage reference."""
    from tests.test_solus import locator_endpoint

    with aioresponses() as mock:
        if operation == "manual_lookup":
            hass.config.latitude = hass.config.longitude = None
            result = await start(hass)
        method = "FindWithLocation" if operation == "discovery" else "QueryWithID"
        mock.post(
            locator_endpoint(method),
            payload={"d": {"Status": "failure", "statusmessage": PIN}},
        )
        if operation == "discovery":
            result = await start(hass)
        else:
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"location_id": "Test"}
            )
        assert result["step_id"] == "library_manual"
        assert result["errors"] == {"base": "cannot_connect"}
        assert result["description_placeholders"] == {
            "reference": f"{operation}/api_rejection"
        }
        assert PIN not in caplog.text


async def test_programming_errors_are_not_provider_diagnostics(hass, api):
    """An unexpected implementation failure must not be mislabeled as Solus."""
    result = await credentials(hass, await start(hass))
    flow = hass.config_entries.flow._progress[result["flow_id"]]
    api[2].side_effect = RuntimeError("synthetic programming failure")
    with pytest.raises(RuntimeError, match="synthetic programming failure"):
        await flow._validate(entry_data())
    assert api[2].call_args.args[0]._session.closed
