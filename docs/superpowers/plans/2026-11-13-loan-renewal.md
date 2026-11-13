# Individual Loan Renewal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add explicit, account-isolated loan renewal with informed confirmation and no automatic write retries.

**Architecture:** Preserve the Solus transport and coordinator. Add a dedicated renewal decoder, a per-entry consent manager serialized with polling, and an admin HA action adapter.

**Tech Stack:** Python 3.14, aiohttp, Home Assistant 2026.11, pytest, Ruff, official hassfest.

**Spec:** `docs/superpowers/specs/2026-11-13-loan-renewal-design.md`

## Global Constraints

- Test actual Home Assistant 2026.11.1 and minimum 2026.11.0; all tests offline and synthetic.
- Existing persistent DeviceID, active validated server, credentials and sessions stay per entry; no new DeviceID or automatic write retry.
- Only explicit individual renewal is authorized. No live renewal, bulk feature, release publication, APK, raw traffic or personal credentials.
- Use loanID, current account UserID and actual Source; never recordID or a caller-supplied account/source.
- Every fee/challenge needs explicit consent; never accept arbitrary acknowledgement codes from the action.
- Never log credentials, tokens, cookies, raw HTTP bodies or provider messages; exceptions at logging boundaries are static.
- Existing read/authentication success checks and read-only to-do behavior remain intact.
- Commit only green tested changes; task reports include RED/GREEN commands, output, files, assumptions and next task.

## Review Focus

- Two simultaneous confirmations must produce at most one write (Task 2).
- Cancellation/unload after dispatch must drain/reconcile, not release a detached write (Task 2).
- Same-day dueObject changes or changed raw cost invalidate consent (Task 2).
- HTML/encoded secrets in provider messages must not escape into UI or logs (Tasks 1 and 3).
- Action calls without response support must still expose challenges and partial success clearly (Task 3).

---

### Task 1: Renewal transport and typed response

**Files:** Modify `custom_components/axiell_libraries/solus.py`; create `tests/test_renewal_protocol.py`; update `docs/protocol.md`.

**Interfaces:** Produce immutable `RenewalReply` with `outcome` (`success`, `error`, `confirmation_required`), sanitized `message`, internal `acknowledgement_code: str | None`. Produce `SolusClient.async_renew_loan(user_id: str, loan_id: str, source: str, *, acknowledged_codes: tuple[str, ...] = (), sensitive_values: tuple[str, ...] = ()) -> RenewalReply`. Later manager passes stored card/PIN as sensitive_values and uses the same user_id as LoansGet. Message and code must not appear in reply repr.

- [x] Write failing tests for exact LoanRenew URL/envelope/headers, current switched server and session/token, Source preservation, loan ID distinct from record ID, no DeviceID generation and no write retries.
- [x] Run `/tmp/axiell-ha202611-venv/bin/pytest -q tests/test_renewal_protocol.py` and record the expected missing-interface failures.
- [x] Factor common catalogue HTTP/envelope handling without relaxing `_call`'s success-only decoder. Implement dedicated renewal decoding. Require session; no authentication recovery inside renewal. Initial PromptAcknowledged `""`, confirmed codes joined `";"`. Preserve valid exact codes; reject semicolons/controls/surrounding whitespace/empty/length >128. Classify success/error and require a usable challenge message.
- [x] Add tests for explicit error, challenge, chained acknowledgement, malformed `d`/status/message, 401, timeout and malformed JSON, plus existing strict reads. Add sanitization tests for HTML/entities/control characters, 512-character cap and known secret/encoded-secret values including cookies before and after response. Do not expose raw bodies/codes in exceptions. Unknown personal provider text cannot be universally detected.
- [x] Document the owner's APK-derived protocol separately from live-tested authentication; no raw extracted JS or APK files.
- [x] Run focused tests, full `/tmp/axiell-ha202611-venv/bin/pytest -q`, `/tmp/axiell-ha202611-venv/bin/ruff check .` and `ruff format --check .`; fix failures, self-review and commit `feat: add explicit Solus loan renewal transport`.

### Task 2: Serialized per-account renewal and consent

**Files:** Create `custom_components/axiell_libraries/renewal.py`, `tests/test_renewal.py`; modify `coordinator.py`, `__init__.py`, and lifecycle tests in `tests/test_entities.py` as needed.

**Interfaces:** Consume Task 1 `async_renew_loan`/`RenewalReply`. Produce `AxiellCoordinator.async_renew_loan(loan_id: str, *, confirm: bool = False, confirmation_id: str | None = None) -> RenewalResult`. `RenewalResult.as_dict()` returns status (`renewed` or `confirmation_required`), loan_id, sanitized message, refreshed and optional confirmation_id/expires_in. `RenewalError` has finite `code`, sanitized `message` (not repr) and static exception text. Exact codes chosen here must be listed in the report for Task 3 translations. Keep config entry runtime_data unchanged. Manager and lock belong to one coordinator.

- [x] Write failing tests for one explicit renewal, fresh preflight, own-account loan/source lookup and immediate updated snapshot; record RED with `pytest -q tests/test_renewal.py`.
- [x] Implement per-entry manager and one operation lock shared with polling/auth recovery. Factor private unlocked refresh from existing read retry loop; no write inside that loop. Direct publish uses static update errors and explicitly starts reauth when required.
- [x] Implement explicit confirmation fields as a pair; pending IDs via `secrets.token_urlsafe(24)`, TTL 600 monotonic seconds, one per loan and maximum 32 pending entries. Under lock consume valid confirmation before any await. Bind original circulation fingerprint exactly as spec; changed values require new consent. Reject cross-account/replay/expiry before writes. Local known-positive cost consent precedes writes without inventing server codes; preserve accumulated provider codes, at most five, reject repeats. Invalidate same-loan tokens on write attempts and unload.
- [x] Add TDD cases for same loan ID across entries, two loans sharing record ID, nonrenewable/returned/missing-source loan, changed raw dueObject/source/cost, catalogue-only change, expired/reused/wrong token, concurrent token calls, fee then multiple server prompts, repeated/overlong challenge chains and bounded pending map. Confirm no writes on invalid consent and no caller injection of Source/UserID/codes.
- [x] Add TDD cases for timeout/401/protocol failure, read reconciliation (including one-time reauth), failed preflight, failed refresh after known success and failed reconciliation after unknown write. Assert one LoanRenew maximum per invocation; no auto-repeat. Follow-up action must freshly read before any subsequent write.
- [x] Retain/drain shielded operations on caller cancellation; serialize unload before session detach, set closing flag before waiting and reject queued/new actions. Add event-driven tests for poll/write ordering, cancel after dispatch and unload during a write; no sleeping race tests or orphan tasks. Retain working setup-failure cleanup and failed-unload behavior.
- [x] Run focused/full target pytest and Ruff, self-review, list public codes/interfaces in report, commit `feat: coordinate explicit renewal and confirmation per account`.

### Task 3: Home Assistant action and release documentation

**Files:** Create `custom_components/axiell_libraries/services.py`, `services.yaml`, `icons.json`, `tests/test_services.py`, `docs/releases/0.4.0.md`; modify `__init__.py`, `strings.json`, `translations/en.json`, `translations/nb.json`, `README.md`, `docs/home-assistant-ui.md`, `docs/releases.md`, `docs/protocol.md`, `CODEX_START.md`, `CHANGELOG.md`, `AGENTS.md`, manifest, release workflow default and `tests/test_marketplace.py` as needed.

**Interfaces:** Consume Task 2 coordinator method, RenewalResult and RenewalError codes. Produce `@callback async_setup_services(hass)` called from integration `async_setup`, with config-entry-only CONFIG_SCHEMA. Register `axiell_libraries.renew_loan` via `homeassistant.helpers.service.async_register_admin_service`, `SupportsResponse.OPTIONAL`, current probatio schema and HA `service.async_get_config_entry`.

- [x] Write failing offline real-HA service registration/call tests; run `pytest -q tests/test_services.py` and record RED.
- [x] Register required config_entry_id (integration-filtered config entry selector) and loan_id, optional confirm and confirmation_id. Validate domain/loaded state, admin authorization and confirmation pair before I/O. No default account fallback. Add translated services/fields/exceptions, service icon, no new entities or todo write features.
- [x] Map renewed/confirmation results to optional response dict. Without return_response, confirmation raises translated ServiceValidationError containing sanitized message and local confirmation ID; success with failed refresh gives explicit partial-success error instructing update rather than repeat renewal. Map rejection/uncertain outcome to translated HA exceptions. Never include raw exception repr, server status code or snapshot in responses/logs.
- [x] Add tests for unavailable/wrong-domain/missing entry, nonadmin denial, two account entries, confirmation visible with/without response, translated sanitized rejection, unknown outcome and partial success, setup/unload/reload, redaction at action boundary, and unchanged read-only todo. Reuse manager tests rather than mock away integration behavior everywhere.
- [x] Document Tools → Actions usage, obtaining loan IDs from structured sensor attributes, interpreting renewal cost/consent, manual second call with confirm true, expiry/reloads, unknown outcomes and no automatic retry. Do not create an automation that auto-accepts prompts. Explain arbitrary provider text privacy limit and no live renewal verification. Update AGENTS and CODEX_START narrowly to reflect explicit renewal authorization while preserving historical v1 docs. Correct Task 1 review minor at docs/protocol.md: only challenge messages must be usable; missing terminal messages are accepted. Existing catalogue wrapper uses AppID for TemplateID as in verified authentication; document this existing limitation rather than silently expanding config schema. Owner has installed the published v0.3.0 release; distinguish that from this unreleased version.
- [x] Prepare manifest version `0.4.0`, matching release notes and release workflow default. Preserve validated manual semantic release/tag process; no tag/release creation. Update actual-version tests and docs, no need to rename synthetic version fixtures.
- [x] Run full target pytest, Ruff and release validation checks; self-review and commit `feat: expose confirmed individual loan renewal action`.

## Final verification and delivery

- [x] Controller runs full pytest on actual 2026.11.1 and minimum 2026.11.0, Ruff, actionlint and official hassfest; record versions/counts in docs/validation.md.
- [ ] Perform independent whole-branch review, address findings with tests and scoped re-review.
- [ ] Create PR, verify hosted CI, use existing merge authorization only after checks pass. Do not dispatch release workflow or invoke live renewal.
- [ ] Report tested evidence, action/confirmation usage, PR, remaining unverified protocol behavior and rulings.
