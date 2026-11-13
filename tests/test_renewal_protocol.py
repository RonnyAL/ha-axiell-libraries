"""Offline renewal request and privacy contract; all secrets are synthetic."""

import base64
import json
import re
from dataclasses import FrozenInstanceError
from html import escape
from unittest.mock import patch
from urllib.parse import quote, quote_plus

import aiohttp
import pytest
from aioresponses import CallbackResult
from yarl import URL

from custom_components.axiell_libraries import solus
from tests.http import AiohttpResponses as aioresponses
from tests.test_auth_protocol import ACCEPT, UA
from tests.test_solus import APP, CARD, DEVICE, PIN, SERVER, client, endpoint, login

USER = "TEST_LINKED_ACCOUNT"
LOAN = "TEST_LOAN_NOT_RECORD"
SOURCE = "ILS/Issued copy Ø"


async def renew(api, **kwargs):
    return await api.async_renew_loan(USER, LOAN, SOURCE, **kwargs)


async def test_renewal_uses_current_routed_server_session_and_exact_envelope():
    """A stale configured host or record identifier would write the wrong target."""
    with aioresponses() as mock:
        login(mock)
        mock.post(endpoint("LoanRenew"), payload={"d": {"status": "success"}})
        async with aiohttp.ClientSession() as session:
            api = solus.SolusClient(
                session, APP, "https://configured-old.sol.us", DEVICE
            )
            with patch("secrets.token_hex", side_effect=AssertionError("New device")):
                await api.async_login(CARD, PIN)
                result = await renew(api)
            assert result.outcome == "success"
            assert result.acknowledgement_code is None
            assert not session.headers
        calls = [
            (str(key[1]), call.kwargs)
            for key, rows in mock.requests.items()
            for call in rows
        ]
        url, request = next(row for row in calls if "/LoanRenew?" in row[0])
        assert re.fullmatch(rf"{SERVER}/v4/Cat.asmx/LoanRenew\?rnd=[0-9a-f]+", url)
        assert request["json"] == {
            "AppID": "TEST-APP",
            "TemplateID": "TEST-APP",
            "SessionID": "TEST_SESSION",
            "DeviceID": "0123456789abcdef",
            "Locale": "nb-NO",
            "UserID": "TEST_LINKED_ACCOUNT",
            "Request": {
                "LoanID": "TEST_LOAN_NOT_RECORD",
                "UserID": "TEST_LINKED_ACCOUNT",
                "Source": "ILS/Issued copy Ø",
                "PromptAcknowledged": "",
            },
        }
        assert request["headers"] == {
            "User-Agent": UA,
            "Accept": ACCEPT,
            "Content-Type": "application/json; charset=utf-8",
            "x-session": "TEST_NEW_TOKEN",
            "x-devicesession": "TEST_SESSION",
            "x-appversion": "2026.42",
            "x-appbuild": "2026420500",
            "x-apppackage": "solus.AllAxiell",
        }
        assert request["allow_redirects"] is False
        assert request["timeout"].total == 20
        assert len(calls) == 5


@pytest.mark.parametrize(
    "status,message,outcome,code",
    [
        ("success", "Renewed", "success", None),
        ("SUCCESS", "Renewed", "success", None),
        ("error", "Cannot renew", "error", None),
        ("ERROR", "Cannot renew", "error", None),
        ("FeeRequired", "Accept fee?", "confirmation_required", "FeeRequired"),
    ],
)
@pytest.mark.parametrize("serialized", [False, True])
async def test_renewal_reply_classification(status, message, outcome, code, serialized):
    detail = {"status": status, "statusmessage": message}
    with aioresponses() as mock:
        login(mock)
        mock.post(
            endpoint("LoanRenew"),
            payload={"d": json.dumps(detail) if serialized else detail},
        )
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            result = await renew(api)
        assert isinstance(result, solus.RenewalReply)
        assert (result.outcome, result.message, result.acknowledgement_code) == (
            outcome,
            message,
            code,
        )
        assert message not in repr(result)
        if code:
            assert code not in repr(result)
        with pytest.raises(FrozenInstanceError):
            result.message = "changed"


async def test_confirmed_chained_codes_preserved_exactly():
    with aioresponses() as mock:
        login(mock)
        mock.post(endpoint("LoanRenew"), payload={"d": {"status": "success"}})
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            await renew(api, acknowledged_codes=("FeeRequired", "Exact_CASE:2"))
        request = next(
            rows[0].kwargs["json"]["Request"]
            for key, rows in mock.requests.items()
            if "LoanRenew" in str(key[1])
        )
        assert request["PromptAcknowledged"] == "FeeRequired;Exact_CASE:2"


@pytest.mark.parametrize(
    "code",
    ["", " spaced", "spaced ", "a;b", "a\nb", "a\x00b", "a\u200bb", "x" * 129, None, 3],
)
async def test_invalid_acknowledgement_code_rejected_before_write(code):
    with aioresponses() as mock:
        login(mock)
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(solus.SolusProtocolError) as error:
                await renew(api, acknowledged_codes=(code,))
            assert str(error.value) == "Invalid Solus renewal acknowledgement"
        assert len(mock.requests) == 4


@pytest.mark.parametrize(
    "detail",
    [
        None,
        [],
        "broken JSON",
        {},
        {"status": None},
        {"status": 3},
        {"status": ""},
        {"status": " spaced", "statusmessage": "Accept?"},
        {"status": "a;b", "statusmessage": "Accept?"},
        {"status": "a\nb", "statusmessage": "Accept?"},
        {"status": "x" * 129, "statusmessage": "Accept?"},
        {"status": "FeeRequired"},
        {"status": "FeeRequired", "statusmessage": ""},
        {"status": "FeeRequired", "statusmessage": "<script>unsafe()</script>"},
        {"status": "FeeRequired", "statusmessage": 3},
        {"status": "error", "statusmessage": []},
        {"status": "success", "statusmessage": {}},
    ],
)
async def test_malformed_renewal_reply_is_static_protocol_error(detail):
    with aioresponses() as mock:
        login(mock)
        mock.post(endpoint("LoanRenew"), payload={"d": detail})
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(solus.SolusProtocolError) as error:
                await renew(api)
            assert str(error.value) == "Malformed Solus renewal response"
        assert len(mock.requests) == 5


async def test_renewal_requires_session_without_logging_in():
    with aioresponses() as mock:
        async with aiohttp.ClientSession() as session:
            with pytest.raises(solus.SolusAuthError):
                await renew(client(session))
        assert not mock.requests


@pytest.mark.parametrize(
    "response,error_class",
    [
        ({"status": 401}, solus.SolusSessionExpired),
        ({"status": 403}, solus.SolusSessionExpired),
        ({"status": 503}, solus.SolusConnectionError),
        (
            {"status": 302, "headers": {"Location": "https://evil.example"}},
            solus.SolusSecurityError,
        ),
        ({"exception": TimeoutError("TEST_SECRET_BODY")}, solus.SolusConnectionError),
        ({"body": "TEST_SECRET_BODY"}, solus.SolusProtocolError),
    ],
)
async def test_write_failures_never_retry_or_reauthenticate(response, error_class):
    with aioresponses() as mock:
        login(mock)
        mock.post(endpoint("LoanRenew"), **response)
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(error_class) as error:
                await renew(api)
            assert "TEST_SECRET_BODY" not in str(error.value)
            assert "TEST_SECRET_BODY" not in repr(error.value)
            if error_class is solus.SolusSessionExpired:
                with pytest.raises(solus.SolusSessionExpired):
                    await renew(api)
        assert sum(len(rows) for rows in mock.requests.values()) == 5


@pytest.mark.parametrize("method", ["LoansGet", "RecordGet"])
@pytest.mark.parametrize("status", ["error", "FeeRequired"])
async def test_renewal_decoder_does_not_relax_existing_reads(method, status):
    with aioresponses() as mock:
        login(mock)
        mock.post(endpoint(method), payload={"d": {"status": status, "Detail": []}})
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(solus.SolusProtocolError):
                if method == "LoansGet":
                    await api.async_get_loans(USER)
                else:
                    await api.async_get_record("TEST_RECORD", SOURCE)


@pytest.mark.parametrize(
    "message,expected",
    [
        ("<b>Fee &amp; terms</b><br>Accept?\x00\u200b", "Fee & terms Accept?"),
        ("&lt;b&gt;Accept&lt;/b&gt; &amp;amp; terms", "Accept & terms"),
        ("<script>private</script><style>hidden</style>Visible", "Visible"),
        ("x" * 600, "x" * 512),
    ],
)
async def test_provider_message_plain_text_and_bound(message, expected):
    with aioresponses() as mock:
        login(mock)
        mock.post(
            endpoint("LoanRenew"),
            payload={"d": {"status": "FeeRequired", "statusmessage": message}},
        )
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            assert (await renew(api)).message == expected


@pytest.mark.parametrize(
    "encode",
    [
        str,
        escape,
        quote,
        quote_plus,
        lambda value: quote(quote(value)),
        lambda value: base64.b64encode(value.encode()).decode(),
        lambda value: "".join(f"&#{ord(char)};" for char in value),
        lambda value: "".join(f"\\u{ord(char):04x}" for char in value),
    ],
)
async def test_known_secrets_and_encoded_forms_redacted_before_truncating(
    encode, caplog
):
    secret = "TEST secret<&/Ø"
    with aioresponses() as mock:
        login(mock)
        mock.post(
            endpoint("LoanRenew"),
            payload={
                "d": {
                    "status": "error",
                    "statusmessage": "Rejected " + encode(secret) + " " + "x" * 600,
                }
            },
        )
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            result = await renew(api, sensitive_values=(secret,))
        assert result.message.startswith("Rejected [redacted] ")
        assert len(result.message) == 512
        assert secret not in result.message
        assert secret not in repr(result)
        assert secret not in caplog.text


async def test_client_account_session_and_before_after_cookie_values_redacted():
    async with aiohttp.ClientSession() as session:
        session.cookie_jar.update_cookies({"old": "TEST_OLD_COOKIE"}, URL(SERVER))

        def response(*args, **kwargs):
            session.cookie_jar.clear()
            session.cookie_jar.update_cookies({"new": "TEST_NEW_COOKIE"}, URL(SERVER))
            return CallbackResult(
                payload={
                    "d": {
                        "status": "error",
                        "statusmessage": " ".join(
                            [
                                CARD,
                                USER,
                                PIN,
                                "TEST_NEW_TOKEN",
                                "TEST_SESSION",
                                DEVICE,
                                "TEST_OLD_COOKIE",
                                "TEST_NEW_COOKIE",
                            ]
                        ),
                    }
                }
            )

        with aioresponses() as mock:
            login(mock)
            mock.post(endpoint("LoanRenew"), callback=response)
            api = client(session)
            await api.async_login(CARD, PIN)
            result = await renew(api, sensitive_values=(CARD, PIN))
            assert result.message == " ".join(["[redacted]"] * 8)


async def test_challenge_code_cannot_leak_via_provider_message():
    with aioresponses() as mock:
        login(mock)
        mock.post(
            endpoint("LoanRenew"),
            payload={
                "d": {
                    "status": "TEST_INTERNAL_CODE",
                    "statusmessage": "Accept TEST_INTERNAL_CODE?",
                }
            },
        )
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            result = await renew(api)
            assert result.message == "Accept [redacted]?"
            assert result.acknowledgement_code == "TEST_INTERNAL_CODE"
