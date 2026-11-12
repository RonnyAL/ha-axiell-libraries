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
