# Axiell Libraries — v1 Design (2026-11-13)

## Intent

Bring loans and due dates from Solus-powered libraries into **Home Assistant** as a fully native, read-only custom integration. The immediate working example is Målselv bibliotek via Axiell Libraries App, but the implementation should use discovery and not hardcode this library.

The owner has verified end-to-end API access from Python: `LoginPreSession` succeeds, `LoginCheckSession` establishes a session, `LoansGet` returns six actual loans, and `RecordGet` returns ISBN, descriptions and working cover URLs. Direct `Cat.asmx/Login` returned `Failure in reCaptcha`, even with a correct PIN. `ItemImage.aspx` returned the same generic JPEG for all items. The **working method and field mapping** are recorded in `docs/protocol.md`.

## Goals

1. Install as an ordinary Home Assistant `custom_components/axiell_libraries` integration with a UI config flow (no MQTT sidecar, Docker service or YAML credentials).
2. **One config entry per library-card/account combination.** Additional accounts are configured as additional integration entries, not as an accounts list inside one entry. Multiple entries coexist without sharing tokens, sessions, device IDs or coordinator state.
3. **One persistent, random DeviceID per config entry:** generate a lowercase 16-hex-char string via `secrets.token_hex(8)` only once. Maintain it through retries, restart, reauth and reconfigure. Avoid registering numerous new devices upstream. Repeated config-flow submissions for a candidate account must reuse the candidate device ID; duplicates must abort before login.
4. Config flow: discover nearby libraries via `FindWithLocation` using the HA location if available; searchable selection from returned results; **manual LocationID fallback** validated by `QueryWithID`; second step collects card number + PIN and validates them. If discovery fails, manual entry must still work. A global server-side text search/typeahead is not proven available; do not invent one.
5. Fetch and display active loans, the next due date, overdue count and a read-only todo list of individual loan titles and due dates. Multi-loan due dates are shown independently. Future calendar and write actions are explicitly outside the v1 acceptance gate.
6. Enrich loans with `RecordGet` metadata (ISBN, author, book description, format, publisher, year) and direct cover URLs. No placeholder images if cover missing. Cache by `recordID` and source; refresh loans more often than catalogue metadata.
7. Robust error management: `ConfigEntryAuthFailed` for invalid/expired credentials, reauth flow that preserves DeviceID, `UpdateFailed` on transport/API failure; preserve previous values or mark unavailable rather than pretending there are zero loans.
8. Respect privacy: never log or publish the card, PIN, AuthToken, HTTP body, or private account data. Store credentials only in HA config entry data; explain that HA configuration storage is not a dedicated secret vault. No .apk or personal captures in Git.

## Explicit non-goals, v1

- Renew, return, reserve books or change account details from HA.
- A separate MQTT bridge/service.
- A custom Lovelace frontend card. HA-standard sensors, todo list and images are sufficient.
- Scraping the old Arena portal; the proven flow is Solus.
- Claiming official API support or claiming global live typeahead without proof.
- Pulling in copyrighted APK/decompiled JS, HARs, or any logged-in responses into the repository.

## Architecture and interfaces

```text
ConfigFlow (library choice -> credentials, unique ID, persist DeviceID)
    -> SolusClient (async aiohttp; discovery; auth; LoansGet; RecordGet)
    -> DataUpdateCoordinator per config entry (6-hour loan poll, longer catalog TTL)
    -> SensorEntity (active count, next due [date], overdue count)
    -> TodoListEntity (read-only list of loans, due date)
```

The client will distinguish *transport/auth response* from *domain model*. The protocol and models live in small focused modules; Home Assistant entities should only consume typed coordinator state, not know about HTTP payload fields. Use current HA developer guidelines for selectors and config-flow support.

### Date handling

`LoansGet.dueObject` is a .NET `/Date(<milliseconds since Unix epoch>)/` string. Observed `/Date(1795046400000)/` -> `2026-11-19` (UTC midnight). Map to a date, **not** a local datetime. `dueDisplay` may contain HTML and library location and is not the data source for date.

### Identity and lifecycle

`unique_id = sha256(f"{app_id}:{normalized_card}".encode()).hexdigest()` (or equivalent deterministic hash), not random DeviceID. `DeviceID` is a separate per-entry random persistent server-facing identity and must not change when password changes. Each entry must own its own client, auth token, cookies, coordinator, and catalogue cache.

### Failure behavior

A failure to enrich one record must **not** hide the rest of the books. No cover is acceptable and should be represented as missing. No false "empty loans" on timeout, unexpected parsing, or auth failure. Avoid repeated failed login attempts that might lock an account.

## Considered approaches

- **Native config entries + sensors/todo (selected):** idiomatic HA UX and multi-entry lifecycle; no extra infrastructure.
- MQTT publishing from a polling Docker service (rejected): additional moving pieces and awkward configuration.
- One integration entry managing a list of multiple card numbers (rejected): makes credentials, DeviceID, reauth and entity identity unnecessarily complicated.

## Acceptance

- Add an account at library A and another at library B; both persist separately and expose separate entities.
- Same DeviceID across two refreshes, across HA restart and after reauthentication, but different between two config entries.
- Duplicate library+card entry blocked before login and without issuing an extra device registration.
- Tested working sequence mocks: locator -> Auth.aspx bootstrap -> LoginPreSession -> LoginCheckSession -> LoansGet -> RecordGet.
- Dates parsed correctly, including invalid/missing dates handled safely, and todo entries use `loanID` to avoid same-title collisions.
- Cover URL from `RecordGet`, not `ItemImage.aspx`; no cover fallback if missing.
- Offline tests cover failures and secret-redaction. Private repo remains free of credentials and binaries.

## Provenance

Owner's controlled test of their own account, November 2026; anonymized protocol in this repository. Official background: <https://developers.home-assistant.io/docs/config_entries_config_flow_handler/> and <https://github.com/obra/superpowers>.
