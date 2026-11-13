# Validation ledger

This records automated implementation evidence and separately attributed
owner-run live checks. Automated tests never use a real library account.
The approved design was reused: native HA integration, one entry per
library/card, persistent DeviceID, initially read-only Solus access, nearby discovery and
manual LocationID. No redesign approval was needed. The original six task briefs came
from the [approved plan](superpowers/plans/2026-11-13-axiell-libraries-v1.md).

## Current: explicit individual loan renewal (prepared 0.4.0)

The owner explicitly authorized an individual renewal action extending read-only
v1. Existing aggregate sensors, structured loan attributes and the to-do entity
remain read-only. The owner has installed published **0.3.0**; this work prepares
**0.4.0** without publishing a tag/release or invoking a live renewal.

Implemented the [renewal plan](superpowers/plans/2026-11-13-loan-renewal.md)
with Superpowers TDD and separate task reviews:

| Task / commit | Files and behavior | Observed RED → GREEN |
| --- | --- | --- |
| Transport / `bc71012` | `solus.py`, protocol tests/docs: exact active-server LoanRenew envelope, dedicated reply decoder, bounded message redaction | 60 failed/4 passed → 64 focused passed; 503 full passed |
| Coordinator / `53cef8a` | `renewal.py`, coordinator/lifecycle, renewal/entity tests: account isolation, consent, read reconciliation, cancellation and unload drain | Initial missing method 1 failed → 1 passed; consent 39 failed/1 passed → 40 passed; lifecycle 4 failed/3 passed → 109 focused passed; 562 full passed |
| HA action / `3b4ef31` | `services.py`, metadata/translations, services/Marketplace tests, manifest/release docs: explicit admin account action and optional response | 17 failed/7 passed initially; schema assertions strengthened to exclude missing-service false positives → 35 service tests passed; 92 action/Marketplace/release tests passed; 599 full passed |

Each final run has the same five known upstream warnings. Renewal tests are
entirely synthetic/offline. Lifecycle tests use events to reproduce cancellation
and session detach during a write; no timing sleeps or real account writes.
The confirmation fingerprint includes exact original circulation values, including
same-day timestamp differences and malformed nested values, while excluding
catalogue metadata. Each write attempt is outside the read/login recovery loop.

Controller verification at `3b4ef31`:

```text
$ /tmp/axiell-ha202611-venv/bin/pytest -q
599 passed, 5 warnings in 6.46s
$ /tmp/axiell-ha2026110-venv/bin/pytest -q
599 passed, 5 warnings in 6.73s
$ /tmp/axiell-ha202611-venv/bin/ruff check .
All checks passed!
$ /tmp/axiell-ha202611-venv/bin/ruff format --check .
47 files already formatted
$ /tmp/axiell-actionlint/actionlint
(no output, exit 0)
$ docker run --rm -v /home/ronny/axiell/ha-axiell-libraries:/github/workspace:ro ghcr.io/home-assistant/hassfest:latest
Integrations: 1
Invalid integrations: 0
$ /tmp/axiell-ha202611-venv/bin/python scripts/check_release.py v0.4.0
Release tag and manifest agree: 0.4.0
```

Actual local Python is **3.14.7**, with Core and official `pytest-homeassistant`
**2026.11.1** in the target environment and **2026.11.0** in the minimum
environment. Ruff is **0.17.5**. The minimum remains the lowest tested version.
Warnings are the existing Core `web.Application` inheritance warning and four
backoff `asyncio.iscoroutinefunction` deprecations; no suppression was added.
Hassfest validated the new action schema, translations and icon as well as the
existing integration metadata/config flow. Actionlint and diff whitespace checks
passed. A bounded tracked-file audit found text files only, with no APK/XAPK,
network captures or private-research paths.

Installed Marketplace code tests load the prepared archive/manifest and compare
0.3.0 with 0.4.0. Release tests retain the manual/main-only CI gate, canonical
manifest/tag equality, immutable validated-SHA tag and reviewed release notes.
This proves offline packaging/update behavior, not a live 0.4.0 installation.

`axiell_libraries.renew_loan` requires explicit account and loan IDs. Positive
known fees and each server challenge need a separate one-use confirmation;
confirmation expires after ten minutes or unload/reload. A lost response causes
read reconciliation and an uncertain-outcome error, never a write replay. A
successful renewal with failed refresh remains explicitly successful. Admins
and trusted HA system contexts can call the action; no automatic renewal is
installed. See the [action guide](home-assistant-ui.md#renew-one-loan).

All three task reviews and the final whole-branch review approved the change
without blocking findings. [PR #5](https://github.com/RonnyAL/ha-axiell-libraries/pull/5)
contains the delivery report and current merge/check status. Hosted validation
at reviewed commit `509da8d` also passed:

- [Push CI](https://github.com/RonnyAL/ha-axiell-libraries/actions/runs/43481884142):
  Python 3.14.10; actual Core/harness 2026.11.0, 599 passed/5 warnings in 13.70s;
  actual Core/harness 2026.11.1, 599 passed/5 warnings in 14.81s.
- Ruff: all checks passed, 47 files already formatted. Official hassfest:
  invalid integrations 0. All four hosted jobs succeeded.

No live renewal, fee acknowledgement or provider challenge sequence was tested.
APK evidence establishes request shape and client behavior only. Browser action
rendering, real provider policy and a live Marketplace 0.4.0 update remain
owner-run checks. The existing wrapper uses AppID for TemplateID and the entry
card as the selected account UserID; different provider identity schemes need
separate evidence. Known-secret redaction cannot remove every possible personal
phrase in provider messages. Credentials, sessions and DeviceIDs remain isolated
and persistent as before.

## Previous: individual loan details and semantic releases

The owner now confirms live HA authentication, active-loan count, next due date
and overdue count, as well as Marketplace installation/update. This supersedes
the setup-failure status in the historical section below. New loan attributes,
dashboard browser layout, live cover loading and installation of a published
semantic release still need an owner-run check. No release or tag was created.

Implemented the [three-task plan](superpowers/plans/2026-11-13-loan-details.md)
using Superpowers TDD and independent task reviews:

| Task | Changes | Observed RED | Final focused GREEN |
| --- | --- | --- | --- |
| 1, `2933c90` | Models, synthetic fixtures, cache regressions, protocol | 57 failed / 79 passed | 143 passed |
| 2, `3a7ed27` | Sensor attributes, read-only to-do descriptions, UI guide and actual-template tests | 6 entity failures; 6 template failures | 24 passed |
| 3, `d76b508` | Release guard/workflow, actual Marketplace tests, manifest and release docs | 44 release failures; 1 Marketplace failure | 55 passed |

All final focused runs have the same five known upstream warnings. Task 2 also
observed a Recorder regression fail without the attribute exclusion and pass
with it through HA's actual `StateAttributes.shared_attrs_bytes_from_event`.
The exact documented YAML/Jinja is rendered by HA's Template implementation;
these tests are not a browser-rendering claim.

Local final implementation checks at `d76b508`:

```text
$ /tmp/axiell-ha202611-venv/bin/python -m pytest -q
439 passed, 5 warnings in 4.83s
$ /tmp/axiell-ha2026110-venv/bin/python -m pytest -q
439 passed, 5 warnings in 5.07s
$ /tmp/axiell-ha202611-venv/bin/ruff check .
All checks passed!
$ /tmp/axiell-ha202611-venv/bin/ruff format --check .
39 files already formatted
$ /tmp/axiell-actionlint/actionlint
(no output, exit 0)
$ docker run --rm -v /home/ronny/axiell/ha-axiell-libraries:/github/workspace:ro ghcr.io/home-assistant/hassfest:latest
Integrations: 1
Invalid integrations: 0
```

Actual local Python is **3.14.7**; Core and official `pytest-homeassistant` are
**2026.11.1** in the target environment and **2026.11.0** in the minimum
environment. Ruff is **0.17.5**. The minimum remains the lowest version actually
tested, not an assertion that older releases work. The five warnings are
upstream Core `web.Application` inheritance and four backoff
`asyncio.iscoroutinefunction` deprecations; none were suppressed.

The release tests execute the real publication shell with an offline fake `gh`.
They verify strict tag/manifest agreement, main-only reusable CI, exact validated
SHA, reviewed nonempty notes, immutable tag creation, and failure before
publication. Actual installed Marketplace code selects `v0.3.0`, downloads its
tag archive, extracts/loads manifest `0.3.0`, and compares it with older/equal/
newer versions and a previous installed commit hash. Repository structure,
metadata, config flow and minimum-version checks also remain covered.

Decisions and tradeoffs recorded during execution:

- Reuse the existing four entities and expose structured data on Active loans.
  This avoids entity churn; a future calendar would be an additional feature.
- Retain only selected original fields internally and expose recognized
  bibliography labels. A provider using other labels needs a tested alias.
- Prepare `0.3.0`/`v0.3.0` while preserving the owner's release hold. Marketplace
  hash labels remain until a real GitHub Release is published and installed.

No new protocol requests or authentication changes were needed. Subject/English
metadata aliases remain defensive; new provider schemas, unusual routing and
external image availability are not proven by offline tests. Credentials,
sessions and persistent DeviceIDs remain entry-local under the existing tests.

## Previous: authentication parity and safe setup references

At the time of this earlier work, the owner reported successful Marketplace
installation/update but failing HA credentialed setup. Their Python PoC was live-verified through
bootstrap, LoginPreSession, LoginCheckSession, loans and catalogue, with no
observed processing-host change. Live integration success had not yet been
confirmed (it is now confirmed above). The corrected request contract and
remaining model/routing/schema differences are in [protocol.md](protocol.md).

Task 1 (`c0e3b5f`) corrected the request/response contract. Task 2 adds only
allowlisted setup stage/reason/validated-status references and translated HA
placeholders. Routing/bootstrap HTTP 401/403 is a provider failure, while the
existing explicit auth-stage rejection behavior and bounded expiry recovery
remain. Known API rejection is distinguished from schema failure; missing
pre-session tokens have a separate reference. Existing SolusError subclasses
and no-argument constructors remain compatible. No raw provider message, body,
URL, header, cookie, account/device identifier or exception text enters the
reference. Programming failures propagate. No runtime dependency, version,
release workflow, publication or repository visibility change was made.

Task 2 files: `custom_components/axiell_libraries/{solus.py,config_flow.py,strings.json,translations/en.json,translations/nb.json}`,
`tests/{test_config_flow.py,test_solus.py}`, `README.md`, `CHANGELOG.md`,
`docs/{protocol.md,library-discovery.md,validation.md}` and the authentication
parity plan completion record (including the controller's existing Task 1
checkbox/NB-scope edits). The NB directory research is preserved with primary
links; no XML, contact data or guessed Solus mapping was added.

```text
$ /tmp/axiell-ha202611-venv/bin/python -m pytest -q tests/test_config_flow.py -k 'real_setup_diagnostics or locator_diagnostics' --tb=short
RED: 53 failed, 13 deselected, 5 warnings in 0.88s
GREEN (final): 53 passed, 14 deselected, 5 warnings in 0.79s
$ /tmp/axiell-ha202611-venv/bin/python -m pytest -q tests/test_config_flow.py tests/test_solus.py tests/test_auth_protocol.py --tb=short
204 passed, 5 warnings in 1.66s
$ /tmp/axiell-ha202611-venv/bin/python -m pytest -q tests/test_solus.py -k 'generic_errors or diagnostic_reference or login_failure_retains' --tb=short
RED constructor compatibility check: 4 failed, 8 passed, 110 deselected, 5 warnings in 0.19s
GREEN: 12 passed, 110 deselected, 5 warnings in 0.14s
$ /tmp/axiell-ha202611-venv/bin/python -m pytest -q
318 passed, 5 warnings in 3.69s
$ /tmp/axiell-ha2026110-venv/bin/python -m pytest -q
318 passed, 5 warnings in 3.53s
$ /tmp/axiell-ha202611-venv/bin/ruff check .
All checks passed!
$ /tmp/axiell-ha202611-venv/bin/ruff format --check .
34 files already formatted
$ docker run --rm -v /home/ronny/axiell/ha-axiell-libraries:/github/workspace:ro ghcr.io/home-assistant/hassfest:latest
Integrations: 1
Invalid integrations: 0
$ /tmp/axiell-ha202611-venv/bin/python scripts/check_release.py 0.2.0
Release tag and manifest agree: 0.2.0
$ git diff --check
(no output, exit 0)
```

Actual versions were printed immediately before each full suite with:

```text
<venv>/bin/python -c 'import sys; from importlib.metadata import version; print(sys.version); print({name: version(name) for name in ("homeassistant", "pytest-homeassistant", "pytest", "aiohttp", "aioresponses", "ruff")})'
2026.11.1 environment: Python 3.14.7; homeassistant 2026.11.1; pytest-homeassistant 2026.11.1
2026.11.0 environment: Python 3.14.7; homeassistant 2026.11.0; pytest-homeassistant 2026.11.0
Both: pytest 9.0.3; aiohttp 3.14.5; aioresponses 0.7.9; Ruff 0.17.5
```

RED failed on expected missing diagnostic placeholders and incorrect
routing/bootstrap invalid-auth classification. During implementation, one
intermediate run had 17 failures/36 passes because the test initially expected
only `reference`; HA correctly adds its standard reauth `name` placeholder.
The test now preserves/checks that framework behavior. The no-argument error
constructor regression failed with TypeError before compatibility was restored.
All final checks exited 0; the two intentional RED runs exited 1.

All API tests remain offline. Escalation allowed HA's local event-loop sockets
and the loopback synthetic cookie server, with the official harness network
guard retained. The same five upstream warnings remain visible (one Core
web.Application subclass and four backoff asyncio.iscoroutinefunction sites);
no warning suppression was added. Real HA forms and loaded en/nb translations
are formatted with hostile synthetic secret markers and checked for safe
references. This tests backend rendering context, not the browser frontend.
Retries, initial setup, reauth/reconfigure, stable DeviceID, token cleanup and
managed-session detachment are covered. Existing cookie-present/absent,
session-expiry recovery and partial-catalogue regressions still pass.

Metadata/document checks parsed strings/en/nb JSON, compared leaf keys and
reference placeholders, verified changed documentation's local link targets,
and confirmed manifest `0.2.0` with empty requirements. Official hassfest also
validated manifest/translations/config flow. Release checking only validates
version agreement; it does not create a tag or release. Primary discovery/NB
facts were reconciled against the supplied bounded investigations, including
later HTTP 200 follow-ups superseding earlier HTTP 403 conclusions. No new
external probes or live integration requests were performed in this task.

Self-review checked finite output construction, innermost-stage preservation,
HTTP classification, no credential-retry loops, identity persistence, unchanged
Task 1 request bytes and successful/abort semantics. No remaining findings were
identified. Remaining live API assumptions and the next owner step are in
[Unverified behavior and handoff](#unverified-behavior-and-handoff).

## Historical: public locator response correction

The owner's manual LocationID failed before credential entry because discovery
required uppercase `OK`, a `Name`, and a nearby `Status`/`Detail` wrapper.
Anonymous public probes on 2026-11-13 instead observed lowercase `ok`, no `Name`,
and direct nearby rows under `d`, each with its own status. The trusted HTTPS
repo returned a valid Solus processing origin. Only safe structural facts were
recorded; no raw response, credentials, DeviceID or account request was used.

Discovery now checks string success statuses case-insensitively and falls back
to the valid LocationID for missing/blank string names. Direct nearby lists
validate all row statuses before repo routing; existing wrapper responses still
work without per-row statuses. Required identity, malformed Name types, HTTPS
origins, repo routing and authentication parsing retain their checks. The
integration remains unreleased version `0.2.0`; no migration or new account
identity is needed.

Separately, after the fix, the controller ran the actual corrected client
anonymously. `async_lookup_location('Malselv')` returned LocationID and fallback
name `Malselv`, using `https://process-m-eu1.sol.us` as processing origin.
`async_find_nearby(69.0, 19.0)` parsed/resolved one candidate; that public sample
candidate was not Malselv. This does not check nearby results for the owner's HA
coordinates. These successful typed-result checks are distinct from the initial
response-shape observations, and used no credentials, DeviceID, login or account
requests. No raw response is saved.

Changed files: `custom_components/axiell_libraries/solus.py`,
`tests/test_solus.py`, `tests/test_config_flow.py`, `docs/protocol.md` and this
ledger. The HTTP-boundary regressions use synthetic values and `tests/http.py`.
Real HA manual lookup (including a provider-failure retry) and nearby selection
reach credentials using the real locator parser, retain a single DeviceID and
perform no login. Existing duplicate-account, lifecycle and auth tests remain.

```text
$ /tmp/axiell-ha202611-venv/bin/python -m pytest -q tests/test_solus.py tests/test_config_flow.py -k 'observed_locator or locator_rejects_invalid_status or locator_direct_rows' --tb=short
RED: 16 failed, 32 passed, 72 deselected, 5 warnings in 0.51s
GREEN: 48 passed, 72 deselected, 5 warnings in 0.33s
$ /tmp/axiell-ha202611-venv/bin/python -m pytest -q
224 passed, 5 warnings in 2.72s
$ /tmp/axiell-ha2026110-venv/bin/python -m pytest -q
224 passed, 5 warnings in 2.71s
$ /tmp/axiell-ha202611-venv/bin/ruff check .
All checks passed!
$ /tmp/axiell-ha202611-venv/bin/ruff format --check .
29 files already formatted
$ git diff --check
(no output, exit 0)
```

RED exited 1 for the expected locator exceptions and config-flow step assertions;
all GREEN and quality commands exited 0. The final suite adds three
characterization cases confirming authentication still rejects `SUCCESS`, `ok`
and `OK`, and clarifies direct-row missing-identity coverage. Both actual
Core/official harness pairs were verified via installed package metadata:
2026.11.1 in `/tmp/axiell-ha202611-venv`, 2026.11.0 in
`/tmp/axiell-ha2026110-venv`, both Python 3.14.7.

Exactly five upstream warnings remain unsuppressed in both environments:
`homeassistant/components/http/server.py:223` inherits aiohttp `web.Application`;
backoff uses deprecated `asyncio.iscoroutinefunction` at `_decorator.py:201`
and `_async.py:11`, `:127`, `:128`. No new warnings appeared.

Implementer self-review checked observed and legacy formats, rejected statuses
before routing, required identity, safe destinations, persistent DeviceID and
the diff's privacy boundary. Independent task and whole-branch reviews found no
code findings. The fix is in [PR #2](https://github.com/RonnyAL/ha-axiell-libraries/pull/2);
the latest commit's hosted validation is attached to its
[checks](https://github.com/RonnyAL/ha-axiell-libraries/pull/2/checks).
No live integration login,
account/loan request, or provider call was performed by the implementer. The
credentialed assumptions below and in `protocol.md` remain unverified.

After the owner merges and updates the installed integration to the fix,
restart Home Assistant and retry manual `Malselv` lookup or nearby selection.
Because `0.2.0` is unreleased and unchanged, ensure the installed source includes
the fix rather than relying on a version bump. Existing entry identities and
stored DeviceIDs need no replacement. Enter credentials only in Home Assistant.

## Previous: Core 2026.11 and Marketplace preparation

Branch `feat/ha-2026-11-marketplace` targets integration version `0.2.0`, which
is not published. The repository remains private. All three tasks passed
independent review. Whole-branch review found one release help-argument bypass;
commit `e6060f4` fixed it with RED/GREEN evidence below. Scoped re-review confirmed
the finding addressed with no new breakage. All code reviews are complete.
The original v1 evidence below is historical, not the current support statement.

### Runtime and command evidence

Final fix complete suites used actual installed Core and the matching official
`pytest-homeassistant`, not a Core dependency override. Both environments used
Python **3.14.7**, aiohttp **3.14.5**, aioresponses **0.7.9**, pytest **9.0.3**,
aiogithubapi **26.0.0** and Ruff **0.17.5**.

| Environment | Core / official harness | Command | Recorded result |
| --- | --- | --- | --- |
| `/tmp/axiell-ha202611-venv` | 2026.11.1 / 2026.11.1 | `bin/python -m pytest -q` | `173 passed, 5 warnings in 2.34s` |
| `/tmp/axiell-ha2026110-venv` | 2026.11.0 / 2026.11.0 | `bin/python -m pytest -q` | `173 passed, 5 warnings in 2.24s` |

Historical Task 2 runs before the final review fix recorded `171 passed,
5 warnings in 2.33s` on Core 2026.11.1 and `171 passed, 5 warnings in 2.23s`
on Core 2026.11.0. The two help-argument regressions raise the local total to 173.

Commands above append `bin/...` to the environment path. Other final commands:

```text
/tmp/axiell-ha202611-venv/bin/ruff check .
All checks passed!
/tmp/axiell-ha202611-venv/bin/ruff format --check .
28 files already formatted
/tmp/axiell-actionlint/actionlint -color
(no output, exit 0)
/tmp/axiell-ha202611-venv/bin/python scripts/check_release.py 0.2.0
Release tag and manifest agree: 0.2.0
git diff --check
(no output, exit 0)
```

Actionlint was 1.7.11 (Go 1.25.7, linux/amd64). After updating workflow actions to
`actions/checkout@v7.0.1` and `actions/setup-python@v7.1.0` (official Node 24
releases) in `fdaa236`, actionlint and diff checks again exited 0.

Earlier Task 2 official container validation (not repeated for this release-only
fix):

```text
docker run --rm -v /home/ronny/axiell/ha-axiell-libraries:/github/workspace:ro ghcr.io/home-assistant/hassfest:latest
Integrations: 1
Invalid integrations: 0
(exit 0)
```

Image identity:
`ghcr.io/home-assistant/hassfest@sha256:da6522993280166fe072704989a2b4c33e639e8ceb69c8ab6ad7ec5045c1a1e3`.
Before fixes hassfest rejected manifest ordering and the `__manual__` translation
key; the valid `manual` key now agrees across flow, strings and translations.
This supersedes the historical statement below that hassfest was unavailable.

### Coverage and migration boundary

The complete suites retain auth/HTTPS/error sanitization, discovery/manual
fallback, duplicate-before-login, independent multiple accounts, persistent
DeviceID and reauth/reconfigure, malformed dates, explicit empty loans, session
expiry/recovery, partial catalogue failure, sensors and read-only to-do coverage.
A strengthened existing-entry lifecycle regression forbids generating a new
DeviceID and verifies original entry data, schema and login IDs through setup,
reload, unload and setup. A deliberate regeneration mutation failed the test.
No separate process restart or live account was tested.

The discontinued custom-component harness was replaced by the matching official
Core harness. Both requirements files share test tools; the official bootstrap
setting `-p no:respx` is in pyproject.toml. Existing APIs needed no production
behavior changes. The narrow `tests/http.py` response-class adapter supplies the
constructor writer argument missing in aioresponses 0.7.9 for aiohttp 3.14.5;
it retains real ClientResponse behavior without patching Core/aiohttp.

Exactly five upstream warnings remain visible: Core's HomeAssistantApplication
subclasses aiohttp web.Application, and four backoff 2.2.1 sites use deprecated
asyncio.iscoroutinefunction. No warning filters were added.

Offline Marketplace tests use the actual installed Core repository metadata,
content resolution, source archive extraction, manifest loading, domain-collision
and minimum-version validators. An isolated subprocess imports config flow,
sensors and to-do from the extracted integration with no checkout on its path.
Only the small Marketplace manager context is synthetic. This proves local
metadata/structure and importability; it does not prove GitHub access, live
installation/download, public availability, browser rendering or update polling.

### CI, release and review handoff

[PR #1](https://github.com/RonnyAL/ha-axiell-libraries/pull/1) was opened by
the controller. Hosted Validate completed successfully for commit `fdaa236` in
the [push run](https://github.com/RonnyAL/ha-axiell-libraries/actions/runs/43383733854)
and [PR run](https://github.com/RonnyAL/ha-axiell-libraries/actions/runs/43383785554).
The PR log prints Python **3.14.10**, distinct from local **3.14.7**, and asserts
exact Core/harness pairs. Core 2026.11.0: `171 passed, 5 warnings in 4.09s`;
Core 2026.11.1: `171 passed, 5 warnings in 3.38s`. Official hassfest reports
`Invalid integrations: 0`; Ruff reports `All checks passed!` and
`28 files already formatted`. This historical 171-test evidence applies to
`fdaa236`. The documentation head `1d31757` also passed the controller-observed
[PR run](https://github.com/RonnyAL/ha-axiell-libraries/actions/runs/43384542304)
and [push run](https://github.com/RonnyAL/ha-axiell-libraries/actions/runs/43384535505).
These hosted passes predate the final fix. The latest commit's execution evidence
is attached to the [PR checks](https://github.com/RonnyAL/ha-axiell-libraries/pull/1/checks);
the controller requires all jobs to pass before marking the PR ready. Scoped
fix review confirmed both help arguments are rejected and found no new issue.
The Release publishing workflow has not been executed.

Whole-branch review found that argparse's default `-h`/`--help` handling returned
success before validating the dispatch version. `scripts/check_release.py` now
disables automatic help, so both flags fail with exit 2. The two regressions in
`tests/test_release.py` parse the workflow and execute its actual validation
command with each flag in `RELEASE_VERSION`; they do not invoke any publishing
step. Existing normal/future version, manifest-mismatch, prefix, shell-shaped,
trailing-newline, path and empty-value cases remain unchanged.

```text
/tmp/axiell-ha202611-venv/bin/python -m pytest -q tests/test_release.py --tb=short
RED: 2 failed, 8 passed, 5 warnings in 0.42s
GREEN: 10 passed, 5 warnings in 0.39s
```

Both RED failures were the expected `0 == 2` return-code assertions: the command
printed help and returned success. GREEN confirms exit 2, a missing-tag error
and empty stdout for both inputs. No integration behavior or workflow publishing
permissions changed. API assumptions and remaining live checks are unchanged.

Validate runs official hassfest, Ruff and the full exact-pair runtime matrix on
push/PR and as a reusable workflow, using read-only contents access. Release
accepts a plain manifest version only from main, reruns all validation, checks
exact manifest/tag agreement, atomically creates a new tag at the validated SHA,
then publishes a GitHub source release. Existing tags are rejected; only the
publishing job has contents-write permission. No attached ZIP or catalog
submission is needed. Publication failure after tag creation requires manual
investigation/recovery, not a blind rerun or automatic tag movement.

Public Add from link requires merge, the owner's separate visibility decision
and a published release. No visibility change, merge, tag or release publication
was performed in these tasks. The owner still needs to check Marketplace
install/download/update with GitHub connected, restart after updating loaded
code, browser rendering, actual HA process restart and the complete credentialed
Solus flow. Credentials belong only in the owner's HA UI. The live-protocol
assumptions listed below remain unchanged.

## Historical v1: Core 2026.2.3

The remaining implementation evidence records the earlier Python 3.13 / Core
2026.2.3 work. Its tool availability, dependencies and no-push statement apply
to that earlier stage, before the 2026.11 migration and draft PR above.

### Historical environment and implementation choices

Development used local branch `feat/axiell-libraries-v1`. The managed worktree
was not writable in the sandbox, so work continued in the original writable
checkout on that isolated feature branch; `main` was not changed. No push,
merge, publication or repository visibility command was performed.

Full HA tests used Python **3.13.15**, HA **2026.2.3**,
`pytest-homeassistant-custom-component` **0.13.316**, pytest **9.0.0**,
aioresponses **0.7.9** and Ruff **0.17.5**, then pinned in
`requirements-dev.txt` (since replaced by the current pins).
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
All six task reviews are complete. The final whole-branch review identified
one loan-validation issue; commit `a481e30` fixed it and scoped re-review
confirmed it addressed with no new breakage or remaining findings.

| Task / local commit | Files changed | RED → GREEN and final regression output | API assumptions / next task |
| --- | --- | --- | --- |
| 1 Models / `51ff59d` | `cc/models.py`, `cc/const.py`, `tests/test_models.py`, `pyproject.toml`, `docs/protocol.md` | Parser interface stub: `41 failed in 0.02s`; final full `.venv/bin/python -m pytest -q`: `41 passed in 0.03s`. Ruff: `All checks passed!`; changed files: `3 files already formatted`; diff check empty. Full HA runner independently: `41 passed in 0.17s`. | Optional date suffix is defensive, not observed live. Next: client. |
| 2 Client / `76696fe` | `cc/solus.py`, `cc/__init__.py`, `cc/manifest.json`, `tests/test_solus.py`, `requirements-dev.txt`, `docs/protocol.md` | Missing client: `1 error in 0.06s`; initial `26 passed in 0.17s`; HTTP-expiry regression: `1 failed, 34 passed in 0.22s` → `35 passed in 0.20s`; full `76 passed in 0.27s`. Ruff: `All checks passed!`; diff check empty. | Exact locator schema, bootstrap descriptors, optional repo AuthServer and JSON expiry codes unverified. Next: flow. |
| 3 Flow / `0483cb0` | `cc/config_flow.py`, `cc/strings.json`, `cc/translations/{en,nb}.json`, `cc/solus.py`, `tests/{conftest,test_config_flow,test_solus}.py`, `pyproject.toml`, `docs/protocol.md` | Real-flow/auth-status RED: `12 failed, 35 deselected in 0.87s` → focused `47 passed in 0.39s`; flow `10 passed in 0.14s`; full `89 passed in 0.57s`. Ruff: `All checks passed!`; `10 files already formatted`. | Only synthetic explicit `failure` means JSON credential rejection; unknown status is provider failure. Browser selector rendering unverified. Next: coordinator. |
| 4 Coordinator / `1b2babc` + review fix `8eff1ed` | `cc/coordinator.py`, `cc/models.py`, `cc/solus.py`, `tests/{test_coordinator,test_models,test_solus}.py`, `docs/protocol.md` | Coordinator stub: `27 failed in 0.51s` → `27 passed in 0.27s`. Metadata model regression: `1 failed, 41 deselected in 0.12s`; full `117 passed in 0.78s`. Review found queued expiry/recovery state bug: corrected real-client RED `3 failed, 1 passed in 0.18s`, transient recovery RED `1 failed in 0.13s` → `5 passed in 0.15s`; combined client/coordinator `70 passed in 0.56s`; full `122 passed in 0.78s`. Ruff: `All checks passed!`; `12 files already formatted`. | Cache, concurrency, source validation and bounded recovery are integration policies. No new live observations. Next: entities/lifecycle. |
| 5 Entities / `65e3cd7` | `cc/__init__.py`, `cc/sensor.py`, `cc/todo.py`, `cc/manifest.json`, `cc/strings.json`, `cc/translations/{en,nb}.json`, `tests/{test_entities,test_config_flow}.py`, `docs/home-assistant-ui.md` | Missing setup: `9 failed in 0.19s` → `9 passed in 0.18s`. Full run caught config-flow fixture scope: `1 failed, 130 passed in 0.92s`; corrected fixture → `131 passed in 0.89s`. Extended lifecycle checks: `12 passed in 0.21s`; full `134 passed in 0.87s`. Ruff: `All checks passed!`; `15 files already formatted`; diff check empty. Controller independently checked `134 passed in 0.90s`. | Reload simulates restart using unchanged entry data with ID generation forbidden; actual process restart untested. Covers are optional external links. Next: final gate. |
| 6 Documentation / `fd72d1c`, final fix `a481e30` | `README.md`, `CODEX_START.md`, `docs/{home-assistant-ui,protocol,validation}.md`, plan checkboxes | Initial documentation-only gate (before final review): `134 passed in 0.90s`; Ruff: `All checks passed!`; `22 files already formatted`; diff check empty. Installed HA loader/translations: `1 passed in 0.09s`. | Final review found a loan-row validation gap, fixed and reviewed below; final suite 159 tests. Next: optional owner-only local HA UI smoke test. |

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
was performed. Scoped final re-review confirmed the finding addressed with no
new breakage. Task 6 and the whole-branch review are complete; no findings remain.

Final independent verification after review: full offline suite `159 passed in
1.07s`; installed HA loader/translations probe `1 passed in 0.09s`; Ruff
`All checks passed!`; formatting `23 files already formatted`; `git diff
--check` produced no output. All commands exited 0.

## Historical final commands and available HA tooling

The initial documentation gate, before the final review fix, ran from the
checkout in the verified environment (the later 159-test result is recorded above):

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

At this historical stage, `hassfest` was **unavailable**: its source-tree
tooling was not shipped in the installed Home Assistant distribution. It was
not run then; the current successful container run is recorded above. The available runtime checks are narrower than hassfest's full
manifest/strings validation.

Privacy inspection used `git ls-files`, tracked-file byte/suffix inspection,
JSON parsing and filename-only `git grep -Il` searches for credential fields and
common token/private-key patterns. The original 32 pre-documentation tracked
files were text only, with no APK/XAPK, archive, HAR/packet capture, private-research path or
NUL bytes. Credential-field matches were inspected as implementation references
and explicit synthetic `TEST` values. Token/private-key pattern grep returned
no matches (exit 1, expected). The three checked-in JSON fixtures are synthetic.
This is a bounded repository inspection, not a claim that pattern matching can
detect every possible secret. Ignored `research/private/` was neither read nor
staged. A post-commit audit checked all 33 tracked files and found no prohibited
binaries/captures. Final documentation is text and contains no owner credentials.

## Unverified behavior and handoff

The current authentication/diagnostics evidence above supersedes earlier client
metadata and case-sensitive-success statements in the historical task records.
Remaining live assumptions are the generic `PlatModel: Home Assistant` label,
optional repo `AuthServer`, actual negative-auth/JSON-expiry codes, upstream
cookie requirements, and the strict single-label HTTPS Solus same-origin policy.
A live processing-host switch was not observed in the owner's successful PoC.

Compatibility is tested only on Core 2026.11.0/2026.11.1. The owner reports
Marketplace installation/update, but HA credentialed setup still fails before
this fix. Browser rendering, an actual HA process restart and successful live
integration setup remain owner-run checks. Offline translated form rendering,
reload, reauth/reconfigure and cookie presence/absence are covered separately.

Next: install the reviewed fix, restart HA, run the
[local HA UI smoke test](../README.md#optional-owner-run-live-smoke-test) and
report only the UI error/reference, HA/integration version and failed step if
setup fails. Enter credentials in HA only; retain the existing entry/DeviceID
for PIN changes. Do not record or share HTTP bodies or account data. Publication,
version changes and any future directory mapping remain separate owner decisions.
