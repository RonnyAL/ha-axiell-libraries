"""Synthetic request contract from the owner-verified authentication probe."""

import base64
import json
import re
import socket
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import aiohttp
import pytest
from aiohttp import web
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from custom_components.axiell_libraries import solus
from tests.http import AiohttpResponses as aioresponses
from tests.test_solus import (
    APP,
    CARD,
    DEVICE,
    PIN,
    SERVER,
    TOKEN,
    bootstrap,
    client,
    endpoint,
    fixture,
    login,
)

ZERO = "00000000-0000-0000-0000-000000000000"
UA = (
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36"
)
ACCEPT = "application/json, text/javascript, */*; q=0.01"
IDENTITY = {
    "AppID": APP,
    "TemplateID": APP,
    "DeviceID": DEVICE,
    "AppVersion": "2026.42",
    "PackageName": "solus.AllAxiell",
    "PlatType": "Android",
    "PlatVer": "17",
    "PlatModel": "Home Assistant",
    "DName": "Android",
    "Locale": "nb-NO",
    "AppBuild": "2026420500",
}


@pytest.mark.parametrize(
    "boundary",
    [
        "bootstrap_metadata",
        "bootstrap_encoding",
        "bootstrap_headers",
        "pre_headers",
        "check_metadata",
        "check_envelope",
        "loan_user",
    ],
)
async def test_probe_request_boundary(boundary):
    """Catch request omissions at the HTTP boundary without a provider request."""
    with aioresponses() as mock:
        login(mock)
        mock.post(
            endpoint("LoansGet"), payload={"d": {"status": "success", "Detail": []}}
        )
        async with aiohttp.ClientSession() as session:
            api = solus.SolusClient(
                session,
                APP,
                SERVER,
                DEVICE,
                "nb-Ø" if boundary == "bootstrap_encoding" else "nb-NO",
            )
            await api.async_login(CARD, PIN)
            await api.async_get_loans("TEST_LINKED_USER")
            assert not session.headers
        calls = [
            (str(key[1]), call.kwargs)
            for key, rows in mock.requests.items()
            for call in rows
        ]
        auth_url, auth = next((url, kw) for url, kw in calls if "Auth.aspx" in url)
        pre = next(kw for url, kw in calls if "LoginPreSession" in url)
        check = next(kw for url, kw in calls if "LoginCheckSession" in url)
        loans = next(kw for url, kw in calls if "LoansGet" in url)
        metadata_bytes = base64.b64decode(parse_qs(urlsplit(auth_url).query)["s"][0])
        if boundary == "bootstrap_metadata":
            assert json.loads(metadata_bytes) == {
                **IDENTITY,
                "font": "",
                "ServerRoot": SERVER + "/",
            }
        elif boundary == "bootstrap_encoding":
            assert b'": ' not in metadata_bytes and b", " not in metadata_bytes
            assert "Ø".encode() in metadata_bytes
        elif boundary == "bootstrap_headers":
            assert auth.get("headers") == {
                "User-Agent": UA,
                "Accept": ACCEPT,
                "x-session": "",
                "x-devicesession": ZERO,
                "x-appversion": "2026.42",
                "x-appbuild": "2026420500",
                "x-apppackage": "solus.AllAxiell",
            }
        elif boundary == "pre_headers":
            assert pre["headers"] == {
                "User-Agent": UA,
                "Accept": ACCEPT,
                "Content-Type": "application/json; charset=utf-8",
                "Origin": SERVER,
                "Referer": auth_url,
                "X-Requested-With": "XMLHttpRequest",
            }
            assert "SessionID" not in pre["json"] and "VerifyToken" not in pre["json"]
        elif boundary == "check_metadata":
            assert check["json"]["Request"] == {
                **IDENTITY,
                "NetworkType": "WiFi",
                "ScreenW": 384,
                "ScreenAW": 384,
                "ScreenH": 832,
                "ScreenAH": 832,
                "DPR": 1,
                "AuthToken": TOKEN,
            }
            assert check["headers"] == {
                "User-Agent": UA,
                "Accept": ACCEPT,
                "Content-Type": "application/json; charset=utf-8",
                "x-session": TOKEN,
                "x-devicesession": ZERO,
                "x-appversion": "2026.42",
                "x-appbuild": "2026420500",
                "x-apppackage": "solus.AllAxiell",
            }
        elif boundary == "check_envelope":
            assert check["json"]["SessionID"] == ZERO
            assert check["json"]["UserID"] == ""
        else:
            assert loans["json"]["UserID"] == "TEST_LINKED_USER"
            assert loans["json"]["Request"] == {"UserID": "TEST_LINKED_USER"}


@pytest.mark.parametrize("detail", [{}, {"Detail": None}, {"Detail": []}])
async def test_check_without_users_preserves_pre_session_account_and_token(detail):
    with aioresponses() as mock:
        bootstrap(mock)
        mock.post(
            endpoint("LoginPreSession"),
            payload=fixture("login_presession_success.json"),
        )
        mock.post(
            endpoint("LoginCheckSession"),
            payload={
                "d": {
                    "status": "success",
                    **detail,
                    "Detail2": {
                        "SessionID": "TEST_SESSION",
                        "ServerToUse": SERVER + "/",
                    },
                }
            },
        )
        mock.post(
            endpoint("LoansGet"), payload={"d": {"status": "success", "Detail": []}}
        )
        async with aiohttp.ClientSession() as session:
            api = client(session)
            assert (
                await api.async_login(CARD, PIN)
                == fixture("login_presession_success.json")["d"]["Detail"]
            )
            assert await api.async_get_loans(CARD) == []
        loans = next(
            rows[0].kwargs
            for key, rows in mock.requests.items()
            if "LoansGet" in str(key[1])
        )
        assert loans["headers"]["x-session"] == TOKEN
        assert loans["headers"]["x-devicesession"] == "TEST_SESSION"


@pytest.mark.parametrize("status", ["SUCCESS", "Success", "sUcCeSs"])
async def test_case_insensitive_success(status):
    with aioresponses() as mock:
        bootstrap(mock)
        pre = fixture("login_presession_success.json")
        pre["d"]["status"] = status
        mock.post(endpoint("LoginPreSession"), payload=pre)
        mock.post(
            endpoint("LoginCheckSession"),
            payload={"d": {"status": status, "Detail": [{"UserID": CARD}]}},
        )
        async with aiohttp.ClientSession() as session:
            assert await client(session).async_login(CARD, PIN) == [{"UserID": CARD}]


async def test_utf8_bom_responses():
    with aioresponses() as mock:
        mock.get(
            "https://repo.sol.us/id/TEST-APP/2026.42",
            body="\ufeff" + json.dumps({"Server": SERVER}),
        )
        mock.get(re.compile(rf"{SERVER}/v4/Auth.aspx\?s=.+"), body="")
        mock.post(
            endpoint("LoginPreSession"),
            body="\ufeff" + json.dumps(fixture("login_presession_success.json")),
        )
        mock.post(
            endpoint("LoginCheckSession"),
            body="\ufeff"
            + json.dumps({"d": {"status": "success", "Detail": [{"UserID": CARD}]}}),
        )
        async with aiohttp.ClientSession() as session:
            assert await client(session).async_login(CARD, PIN) == [{"UserID": CARD}]


@pytest.mark.parametrize(
    "field,value",
    [
        ("Detail", {}),
        ("Detail", "invalid"),
        ("Detail", [None]),
        ("Detail", [{"AuthToken": 123}]),
        ("Detail2", []),
        ("Detail2", "invalid"),
        ("Detail2", {"SessionID": 123}),
        ("Detail2", {"ServerToUse": []}),
    ],
)
async def test_malformed_provided_session_fields_rejected(field, value):
    with aioresponses() as mock:
        bootstrap(mock)
        mock.post(
            endpoint("LoginPreSession"),
            payload=fixture("login_presession_success.json"),
        )
        detail = {"status": "success", "Detail": [{"UserID": CARD}], field: value}
        mock.post(endpoint("LoginCheckSession"), payload={"d": detail})
        async with aiohttp.ClientSession() as session:
            with pytest.raises(solus.SolusError):
                await client(session).async_login(CARD, PIN)


async def test_relogin_resets_session_identifier_without_changing_device():
    with aioresponses() as mock:
        login(mock)
        login(mock)
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            await api.async_login(CARD, "TEST_CHANGED_PIN")
        requests = [
            row
            for key, rows in mock.requests.items()
            if "LoginCheckSession" in str(key[1])
            for row in rows
        ]
        assert [row.kwargs["json"]["SessionID"] for row in requests] == [ZERO, ZERO]
        assert [row.kwargs["json"]["DeviceID"] for row in requests] == [DEVICE, DEVICE]


@pytest.mark.parametrize("issue_cookie", [True, False])
async def test_real_cookie_transport_isolated_in_ha_owned_sessions(
    hass, issue_cookie, socket_enabled
):
    """Only URLs are mapped to loopback; all aiohttp cookie handling is real."""
    received = []

    async def handler(request):
        received.append((request.path, dict(request.cookies)))
        if request.path.startswith("/id/"):
            return web.json_response({"Server": SERVER})
        if request.path == "/v4/Auth.aspx":
            response = web.Response(text="")
            if issue_cookie:
                response.set_cookie("synthetic_session", "TEST_COOKIE", path="/v4/")
            return response
        if request.path.endswith("LoginPreSession"):
            return web.json_response(fixture("login_presession_success.json"))
        if request.path.endswith("LoginCheckSession"):
            return web.json_response(
                {"d": {"status": "success", "Detail": [{"UserID": CARD}]}}
            )
        if request.path.endswith("LoansGet"):
            return web.json_response({"d": {"status": "success", "Detail": []}})
        raise AssertionError("Unexpected local request")

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    original_request = solus._request

    async def loopback(session, method, url, **kwargs):
        parsed = urlsplit(url)
        assert parsed.hostname in {"repo.sol.us", "process-test.sol.us"}
        return await original_request(
            session,
            method,
            f"http://localhost:{port}{parsed.path}?{parsed.query}",
            **kwargs,
        )

    class LoopbackResolver(aiohttp.abc.AbstractResolver):
        async def resolve(self, host, port=0, family=socket.AF_INET):
            assert host == "localhost"
            return [
                {
                    "hostname": host,
                    "host": "127.0.0.1",
                    "port": port,
                    "family": socket.AF_INET,
                    "proto": 0,
                    "flags": 0,
                }
            ]

        async def close(self):
            pass

    with patch(
        "homeassistant.helpers.aiohttp_client._async_get_or_create_resolver",
        return_value=LoopbackResolver(),
    ):
        sessions = [
            async_create_clientsession(
                hass, auto_cleanup=False, cookie_jar=aiohttp.CookieJar()
            )
            for _ in range(2)
        ]
    original_headers = [dict(session.headers) for session in sessions]
    try:
        with patch.object(solus, "_request", side_effect=loopback):
            assert sessions[0].cookie_jar is not sessions[1].cookie_jar
            for session in sessions:
                api = client(session)
                await api.async_login(CARD, PIN)
                assert await api.async_get_loans(CARD) == []
            assert [dict(session.headers) for session in sessions] == original_headers
        # The second account's bootstrap starts with no first account cookie.
        assert received[1][1] == received[6][1] == {}
        for index in (2, 3, 4, 7, 8, 9):
            assert received[index][1] == (
                {"synthetic_session": "TEST_COOKIE"} if issue_cookie else {}
            )
    finally:
        for session in sessions:
            session.detach()
        await runner.cleanup()
    assert all(session.closed for session in sessions)


@pytest.mark.parametrize(
    "update",
    [{}, {"AuthToken": None, "SessionID": None}, {"AuthToken": "", "SessionID": ""}],
)
async def test_empty_session_updates_retain_pre_token_and_zero_session(update):
    with aioresponses() as mock:
        bootstrap(mock)
        mock.post(
            endpoint("LoginPreSession"),
            payload=fixture("login_presession_success.json"),
        )
        mock.post(
            endpoint("LoginCheckSession"),
            payload={
                "d": {
                    "status": "success",
                    "Detail": [
                        {
                            "UserID": CARD,
                            **{
                                key: value
                                for key, value in update.items()
                                if key == "AuthToken"
                            },
                        }
                    ],
                    "Detail2": {
                        key: value
                        for key, value in update.items()
                        if key == "SessionID"
                    },
                }
            },
        )
        mock.post(
            endpoint("LoansGet"), payload={"d": {"status": "success", "Detail": []}}
        )
        async with aiohttp.ClientSession() as session:
            api = client(session)
            await api.async_login(CARD, PIN)
            assert await api.async_get_loans(CARD) == []
        loans = next(
            rows[0].kwargs
            for key, rows in mock.requests.items()
            if "LoansGet" in str(key[1])
        )
        assert loans["headers"]["x-session"] == TOKEN
        assert loans["headers"]["x-devicesession"] == ZERO
