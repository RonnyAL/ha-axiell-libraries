# Observed Solus API protocol (sanitized)

This is a **reverse-engineered observation**, not official documentation. It was validated by an account owner with their own library card and Axiell Libraries App `2026.42` (package `solus.AllAxiell`, build `2026420500`). It may be version- and server-dependent. No account credentials or tokens are included.

## Discovery

**Nearby libraries** (observed in APK; not yet live-validated for all locations):

`POST https://locator.sol.us/v4/Locator.asmx/FindWithLocation?rnd=<random>`

```json
{"LocationLat": 69.0, "LocationLng": 19.0, "GlobalAppID": "5C72D777-E044-4B76-97A8-F240FA42E9BD"}
```

**Exact library lookup** (live verified):

`POST https://locator.sol.us/v4/Locator.asmx/QueryWithID?rnd=<random>`

```json
{"LocationID": "Malselv", "GlobalAppID": "5C72D777-E044-4B76-97A8-F240FA42E9BD"}
```

Result contains `Status: OK`, `AppID`, `ServerUrl`, and `APIUrl` for the selected library. Do not assume `APIUrl` is the host to use for the subsequent login. In the tested version, the app resolves routing with `GET https://repo.sol.us/id/<AppID>/2026.42` and uses the returned `Server` (for the observed instance: `https://process-m-eu1.sol.us/`). Validate network destinations before sending credentials.

## Working authentication path

1. Generate **one** 16-character lowercase hexadecimal `DeviceID` and persist it with the Home Assistant config entry on successful setup. Do **not** create one per login.
2. Open `GET <AuthServer>/v4/Auth.aspx?s=<base64url-or-normal-base64-of-JSON>` with the same `aiohttp` cookie session. Payload in `s` includes `AppID`, `TemplateID`, `DeviceID`, `AppVersion`, `PackageName`, `PlatType`, `PlatVer`, `PlatModel`, `DName`, `Locale`, `font`, `AppBuild` and `ServerRoot`. Exact field requirements should be covered by tests against the observed protocol and changed only with evidence. The successful reference Python probe used `base64.b64encode(json.dumps(params).encode()).decode()` encoded via normal URL query escaping.
3. `POST <Server>/v4/Cat.asmx/LoginPreSession?rnd=<random>` with JSON shown below. It was **observed live** and worked from Python; no reCAPTCHA token or device session field was needed. Keep cookies, set same-origin `Origin`/`Referer` and `X-Requested-With: XMLHttpRequest` in this browser-stage request as appropriate. Do not log password, headers or returned body.

```json
{
  "AppID": "<selected-app-id>",
  "TemplateID": "<selected-app-id>",
  "DeviceID": "<persisted-device-id>",
  "Locale": "nb-NO",
  "UserID": "<card>",
  "Request": {
    "UserID": "<card>",
    "Password": "<PIN>",
    "StoreCredentials": false,
    "Name": ""
  }
}
```

Response has outer `d` envelope; `d.status` is `success`, `d.Detail[0].AuthToken` is a **secret**.

4. `POST <Server>/v4/Cat.asmx/LoginCheckSession?rnd=<random>` using standard client request envelope: `AppID, TemplateID, SessionID, DeviceID, Locale, UserID, Request`. `Request` is the app's metadata object containing `AuthToken`, package/version/device descriptors. Set request headers `x-session: <auth-token>`, `x-devicesession: <session-id>` (initially blank/zero), `x-appversion`, `x-appbuild`, `x-apppackage`. `Detail2.SessionID` and `Detail2.ServerToUse` may update the connection. Return `Detail` may have a new AuthToken; update in-memory session only. Never persist AuthToken unless its lifetime and need are proven. Validate redirect host before using it.
5. `POST <Server>/v4/Cat.asmx/LoansGet?rnd=<random>` with envelope `UserID: <card>` and `Request: {"UserID": "<card>"}`. Successful JSON `d.Detail` is an array of loans.
6. For each distinct record needing metadata, `POST <Server>/v4/Cat.asmx/RecordGet?rnd=<random>` with same envelope and request `{"RecordID": "<recordID>", "Source": "ILS", "SearchLimit": ""}`. `d.Detail` contains the catalog record (may sometimes be serialized JSON string or single-item list; defensive decode if required).

**Do NOT use** `Cat.asmx/Login`: tests returned `Failure in reCaptcha` with correct credentials. The browser's successful login used `LoginPreSession` instead.

## Useful loan fields

- `loanID` for unique loan identity; `recordID` for catalog metadata; `title`.
- `dueObject`: `/Date(1795046400000)/` => `2026-11-19` date; prefer over `dueDisplay` (which contains `19.11.2026<br />Library`).
- `canRenew` and `Overdue` (booleans), `renewalCost`, `RenewalsRemaining` (`-1` = unknown), `Source` (e.g., `ILS`).
- `author` may be empty; `subtitle` sometimes contains author. Prefer `RecordGet.Author`.
- `imageUrl` fields in `LoansGet` may be empty, as may `ISBN`.

### Date parser semantics

The integration reads `dueObject` only and returns an unknown date for missing,
malformed, or out-of-range values; it never falls back to `dueDisplay` HTML.
Milliseconds in `/Date(milliseconds)/` represent an instant since the Unix epoch
in UTC, and the model exposes that instant's UTC calendar date, independent of
the Home Assistant host timezone. Negative milliseconds are supported.

An optional `+HHMM` or `-HHMM` suffix is accepted only with hours `00`–`23` and
minutes `00`–`59`. The suffix is validated but not applied to the UTC instant.
For example, `/Date(1795046400000-1200)/` still yields `2026-11-19`.
Suffix handling is a defensive parser choice, not a live-verified server variant.

Loan authors use nonempty `author`, then `subtitle`, as a fallback. Catalogue
enrichment replaces that fallback with a nonempty `RecordGet.Author`, while
missing catalogue fields leave available loan metadata intact. Direct `ImageUrl`
is preferred, with `ImageUrlLarge` as fallback. Empty or malformed covers,
non-HTTPS URLs, embedded credentials, and `ItemImage.aspx` placeholders are
discarded. `MainMetadata` is retained as optional string key/value metadata.

## Useful RecordGet fields

- `RecordID`, `Title`, `Author`, `Description`, `ISBN`, `ISBNList`, `Format`, `ImageUrl`, `ImageUrlLarge`, `MainMetadata` (Key/Value array, including publisher and year).
- The verified URL in `ImageUrl` from an external cover provider worked directly in the browser. There can be cover links from `media.aja.bs.no` or `api.axiell.com`. Validate `https://` and treat as optional; do not proxy arbitrary URLs with credentials.
- `https://m.solus.co.uk/catalogue/ItemImage.aspx` returned an identical ~3KB placeholder for all books in one test. It is not the preferred cover source.

## Authentication/privacy guardrails

- No `Authorization`, cookie, `AuthToken`, card or PIN in logs, tracebacks, HA attributes, user-facing diagnostics, Git or automated test fixtures.
- Use HA's managed async HTTP session with limited timeouts and no cross-account session sharing.
- `LoginCheckSession` response may alter routing and session ID. Handle it consistently, not by generating a new DeviceID.
- API schema is not a stable contractual guarantee. Unit tests need to mock network responses.

See `tests/fixtures/` for *synthetic, non-user* JSON samples.

## Client implementation contract and remaining assumptions

`solus.py` exposes `async_lookup_location(session, location_id) -> Library` and
`async_find_nearby(session, latitude, longitude) -> list[Library]`. `Library` has
`location_id`, `name`, `app_id`, and a resolved `server_url` processing origin.
The caller owns an isolated HA-managed `aiohttp.ClientSession` and its cookie
jar for each flow/account. The transport reuses that session for Auth.aspx and
API requests, does not modify its default headers, and does not close it.
`SolusClient(session, app_id, server_url, device_id, locale="nb-NO")` never
creates a DeviceID. Authentication state remains on the client in memory.

The lookup implementation accepts a locator object, optionally wrapped in `d`
(or JSON serialized), with `Status: OK`, `LocationID`, `Name`, `AppID`, and
`ServerUrl`. Nearby uses the same fields in a `Detail` list. These precise
locator field shapes and nearby behavior need local live validation: the
checked-in observations do not include a complete locator response fixture.
Malformed responses fail explicitly. `APIUrl` is never used for credentials.
Both discovery and each login resolve `GET https://repo.sol.us/id/<AppID>/2026.42`
and use its `Server`. An optional repo `AuthServer` can specify the bootstrap
origin; otherwise `Server` is used. That optional field is a defensive assumption,
not a live-verified repo variant.

All dynamic origins must use HTTPS with a single-label subdomain of `sol.us`,
a root path, no user information, explicit port, query, fragment, control
characters, or backslash. HTTP redirects are rejected at every stage. A
`LoginCheckSession` `ServerToUse` must match the processing origin resolved from
the trusted HTTPS repo before login; moving tokens to another hostname requires
additional verified routing evidence. This deliberately fails safely if a
provider introduces a previously unseen routing arrangement.

Bootstrap metadata retains the observed app identity: version `2026.42`, build
`2026420500`, package `solus.AllAxiell`. `AppID` and `TemplateID` use the selected
AppID; `DeviceID` and locale come from the caller; `ServerRoot` is the processing
origin with trailing slash. Device descriptors are deterministic integration
values: `PlatType`, `PlatModel`, and `DName` are `Home Assistant`, `PlatVer` is
`1`, and `font` is `100`. Their exact acceptance and the reuse of bootstrap
metadata plus `AuthToken` for `LoginCheckSession.Request` require a local live
probe; the sanitized protocol lists these keys but not their verified values.

`async_login(card, pin)` returns the decoded nonempty user-detail list;
`async_get_loans(user_id)` returns a decoded list, with `[]` representing an
explicit successful empty account only. `async_get_record(record_id, source)`
returns an object or `None` for an explicit empty record. Catalogue transport
errors propagate so the coordinator can handle individual enrichment failures.
All calls use a 20-second total timeout, no transport retries, and no automatic
login retries. HTTP 401/403 during login raises `SolusAuthError`; during an
authenticated data request it clears the token and raises its subclass
`SolusSessionExpired`, allowing the coordinator to attempt one recovery login.
Actual expiry codes inside JSON `d.status` are unverified: unknown unsuccessful
statuses raise `SolusProtocolError` and never trigger speculative login loops.
All public errors use static messages and suppress sensitive exception context.

The offline tests mock the HTTP request boundary and verify bootstrap ordering,
payloads, safe routing, and separate client tokens. They do not verify live
Solus behavior or actual server cookie issuance; a local owner-run probe with
credentials outside Git remains necessary.

## Configuration identity and validation

The config flow normalizes card numbers by removing all Unicode whitespace,
while preserving case and leading zeros. Its stable unique ID is the SHA-256
hex digest of UTF-8 `AppID:normalized_card`; a duplicate is rejected before
login. A new user flow calls `secrets.token_hex(8)` once and retains that value
through selection, manual lookup, and credential retries. Successful entries
store `location_id`, `library_name`, `app_id`, `server_url`, `card`, `pin`, and
`device_id`. PIN-only reauthentication and reconfiguration update the PIN while
keeping every other identity field and the unique ID unchanged.

Discovery and each login validation use separate HA-managed sessions with
isolated cookie jars. Validation sessions are detached in `finally` blocks,
leaving the HA connector open; validation tokens and cookies are discarded.
Nearby selection filters only returned local candidates. Manual exact LocationID
lookup remains available on empty results, missing coordinates or provider
failure. Provider errors produce static UI messages without logging exception
text or account values. The PIN resides in HA config entry storage, which is
not a dedicated secrets vault.

For login JSON, only explicit `d.status: failure` is treated as credential
rejection; this is the synthetic negative fixture assumption, not a verified
upstream auth error code. Missing, malformed or unknown statuses raise
`SolusProtocolError`, including during authentication, and are shown as provider
failures instead of requesting a new PIN. HTTP 401/403 remains an explicit
authentication rejection. Exact upstream negative status codes still require a
local probe by the owner with credentials outside Git.
