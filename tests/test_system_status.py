"""Synthetic APK status values at the real HTTP and coordinator boundaries."""

import json
from unittest.mock import Mock, patch

import aiohttp
import pytest

from custom_components.axiell_libraries.coordinator import AxiellCoordinator
from custom_components.axiell_libraries.solus import (
    SolusProtocolError,
    SolusSecurityError,
    SolusSessionExpired,
)
from tests.http import AiohttpResponses as aioresponses
from tests.test_coordinator import setup_coordinator as setup_coordinator
from tests.test_recovery import advance
from tests.test_solus import CARD, PIN, TOKEN, bootstrap, client, endpoint, login
from tests.test_solus_recovery import operation

STATUSES = [
    ("sessionexpired", SolusSessionExpired, "session_expired"),
    ("LOGINEXPIRED", SolusSessionExpired, "login_expired"),
    ("VALIDATIONREQUIRED", SolusSecurityError, "validation_required"),
]


def payload(status, serialized=False):
    section = {"status": status, "statusmessage": TOKEN, "Detail": PIN}
    return {"d": json.dumps(section) if serialized else section}


@pytest.mark.parametrize(
    "method,stage",
    [("LoansGet", "loans"), ("RecordGet", "catalogue"), ("LoanRenew", "renewal")],
)
@pytest.mark.parametrize("status,error_type,reason", STATUSES)
@pytest.mark.parametrize("serialized", [False, True, "outer"])
async def test_system_status_classified_before_decoder(
    method, stage, status, error_type, reason, serialized, caplog
):
    with aioresponses() as http:
        login(http)
        http.post(
            endpoint(method),
            payload=json.dumps(payload(status))
            if serialized == "outer"
            else payload(status, serialized),
        )
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(error_type) as caught:
                await operation(api, method)
            assert caught.value.reference() == f"{stage}/{reason}"
            assert (
                not caught.value.retryable
                if error_type is SolusSecurityError
                else caught.value.retryable
            )
            if error_type is SolusSessionExpired:
                assert not api._authenticated
                assert api._token == ""
                with pytest.raises(SolusSessionExpired):
                    await api.async_get_loans(CARD)
        assert sum(len(calls) for calls in http.requests.values()) == 5
        assert all(
            "x-token" not in call.kwargs.get("headers", {})
            for calls in http.requests.values()
            for call in calls
        )
        assert TOKEN not in str(caught.value) + caplog.text
        assert PIN not in str(caught.value) + caplog.text


@pytest.mark.parametrize("method", ["LoansGet", "RecordGet", "LoanRenew"])
@pytest.mark.parametrize(
    "status", ["SESSIONEXPIRED", "loginexpired", "validationrequired", "TEST_UNKNOWN"]
)
async def test_unknown_and_wrong_case_status_keeps_existing_fallback(method, status):
    with aioresponses() as http:
        login(http)
        http.post(endpoint(method), payload={"d": {"status": status}})
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(SolusProtocolError):
                await operation(api, method)
            assert api._authenticated


@pytest.mark.parametrize("method", ["LoginPreSession", "LoginCheckSession"])
@pytest.mark.parametrize("status,error_type,reason", STATUSES)
async def test_login_system_status_has_safe_flow_error_and_preserves_expiry(
    method, status, error_type, reason
):
    from custom_components.axiell_libraries.config_flow import AxiellLibrariesConfigFlow

    with aioresponses() as http:
        bootstrap(http)
        if method == "LoginCheckSession":
            from tests.test_solus import fixture

            http.post(
                endpoint("LoginPreSession"),
                payload=fixture("login_presession_success.json"),
            )
        http.post(endpoint(method), payload=payload(status))
        async with aiohttp.ClientSession() as session:
            api = client(session)
            awaitable = api.async_login(CARD, PIN)
            with pytest.raises(error_type):
                await awaitable
            if error_type is SolusSessionExpired:
                with pytest.raises(SolusSessionExpired):
                    await api.async_get_loans(CARD)
    flow = AxiellLibrariesConfigFlow()
    with (
        patch.object(flow, "_session"),
        patch(
            "custom_components.axiell_libraries.solus.SolusClient.async_login",
            side_effect=error_type("Static", reason=reason),
        ),
    ):
        assert (
            await flow._validate(
                {
                    "app_id": "TEST-APP",
                    "server_url": "https://process-test.sol.us",
                    "device_id": "0123456789abcdef",
                    "card": CARD,
                    "pin": PIN,
                }
            )
            == "cannot_connect"
        )


@pytest.mark.parametrize("status,error_type,reason", STATUSES)
@pytest.mark.parametrize("repeated", [False, True])
async def test_real_client_coordinator_system_status_is_bounded(
    setup_coordinator, hass, freezer, status, error_type, reason, repeated
):
    _, entry, _ = setup_coordinator
    with aioresponses() as http:
        login(http)
        http.post(
            endpoint("LoansGet"), payload={"d": {"status": "success", "Detail": []}}
        )
        async with aiohttp.ClientSession() as session:
            api = client(session)
            coordinator = AxiellCoordinator(hass, entry, api)
            await coordinator.async_config_entry_first_refresh()
            unsubscribe = coordinator.async_add_listener(Mock())
            try:
                http.post(endpoint("LoansGet"), payload=payload(status))
                if error_type is SolusSessionExpired:
                    login(http)
                    http.post(
                        endpoint("LoansGet"),
                        payload=payload(status)
                        if repeated
                        else {"d": {"status": "success", "Detail": []}},
                    )
                with patch.object(entry, "async_start_reauth_if_available") as reauth:
                    await coordinator.async_refresh()
                    assert not reauth.called
                assert coordinator.last_update_success == (
                    error_type is SolusSessionExpired and not repeated
                )
                if error_type is SolusSecurityError:
                    before = sum(len(calls) for calls in http.requests.values())
                    await advance(hass, freezer, 600)
                    assert sum(len(calls) for calls in http.requests.values()) == before
            finally:
                unsubscribe()


@pytest.mark.parametrize("status,error_type,reason", STATUSES)
async def test_real_client_renewal_system_status_never_prompts_or_replays(
    setup_coordinator, hass, status, error_type, reason
):
    from custom_components.axiell_libraries.renewal import RenewalError
    from tests.test_coordinator import loan

    with aioresponses() as http:
        login(http)
        http.post(
            endpoint("LoansGet"),
            payload={"d": {"status": "success", "Detail": [loan()]}},
            repeat=True,
        )
        http.post(
            endpoint("RecordGet"),
            payload={"d": {"status": "success", "Detail": {"Author": "Synthetic"}}},
            repeat=True,
        )
        http.post(endpoint("LoanRenew"), payload=payload(status))
        _, entry, _ = setup_coordinator
        async with aiohttp.ClientSession() as session:
            coordinator = AxiellCoordinator(hass, entry, client(session))
            await coordinator.async_config_entry_first_refresh()
            if error_type is SolusSessionExpired:
                login(http)
            with pytest.raises(RenewalError) as caught:
                await coordinator.async_renew_loan("loan-a")
            assert caught.value.code == "outcome_unknown"
            assert not coordinator._renewal._pending
        writes = [
            call
            for key, calls in http.requests.items()
            if "LoanRenew" in str(key)
            for call in calls
        ]
        assert len(writes) == 1


async def test_real_client_validation_in_optional_enrichment_is_not_swallowed(
    setup_coordinator, hass
):
    from homeassistant.exceptions import ConfigEntryNotReady

    from tests.test_coordinator import loan

    _, entry, _ = setup_coordinator
    with aioresponses() as http:
        login(http)
        http.post(
            endpoint("LoansGet"),
            payload={"d": {"status": "success", "Detail": [loan()]}},
        )
        http.post(endpoint("RecordGet"), payload=payload("VALIDATIONREQUIRED"))
        async with aiohttp.ClientSession() as session:
            coordinator = AxiellCoordinator(hass, entry, client(session))
            with pytest.raises(
                ConfigEntryNotReady, match="catalogue/validation_required"
            ):
                await coordinator.async_config_entry_first_refresh()
            assert not coordinator.last_update_success


@pytest.mark.parametrize(
    "status", ["TEST_UNKNOWN", "validationrequired", "SESSIONEXPIRED", "loginexpired"]
)
async def test_unknown_renewal_confirmation_retains_explicit_consent(status):
    with aioresponses() as http:
        login(http)
        http.post(
            endpoint("LoanRenew"),
            payload={
                "d": {"status": status, "statusmessage": "Accept synthetic condition?"}
            },
        )
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            reply = await operation(api, "LoanRenew")
            assert reply.outcome == "confirmation_required"
            assert reply.acknowledgement_code == status
