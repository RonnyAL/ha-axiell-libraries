# Observed Solus API protocol (sanitized)

This is a **reverse-engineered observation**, not official documentation. It was validated by an account owner with their own library card and Axiell Libraries App `2026.42` (package `solus.AllAxiell`, build `2026420500`). It may be version- and server-dependent. No account credentials or tokens are included.

## Discovery

**Nearby libraries** (anonymous public request verified 2026-11-13 for the
sample coordinates below; not verified for all locations):

`POST https://locator.sol.us/v4/Locator.asmx/FindWithLocation?rnd=<random>`

```json
{"LocationLat": 69.0, "LocationLng": 19.0, "GlobalAppID": "5C72D777-E044-4B76-97A8-F240FA42E9BD"}
```

**Exact library lookup** (live verified):

`POST https://locator.sol.us/v4/Locator.asmx/QueryWithID?rnd=<random>`

```json
{"LocationID": "Malselv", "GlobalAppID": "5C72D777-E044-4B76-97A8-F240FA42E9BD"}
```

Anonymous public probes on 2026-11-13 returned a `d` object for `QueryWithID`
with `Status: "ok"`, `LocationID`, `AppID`, `ServerUrl`, and `APIUrl`, without
`Name`. `FindWithLocation` returned a `d` list whose rows each had `Status: "ok"`
and the same identity/routing fields, also without `Name`. These structural
observations explain why requiring uppercase `OK`, a display name, and a nearby
`Detail` wrapper blocked setup before credential entry. No credentials,
DeviceID, login, or account request was used; no raw response was saved.

Do not assume `APIUrl` is the host to use for subsequent login. The app resolves
routing with `GET https://repo.sol.us/id/<AppID>/2026.42` and uses the returned
`Server` (for the observed instance: `https://process-m-eu1.sol.us/`). The anonymous
probe also confirmed a valid HTTPS Solus `Server` from that repo route. Validate
network destinations before sending credentials; this public check does not
verify the integration's live login or account behavior.

After the parser correction, a separate anonymous check using the actual client
resolved `Malselv`: LocationID and fallback name were both `Malselv`, with
processing origin `https://process-m-eu1.sol.us`. The actual nearby client also
parsed/resolved one candidate for `(69.0, 19.0)`; that sample candidate was not
Malselv. This checks discovery only, not nearby results for the owner's HA
coordinates. No credentials, DeviceID, login or account requests were used.

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

4. `POST <Server>/v4/Cat.asmx/LoginCheckSession?rnd=<random>` using standard client request envelope: `AppID, TemplateID, SessionID, DeviceID, Locale, UserID, Request`. `Request` is the app's metadata object containing `AuthToken`, package/version/device descriptors. Set request headers `x-session: <auth-token>`, `x-devicesession: <session-id>` (initially the zero UUID), `x-appversion`, `x-appbuild`, `x-apppackage`. `Detail2.SessionID` and `Detail2.ServerToUse` may update the connection. Return `Detail` may have a new AuthToken; update in-memory session only. Never persist AuthToken unless its lifetime and need are proven. Validate redirect host before using it.
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
(or JSON serialized), with string `Status` equal to `ok` case-insensitively,
nonempty string `LocationID` and `AppID`, and a validated `ServerUrl`. An absent
or whitespace-only string `Name` falls back to `LocationID`; other Name types
are malformed. Nearby accepts the observed direct list, validating every row's
success status before resolving any repo route. The previously tested
`Status`/`Detail` wrapper remains supported; its rows need no separate status.
Empty direct lists yield no candidates, keeping manual entry available.
Serialized envelopes remain a defensive allowance; the legacy wrapper is
covered offline. Neither is a new live observation. Malformed responses fail explicitly.
Discovery and authenticated success statuses are case-insensitive; their
success words remain distinct (`ok` and `success`, respectively). `APIUrl` is
never used for credentials.
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

The supplied owner-run Python PoC succeeded on 2026-11-13 through bootstrap,
pre-session, check-session, loans and catalogue. The processing host stayed
`process-m-eu1.sol.us`; a live server switch was not observed. The corrected HA
request contract is now covered at the offline HTTP boundary:

- Common headers: `User-Agent: Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36`
  and `Accept: application/json, text/javascript, */*; q=0.01`. JSON POSTs add
  `Content-Type: application/json; charset=utf-8`.
- Shared metadata: selected `AppID` and `TemplateID`, persistent `DeviceID`,
  `AppVersion: 2026.42`, `AppBuild: 2026420500`, `PackageName: solus.AllAxiell`,
  `PlatType: Android`, `PlatVer: 17`, `DName: Android`, `Locale: nb-NO`.
  HA uses `PlatModel: Home Assistant`; this generic label differs from the
  owner's physical-device label and remains unverified live.
- Bootstrap adds `font: ""` and `ServerRoot` with trailing slash. Its `s` query
  contains normal Base64 of compact UTF-8 JSON with non-ASCII text preserved,
  then normal URL query escaping. Initial session ID is
  `00000000-0000-0000-0000-000000000000` in bootstrap/catalogue headers; initial
  `x-session` is empty. Each login resets that session ID while retaining DeviceID.
- Pre-session sends the JSON shown above, without `SessionID` or `VerifyToken`.
  Its headers include the processing `Origin`, the **full bootstrap URL** as
  `Referer`, and `X-Requested-With: XMLHttpRequest`.
- Check-session uses the standard envelope with outer `UserID: ""`, the zero
  session UUID initially, and `Request` containing shared metadata plus
  `NetworkType: WiFi`, `ScreenW: 384`, `ScreenAW: 384`, `ScreenH: 832`,
  `ScreenAH: 832`, `DPR: 1` and the pre-session `AuthToken`. The bootstrap-only
  `font`/`ServerRoot` fields are absent. Token and session are sent in the
  catalogue headers described above, together with version/build/package.
- Absent, null or empty check-session user details retain the pre-session
  users/token. Supplied new details must be valid. Optional returned session
  ID/token update only memory. Success is case-insensitive and JSON accepts
  a UTF-8 BOM. Loans use the selected user in both envelope and inner request.

This corrects the earlier empty session ID, card-valued check-session outer
UserID, reused bootstrap metadata, omitted browser headers/full Referer,
different platform values and required fresh check-session users. Which mismatch
caused the owner's failure remains unknown until the corrected integration is
run locally. Remaining deliberate differences include the generic model label,
strict same-processing-origin routing, blocked redirects and response validation
that rejects malformed supplied fields rather than accepting them permissively.
Cookie absence is nonfatal; real isolated aiohttp cookie transport is tested
locally both with and without a synthetic server-issued cookie. That establishes
client behavior, not the upstream server's cookie requirements.

`async_login(card, pin)` returns the decoded nonempty user-detail list;
`async_get_loans(user_id)` returns a decoded list, with `[]` representing an
explicit successful empty account only. `async_get_record(record_id, source)`
returns an object or `None` for an explicit empty record. Catalogue transport
errors propagate so the coordinator can handle individual enrichment failures.
All calls use a 20-second total timeout, no transport retries, and no automatic
login retries. HTTP 401/403 from pre-session/check-session raises `SolusAuthError`;
unauthenticated locator/routing/bootstrap HTTP rejection is a connection error,
not evidence of a bad card/PIN. During an authenticated data request, HTTP
401/403 clears the token and raises `SolusSessionExpired`, allowing the coordinator to attempt one recovery login.
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
failures instead of requesting a new PIN. Pre-session/check-session HTTP
401/403 remains an explicit authentication rejection. Exact upstream negative status codes still require a
local probe by the owner with credentials outside Git.

## Coordinator refresh and catalogue policy

Each config entry owns an `AxiellCoordinator` and its client/cache. Integration
setup must create the client using the stored DeviceID and call
`async_config_entry_first_refresh()`; the coordinator's `_async_setup` performs
initial login, so setup must not log in separately. Subsequent manual and
six-hour scheduled refreshes reuse that client and its in-memory session.
Neither refresh nor authentication recovery constructs a new device identity.

Only explicit `SolusSessionExpired` triggers one recovery login and one complete
refresh retry. Invalid credentials request reauthentication immediately. Metadata
requests are settled before recovery starts, and credential rejection takes
precedence if parallel requests report both rejection and expiry. A second
expiry requests reauthentication; transport/protocol failures produce a static
`UpdateFailed`. Failed loan updates retain the previous snapshot and mark the
coordinator unavailable; an explicit successful `[]` replaces it with zero loans.

At the `LoansGet` boundary, every row must contain nonempty string `loanID` and
`title` values. Loan IDs must be unique after trimming whitespace, using the
same normalization as the loan model. Missing, malformed or duplicate identities
reject the entire response with a static protocol error, preserving the previous
snapshot and making entities unavailable instead of publishing blank or ambiguous
to-do items. Missing or malformed `dueObject` and optional catalogue fields remain
permissive. This is a defensive integration policy verified with synthetic
responses, not a newly observed upstream guarantee.

Catalogue records are cached by `(record_id, source)` for 24 hours, with an
entry-local least-recently-used limit of 256 records and at most four concurrent
`RecordGet` calls. Distinct issued copies share metadata requests while keeping
their own loan IDs and due dates. Expired cache entries are refreshed on demand;
failed, empty, or mismatched metadata responses leave available stale metadata
and the loan intact, without renewing the stale cache timestamp. Records without
a usable record ID/source skip enrichment. Optional returned `Source`, when
present, must match the requested source, and `RecordID` must always match.

Catalogue `Format` and string `MainMetadata` values reach the enriched loan.
Publisher/year values remain in an immutable mapping under the provider's keys
(`Utgiver` and `Utgitt` in the synthetic Norwegian fixture); no universal localized
publisher/year key scheme is assumed. These cache, concurrency, retry, and
optional source-validation policies are implementation choices verified offline,
not new claims about upstream API behavior. No live account test was performed.

When an authenticated HTTP 401/403 invalidates the client session, later queued
data requests retain `SolusSessionExpired` without sending another HTTP request.
That recoverable state survives a transport/protocol failure during recovery
login, allowing a later poll to try its single recovery attempt. Successful
login clears expiry; explicit credential rejection clears it to ordinary
unauthenticated state and requests reauthentication. These distinctions prevent
queued catalogue requests or temporary recovery outages from masquerading as
invalid credentials.

## Implementation validation boundary

The implemented integration uses the approved native HA, multiple-entry,
read-only design. Offline tests now run against HA 2026.11.0 and 2026.11.1
with Python 3.14.7 locally and 3.14.10 in CI, including real HA flow, entity,
reload and session lifecycle APIs. They do not establish compatibility beyond
those versions, browser rendering, a separate HA process restart, upstream
cookie issuance, or a successful live integration login. The owner separately
reports Marketplace installation/update, but HA account setup still fails. Earlier
owner-verified endpoint observations must not be conflated with those checks.

Anonymous public discovery and repo routing were checked on 2026-11-13 as
described above. Before relying on live account operation, the owner must check
acceptance of the generic `Home Assistant` model label, optional repo `AuthServer`,
JSON auth rejection/expiry codes, and the strict single-label `*.sol.us`
same-processing-origin routing policy. No credentialed integration requests
were made during implementation. Use the [README's HA UI smoke test](../README.md#optional-owner-run-live-smoke-test)
without exposing credentials or recording HTTP bodies. The
[validation ledger](validation.md) records task evidence and remaining review.

## Safe setup references

HA error descriptions interpolate only a fixed `stage/reason[/HTTP-status]`
reference. Stages are `discovery`, `manual_lookup`, `routing`, `bootstrap`,
`login_presession`, `login_checksession`, with `provider` for generic existing
errors. Reasons are `transport`, `http`, `api_rejection`, `response_schema`,
`missing_token` and `security`. Status is optional, an integer from 100 to 599;
strings and booleans are excluded. The boundary revalidates these allowlists.
Neither exception text nor provider status messages, bodies, URLs, headers,
cookies, credentials, tokens or DeviceID are interpolated.

Literal `failure`/`error` API statuses get an API-rejection reference, while
missing, malformed or unrecognized statuses remain schema failures. Only the
existing exact authentication `failure` and auth-stage HTTP 401/403 paths
request card/PIN correction. An unverified API error does not imply bad PIN or
JSON session expiry. Errors retain existing catchable SolusError subclasses and
static production messages; arbitrary programming exceptions are not caught.

For incomplete nearby results and authoritative Norwegian library names without
a verified Solus join key, see [library discovery evidence](library-discovery.md).
