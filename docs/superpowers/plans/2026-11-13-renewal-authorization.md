# Renewal Authorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let authorized non-admin HA users renew loans while enforcing access per library account.

**Architecture:** Replace the action's admin wrapper with a scoped entity-control permission check. Keep the service schema, response adapter and coordinator/transport unchanged.

**Tech Stack:** Python 3.14, actual Home Assistant/official pytest harness 2026.11.1 and 2026.11.0, Ruff, hassfest.

**Spec:** `docs/superpowers/specs/2026-11-13-renewal-authorization-design.md`

## Global Constraints

- This is authorization only: no Solus, coordinator, renewal manager, DeviceID, session, action schema, dependencies or entity changes.
- Require POLICY_CONTROL for at least one registered axiell_libraries entity belonging to the selected config entry; never a domain-wide permission shortcut.
- Resolve current HA user/context and permissions on each call, including confirmations; unknown/inactive users and missing permissions fail before provider I/O or token consumption.
- Keep SupportsResponse.OPTIONAL and all four action fields unchanged; user_id None retains trusted internal behavior.
- All tests are offline and synthetic. Never log credentials, tokens, account data or raw responses.
- No release/tag publication or live renewal is authorized for this fix. Leave manifest/version and released notes unchanged.

## Review Focus

- Two entries with identical loan IDs: access to one cannot authorize the other.
- Permission revocation before confirmation: reject without consuming the token or invoking the coordinator.
- Fake/unknown/inactive identity versus user_id None: reject invalid user identities; preserve only the standard trusted-system path.
- Registry changes: renamed entities still work, missing entities and unrelated platforms cannot grant access.
- Backend policy versus frontend visibility: real permission objects drive authorization; no frontend/admin flag or mocked permission verdict substitutes for them.

---

### Task 1: Account-specific renewal permission gate

**Files:** Modify `custom_components/axiell_libraries/services.py`, `tests/test_services.py` (or create focused `tests/test_service_authorization.py`), `strings.json`, `translations/en.json`, `translations/nb.json`, `README.md`, `docs/home-assistant-ui.md`, `CODEX_START.md`, the current authorization sentence in `docs/protocol.md`, and add an Unreleased authorization entry in `CHANGELOG.md`. The JSON paths are under `custom_components/axiell_libraries/`. Leave historical release docs/specs and all protocol code/contracts untouched; only replace the stale admin adjective in current protocol documentation.

**Interfaces:** Keep `async_setup_services(hass)` and existing action public schema. Add a small private async helper in `services.py`, e.g. `_async_authorize_entry(call: ServiceCall, entry_id: str) -> None`. It resolves the caller using `call.hass`, validates identity/activity, gets HA's entity registry, filters entries by config_entry_id and platform==DOMAIN, then uses `user.permissions.check_entity(entity_id, POLICY_CONTROL)`. Raise native UnknownUser/Unauthorized as appropriate. Call it before existing selected-entry validation and consent handling. Register via `hass.services.async_register` preserving schema and response support. No role cache or global authorization state.

- [ ] Write an authorized ordinary non-admin service-call test using a real active HA user and actual control policy; assert a successful renewal, unchanged DeviceID and exactly the selected account's write. Run it before implementation and record Unauthorized from the current admin wrapper as RED.
- [ ] Add a real scoped policy test granting control for an entity of account A, while account B has the same loan ID. Assert A renews and B raises Unauthorized before any loan read, write, coordinator invocation or challenge. Add read-only and no-control users, admin/owner success and unchanged trusted-system calls.
- [ ] Run focused RED with `/tmp/axiell-ha202611-venv/bin/pytest -q tests/test_services.py` (plus the new authorization file if used). Report meaningful failed assertions, distinguish already-passing negative cases.
- [ ] Implement the smallest helper/registration change. Resolve unknown/empty supplied IDs via async_get_user, reject inactive users, treat only None as the internal path. Use current registry entry association and platform filter; avoid relying on display names/entity IDs or Core verify_domain_control.
- [ ] Add focused behavioral tests for permission revocation between initial prompt and explicit confirmation, denied caller using a valid token (token remains usable by the permitted caller), authorized non-admin provider challenge with exact acknowledgement, response/no-response behavior, renamed entities, absent matching registry entities, and an unrelated platform entity on the selected entry. Exercise actual HA PolicyPermissions/group policy changes, not stubbed check_entity booleans. Tests may replace upstream I/O and use existing real coordinator/manager fixtures.
- [ ] Update current English/Norwegian action text and guide to describe entity-control authorization and non-admin dashboard use; explain default Users-group access and that hiding a dashboard/card is not access control. Preserve live renewal limitations. No Origami code changes or new ACL UI.
- [ ] Run focused GREEN, full `/tmp/axiell-ha202611-venv/bin/pytest -q`, Ruff check/format and diff check; self-review and commit `fix: authorize loan renewal per account entity permissions`. Report exact RED/GREEN output, files, unchanged protocol/consent boundaries and remaining validation.

## Final verification and delivery

- [ ] Independent task review, then whole-branch review; fix findings with regression tests and scoped re-review.
- [ ] Verify actual minimum Core 2026.11.0 as well as target 2026.11.1, official hassfest, Ruff and hosted CI; record results in docs/validation.md.
- [ ] Create PR and use existing merge authorization only after checks pass. No release or live renewal.
