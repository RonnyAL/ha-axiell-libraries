"""Small, read-only Solus transport with explicit destination and session bounds.

The caller supplies and owns an isolated aiohttp session and persistent DeviceID.
Tokens stay on this client; no session defaults or global authentication are used.
"""

import base64
import json
import math
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode, urlsplit
from uuid import uuid4

import aiohttp

APP_VERSION = "2026.42"
APP_BUILD = "2026420500"
PACKAGE_NAME = "solus.AllAxiell"
GLOBAL_APP_ID = "5C72D777-E044-4B76-97A8-F240FA42E9BD"
_TIMEOUT = aiohttp.ClientTimeout(total=20)
_SOLUS_HOST = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.sol\.us")


class SolusError(Exception):
    """Safe error boundary; messages never include upstream data."""


class SolusConnectionError(SolusError):
    """Transport or HTTP server failure."""


class SolusAuthError(SolusError):
    """Authentication was rejected or an HTTP session expired."""


class SolusSessionExpired(SolusAuthError):
    """An authenticated data request received HTTP 401/403."""


class SolusProtocolError(SolusError):
    """Unexpected or unsuccessful API response."""


class SolusSecurityError(SolusError):
    """Unsafe destination or redirect rejected before forwarding secrets."""


@dataclass(frozen=True, slots=True)
class Library:
    """Resolved library identity and processing origin, without account state."""

    location_id: str
    name: str
    app_id: str
    server_url: str


def _origin(value: Any) -> str:
    """Accept a root HTTPS origin on a strict single-label Solus subdomain."""
    try:
        parsed = urlsplit(value) if isinstance(value, str) else None
        if (
            parsed is None
            or any(char.isspace() or ord(char) < 32 for char in value)
            or "\\" in value
            or parsed.scheme != "https"
            or not parsed.hostname
            or _SOLUS_HOST.fullmatch(parsed.hostname) is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or ":" in parsed.netloc
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or "?" in value
            or "#" in value
        ):
            raise SolusSecurityError("Unsafe Solus destination") from None
        return f"https://{parsed.hostname}"
    except ValueError:
        raise SolusSecurityError("Unsafe Solus destination") from None


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SolusProtocolError("Malformed Solus response") from None
    return value.strip()


def _decode(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            raise SolusProtocolError("Malformed Solus response") from None
    return value


async def _request(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    payload: dict | None = None,
    headers: dict | None = None,
    bootstrap: bool = False,
) -> Any:
    """No automatic redirects, retries, raw exception messages or HTTP logging."""
    kwargs = {"allow_redirects": False, "timeout": _TIMEOUT}
    if payload is not None:
        kwargs["json"] = payload
    if headers is not None:
        kwargs["headers"] = headers
    try:
        async with session.request(method, url, **kwargs) as response:
            if 300 <= response.status < 400:
                raise SolusSecurityError("Solus redirect rejected") from None
            if response.status in (401, 403):
                raise SolusAuthError("Solus authentication required") from None
            if response.status != 200:
                raise SolusConnectionError("Solus server unavailable") from None
            if bootstrap:
                await response.read()
                return None
            return await response.json(content_type=None)
    except (TimeoutError, aiohttp.ClientError):
        raise SolusConnectionError("Unable to contact Solus") from None
    except (ValueError, TypeError, UnicodeError):
        raise SolusProtocolError("Malformed Solus response") from None


def _section(payload: Any, *, authentication: bool = False) -> dict:
    payload = _decode(payload)
    detail = _decode(payload.get("d")) if isinstance(payload, dict) else None
    if not isinstance(detail, dict):
        raise SolusProtocolError("Malformed Solus response") from None
    if detail.get("status") != "success":
        if authentication and detail.get("status") == "failure":
            raise SolusAuthError("Solus authentication rejected") from None
        raise SolusProtocolError("Unsuccessful Solus response") from None
    return detail


def _list_detail(section: dict, *, nonempty: bool = False) -> list[dict]:
    detail = _decode(section.get("Detail"))
    if (
        not isinstance(detail, list)
        or any(not isinstance(item, dict) for item in detail)
        or (nonempty and not detail)
    ):
        raise SolusProtocolError("Malformed Solus response") from None
    return detail


async def _routing(session: aiohttp.ClientSession, app_id: str) -> tuple[str, str]:
    payload = _decode(
        await _request(
            session,
            "GET",
            f"https://repo.sol.us/id/{quote(app_id, safe='')}/{APP_VERSION}",
        )
    )
    if not isinstance(payload, dict):
        raise SolusProtocolError("Malformed Solus routing") from None
    server = _origin(payload.get("Server"))
    auth_server = _origin(payload.get("AuthServer", server))
    return server, auth_server


async def _library(session: aiohttp.ClientSession, item: Any) -> Library:
    if not isinstance(item, dict):
        raise SolusProtocolError("Malformed Solus library") from None
    location_id, app_id = _text(item.get("LocationID")), _text(item.get("AppID"))
    _origin(item.get("ServerUrl"))
    server, _ = await _routing(session, app_id)
    return Library(location_id, _text(item.get("Name")), app_id, server)


async def _locator(session: aiohttp.ClientSession, method: str, payload: dict) -> Any:
    response = _decode(
        await _request(
            session,
            "POST",
            f"https://locator.sol.us/v4/Locator.asmx/{method}?rnd={uuid4().hex}",
            payload={**payload, "GlobalAppID": GLOBAL_APP_ID},
        )
    )
    response = (
        _decode(response.get("d", response)) if isinstance(response, dict) else None
    )
    if not isinstance(response, dict) or response.get("Status") != "OK":
        raise SolusProtocolError("Unable to discover Solus libraries") from None
    return response


async def async_lookup_location(
    session: aiohttp.ClientSession, location_id: str
) -> Library:
    """Resolve a manual LocationID through the locator and HTTPS routing repo."""
    response = await _locator(session, "QueryWithID", {"LocationID": location_id})
    return await _library(session, response)


async def async_find_nearby(
    session: aiohttp.ClientSession, latitude: float, longitude: float
) -> list[Library]:
    """Find nearby candidates; no server-side text search is assumed."""
    if (
        not isinstance(latitude, (float, int))
        or not isinstance(longitude, (float, int))
        or not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise SolusProtocolError("Invalid library search location") from None
    response = await _locator(
        session,
        "FindWithLocation",
        {
            "LocationLat": latitude,
            "LocationLng": longitude,
        },
    )
    items = _decode(response.get("Detail"))
    if not isinstance(items, list):
        raise SolusProtocolError("Malformed Solus library results") from None
    return [await _library(session, item) for item in items]


class SolusClient:
    """One account's in-memory authentication, with no automatic login retries."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        app_id: str,
        server_url: str,
        device_id: str,
        locale: str = "nb-NO",
    ) -> None:
        self._session = session
        self._app_id = _text(app_id)
        self._server = _origin(server_url)
        if (
            not isinstance(device_id, str)
            or re.fullmatch(r"[0-9a-f]{16}", device_id) is None
        ):
            raise SolusProtocolError("A persistent DeviceID is required") from None
        self._device_id = device_id
        self._locale = locale
        self._token = ""
        self._session_id = ""
        self._user_id = ""
        self._authenticated = False
        self._session_expired = False

    def _metadata(self) -> dict:
        return {
            "AppID": self._app_id,
            "TemplateID": self._app_id,
            "DeviceID": self._device_id,
            "AppVersion": APP_VERSION,
            "PackageName": PACKAGE_NAME,
            "PlatType": "Home Assistant",
            "PlatVer": "1",
            "PlatModel": "Home Assistant",
            "DName": "Home Assistant",
            "Locale": self._locale,
            "font": "100",
            "AppBuild": APP_BUILD,
            "ServerRoot": self._server + "/",
        }

    async def _call(self, method: str, request: dict, *, authentication=False) -> dict:
        headers = {
            "x-session": self._token,
            "x-devicesession": self._session_id,
            "x-appversion": APP_VERSION,
            "x-appbuild": APP_BUILD,
            "x-apppackage": PACKAGE_NAME,
        }
        if method == "LoginPreSession":
            envelope = {
                "AppID": self._app_id,
                "TemplateID": self._app_id,
                "DeviceID": self._device_id,
                "Locale": self._locale,
                "UserID": self._user_id,
                "Request": request,
            }
            headers.update(
                {
                    "Origin": self._server,
                    "Referer": self._server + "/v4/",
                    "X-Requested-With": "XMLHttpRequest",
                }
            )
        else:
            envelope = {
                "AppID": self._app_id,
                "TemplateID": self._app_id,
                "SessionID": self._session_id,
                "DeviceID": self._device_id,
                "Locale": self._locale,
                "UserID": self._user_id,
                "Request": request,
            }
        try:
            return _section(
                await _request(
                    self._session,
                    "POST",
                    f"{self._server}/v4/Cat.asmx/{method}?rnd={uuid4().hex}",
                    payload=envelope,
                    headers=headers,
                ),
                authentication=authentication,
            )
        except SolusAuthError:
            self._authenticated = False
            self._token = ""
            self._session_expired = not authentication
            if not authentication:
                raise SolusSessionExpired("Solus session expired") from None
            raise

    async def async_login(self, card: str, pin: str) -> list[dict]:
        """Bootstrap cookies then establish an account session; never create IDs."""
        self._authenticated = False
        self._token = self._session_id = ""
        self._user_id = card
        self._server, auth_server = await _routing(self._session, self._app_id)
        try:
            metadata = self._metadata()
            query = urlencode(
                {"s": base64.b64encode(json.dumps(metadata).encode()).decode()}
            )
            await _request(
                self._session,
                "GET",
                f"{auth_server}/v4/Auth.aspx?{query}",
                bootstrap=True,
            )
            pre = await self._call(
                "LoginPreSession",
                {
                    "UserID": card,
                    "Password": pin,
                    "StoreCredentials": False,
                    "Name": "",
                },
                authentication=True,
            )
            self._token = _text(_list_detail(pre, nonempty=True)[0].get("AuthToken"))
            check = await self._call(
                "LoginCheckSession",
                {
                    **metadata,
                    "AuthToken": self._token,
                },
                authentication=True,
            )
            users = _list_detail(check, nonempty=True)
            session = check.get("Detail2")
            if session is not None:
                session = _decode(session)
                if not isinstance(session, dict):
                    raise SolusProtocolError("Malformed Solus session") from None
                destination = session.get("ServerToUse")
                if destination and _origin(destination) != self._server:
                    raise SolusSecurityError(
                        "Untrusted Solus session destination"
                    ) from None
                if session.get("SessionID") is not None:
                    self._session_id = str(session["SessionID"])
            if users[0].get("AuthToken"):
                self._token = _text(users[0]["AuthToken"])
            self._authenticated = True
            self._session_expired = False
            return users
        except SolusError as error:
            self._token = self._session_id = ""
            if isinstance(error, SolusAuthError):
                self._session_expired = False
            raise

    def _require_session(self) -> None:
        if not self._authenticated:
            if self._session_expired:
                raise SolusSessionExpired("Solus session expired") from None
            raise SolusAuthError("Solus authentication required") from None

    async def async_get_loans(self, user_id: str) -> list[dict]:
        """Fetch loans; malformed responses never imply an empty account."""
        self._require_session()
        section = await self._call("LoansGet", {"UserID": user_id})
        rows = _list_detail(section)
        loan_ids: set[str] = set()
        for row in rows:
            loan_id = _text(row.get("loanID"))
            _text(row.get("title"))
            if loan_id in loan_ids:
                raise SolusProtocolError("Malformed Solus loans response") from None
            loan_ids.add(loan_id)
        return rows

    async def async_get_record(self, record_id: str, source: str) -> dict | None:
        """Fetch optional metadata; callers may catch SolusError per record."""
        self._require_session()
        section = await self._call(
            "RecordGet",
            {
                "RecordID": record_id,
                "Source": source,
                "SearchLimit": "",
            },
        )
        detail = _decode(section.get("Detail"))
        if detail is None or detail == []:
            return None
        if isinstance(detail, list) and len(detail) == 1:
            detail = detail[0]
        if not isinstance(detail, dict):
            raise SolusProtocolError("Malformed Solus catalogue response") from None
        return detail
