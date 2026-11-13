# Axiell Libraries v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested, read-only Home Assistant integration for Solus/Axiell library loans, with one stable DeviceID and one HA config entry per library card.

**Architecture:** A small async Solus API client handles discovery/auth/loans/catalogue. A `DataUpdateCoordinator` per HA config entry supplies typed loan data to read-only sensor/todo platforms; UI config flow supports nearby discovery and exact manual lookup, then credentials and reauth.

**Tech Stack:** Python, Home Assistant custom integration API, `aiohttp`, `pytest`, `pytest-homeassistant-custom-component`, Ruff. Follow current HA version/style available to development environment; do not claim an API signature without checking it.

**Spec:** `docs/superpowers/specs/2026-11-13-axiell-libraries-design.md` and `docs/protocol.md`.

## Global Constraints

- Native HA custom component under `custom_components/axiell_libraries/`. No MQTT, no external Docker service.
- One config entry per AppID+normalized-card, unique ID deterministic; DeviceID generated `secrets.token_hex(8)` exactly once per flow and persisted on success.
- Fully read-only v1; no renewing/returning/holds mutations.
- API verified sequence is `LoginPreSession` -> `LoginCheckSession` -> `LoansGet` -> optional `RecordGet`; never call direct `Login`.
- Date from `dueObject`, not HTML; no placeholder image fallback; metadata best effort and cached.
- All tests offline with synthetic fixtures; no credentials, reverse-engineered APK or raw personal responses in Git.
- Preserve DeviceID on restart, refresh and reauth; never create extra upstream device for repeated polling.

## Review Focus

1. A duplicated library+card setup must abort *before* attempting `LoginPreSession` (Task 3 test).
2. A coordinator fetch that times out after successful earlier fetch must not publish 0 books (Task 4 test).
3. A missing/malformed `dueObject` must not crash an entire account or invent a due date (Task 1 test).
4. A missing `RecordGet` response or invalid cover URL must keep the loan visible without exposing credentials (Task 4 test).
5. Credential or network failure must not loop retries and create multiple upstream device records, including when reauth happens (Task 3/4 tests).

---

## File map

- `custom_components/axiell_libraries/__init__.py` — config-entry setup/unload, coordinator ownership.
- `custom_components/axiell_libraries/manifest.json` — integration metadata, `config_flow: true`.
- `custom_components/axiell_libraries/const.py` — identifiers, app version/build, polling interval, keys.
- `custom_components/axiell_libraries/models.py` — typed models + pure date / metadata mapping helpers.
- `custom_components/axiell_libraries/solus.py` — async HTTPS transport, locator, auth and catalog API.
- `custom_components/axiell_libraries/config_flow.py` — setup, duplicate detection, reauth/reconfigure.
- `custom_components/axiell_libraries/coordinator.py` — polling, typed snapshot, cache, errors.
- `custom_components/axiell_libraries/sensor.py` — active loans, earliest due date, overdue count.
- `custom_components/axiell_libraries/todo.py` — one read-only todo entity per entry, loans with due dates.
- `custom_components/axiell_libraries/strings.json`, `translations/en.json`, `translations/nb.json` — UI labels and errors.
- `tests/test_models.py`, `tests/test_solus.py`, `tests/test_config_flow.py`, `tests/test_coordinator.py`, `tests/test_entities.py` — offline tests.

## Task 1: Model and date parser

**Files:** Create `custom_components/axiell_libraries/models.py`, `const.py`; `tests/test_models.py`.

**Interfaces:** `parse_due_date(raw: str | None) -> date | None`, `Loan.from_api(payload: Mapping[str,Any]) -> Loan`, `CatalogueRecord.from_api(payload) -> CatalogueRecord`. Define dataclasses with fields `loan_id`, `record_id`, `title`, `due_date`, `can_renew`, `overdue`, `source`, `author`, `image_url`, `isbn`, `description`, and optional catalogue fields (keep models small). Choose date parser semantics explicitly for optional `.NET` zone suffixes.

- [x] **Step 1:** Write failing offline tests: `test_due_date_dotnet_utc()` asserts `/Date(1795046400000)/` == `date(2026,11,19)`; `test_missing_date_returns_none()`, `test_bad_date_returns_none()`, `test_renewals_minus_one_is_unknown()`, and `test_loan_ids_distinguish_same_title()`.
- [x] **Step 2:** `pytest -q tests/test_models.py` — verify RED.
- [x] **Step 3:** Implement pure dataclasses/parsers; ensure `dueDisplay` is not parsed.
- [x] **Step 4:** `pytest -q tests/test_models.py` — verify GREEN; `ruff check` on changed paths.
- [x] **Step 5:** Commit `feat: add typed loan models and due date parser`.

## Task 2: Asynchronous Solus client

**Files:** Create `custom_components/axiell_libraries/solus.py`, manifest basics; `tests/test_solus.py`.

**Interfaces:** `SolusClient(session: aiohttp.ClientSession, app_id: str, server_url: str, device_id: str, locale: str, ...)`, methods `async_login(card: str,pin: str) -> list[dict]`, `async_get_loans(user_id: str) -> list[dict]`, `async_get_record(record_id: str, source: str) -> dict | None`; separate standalone locator methods `async_find_nearby(latitude,longitude)` and `async_lookup_location(location_id)` (either client methods or module functions; maintain consistent signatures).

- [x] **Step 1:** Write failing mocked HTTP tests for `QueryWithID`, `FindWithLocation`, `Auth.aspx` cookie bootstrap, exact `LoginPreSession` request, `LoginCheckSession` envelope/session updates, `LoansGet`, `RecordGet`, timeout, invalid auth, untrusted redirect, and secret-free errors. Mock `aiohttp` at request boundary (no live accounts).
- [x] **Step 2:** `pytest -q tests/test_solus.py` — RED.
- [x] **Step 3:** Implement minimum async transport and tested flow from `docs/protocol.md`, parse `d.status` and `d.Detail`, maintain cookies/token in memory. Use timeouts and HTTPS destination validation. Do not perform direct `Login` or persist tokens to disk.
- [x] **Step 4:** `pytest -q tests/test_solus.py` — GREEN; Ruff.
- [x] **Step 5:** Commit `feat: implement async Solus API client`.

## Task 3: HA config flow and stable device identity

**Files:** Create `custom_components/axiell_libraries/config_flow.py`, strings/translations; `tests/test_config_flow.py`.

**Interfaces:** `async_step_user` library selection step; `async_step_library_manual` fallback; `async_step_credentials` validation; `async_step_reauth`/`async_step_reauth_confirm` preserving DeviceID; create stable unique ID from AppID+normalized library card. Validate unique ID before API login. Persist `DeviceID` generated **once per flow** even if user changes fields/retries; do not regenerate during reauth or entry reload.

- [x] **Step 1:** Write config-flow tests for 2 entries with different card numbers, duplicates blocked without auth request, one DeviceID reused over validation retries, 16-hex ID saved after success, matching DeviceID after reauth/reconfigure, nearby discovery failures falling back to exact `LocationID`, and no secrets in logged errors.
- [x] **Step 2:** `pytest -q tests/test_config_flow.py` — RED.
- [x] **Step 3:** Implement HA config flow using current HA selector APIs. Search among returned local choices; manual `LocationID` when none or not found; no invented global typeahead. Validate credentials once per submission. Keep device registration minimal.
- [x] **Step 4:** `pytest -q tests/test_config_flow.py` — GREEN; Ruff.
- [x] **Step 5:** Commit `feat: add multi-entry library config flow`.

## Task 4: Per-entry coordinator and enrichment

**Files:** Create `custom_components/axiell_libraries/coordinator.py`, enhance `models.py`; `tests/test_coordinator.py`.

**Interfaces:** `AxiellCoordinator(hass, entry, client)` subclasses `DataUpdateCoordinator[LibrarySnapshot]`; `LibrarySnapshot(loans: tuple[Loan,...], fetched_at: datetime)`. Catalogue record cache keyed on `(record_id,source)` within entry, TTL 24h–7d (choose and test one), bounded parallel enrichment, no cross-card shared secrets. Loan refresh every ~6h; support HA manual refresh without device ID changes.

- [x] **Step 1:** Write tests for two consecutive refreshes with same device ID, refreshed due date after extension, stale/failed `RecordGet` not hiding loan, identical record reused without extra HTTP metadata calls, auth errors map to `ConfigEntryAuthFailed`, update/network errors to `UpdateFailed`, prior data not becoming false 0, zero real loans become 0.
- [x] **Step 2:** `pytest -q tests/test_coordinator.py` — RED.
- [x] **Step 3:** Implement coordinator, bounded cache, errors, small-poll rate. Never create a new DeviceID/client identity in coordinator refresh.
- [x] **Step 4:** `pytest -q tests/test_coordinator.py` — GREEN; Ruff.
- [x] **Step 5:** Commit `feat: add loan coordinator and catalog cache`.

## Task 5: Native HA entities and lifecycle

**Files:** Create `custom_components/axiell_libraries/__init__.py`, `sensor.py`, `todo.py`; update manifest/translations; `tests/test_entities.py`.

**Interfaces:** three sensors per entry: `active_loans` (int), `next_due_date` (`SensorDeviceClass.DATE`, native `date | None`) and `overdue_loans` (int). One read-only TodoListEntity per config entry listing each Loan with due date and unique `loan_id`; no create/update/delete features. Entity unique IDs must include config entry ID or stable account key. Follow latest HA TodoEntity API (verify signature before code).

- [x] **Step 1:** Add failing mocked HA lifecycle tests for adding two config entries, entity uniqueness, correct `date` sensor type, same-titled distinct loans, zero loans, no todo mutation support, reauth/restart preserving identity, unloading entries without cross-account state leaks.
- [x] **Step 2:** `pytest -q tests/test_entities.py` — RED.
- [x] **Step 3:** Implement entry setup/unload, sensors, todo, device info, translated names and documentation for HA UI use.
- [x] **Step 4:** `pytest -q tests/test_entities.py` — GREEN; Ruff.
- [x] **Step 5:** Commit `feat: expose library loans in Home Assistant`.

## Task 6: Quality gate, docs and user handoff

**Files:** Update `README.md`, `docs/protocol.md`, translations, tests, and any production files revealed by review.

- [x] **Step 1:** Add integration installation/config documentation, limitations (unofficial API), local-only live smoke test instructions without writing PIN to disk or logs, and tests for any uncovered high-risk failure.
- [x] **Step 2:** Run full `pytest -q`, `ruff check .`, `ruff format --check .`, validate manifest/config flow against available HA toolchain and ensure no credentials/PII (`git grep` + tracked-file inspection). Do not claim unavailable tools passed.
- [x] **Step 3:** Run Superpowers code review (`requesting-code-review`), address findings, rerun tests. All task reviews and final whole-branch review completed; the final loan-validation finding was fixed in `a481e30` and passed scoped re-review. See `docs/validation.md`.
- [x] **Step 4:** Commit `docs: finalize v1 installation and security notes`, report tested scope and unverified live assumptions. Leave repo private.

## Self-review (for implementer)

Before starting Task 1, verify the plan uses filenames consistently and test runner can install HA test dependencies. As tasks proceed, confirm all spec acceptance criteria have a test; identify any design assumptions that need live validation before release. This plan is a guide, not a substitute for checking actual HA API signatures and test outputs.
