"""Offline request-boundary tests; all identity values are synthetic markers."""

import base64
import json
import re
from pathlib import Path

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.axiell_libraries.models import Loan
from custom_components.axiell_libraries.solus import (
    SolusAuthError,
    SolusClient,
    SolusConnectionError,
    SolusProtocolError,
    SolusSecurityError,
    async_find_nearby,
    async_lookup_location,
)

APP = "TEST-APP"
SERVER = "https://process-test.sol.us"
CARD = "TEST-CARD-0000"
PIN = "TEST_PIN_NOT_VALID"
DEVICE = "0123456789abcdef"
TOKEN = "TEST_TOKEN_NOT_VALID"
ROOT = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((ROOT / name).read_text())


def endpoint(method):
    return re.compile(rf"{SERVER}/v4/Cat.asmx/{method}\?rnd=[^&]+$")


def bootstrap(mock):
    mock.get("https://repo.sol.us/id/TEST-APP/2026.42", payload={"Server": SERVER})
    mock.get(re.compile(rf"{SERVER}/v4/Auth.aspx\?s=.+"), body="")


def login(mock, *, detail2=None):
    bootstrap(mock)
    mock.post(
        endpoint("LoginPreSession"), payload=fixture("login_presession_success.json")
    )
    mock.post(
        endpoint("LoginCheckSession"),
        payload={
            "d": {
                "status": "success",
                "Detail": [{"UserID": CARD, "AuthToken": "TEST_NEW_TOKEN"}],
                "Detail2": detail2
                or {"SessionID": "TEST_SESSION", "ServerToUse": SERVER},
            }
        },
    )


def client(session):
    return SolusClient(session, APP, SERVER, DEVICE, "nb-NO")


@pytest.mark.asyncio
async def test_lookup_resolves_repo_processing_server():
    """Sending credentials to locator APIUrl instead of repo Server breaks routing."""
    with aioresponses() as mock:
        mock.post(
            re.compile(r"https://locator.sol.us/v4/Locator.asmx/QueryWithID\?rnd=.+"),
            payload={
                "d": {
                    "Status": "OK",
                    "LocationID": "Test",
                    "Name": "Test Library",
                    "AppID": APP,
                    "ServerUrl": "https://m.sol.us/",
                    "APIUrl": "https://untrusted.example/",
                }
            },
        )
        mock.get("https://repo.sol.us/id/TEST-APP/2026.42", payload={"Server": SERVER})
        async with aiohttp.ClientSession() as session:
            library = await async_lookup_location(session, "Test")
        assert (
            library.location_id,
            library.name,
            library.app_id,
            library.server_url,
        ) == ("Test", "Test Library", APP, SERVER)
        request = next(iter(mock.requests.values()))[0]
        assert request.kwargs["json"] == {
            "LocationID": "Test",
            "GlobalAppID": "5C72D777-E044-4B76-97A8-F240FA42E9BD",
        }


@pytest.mark.asyncio
async def test_nearby_returns_typed_libraries_and_sends_coordinates():
    with aioresponses() as mock:
        mock.post(
            re.compile(
                r"https://locator.sol.us/v4/Locator.asmx/FindWithLocation\?rnd=.+"
            ),
            payload={
                "d": {
                    "Status": "OK",
                    "Detail": [
                        {
                            "LocationID": "Test",
                            "Name": "Test Library",
                            "AppID": APP,
                            "ServerUrl": SERVER,
                        }
                    ],
                }
            },
        )
        mock.get("https://repo.sol.us/id/TEST-APP/2026.42", payload={"Server": SERVER})
        async with aiohttp.ClientSession() as session:
            result = await async_find_nearby(session, 69.0, 19.0)
        assert [library.location_id for library in result] == ["Test"]
        request = next(iter(mock.requests.values()))[0]
        assert request.kwargs["json"]["LocationLat"] == 69.0
        assert request.kwargs["json"]["LocationLng"] == 19.0


@pytest.mark.asyncio
async def test_login_bootstrap_and_exact_browser_and_client_envelopes():
    with aioresponses() as mock:
        login(mock)
        async with aiohttp.ClientSession() as session:
            api = client(session)
            result = await api.async_login(CARD, PIN)
            mock.post(endpoint("LoansGet"), payload=fixture("loans_get.json"))
            loans = await api.async_get_loans(CARD)
        assert result[0]["UserID"] == CARD
        assert len(loans) == 2
        calls = [(str(key[1]), value[0].kwargs) for key, value in mock.requests.items()]
        auth = next((url, kw) for url, kw in calls if "Auth.aspx" in url)
        from urllib.parse import parse_qs, urlsplit

        metadata = json.loads(
            base64.b64decode(parse_qs(urlsplit(auth[0]).query)["s"][0])
        )
        assert metadata["DeviceID"] == DEVICE
        assert metadata["AppVersion"] == "2026.42"
        assert metadata["AppBuild"] == "2026420500"
        assert metadata["PackageName"] == "solus.AllAxiell"
        assert set(metadata) == {
            "AppID",
            "TemplateID",
            "DeviceID",
            "AppVersion",
            "PackageName",
            "PlatType",
            "PlatVer",
            "PlatModel",
            "DName",
            "Locale",
            "font",
            "AppBuild",
            "ServerRoot",
        }
        pre = next(kw for url, kw in calls if "LoginPreSession" in url)
        assert pre["json"] == {
            "AppID": APP,
            "TemplateID": APP,
            "DeviceID": DEVICE,
            "Locale": "nb-NO",
            "UserID": CARD,
            "Request": {
                "UserID": CARD,
                "Password": PIN,
                "StoreCredentials": False,
                "Name": "",
            },
        }
        assert pre["headers"]["Origin"] == SERVER
        assert pre["headers"]["X-Requested-With"] == "XMLHttpRequest"
        check = next(kw for url, kw in calls if "LoginCheckSession" in url)
        assert check["headers"]["x-session"] == TOKEN
        assert check["json"]["Request"]["AuthToken"] == TOKEN
        assert check["json"]["SessionID"] == ""
        loan_call = next(kw for url, kw in calls if "LoansGet" in url)
        assert loan_call["headers"]["x-session"] == "TEST_NEW_TOKEN"
        assert loan_call["headers"]["x-devicesession"] == "TEST_SESSION"
        assert loan_call["json"]["Request"] == {"UserID": CARD}
        assert all(kw["allow_redirects"] is False for _, kw in calls)
        assert all(0 < kw["timeout"].total <= 30 for _, kw in calls)
        assert not any(url.split("?")[0].endswith("/Login") for url, _ in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("detail", [[], None, {}, "not-json", [None]])
async def test_malformed_loans_are_not_empty_accounts(detail):
    with aioresponses() as mock:
        login(mock)
        mock.post(
            endpoint("LoansGet"), payload={"d": {"status": "success", "Detail": detail}}
        )
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            if detail == []:
                assert await api.async_get_loans(CARD) == []
            else:
                with pytest.raises(SolusProtocolError):
                    await api.async_get_loans(CARD)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["loanID", "title"])
@pytest.mark.parametrize("value", [None, "", " \t\n", 123, False, {}, []])
async def test_invalid_required_loan_fields_are_protocol_failure(field, value, caplog):
    row = {"loanID": "loan-a", "title": "Example book", field: value}
    row["description"] = f"{CARD} {PIN} {TOKEN} {DEVICE}"
    with aioresponses() as mock:
        login(mock)
        mock.post(
            endpoint("LoansGet"),
            payload={"d": {"status": "success", "Detail": [row]}},
        )
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(SolusProtocolError) as caught:
                await api.async_get_loans(CARD)
    assert all(
        secret not in str(caught.value) + caplog.text
        for secret in (CARD, PIN, TOKEN, DEVICE)
    )
    assert caught.value.__suppress_context__


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["loanID", "title"])
async def test_missing_required_loan_fields_are_protocol_failure(field):
    row = {"loanID": "loan-a", "title": "Example book"}
    del row[field]
    with aioresponses() as mock:
        login(mock)
        mock.post(
            endpoint("LoansGet"),
            payload={"d": {"status": "success", "Detail": [row]}},
        )
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(SolusProtocolError):
                await api.async_get_loans(CARD)


@pytest.mark.asyncio
@pytest.mark.parametrize("second_id", ["loan-a", " \tloan-a\n"])
async def test_duplicate_normalized_loan_ids_are_protocol_failure(second_id):
    rows = [
        {"loanID": "loan-a", "title": "Example book A"},
        {"loanID": second_id, "title": "Example book B"},
    ]
    with aioresponses() as mock:
        login(mock)
        mock.post(
            endpoint("LoansGet"),
            payload={"d": {"status": "success", "Detail": rows}},
        )
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(SolusProtocolError):
                await api.async_get_loans(CARD)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "optional",
    [{}, {"dueObject": None}, {"dueObject": {}, "recordID": [], "Source": 123}],
)
async def test_valid_loan_identity_allows_unknown_date_and_optional_metadata(optional):
    rows = [
        {"loanID": " \tloan-a\n", "title": " Example book ", **optional},
        {"loanID": "loan-b", "title": "Example book", "dueObject": "invalid"},
    ]
    with aioresponses() as mock:
        login(mock)
        mock.post(
            endpoint("LoansGet"),
            payload={"d": {"status": "success", "Detail": rows}},
        )
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            loans = [Loan.from_api(row) for row in await api.async_get_loans(CARD)]
    assert [item.loan_id for item in loans] == ["loan-a", "loan-b"]
    assert [item.title for item in loans] == ["Example book", "Example book"]
    assert all(item.due_date is None for item in loans)


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["object", "string", "list"])
async def test_record_detail_variants(shape):
    record = fixture("record_get.json")["d"]["Detail"]
    detail = {"object": record, "string": json.dumps(record), "list": [record]}[shape]
    with aioresponses() as mock:
        login(mock)
        mock.post(
            endpoint("RecordGet"),
            payload={"d": {"status": "success", "Detail": detail}},
        )
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            result = await api.async_get_record("TEST_RECORD", "ILS")
        assert result["Author"] == "Sample, Alex"
        request = next(
            value[0].kwargs
            for key, value in mock.requests.items()
            if "RecordGet" in str(key[1])
        )
        assert request["json"]["Request"] == {
            "RecordID": "TEST_RECORD",
            "Source": "ILS",
            "SearchLimit": "",
        }


@pytest.mark.asyncio
async def test_invalid_auth_has_no_retry_or_sensitive_exception_context(caplog):
    with aioresponses() as mock:
        bootstrap(mock)
        mock.post(
            endpoint("LoginPreSession"),
            payload={"d": {"status": "failure", "statusmessage": PIN}},
        )
        async with aiohttp.ClientSession() as session:
            with pytest.raises(SolusAuthError) as caught:
                await client(session).async_login(CARD, PIN)
        assert len(mock.requests) == 3
        assert all(
            secret not in str(caught.value) + caplog.text
            for secret in (CARD, PIN, TOKEN, DEVICE)
        )
        assert caught.value.__suppress_context__


@pytest.mark.asyncio
async def test_timeout_sanitizes_exception_and_is_bounded():
    with aioresponses() as mock:
        mock.get("https://repo.sol.us/id/TEST-APP/2026.42", exception=TimeoutError(PIN))
        async with aiohttp.ClientSession() as session:
            with pytest.raises(SolusConnectionError) as caught:
                await client(session).async_login(CARD, PIN)
        assert PIN not in str(caught.value)
        assert caught.value.__suppress_context__
        assert len(mock.requests) == 1


@pytest.mark.asyncio
async def test_expired_http_session_does_not_retry_login():
    with aioresponses() as mock:
        login(mock)
        mock.post(endpoint("LoansGet"), status=401, body=TOKEN)
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(SolusAuthError):
                await api.async_get_loans(CARD)
        assert len(mock.requests) == 5


@pytest.mark.asyncio
async def test_partial_catalogue_failure_keeps_loan_access():
    with aioresponses() as mock:
        login(mock)
        mock.post(endpoint("RecordGet"), status=503, body=TOKEN)
        mock.post(endpoint("LoansGet"), payload=fixture("loans_get.json"))
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(SolusConnectionError):
                await api.async_get_record("TEST_RECORD", "ILS")
            assert len(await api.async_get_loans(CARD)) == 2


@pytest.mark.parametrize(
    "url",
    [
        "http://process-test.sol.us",
        "https://process-test.sol.us.evil.example",
        "https://user:pass@process-test.sol.us",
        "https://process-test.sol.us:444",
        "https://process-test.sol.us?x=1",
        "https://process-test.sol.us/#x",
        "https://process-test.sol.us/other",
        "https://process-test.sol.us\\@evil.example",
    ],
)
def test_untrusted_initial_destination_rejected(url):
    with pytest.raises(SolusSecurityError):
        SolusClient(None, APP, url, DEVICE, "nb-NO")


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["repo", "http", "session"])
async def test_untrusted_routing_never_receives_credentials_or_tokens(source):
    with aioresponses() as mock:
        if source == "repo":
            mock.get(
                "https://repo.sol.us/id/TEST-APP/2026.42",
                payload={"Server": "https://evil.example"},
            )
        elif source == "http":
            mock.get(
                "https://repo.sol.us/id/TEST-APP/2026.42",
                status=302,
                headers={"Location": "https://evil.example"},
            )
        else:
            login(
                mock,
                detail2={
                    "SessionID": "TEST_SESSION",
                    "ServerToUse": "https://process-other.sol.us",
                },
            )
        async with aiohttp.ClientSession() as session:
            with pytest.raises(SolusSecurityError):
                await client(session).async_login(CARD, PIN)
        assert all(
            "evil.example" not in str(key[1]) and "process-other" not in str(key[1])
            for key in mock.requests
        )


@pytest.mark.asyncio
async def test_http_auth_on_data_requests_is_distinct_session_expiry():
    """The coordinator can retry an expired session once without retrying bad PINs."""
    with aioresponses() as mock:
        login(mock)
        mock.post(endpoint("LoansGet"), status=403)
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(SolusAuthError) as caught:
                await api.async_get_loans(CARD)
            assert type(caught.value).__name__ == "SolusSessionExpired"
            with pytest.raises(SolusAuthError):
                await api.async_get_loans(CARD)
        assert len(mock.requests) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["bootstrap", "pre", "check", "loans"])
async def test_http_redirects_are_blocked_at_each_authentication_stage(stage):
    with aioresponses() as mock:
        mock.get("https://repo.sol.us/id/TEST-APP/2026.42", payload={"Server": SERVER})
        auth_pattern = re.compile(rf"{SERVER}/v4/Auth.aspx\?s=.+")
        if stage == "bootstrap":
            mock.get(
                auth_pattern, status=302, headers={"Location": "https://evil.example"}
            )
        else:
            mock.get(auth_pattern, body="")
            if stage == "pre":
                mock.post(
                    endpoint("LoginPreSession"),
                    status=307,
                    headers={"Location": "https://evil.example"},
                )
            else:
                mock.post(
                    endpoint("LoginPreSession"),
                    payload=fixture("login_presession_success.json"),
                )
                if stage == "check":
                    mock.post(
                        endpoint("LoginCheckSession"),
                        status=308,
                        headers={"Location": "https://evil.example"},
                    )
                else:
                    mock.post(
                        endpoint("LoginCheckSession"),
                        payload={
                            "d": {
                                "status": "success",
                                "Detail": [{"AuthToken": TOKEN}],
                                "Detail2": {"SessionID": "TEST_SESSION"},
                            }
                        },
                    )
                    mock.post(
                        endpoint("LoansGet"),
                        status=302,
                        headers={"Location": "https://evil.example"},
                    )
        async with aiohttp.ClientSession() as session:
            api = client(session)
            with pytest.raises(SolusSecurityError):
                await api.async_login(CARD, PIN)
                await api.async_get_loans(CARD)
        assert all("evil.example" not in str(key[1]) for key in mock.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body", [PIN, json.dumps({"d": {"status": "failure", "statusmessage": PIN}})]
)
async def test_hostile_body_never_reaches_exception_traceback_or_logs(body, caplog):
    import traceback

    with aioresponses() as mock:
        login(mock)
        mock.post(endpoint("LoansGet"), body=body)
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(SolusProtocolError) as caught:
                await api.async_get_loans(CARD)
        rendered = "".join(traceback.format_exception(caught.value)) + caplog.text
        assert all(secret not in rendered for secret in (CARD, PIN, TOKEN, DEVICE))


@pytest.mark.asyncio
async def test_unknown_expiry_code_fails_safely_without_guessing_authentication():
    with aioresponses() as mock:
        login(mock)
        mock.post(
            endpoint("LoansGet"),
            payload={"d": {"status": "TEST_UNVERIFIED_EXPIRY", "Detail": []}},
        )
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(SolusProtocolError):
                await api.async_get_loans(CARD)
        assert len(mock.requests) == 5


@pytest.mark.asyncio
async def test_clients_do_not_share_tokens_or_change_session_defaults():
    with aioresponses() as mock:
        login(mock)
        bootstrap(mock)
        mock.post(
            endpoint("LoginPreSession"),
            payload={
                "d": {
                    "status": "success",
                    "Detail": [{"AuthToken": "TEST_OTHER_TOKEN"}],
                }
            },
        )
        mock.post(
            endpoint("LoginCheckSession"),
            payload={
                "d": {
                    "status": "success",
                    "Detail": [{"AuthToken": "TEST_OTHER_NEW"}],
                    "Detail2": {"SessionID": "TEST_OTHER_SESSION"},
                }
            },
        )
        mock.post(
            endpoint("LoansGet"),
            payload={"d": {"status": "success", "Detail": []}},
            repeat=True,
        )
        async with (
            aiohttp.ClientSession() as session_a,
            aiohttp.ClientSession() as session_b,
        ):
            api_a, api_b = client(session_a), client(session_b)
            await api_a.async_login(CARD, PIN)
            await api_b.async_login("TEST_OTHER_CARD", "TEST_OTHER_PIN")
            await api_a.async_get_loans(CARD)
            await api_b.async_get_loans("TEST_OTHER_CARD")
            assert not session_a.headers and not session_b.headers
        requests = [
            item
            for key, value in mock.requests.items()
            if "LoansGet" in str(key[1])
            for item in value
        ]
        assert [item.kwargs["headers"]["x-session"] for item in requests] == [
            "TEST_NEW_TOKEN",
            "TEST_OTHER_NEW",
        ]
        assert [item.kwargs["headers"]["x-devicesession"] for item in requests] == [
            "TEST_SESSION",
            "TEST_OTHER_SESSION",
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [None, "TEST_UNKNOWN_STATUS", 123])
async def test_malformed_auth_status_is_protocol_failure(status):
    """A provider/schema outage must not be reported as a rejected PIN."""
    with aioresponses() as mock:
        bootstrap(mock)
        mock.post(endpoint("LoginPreSession"), payload={"d": {"status": status}})
        async with aiohttp.ClientSession() as session:
            with pytest.raises(SolusProtocolError):
                await client(session).async_login(CARD, PIN)


@pytest.mark.asyncio
async def test_expiry_state_survives_queued_requests_until_successful_login():
    """Queued calls after HTTP expiry retain the recoverable classification."""
    from custom_components.axiell_libraries.solus import SolusSessionExpired

    with aioresponses() as mock:
        login(mock)
        mock.post(endpoint("RecordGet"), status=401)
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(SolusSessionExpired):
                await api.async_get_record("TEST_RECORD", "ILS")
            with pytest.raises(SolusSessionExpired):
                await api.async_get_record("QUEUED_RECORD", "ILS")
            with pytest.raises(SolusSessionExpired):
                await api.async_get_loans(CARD)
            login(mock)
            await api.async_login(CARD, PIN)
            mock.post(
                endpoint("LoansGet"), payload={"d": {"status": "success", "Detail": []}}
            )
            assert await api.async_get_loans(CARD) == []


@pytest.mark.asyncio
async def test_failed_login_clears_expiry_state_and_remains_credential_rejection():
    """Expired state cannot cause invalid credentials to enter recovery loops."""
    from custom_components.axiell_libraries.solus import SolusSessionExpired

    with aioresponses() as mock:
        login(mock)
        mock.post(endpoint("LoansGet"), status=401)
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(SolusSessionExpired):
                await api.async_get_loans(CARD)
            bootstrap(mock)
            mock.post(endpoint("LoginPreSession"), status=403)
            with pytest.raises(SolusAuthError) as rejected:
                await api.async_login(CARD, PIN)
            assert not isinstance(rejected.value, SolusSessionExpired)
            with pytest.raises(SolusAuthError) as unauthenticated:
                await api.async_get_loans(CARD)
            assert not isinstance(unauthenticated.value, SolusSessionExpired)


@pytest.mark.asyncio
async def test_transient_recovery_failure_preserves_expiry_for_next_poll():
    from custom_components.axiell_libraries.solus import SolusSessionExpired

    with aioresponses() as mock:
        login(mock)
        mock.post(endpoint("LoansGet"), status=401)
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(SolusSessionExpired):
                await api.async_get_loans(CARD)
            mock.get("https://repo.sol.us/id/TEST-APP/2026.42", status=503)
            with pytest.raises(SolusConnectionError):
                await api.async_login(CARD, PIN)
            with pytest.raises(SolusSessionExpired):
                await api.async_get_loans(CARD)
