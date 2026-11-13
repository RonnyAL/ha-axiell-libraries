"""Small Solus transport with explicit destination and session bounds.

The caller supplies and owns an isolated aiohttp session and persistent DeviceID.
Tokens stay on this client; no session defaults or global authentication are used.
"""

import base64
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from functools import wraps
from html import escape, unescape
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.parse import quote, quote_plus, urlencode, urlsplit
from uuid import uuid4

import aiohttp

APP_VERSION = "2026.42"
APP_BUILD = "2026420500"
PACKAGE_NAME = "solus.AllAxiell"
GLOBAL_APP_ID = "5C72D777-E044-4B76-97A8-F240FA42E9BD"
_TIMEOUT = aiohttp.ClientTimeout(total=20)
_ZERO_SESSION_ID = "00000000-0000-0000-0000-000000000000"
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
}
_SOLUS_HOST = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.sol\.us")


_STAGES = frozenset(
    {
        "provider",
        "discovery",
        "manual_lookup",
        "routing",
        "bootstrap",
        "login_presession",
        "login_checksession",
    }
)
_REASONS = frozenset(
    {
        "transport",
        "http",
        "api_rejection",
        "response_schema",
        "missing_token",
        "security",
    }
)


class SolusError(Exception):
    """Static messages and finite diagnostic context, never upstream content."""

    default_reason = "response_schema"

    def __init__(self, *args: object, reason=None, status=None) -> None:
        super().__init__(*args)
        self.stage = "provider"
        self.reason = reason if reason in _REASONS else self.default_reason
        self.status = status if type(status) is int and 100 <= status <= 599 else None

    def at_stage(self, stage: str) -> None:
        """Keep the innermost known stage, including routing during discovery."""
        if self.stage == "provider" and stage in _STAGES:
            self.stage = stage

    def reference(self, fallback: str = "provider") -> str:
        """Validate again at the UI boundary; exception text is never rendered."""
        stage = self.stage if self.stage in _STAGES else "provider"
        if stage == "provider" and fallback in _STAGES:
            stage = fallback
        reason = self.reason if self.reason in _REASONS else "response_schema"
        status = self.status
        suffix = f"/{status}" if type(status) is int and 100 <= status <= 599 else ""
        return f"{stage}/{reason}{suffix}"


def _at_stage(stage):
    """Annotate only expected provider errors; programming errors propagate."""

    def decorate(function):
        @wraps(function)
        async def wrapped(*args, **kwargs):
            try:
                return await function(*args, **kwargs)
            except SolusError as error:
                error.at_stage(stage)
                raise

        return wrapped

    return decorate


class SolusConnectionError(SolusError):
    """Transport or HTTP server failure."""

    default_reason = "transport"


class SolusAuthError(SolusError):
    """Authentication was rejected or an HTTP session expired."""

    default_reason = "api_rejection"


class SolusSessionExpired(SolusAuthError):
    """An authenticated data request received HTTP 401/403."""


class SolusProtocolError(SolusError):
    """Unexpected or unsuccessful API response."""


class SolusSecurityError(SolusError):
    """Unsafe destination or redirect rejected before forwarding secrets."""

    default_reason = "security"


@dataclass(frozen=True, slots=True)
class Library:
    """Resolved library identity and processing origin, without account state."""

    location_id: str
    name: str
    app_id: str
    server_url: str


@dataclass(frozen=True, slots=True)
class RenewalReply:
    """A renewal result; provider text and internal consent codes stay out of repr."""

    outcome: Literal["success", "error", "confirmation_required"]
    message: str = field(repr=False)
    acknowledgement_code: str | None = field(default=None, repr=False)


def _valid_acknowledgement(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 128
        and value == value.strip()
        and ";" not in value
        and not any(unicodedata.category(char).startswith("C") for char in value)
    )


class _PlainText(HTMLParser):
    """Discard markup and hidden script/style content from provider messages."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        if tag in {"script", "style"}:
            self._hidden.append(tag)
        elif not self._hidden:
            self.parts.append(" ")

    def handle_endtag(self, tag) -> None:
        if self._hidden:
            if tag == self._hidden[-1]:
                self._hidden.pop()
        else:
            self.parts.append(" ")

    def handle_data(self, data) -> None:
        if not self._hidden:
            self.parts.append(data)


def _redact_message(value: str, sensitive_values: tuple[str, ...]) -> str:
    """Redact known secrets before HTML parsing/truncation can split them."""
    variants: set[str] = set()
    for secret in sensitive_values:
        if not isinstance(secret, str) or not secret:
            continue
        variants.add(secret)
        variants.add(escape(secret))
        variants.add(escape(secret, quote=False))
        variants.add(base64.b64encode(secret.encode()).decode())
        variants.add(base64.urlsafe_b64encode(secret.encode()).decode())
        variants.add(json.dumps(secret, ensure_ascii=True)[1:-1])
        variants.add("".join(f"\\u{ord(char):04x}" for char in secret))
        variants.add("".join(f"&#{ord(char)};" for char in secret))
        variants.add("".join(f"&#x{ord(char):x};" for char in secret))
        for encode in (quote, quote_plus):
            for safe in ("", "/"):
                encoded = encode(secret, safe=safe)
                variants.add(encoded)
                variants.add(encode(encoded, safe=safe))
                # Percent-encoding hex digits are case insensitive.
                variants.add(re.sub(r"%[0-9A-F]{2}", lambda m: m[0].lower(), encoded))
    for secret in sorted(variants, key=len, reverse=True):
        value = value.replace(secret, "[redacted]")
    return value


def _renewal_message(value: str, sensitive_values: tuple[str, ...]) -> str:
    """Bounded plain text with known-secret redaction, never safe for logging."""
    # Decode nested HTML entities before parsing, but redact at each stage so
    # a secret containing HTML syntax never gets split into printable fragments.
    for _ in range(5):
        value = _redact_message(value, sensitive_values)
        decoded = unescape(value)
        if decoded == value:
            break
        value = decoded
    value = _redact_message(value, sensitive_values)
    parser = _PlainText()
    parser.feed(value)
    parser.close()
    value = "".join(parser.parts)
    value = "".join(
        " " if char.isspace() else char
        for char in value
        if char.isspace() or not unicodedata.category(char).startswith("C")
    )
    value = _redact_message(value, sensitive_values)
    return " ".join(value.split())[:512]


def _renewal_reply(payload: Any, sensitive_values: tuple[str, ...]) -> RenewalReply:
    """Only this decoder interprets non-success status strings as prompts."""
    try:
        payload = _decode(payload)
        detail = _decode(payload.get("d")) if isinstance(payload, dict) else None
    except SolusProtocolError:
        raise SolusProtocolError("Malformed Solus renewal response") from None
    if not isinstance(detail, dict):
        raise SolusProtocolError("Malformed Solus renewal response") from None
    status = detail.get("status")
    if not _valid_acknowledgement(status):
        raise SolusProtocolError("Malformed Solus renewal response") from None
    message = detail.get("statusmessage", "")
    if not isinstance(message, str):
        raise SolusProtocolError("Malformed Solus renewal response") from None
    if status.lower() in {"success", "error"}:
        return RenewalReply(status.lower(), _renewal_message(message, sensitive_values))
    message = _renewal_message(message, (*sensitive_values, status))
    if not message or not message.replace("[redacted]", "").strip():
        raise SolusProtocolError("Malformed Solus renewal response") from None
    return RenewalReply("confirmation_required", message, status)


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
        except ValueError, TypeError:
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
    auth_response: bool = False,
) -> Any:
    """No automatic redirects, retries, raw exception messages or HTTP logging."""
    kwargs = {"allow_redirects": False, "timeout": _TIMEOUT}
    request_headers = {**_BROWSER_HEADERS, **(headers or {})}
    if payload is not None:
        kwargs["json"] = payload
        request_headers["Content-Type"] = "application/json; charset=utf-8"
    kwargs["headers"] = request_headers
    try:
        async with session.request(method, url, **kwargs) as response:
            if 300 <= response.status < 400:
                raise SolusSecurityError(
                    "Solus redirect rejected", status=response.status
                ) from None
            if auth_response and response.status in (401, 403):
                raise SolusAuthError(
                    "Solus authentication required",
                    reason="http",
                    status=response.status,
                ) from None
            if response.status != 200:
                raise SolusConnectionError(
                    "Solus server unavailable", reason="http", status=response.status
                ) from None
            if bootstrap:
                await response.read()
                return None
            return await response.json(content_type=None, encoding="utf-8-sig")
    except TimeoutError, aiohttp.ClientError:
        raise SolusConnectionError("Unable to contact Solus") from None
    except ValueError, TypeError, UnicodeError:
        raise SolusProtocolError("Malformed Solus response") from None


def _section(payload: Any, *, authentication: bool = False) -> dict:
    payload = _decode(payload)
    detail = _decode(payload.get("d")) if isinstance(payload, dict) else None
    if not isinstance(detail, dict):
        raise SolusProtocolError("Malformed Solus response") from None
    status = detail.get("status")
    if not isinstance(status, str) or status.lower() != "success":
        if authentication and detail.get("status") == "failure":
            raise SolusAuthError("Solus authentication rejected") from None
        raise SolusProtocolError(
            "Unsuccessful Solus response",
            reason="api_rejection"
            if isinstance(status, str) and status.lower() in {"failure", "error"}
            else "response_schema",
        ) from None
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


@_at_stage("routing")
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
    name = item.get("Name", "")
    if not isinstance(name, str):
        raise SolusProtocolError("Malformed Solus library") from None
    _origin(item.get("ServerUrl"))
    server, _ = await _routing(session, app_id)
    return Library(location_id, name.strip() or location_id, app_id, server)


def _locator_success(response: Any) -> None:
    """Locator status is separate from the authenticated catalogue protocol."""
    status = response.get("Status") if isinstance(response, dict) else None
    if not isinstance(status, str) or status.lower() != "ok":
        raise SolusProtocolError(
            "Unable to discover Solus libraries",
            reason="api_rejection"
            if isinstance(status, str) and status.lower() in {"failure", "error"}
            else "response_schema",
        ) from None


async def _locator(session: aiohttp.ClientSession, method: str, payload: dict) -> Any:
    response = _decode(
        await _request(
            session,
            "POST",
            f"https://locator.sol.us/v4/Locator.asmx/{method}?rnd={uuid4().hex}",
            payload={**payload, "GlobalAppID": GLOBAL_APP_ID},
        )
    )
    return (
        _decode(response.get("d", response)) if isinstance(response, dict) else response
    )


@_at_stage("manual_lookup")
async def async_lookup_location(
    session: aiohttp.ClientSession, location_id: str
) -> Library:
    """Resolve a manual LocationID through the locator and HTTPS routing repo."""
    response = await _locator(session, "QueryWithID", {"LocationID": location_id})
    _locator_success(response)
    return await _library(session, response)


@_at_stage("discovery")
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
    if isinstance(response, dict):
        _locator_success(response)
        items = _decode(response.get("Detail"))
    else:
        items = response
        if isinstance(items, list):
            # Direct rows carry their own statuses. Validate every row before
            # any repo routing; legacy Status/Detail rows need no row status.
            for item in items:
                _locator_success(item)
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
        self._session_id = _ZERO_SESSION_ID
        self._user_id = ""
        self._bootstrap_url = ""
        self._authenticated = False
        self._session_expired = False

    def _metadata(self) -> dict:
        return {
            "AppID": self._app_id,
            "TemplateID": self._app_id,
            "DeviceID": self._device_id,
            "AppVersion": APP_VERSION,
            "PackageName": PACKAGE_NAME,
            "PlatType": "Android",
            "PlatVer": "17",
            "PlatModel": "Home Assistant",
            "DName": "Android",
            "Locale": self._locale,
            "AppBuild": APP_BUILD,
        }

    def _catalogue_headers(self) -> dict:
        return {
            **_BROWSER_HEADERS,
            "x-session": self._token,
            "x-devicesession": self._session_id,
            "x-appversion": APP_VERSION,
            "x-appbuild": APP_BUILD,
            "x-apppackage": PACKAGE_NAME,
        }

    async def _catalogue_request(
        self,
        method: str,
        request: dict,
        *,
        authentication=False,
        user_id: str | None = None,
    ) -> Any:
        """Share envelopes and expiry handling, without choosing a decoder."""
        headers = self._catalogue_headers()
        if method == "LoginPreSession":
            envelope = {
                "AppID": self._app_id,
                "TemplateID": self._app_id,
                "DeviceID": self._device_id,
                "Locale": self._locale,
                "UserID": self._user_id,
                "Request": request,
            }
            headers = {
                **_BROWSER_HEADERS,
                "Origin": self._server,
                "Referer": self._bootstrap_url,
                "X-Requested-With": "XMLHttpRequest",
            }
        else:
            envelope = {
                "AppID": self._app_id,
                "TemplateID": self._app_id,
                "SessionID": self._session_id,
                "DeviceID": self._device_id,
                "Locale": self._locale,
                "UserID": self._user_id if user_id is None else user_id,
                "Request": request,
            }
        try:
            return await _request(
                self._session,
                "POST",
                f"{self._server}/v4/Cat.asmx/{method}?rnd={uuid4().hex}",
                payload=envelope,
                headers=headers,
                auth_response=True,
            )
        except SolusAuthError:
            self._authenticated = False
            self._token = ""
            self._session_expired = not authentication
            if not authentication:
                raise SolusSessionExpired("Solus session expired") from None
            raise

    async def _call(
        self,
        method: str,
        request: dict,
        *,
        authentication=False,
        user_id: str | None = None,
    ) -> dict:
        """Keep authentication and read calls strictly success-only."""
        return _section(
            await self._catalogue_request(
                method, request, authentication=authentication, user_id=user_id
            ),
            authentication=authentication,
        )

    async def async_login(self, card: str, pin: str) -> list[dict]:
        """Bootstrap cookies then establish an account session; never create IDs."""
        self._authenticated = False
        self._token = ""
        self._session_id = _ZERO_SESSION_ID
        self._user_id = card
        stage = "routing"
        try:
            self._server, auth_server = await _routing(self._session, self._app_id)
            stage = "bootstrap"
            bootstrap_metadata = {
                **self._metadata(),
                "font": "",
                "ServerRoot": self._server + "/",
            }
            query = urlencode(
                {
                    "s": base64.b64encode(
                        json.dumps(
                            bootstrap_metadata,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).decode("ascii")
                }
            )
            self._bootstrap_url = f"{auth_server}/v4/Auth.aspx?{query}"
            await _request(
                self._session,
                "GET",
                self._bootstrap_url,
                headers=self._catalogue_headers(),
                bootstrap=True,
            )
            stage = "login_presession"
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
            users = _list_detail(pre, nonempty=True)
            token = users[0].get("AuthToken")
            if (
                token is None
                or token == ""
                or (isinstance(token, str) and not token.strip())
            ):
                raise SolusProtocolError(
                    "Missing Solus authentication token", reason="missing_token"
                ) from None
            self._token = _text(token)
            stage = "login_checksession"
            check = await self._call(
                "LoginCheckSession",
                {
                    **self._metadata(),
                    "NetworkType": "WiFi",
                    "ScreenW": 384,
                    "ScreenAW": 384,
                    "ScreenH": 832,
                    "ScreenAH": 832,
                    "DPR": 1,
                    "AuthToken": self._token,
                },
                authentication=True,
                user_id="",
            )
            check_users = _decode(check.get("Detail"))
            if check_users is not None and check_users != []:
                users = _list_detail(check, nonempty=True)
            session = check.get("Detail2")
            if session is not None:
                session = _decode(session)
                if not isinstance(session, dict):
                    raise SolusProtocolError("Malformed Solus session") from None
                destination = session.get("ServerToUse")
                if destination is not None and destination != "":
                    if _origin(destination) != self._server:
                        raise SolusSecurityError(
                            "Untrusted Solus session destination"
                        ) from None
                session_id = session.get("SessionID")
                if session_id is not None and session_id != "":
                    self._session_id = _text(session_id)
            token = users[0].get("AuthToken")
            if token is not None and token != "":
                self._token = _text(token)
            self._authenticated = True
            self._session_expired = False
            return users
        except SolusError as error:
            error.at_stage(stage)
            self._token = ""
            self._session_id = _ZERO_SESSION_ID
            if isinstance(error, SolusAuthError):
                self._session_expired = False
            raise

    def _require_session(self) -> None:
        if not self._authenticated:
            if self._session_expired:
                raise SolusSessionExpired("Solus session expired") from None
            raise SolusAuthError("Solus authentication required") from None

    def _renewal_secrets(self) -> tuple[str, ...]:
        """Snapshot cookie values as well as client state before a write."""
        return (
            self._token,
            self._session_id,
            self._device_id,
            self._user_id,
            *(cookie.value for cookie in self._session.cookie_jar),
        )

    async def async_renew_loan(
        self,
        user_id: str,
        loan_id: str,
        source: str,
        *,
        acknowledged_codes: tuple[str, ...] = (),
        sensitive_values: tuple[str, ...] = (),
    ) -> RenewalReply:
        """Attempt exactly one explicit write; caller owns consent and recovery."""
        self._require_session()
        if any(not _valid_acknowledgement(code) for code in acknowledged_codes):
            raise SolusProtocolError("Invalid Solus renewal acknowledgement") from None
        secrets = (
            *sensitive_values,
            *self._renewal_secrets(),
            user_id,
            *acknowledged_codes,
        )
        response = await self._catalogue_request(
            "LoanRenew",
            {
                "LoanID": loan_id,
                "UserID": user_id,
                "Source": source,
                "PromptAcknowledged": ";".join(acknowledged_codes),
            },
            user_id=user_id,
        )
        return _renewal_reply(response, (*secrets, *self._renewal_secrets()))

    async def async_get_loans(self, user_id: str) -> list[dict]:
        """Fetch loans; malformed responses never imply an empty account."""
        self._require_session()
        section = await self._call("LoansGet", {"UserID": user_id}, user_id=user_id)
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
