# Fix public locator response parsing

**Spec:** Existing approved Axiell design and `docs/protocol.md`; preserve native,
read-only, multiple-entry, persistent DeviceID and strict credential routing.
**Workflow:** Superpowers systematic debugging, subagent development, TDD,
independent review and verified final CI.

## Evidence and root cause

The owner reports the manual `Malselv` LocationID fails before credential entry.
Anonymous public probes on 2026-11-13 found:

- QueryWithID: HTTP 200, `d` object, `Status: "ok"`, LocationID/AppID/ServerUrl/
  APIUrl present, no Name field. Current parser requires `"OK"` and Name.
- Repo route: HTTP 200 JSON with Server set to a valid HTTPS Solus origin.
- FindWithLocation with the protocol's public sample coordinates: HTTP 200,
  `d` is a list of rows, each with `Status: "ok"` and no Name. Current parser
  requires an object containing Status and Detail instead.

Only response shapes and public routing fields were inspected. No credentials,
DeviceID, login or account request was used. No raw response is saved or committed.

## Global Constraints

- Keep all tests offline and use synthetic fixture values.
- Preserve required LocationID/AppID, strict HTTPS Solus origins, trusted repo
  routing, no redirects, static exceptions, bounded timeouts and no login here.
- Preserve persistent DeviceID, authentication, card identity and read-only v1.
- No APKs, raw traffic, credentials or raw responses; no merge/release/visibility
  changes. Existing PR is merged, so deliver a separate fix PR.

### Task 1: Correct observed locator formats with regression coverage

**Files:** `solus.py`, focused API/config-flow tests, `docs/protocol.md`,
`docs/validation.md`, this plan's verification record as needed.

1. Add failing synthetic HTTP-boundary tests for lowercase `ok`, missing Name,
   and a nearby direct list with per-row status. Keep support for existing tested
   uppercase status and Status/Detail wrappers. Check empty direct lists return
   no candidates and unsuccessful/malformed statuses still fail safely before
   repo routing. Do not relax unrelated auth/status parsing.
2. Add a config-flow regression using the real locator parser and mocked HTTP:
   manual LocationID reaches credentials with LocationID as display-name fallback,
   without login or generating another DeviceID. Exercise nearby selection with
   observed-shaped rows where useful; existing manual fallback remains available.
3. Implement the narrow parser correction: locator success status case-insensitive
   for strings only; optional missing/empty name falls back to valid LocationID;
   direct nearby arrays validated per row while retaining legacy wrapper support.
   Required identity and unsafe routing remain errors. No speculative field aliases
   or broad response-shape guessing.
4. Update protocol docs to distinguish newly observed anonymous discovery from
   still-unverified credentialed login/account behavior. Record evidence without
   capturing a raw live response. Keep version 0.2.0: no release exists yet.
5. Run focused RED/GREEN, then full pytest on actual Core 2026.11.0 and 2026.11.1,
   Ruff lint/format and diff checks. Report exact outputs and five known upstream
   warning origins; no warning suppression. Commit green code and self-review.

## Completion

Review the task and final branch. Controller repeats the corrected public manual
lookup and nearby path without credentials, reports only safe typed-result facts,
opens a fix PR and monitors pytest/Ruff/official hassfest CI. Do not claim live
login/loans verified. Final report explains root cause and how to install/retry the
fix after owner merge/update; no need to replace account identity or ask for PIN.
