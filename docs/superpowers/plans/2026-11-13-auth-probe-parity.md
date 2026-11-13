# Authentication probe parity implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox syntax for tracking.

**Goal:** Correct verified differences from the working probe and make any remaining setup failure diagnosable without private data.
**Architecture:** Amend the existing async client and HA flow; preserve entry identity, session ownership and read-only entities.
**Tech Stack:** Python 3.14, Core/pytest-homeassistant 2026.11.0 and 2026.11.1, aiohttp, pytest, Ruff, hassfest.
**Spec:** `docs/superpowers/specs/2026-11-13-auth-probe-parity-design.md`.

## Global Constraints

- One entry per library/card; reject duplicates before login. Generate secrets.token_hex(8) once per new flow and persist/reuse it across retries, restart, reauth and upgrades.
- Keep HA-managed asynchronous sessions with separate CookieJar instances; no shared tokens or session-default header mutations.
- Use LoginPreSession then LoginCheckSession; never direct Login, CAPTCHA handling, credential retries or device regeneration.
- Keep strict HTTPS Solus origins and blocked HTTP redirects; do not forward credentials/tokens to a newly suggested untrusted host.
- All tests offline and synthetic; no credentials, tokens, cookies, device IDs, raw response bodies, URLs or exception text in diagnostics.
- No invented library names/global APIs. No release, tag, release dispatch, version bump or repository visibility change.

## Review Focus

1. A successful session check without new Detail must retain the first response's account/token (Task 1).
2. Initial and retry requests must use the zero session UUID and the same persistent DeviceID (Task 1).
3. Cookies must cross the bootstrap/login boundary but not entry boundaries (Task 1).
4. Provider text or redirected URLs must never enter diagnostics, including HA errors (Task 2).
5. Correct protocol requests must still fail safely on an untrusted destination or malformed response (Tasks 1 and 2).

### Task 1: Match the owner-verified request and session contract

**Files:** `custom_components/axiell_libraries/solus.py`, focused `tests/test_solus.py` additions or a separate `tests/test_auth_protocol.py`, `tests/test_config_flow.py`, test utilities only as needed.
**Interfaces:** Preserve the existing SolusClient and discovery call signatures. Preserve its list-of-user-dicts login result. Config entry data is unchanged.

- [x] Add failing offline request-boundary tests for the differences below; record RED before production edits. Add an actual HA flow test that uses the real client with mocked HTTP to reach CREATE_ENTRY from probe-shaped responses and retains exactly one DeviceID.
- [x] Initialize/reset session ID to `00000000-0000-0000-0000-000000000000`. LoginPreSession body has no SessionID/VerifyToken; nested credentials stay as before. LoginCheckSession outer UserID is `""`. LoansGet uses the supplied user ID at both outer and Request levels.
- [x] Use separate metadata dictionaries. Shared identity includes AppID/TemplateID/DeviceID/AppVersion/PackageName/PlatType=`Android`/PlatVer=`17`/PlatModel=`Home Assistant`/DName=`Android`/Locale/AppBuild. Bootstrap adds font=`""` and ServerRoot with trailing slash. CheckSession adds NetworkType=`WiFi`, ScreenW/ScreenAW=384, ScreenH/ScreenAH=832, DPR=1 and AuthToken, but no font/ServerRoot. Do not hardcode the owner's phone model or AppID.
- [x] Use the probe's User-Agent `Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36` and Accept `application/json, text/javascript, */*; q=0.01`. POST Content-Type is `application/json; charset=utf-8`. PreSession alone has Origin, the exact generated bootstrap URL as Referer, and X-Requested-With; omit regular catalogue x-headers on that browser request. Bootstrap and regular catalogue calls have x-session, x-devicesession, x-appversion, x-appbuild, x-apppackage, with the current token/session. Never mutate session defaults.
- [x] Encode bootstrap JSON as compact UTF-8 with ensure_ascii=False and ordinary Base64/query escaping. Decode response JSON with UTF-8 BOM support. Accept string success status case-insensitively; retain explicit credential rejection behavior and reject unknown/malformed statuses safely.
- [x] Keep pre-session users/token when CheckSession Detail is absent/null/empty list. Accept valid replacement user details/token, and nonempty string SessionID. Reject malformed provided account/session shapes rather than silently accepting them. Handle the verified same-origin ServerToUse (including trailing slash); retain safe rejection of untrusted destinations. No live alternate host has been verified.
- [x] Exercise real aiohttp cookie transfer using a local synthetic mock server (loopback only), plus HA-owned separate cookie jars and cleanup. Do not infer cookie transport solely from aioresponses calls, and do not assume a cookie must be issued. Any test-local endpoint substitution must leave production routing guards intact and have separate routing regressions.
- [x] Run focused tests while iterating, then full `/tmp/axiell-ha202611-venv/bin/python -m pytest -q` and Ruff lint/format before committing. Report exact RED/GREEN outputs and every remaining mismatch from the reference.

### Task 2: Safe setup diagnostics and release/discovery documentation

**Files:** `solus.py`, `config_flow.py`, strings and en/nb translations, focused API/config-flow tests, `README.md`, `docs/protocol.md`, `docs/validation.md`, `docs/library-discovery.md`, `CHANGELOG.md`, this plan's completion record.
**Interfaces:** Keep existing SolusError subclasses catchable and static exception messages; add only finite diagnostic context. Keep standard HA form error/description placeholders and existing success/abort semantics.

- [x] Add failing tests for routing, bootstrap, pre-session and check-session failures and missing AuthToken; distinguish transport/HTTP/API/response-schema/security reasons without using provider text. Test real flow rendering context for initial setup, retries, reauth and reconfigure. Error fields must not include synthetic secret markers even when underlying exception/response content contains them; verify DeviceID reuse and cleanup.
- [x] Add allowlisted stage/reason references, optionally validated HTTP status numbers, exposed in translated HA error descriptions. Discovery/manual lookup errors must be distinguishable from authentication errors. No raw headers, cookies, response text, URLs, DeviceID, card, PIN, tokens or exception strings. Keep missing cookies nonfatal; test handling instead of inferring cookie requirements. Do not broadly catch arbitrary programming errors and mislabel them as provider failures.
- [x] A known API failure status must be reported as API rejection rather than malformed JSON. Do not guess that an unverified API error means bad PIN; only the existing explicit credential rejection paths request PIN correction. Unauthenticated routing/bootstrap HTTP rejection must not misleadingly claim the card/PIN was rejected. Preserve bounded requests and existing session-expiry recovery behavior.
- [x] Explain the provider list can be incomplete in UI/README; retain Name when supplied and LocationID fallback. Record actual anonymous sample results, no global/name-field proof, and no fabricated names. Update protocol with the supplied PoC's exact contract, confirmed corrected differences and remaining generic model/strict-routing/response-validation differences.
- [x] Preserve the owner's subsequent NB directory investigation in a concise `docs/library-discovery.md` linked from README: authoritative inst names and branch identifiers are available, but shared Quria hosts/NCIP tenants are not Solus join keys. Use the verified findings in `/tmp/axiell-national-library-investigation.md` and `/tmp/axiell-discovery-investigation.md`, with primary links and exact provenance. No XML download, contact data, guessed mapping or new runtime dependency in the integration.
- [x] Correct stale README private-repo wording. Explain that a published GitHub release (tag matches manifest) changes hash labels to numeric versions; first planned version remains 0.2.0 and patch example 0.2.1. Add concise CHANGELOG Unreleased notes and link it from maintainer release instructions. Do not publish anything or alter the release workflow/version merely to change labels.
- [x] Run full pytest on `/tmp/axiell-ha202611-venv` and `/tmp/axiell-ha2026110-venv`, print actual runtime versions, Ruff check/format, official hassfest container and git diff --check. Record outputs and limits in validation docs; report files, API assumptions and owner-run next step. Commit and self-review.


### Task 2 completion record — 2026-11-13

Safe finite setup references, translated form context and discovery/release/NB
research documentation are implemented. Focused flow RED: `53 failed`;
final selection GREEN: `53 passed`; constructor compatibility RED `4 failed,
8 passed` → GREEN `12 passed`. Complete offline suites: Core/harness 2026.11.1
`318 passed, 5 warnings in 3.69s`; 2026.11.0 `318 passed, 5 warnings in 3.53s`;
both Python 3.14.7. Ruff checks pass (34 formatted files), official hassfest
reports `Invalid integrations: 0`, manifest/release agreement remains 0.2.0,
and diff check is clean. Existing five upstream warnings remain visible.
See [validation evidence](../../validation.md) for commands, files, self-review,
limits and API assumptions. Next: owner installs/restarts HA and checks the
credentialed integration flow, sharing only the fixed UI reference if it fails.
No live integration success, release publication or directory mapping is claimed.
