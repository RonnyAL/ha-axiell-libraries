# v1 validation ledger

This records offline implementation evidence, not a live compatibility claim.
The approved design was reused: native HA integration, one entry per
library/card, persistent DeviceID, read-only Solus access, nearby discovery and
manual LocationID. No redesign approval was needed. All six task briefs came
from the [approved plan](superpowers/plans/2026-11-13-axiell-libraries-v1.md).

## Environment and implementation choices

Development used local branch `feat/axiell-libraries-v1`. The managed worktree
was not writable in the sandbox, so work continued in the original writable
checkout on that isolated feature branch; `main` was not changed. No push,
merge, publication or repository visibility command was performed.

Full HA tests used Python **3.13.15**, HA **2026.2.3**,
`pytest-homeassistant-custom-component` **0.13.316**, pytest **9.0.0**,
aioresponses **0.7.9** and Ruff **0.17.5**, pinned in `requirements-dev.txt`.
The local test interpreter is `/tmp/axiell-ha-venv/bin/python`; this path is
an ephemeral development environment, not an installation requirement. A local
compiler workaround was needed to build pinned `lru-dict`; no compiler or
virtual environment is committed. Initial pure-model tests used `.venv` with
pytest 9.2.0, then were independently checked in the full HA environment.

The sandbox blocks asyncio self-pipe writes. HA pytest runs therefore used an
authorized sandbox escalation for local event-loop sockets; the HA pytest
plugin's offline network guard and cleanup fixtures remained enabled. No live
Solus calls were made. The baseline was `no tests ran in 0.00s` (exit 5).

Implementation choices include UTC calendar dates from `dueObject`, validated
but unapplied optional date suffixes, six-hour loan polling, a per-entry
24-hour/256-record catalogue cache, four concurrent metadata requests, and one
recovery login for explicit expiry per refresh. Missing metadata and covers
are optional. API calls have 20-second timeouts and no transport retries.
Auth tokens and cookies are in memory; the card, PIN and DeviceID persist in HA
config entry data, which is not a dedicated secrets vault.

## Task evidence

Paths below are relative to the repository. `cc/` abbreviates
`custom_components/axiell_libraries/`. Historical task outputs come from the
local task reports; timing is the recorded run, not a performance guarantee.
Task 1–5 independent reviews were recorded as complete by the controller.
Task 6 review completion remains pending the controller's scoped final re-review.

| Task / local commit | Files changed | RED → GREEN and final regression output | API assumptions / next task |
| --- | --- | --- | --- |
| 1 Models / `51ff59d` | `cc/models.py`, `cc/const.py`, `tests/test_models.py`, `pyproject.toml`, `docs/protocol.md` | Parser interface stub: `41 failed in 0.02s`; final full `.venv/bin/python -m pytest -q`: `41 passed in 0.03s`. Ruff: `All checks passed!`; changed files: `3 files already formatted`; diff check empty. Full HA runner independently: `41 passed in 0.17s`. | Optional date suffix is defensive, not observed live. Next: client. |
| 2 Client / `76696fe` | `cc/solus.py`, `cc/__init__.py`, `cc/manifest.json`, `tests/test_solus.py`, `requirements-dev.txt`, `docs/protocol.md` | Missing client: `1 error in 0.06s`; initial `26 passed in 0.17s`; HTTP-expiry regression: `1 failed, 34 passed in 0.22s` → `35 passed in 0.20s`; full `76 passed in 0.27s`. Ruff: `All checks passed!`; diff check empty. | Exact locator schema, bootstrap descriptors, optional repo AuthServer and JSON expiry codes unverified. Next: flow. |
| 3 Flow / `0483cb0` | `cc/config_flow.py`, `cc/strings.json`, `cc/translations/{en,nb}.json`, `cc/solus.py`, `tests/{conftest,test_config_flow,test_solus}.py`, `pyproject.toml`, `docs/protocol.md` | Real-flow/auth-status RED: `12 failed, 35 deselected in 0.87s` → focused `47 passed in 0.39s`; flow `10 passed in 0.14s`; full `89 passed in 0.57s`. Ruff: `All checks passed!`; `10 files already formatted`. | Only synthetic explicit `failure` means JSON credential rejection; unknown status is provider failure. Browser selector rendering unverified. Next: coordinator. |
| 4 Coordinator / `1b2babc` + review fix `8eff1ed` | `cc/coordinator.py`, `cc/models.py`, `cc/solus.py`, `tests/{test_coordinator,test_models,test_solus}.py`, `docs/protocol.md` | Coordinator stub: `27 failed in 0.51s` → `27 passed in 0.27s`. Metadata model regression: `1 failed, 41 deselected in 0.12s`; full `117 passed in 0.78s`. Review found queued expiry/recovery state bug: corrected real-client RED `3 failed, 1 passed in 0.18s`, transient recovery RED `1 failed in 0.13s` → `5 passed in 0.15s`; combined client/coordinator `70 passed in 0.56s`; full `122 passed in 0.78s`. Ruff: `All checks passed!`; `12 files already formatted`. | Cache, concurrency, source validation and bounded recovery are integration policies. No new live observations. Next: entities/lifecycle. |
| 5 Entities / `65e3cd7` | `cc/__init__.py`, `cc/sensor.py`, `cc/todo.py`, `cc/manifest.json`, `cc/strings.json`, `cc/translations/{en,nb}.json`, `tests/{test_entities,test_config_flow}.py`, `docs/home-assistant-ui.md` | Missing setup: `9 failed in 0.19s` → `9 passed in 0.18s`. Full run caught config-flow fixture scope: `1 failed, 130 passed in 0.92s`; corrected fixture → `131 passed in 0.89s`. Extended lifecycle checks: `12 passed in 0.21s`; full `134 passed in 0.87s`. Ruff: `All checks passed!`; `15 files already formatted`; diff check empty. Controller independently checked `134 passed in 0.90s`. | Reload simulates restart using unchanged entry data with ID generation forbidden; actual process restart untested. Covers are optional external links. Next: final gate. |
| 6 Documentation / current local change | `README.md`, `CODEX_START.md`, `docs/{home-assistant-ui,protocol,validation}.md`, plan checkboxes | Documentation-only change; no new production behavior or high-risk gap found requiring another behavior test. Final full suite: `134 passed in 0.90s`; Ruff: `All checks passed!`; `22 files already formatted`; diff check empty. Installed HA loader/translations: `1 passed in 0.09s`. | Independent Task 6 review and broad final review pending with controller; then owner-only local HA UI smoke test. |

Historical command forms: Task 1 used `.venv/bin/python -m pytest -q` and
`.venv/bin/ruff`; Tasks 2–6 used `/tmp/axiell-ha-venv/bin/python -m pytest -q`
and `/tmp/axiell-ha-venv/bin/ruff`. Focused commands append the named test file
or test node. Task 2's final full run additionally used `--timeout=20`.
Task 3's focused RED used
`tests/test_config_flow.py tests/test_solus.py -k 'config_flow or malformed_auth_status' --tb=short`.
Task 4's review regression used the real `SolusClient`, HA session, mocked HTTP
boundary and more than four uncached records to exercise queued work, rather
than relying only on a mocked client's expiry behavior.

## Final review boundary fix

Review found that `LoansGet` accepted dictionary rows without usable `loanID` or
`title`, including duplicate IDs. Those rows could replace a valid snapshot with
blank or ambiguous to-do items. The client now requires both fields to be
nonempty strings and rejects IDs duplicated after whitespace trimming. The
error text is static; optional dates and catalogue fields remain permissive,
and a real empty list remains valid. This is defensive validation, not a new
live API observation.

Files changed for this fix: `cc/solus.py`, `tests/test_solus.py`,
`tests/test_coordinator.py`, `docs/protocol.md` and this ledger. The focused
regressions exercise required-field types and omissions, raw/normalized duplicate
IDs, permissive optional values, and real `SolusClient`/HA coordinator/to-do
behavior across a valid refresh followed by malformed HTTP success. They assert
the exact previous snapshot is retained, the update fails, the entity becomes
unavailable, and the previous distinct nonblank to-do IDs and titles remain.

```text
$ /tmp/axiell-ha-venv/bin/python -m pytest -q tests/test_solus.py tests/test_coordinator.py -k 'required_loan_fields or duplicate_normalized_loan_ids or valid_loan_identity or real_client_malformed_loans' --tb=short
RED: 22 failed, 3 passed, 70 deselected in 0.41s
GREEN: 25 passed, 70 deselected in 0.29s
$ /tmp/axiell-ha-venv/bin/python -m pytest -q
159 passed in 1.06s
$ /tmp/axiell-ha-venv/bin/ruff check .
All checks passed!
$ /tmp/axiell-ha-venv/bin/ruff format --check .
23 files already formatted
$ git diff --check
(no output, exit 0)
```

RED exited 1 for the expected acceptance/snapshot assertions; all GREEN and
quality commands exited 0. The 25 additions increase the historical 134-test
suite to 159 tests. Tests were offline, with the same authorized local event-loop
socket escalation and HA network guard described above. No live account test
was performed. Next: the controller's scoped final re-review of this fix; Task 6
review completion remains pending.

## Historical final commands and available HA tooling

Run from the checkout in the verified environment:

```text
$ /tmp/axiell-ha-venv/bin/python -m pytest -q
134 passed in 0.90s
$ /tmp/axiell-ha-venv/bin/ruff check .
All checks passed!
$ /tmp/axiell-ha-venv/bin/ruff format --check .
22 files already formatted
$ git diff --check
(no output, exit 0)
```

All four commands exited 0. The real HA suite validates config-flow schemas,
manifest loading, entry setup/unload, native date sensors, read-only todo
services, separate sessions, reload and PIN-update identity. The extra one-off
HA runtime check used `homeassistant.loader.async_get_integration` and
`homeassistant.helpers.translation.async_get_translations` for both `en` and
`nb` across `config`, `entity` and `selector`, comparing loaded static values and
translation/source leaf-key parity. It checked config-flow registration,
service/cloud-polling manifest fields, version, empty requirements and multiple
entries. Exact local command:

```text
/tmp/axiell-ha-venv/bin/python -m pytest -q /tmp/test_axiell_toolchain.py -o pythonpath=/home/ronny/axiell/ha-axiell-libraries -o asyncio_mode=auto -o asyncio_default_fixture_loop_scope=function
1 passed in 0.09s
```

The temporary probe initially failed because HA's fixture changed the import
namespace, then because the probe omitted the trailing dot expected by HA's
`recursive_flatten` prefix. Loading the checkout namespace before HA's fixture
and correcting that probe prefix resolved these tool-check errors; no product
code or translations changed. The probe is local, outside the product suite.
This validates backend loading; it does not validate browser rendering or prove
that Norwegian dropdown labels render correctly.

`hassfest` is **unavailable**: its source-tree tooling is not shipped in the
installed Home Assistant distribution. It was not run and is not claimed to
have passed. The available runtime checks are narrower than hassfest's full
manifest/strings validation.

Privacy inspection used `git ls-files`, tracked-file byte/suffix inspection,
JSON parsing and filename-only `git grep -Il` searches for credential fields and
common token/private-key patterns. The 32 pre-documentation tracked files were
text only, with no APK/XAPK, archive, HAR/packet capture, private-research path or
NUL bytes. Credential-field matches were inspected as implementation references
and explicit synthetic `TEST` values. Token/private-key pattern grep returned
no matches (exit 1, expected). The three checked-in JSON fixtures are synthetic.
This is a bounded repository inspection, not a claim that pattern matching can
detect every possible secret. Ignored `research/private/` was neither read nor
staged. Final documentation is text and contains no owner credentials.

## Unverified behavior and handoff

- Nearby/locator responses: exact object keys
  `Status/LocationID/Name/AppID/ServerUrl`, optional `d`/serialized envelope, and
  nearby `Detail` list need live validation. Search only filters returned choices.
- Bootstrap descriptors (`Home Assistant`, platform version `1`, font `100`),
  the metadata/AuthToken LoginCheckSession request and optional repo `AuthServer`
  need confirmation. The observed app version/build/package are retained.
- Exact upstream negative-auth and JSON session-expiry codes are unknown.
  HTTP 401/403 has explicit behavior; unknown JSON status fails as a provider
  error without speculative retry loops. Actual cookie issuance is untested.
- Dynamic origins accept only root HTTPS single-label `*.sol.us` hosts without
  credentials, explicit port, query or fragment. Redirects are blocked.
  `ServerToUse` must equal the trusted repo's resolved processing origin. This
  may reject an otherwise valid new provider route until independently verified.
- No latest-HA compatibility, browser testing, actual process restart, or live
  complete-integration success is claimed. Reload/reauth identity is tested
  offline. The earlier owner's protocol probe is separate evidence.

Next: the controller performs the scoped final re-review of the loan-validation
fix and confirms Task 6 review completion. Only after that, the owner may use the
[local HA UI smoke test](../README.md#optional-owner-run-live-smoke-test), entering
card/PIN in HA only. Keep credentials, traces and account data out of chat,
issues, logs and files, and keep this repository private.
