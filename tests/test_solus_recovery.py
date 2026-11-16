"""Offline classification at the HTTP boundary, including one-shot renewals."""

import ssl
import traceback
from datetime import UTC, datetime
from unittest.mock import patch

import aiohttp
import pytest

from custom_components.axiell_libraries.solus import (
    SolusAuthError,
    SolusConnectionError,
    SolusError,
    SolusProtocolError,
    SolusSecurityError,
    SolusSessionExpired,
)
from tests.http import AiohttpResponses as aioresponses
from tests.test_solus import (
    CARD,
    DEVICE,
    PIN,
    TOKEN,
    bootstrap,
    client,
    endpoint,
    fixture,
    login,
)


async def operation(api, method):
    if method == "LoansGet":
        return await api.async_get_loans(CARD)
    if method == "RecordGet":
        return await api.async_get_record("TEST_RECORD", "ILS")
    return await api.async_renew_loan(CARD, "TEST_LOAN", "ILS")


@pytest.mark.parametrize(
    "status,category,retryable",
    [
        (408, "timeout", True),
        (429, "rate_limit", True),
        (500, "server", True),
        (502, "server", True),
        (503, "server", True),
        (504, "server", True),
        (599, "server", True),
        (400, "protocol", False),
        (404, "protocol", False),
        (422, "protocol", False),
    ],
)
async def test_http_failure_exposes_recovery_policy_without_retrying(
    status, category, retryable
):
    """Without HTTP classification the scheduler cannot choose recovery safely."""
    with aioresponses() as mock:
        login(mock)
        mock.post(endpoint("LoansGet"), status=status, body=TOKEN)
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(SolusConnectionError) as caught:
                await api.async_get_loans(CARD)
        error = caught.value
        assert (error.category, error.retryable, error.retry_after) == (
            category,
            retryable,
            None,
        )
        assert error.reference() == f"loans/http/{status}"
        assert sum(len(calls) for calls in mock.requests.values()) == 5


@pytest.mark.parametrize(
    "failure,category,error_type",
    [
        (TimeoutError(PIN), "timeout", SolusConnectionError),
        (aiohttp.ServerTimeoutError(PIN), "timeout", SolusConnectionError),
        (aiohttp.ClientConnectionError(PIN), "transport", SolusConnectionError),
        (aiohttp.ClientPayloadError(PIN), "transport", SolusConnectionError),
        (ssl.SSLCertVerificationError(PIN), "security", SolusSecurityError),
        (aiohttp.ClientSSLError(None, OSError(PIN)), "security", SolusSecurityError),
        (
            aiohttp.ClientConnectorCertificateError(None, ssl.CertificateError(PIN)),
            "security",
            SolusSecurityError,
        ),
        (
            aiohttp.ServerFingerprintMismatch(b"expected", b"actual", PIN, 443),
            "security",
            SolusSecurityError,
        ),
    ],
)
async def test_transport_timeout_and_tls_failures_are_distinct_and_redacted(
    failure, category, error_type, caplog
):
    with aioresponses() as mock:
        login(mock)
        mock.post(endpoint("LoansGet"), exception=failure)
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(error_type) as caught:
                await api.async_get_loans(CARD)
        error = caught.value
        assert error.category == category
        assert error.retryable is (category != "security")
        assert error.reference() == f"loans/{category}"
        rendered = "".join(traceback.format_exception(error)) + caplog.text
        assert all(secret not in rendered for secret in (CARD, PIN, TOKEN, DEVICE))


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize(
    "header,expected",
    [
        ("120", 120.0),
        ("0", 0.0),
        (" 120 ", 120.0),
        ("Sun, 15 Nov 2026 12:02:00 GMT", 120.0),
        ("Sun, 15 Nov 2026 11:59:00 GMT", 0.0),
        ("-1", None),
        ("1.5", None),
        ("nan", None),
        ("inf", None),
        (TOKEN, None),
        ("9" * 400, None),
        ("Sun, 15 Nov 2026 12:02:00", None),
    ],
)
async def test_retry_after_seconds_and_http_dates_are_bounded_values(
    status, header, expected
):
    with (
        aioresponses() as mock,
        patch(
            "custom_components.axiell_libraries.solus.time",
            return_value=datetime(2026, 11, 15, 12, tzinfo=UTC).timestamp(),
            create=True,
        ),
    ):
        login(mock)
        mock.post(endpoint("LoansGet"), status=status, headers={"Retry-After": header})
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(SolusConnectionError) as caught:
                await api.async_get_loans(CARD)
        assert caught.value.retry_after == expected
        assert header not in repr(caught.value)


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize(
    "method,stage",
    [("LoansGet", "loans"), ("RecordGet", "catalogue"), ("LoanRenew", "renewal")],
)
async def test_authenticated_http_rejection_is_session_expiry(method, stage, status):
    with aioresponses() as mock:
        login(mock)
        mock.post(endpoint(method), status=status)
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(SolusSessionExpired) as caught:
                await operation(api, method)
        assert caught.value.category == "session"
        assert caught.value.retryable is True
        assert caught.value.reference() == f"{stage}/http/{status}"
        assert sum(len(calls) for calls in mock.requests.values()) == 5


@pytest.mark.parametrize(
    "response",
    [{"status": 401}, {"status": 403}, {"payload": {"d": {"status": "failure"}}}],
)
async def test_only_credential_submission_rejection_requests_reauthentication(response):
    with aioresponses() as mock:
        bootstrap(mock)
        mock.post(endpoint("LoginPreSession"), **response)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(SolusAuthError) as caught:
                await client(session).async_login(CARD, PIN)
        assert not isinstance(caught.value, SolusSessionExpired)
        assert caught.value.category == "credentials"
        assert caught.value.retryable is False
        assert caught.value.stage == "login_presession"


@pytest.mark.parametrize(
    "response",
    [
        {"status": 401},
        {"status": 403},
        {"payload": {"d": {"status": "failure"}}},
        {"payload": {"d": {"status": "error"}}},
    ],
)
async def test_checksession_rejection_is_not_evidence_of_bad_credentials(response):
    with aioresponses() as mock:
        bootstrap(mock)
        mock.post(
            endpoint("LoginPreSession"),
            payload=fixture("login_presession_success.json"),
        )
        mock.post(endpoint("LoginCheckSession"), **response)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(SolusProtocolError) as caught:
                await client(session).async_login(CARD, PIN)
        assert caught.value.category == "protocol"
        assert caught.value.retryable is True
        assert caught.value.stage == "login_checksession"


@pytest.mark.parametrize(
    "response",
    [
        {"status": 401},
        {"status": 403},
        {"status": 503},
        {"exception": TimeoutError(TOKEN)},
        {"payload": {"d": {"status": "failure"}}},
    ],
)
async def test_failed_recovery_session_check_remains_recoverable_on_next_poll(response):
    """Check-session errors must not turn known expiry into a rejected PIN."""
    with aioresponses() as mock:
        login(mock)
        mock.post(endpoint("LoansGet"), status=401)
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(SolusSessionExpired):
                await api.async_get_loans(CARD)
            bootstrap(mock)
            mock.post(
                endpoint("LoginPreSession"),
                payload=fixture("login_presession_success.json"),
            )
            mock.post(endpoint("LoginCheckSession"), **response)
            with pytest.raises((SolusProtocolError, SolusConnectionError)):
                await api.async_login(CARD, PIN)
            with pytest.raises(SolusSessionExpired) as caught:
                await api.async_get_loans(CARD)
            assert caught.value.category == "session"
            assert caught.value.retryable is True
        assert sum(len(calls) for calls in mock.requests.values()) == 9


@pytest.mark.parametrize("status", [401, 403, 429, 503])
async def test_bootstrap_http_rejection_never_claims_invalid_credentials(status):
    with aioresponses() as mock:
        mock.get("https://repo.sol.us/id/TEST-APP/2026.42", status=status)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(SolusConnectionError) as caught:
                await client(session).async_login(CARD, PIN)
        assert caught.value.category != "credentials"


@pytest.mark.parametrize(
    "method,stage",
    [("LoansGet", "loans"), ("RecordGet", "catalogue"), ("LoanRenew", "renewal")],
)
async def test_response_schema_errors_retain_operation_and_do_not_guess_expiry(
    method, stage
):
    with aioresponses() as mock:
        login(mock)
        mock.post(endpoint(method), payload={"d": {"status": "TEST_UNVERIFIED_EXPIRY"}})
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(SolusProtocolError) as caught:
                await operation(api, method)
        assert caught.value.category == "protocol"
        assert caught.value.retryable is True
        assert caught.value.stage == stage


@pytest.mark.parametrize("status", [408, 429, 503])
async def test_renewal_failure_is_never_retried_at_the_transport(status):
    with aioresponses() as mock:
        login(mock)
        mock.post(endpoint("LoanRenew"), status=status, headers={"Retry-After": "120"})
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            with pytest.raises(SolusConnectionError) as caught:
                await operation(api, "LoanRenew")
        assert caught.value.reference() == f"renewal/http/{status}"
        assert sum(len(calls) for calls in mock.requests.values()) == 5


@pytest.mark.parametrize("value", [True, "120", float("inf"), float("nan"), -1, TOKEN])
def test_retry_delay_metadata_cannot_include_nonfinite_or_private_values(value):
    error = SolusError(retry_after=value)
    assert error.retry_after is None
