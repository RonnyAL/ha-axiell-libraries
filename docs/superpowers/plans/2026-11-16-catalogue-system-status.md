# Catalogue System Status Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development and TDD.

**Goal:** Classify known HTTP 200 body statuses safely before read/renewal decoding.
**Architecture:** One shared classification point, existing session/security error
types with finite distinct reasons, unchanged coordinator recovery and write policy.
**Tech Stack:** Python 3.14, Home Assistant 2026.11.0/2026.11.1, aiohttp, pytest.
**Spec:** `docs/superpowers/specs/2026-11-16-catalogue-system-status-design.md`

## Global Constraints

- Match `sessionexpired`, `LOGINEXPIRED`, `VALIDATIONREQUIRED` case-sensitively.
- Preserve serialized `d`, unknown-status fallback and v0.5.0 recovery limits.
- Never replay a renewal write or treat a system status as consent.
- Never bypass validation or infer invalid PIN from these body statuses.
- Keep tests synthetic and diagnostics static; preserve identity and security.
- No new release, deployment, or live provider operation.

## Review Focus

- System status during login must not be misreported by config flow as invalid PIN.
- RecordGet validation/session failures must not disappear as optional metadata errors.
- Repeated expiry must exhaust the existing bounded read recovery without reauth.
- Case variants and unknown values must keep the existing decoder fallback.
- Renewal response with prompt-like private text must not create a confirmation.

### Task 1: Classify body statuses and verify end-to-end consequences

**Files:** `solus.py`, `config_flow.py`, focused Solus/coordinator/config/renewal
tests, `docs/protocol.md`, `CHANGELOG.md`, `docs/validation.md`.
**Interfaces:** `_catalogue_request` continues returning unknown/success payloads.
Known expiries raise `SolusSessionExpired` with reason `session_expired` or
`login_expired`; validation raises `SolusSecurityError` with reason
`validation_required`. Add these reasons to the finite allowlist. Preserve
expiry state when login itself raises a session expiry. Config flow reports
invalid_auth only for genuine credential errors, not session subclasses.

- [x] Add synthetic HTTP 200 tests across LoansGet/RecordGet/LoanRenew, all three
  statuses, object/string d, unknown and wrong-case values. Assert safe references,
  invalidated sessions, no local retries or x-token, and unknown fallback behavior.
- [x] Add real-client/coordinator tests for successful expiry relogin, repeated
  expiry, validation surfacing without accelerated retries/reauth, and one-shot
  renewal unknown outcome with no confirmation. Cover login-stage config flow.
- [x] Run the new cases RED against the existing code; record meaningful failures.
- [x] Implement central classification and narrowly required config-flow/state fixes.
- [x] Run focused and full available suites, Ruff check/format and diff checks.
  Preserve requirements and report local runtime limitations; do not weaken gates.
- [x] Update protocol/changelog/validation with provenance, evidence and limitations;
  commit the reviewed local change without bumping or publishing a release.
