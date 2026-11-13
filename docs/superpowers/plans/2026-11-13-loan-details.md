# Individual Loan Details Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Expose useful individual loan details through existing HA entities and prepare validated semantic releases.

**Architecture:** Extend the current pure models and active-loans sensor; keep three sensors, one read-only to-do list, and the existing per-entry coordinator/cache. Publish structured attributes without recording rich book data. Validate versioned source releases through the existing CI workflow.

**Tech Stack:** Python 3.14, Home Assistant 2026.11.1/2026.11.0, aiohttp, pytest-homeassistant, Ruff, hassfest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-13-loan-details-design.md`

## Global Constraints

- Target Home Assistant 2026.11.1; minimum 2026.11.0, both actually tested.
- Exactly one library/card per entry; persistent `secrets.token_hex(8)` DeviceID.
- Preserve working async authentication; no new endpoints or write operations.
- Offline synthetic tests only; never commit account data, credentials or captures.
- Keep three sensors and one read-only to-do entity per entry; no calendar or per-loan entities.
- `LoansGet` owns membership/dates/status; cached `RecordGet` owns optional enrichment.
- No full raw payload exposure; selected original `api_fields` remain internal.
- Prepare manifest `0.3.0` and tag `v0.3.0`; no publication during implementation.

## Review Focus

- A subtitle that is a series name must not become the author (Task 1).
- Multiple copies with the same record retain different due dates/status while sharing only catalogue metadata (Task 1).
- Arbitrary account-shaped metadata and internal originals never enter HA state or descriptions (Task 2).
- An unavailable cover never causes an HTTP fetch or prevents displaying title/due text (Tasks 1–2).
- Release validation failures, help arguments or tag/manifest disagreement cannot reach publication (Task 3).

## Execution and verification

Use `/tmp/axiell-ha202611-venv/bin/python -m pytest` for target tests and
`/tmp/axiell-ha2026110-venv/bin/python -m pytest` for minimum. Tests requiring
HA local sockets may need sandbox escalation, but all API data stays offline.
Ruff lives in the target venv. Each implementer runs focused RED/GREEN checks,
then the full target suite and Ruff before committing. Controller runs both
versions, hassfest, actionlint and hosted CI for the final artifact.

### Task 1: Preserve and normalize individual loan metadata

**Files:** Modify `custom_components/axiell_libraries/models.py`, `tests/test_models.py`, `tests/test_coordinator.py`, `tests/fixtures/loans_get.json`, `tests/fixtures/record_get.json`, `docs/protocol.md`. Change coordinator implementation only if a regression exposes a real cache defect.

**Interfaces:** Keep `Loan.from_api`, `CatalogueRecord.from_api`, `Loan.with_catalogue`. Add `Loan.subtitle`, `item_id` (str or None), `renewal_count` (int or None), `renewal_cost` (int/float or None), `overdue_specified` (bool or None). Both models have immutable `api_fields` Mapping of selected original scalar fields. Add Loan publisher/publication_year/language/subjects properties (str or None), `bibliographic_metadata` (filtered Mapping), and `as_dict() -> dict[str, Any]` with exactly the public keys in the spec. Dates become ISO strings only in as_dict.

- [x] Write regression tests for subtitle-only author None, explicit loan author fallback, catalogue author priority, stable title/IDs/date/status after enrichment, large cover priority with invalid-large fallback, malformed/negative/bool counts and costs, original selected fields immutable and unknown fields dropped, scalar metadata aliases and unknown keys excluded from as_dict. Existing .NET date tests remain authoritative. Demonstrate failures before implementation.
- [x] Implement the model changes. Use explicit allowlists, not arbitrary recursive raw copies. Original loan scalar keys: loanID/recordID/itemID/title/author/subtitle/dueObject/canRenew/renewalCost/RenewalCount/RenewalsRemaining/OverdueSpecified/Overdue/Source/ISBN/imageUrl/description. Catalogue scalar keys: RecordID/Title/Author/ISBN/Description/Format/ImageUrl/ImageUrlLarge. Never retain dueDisplay or credentials. MainMetadata remains internally immutable.
- [x] Supported bibliographic labels: Utgiver/Publisher, Utgitt/Year/Publication year, Språk/Language, Emne/Emner/Subject/Subjects (case-insensitive). Keep values as strings. No invented subject splitting; unknown/malformed values are absent.
- [x] Add coordinator regressions for two loans sharing a cached record but independent IDs/dates/status; later renewal changes due/flags without extra RecordGet; a returned loan disappears; a new record triggers enrichment; partial failure and stale-cache retry preserve available bibliographic data; another entry remains isolated. Update old subtitle-as-author assertions to the new explicit requirement. Retain current cache limits/TTL/concurrency.
- [x] Run focused model/coordinator tests GREEN, full target pytest and Ruff. Update protocol field mapping and record the owner's live authentication/aggregate confirmation narrowly. Commit green changes and write task report with commands/counts and RED evidence.

### Task 2: Expose loan dictionaries and document usable dashboards

**Files:** Modify `custom_components/axiell_libraries/sensor.py`, `todo.py`, `tests/test_entities.py`, `README.md`, `docs/home-assistant-ui.md`; add `tests/test_loan_presentation.py` if needed to keep entity tests focused.

**Interfaces:** Consume `Loan.as_dict()` and `Loan.bibliographic_metadata` from Task 1. Active sensor `extra_state_attributes` returns `{"loans": [...]}`; other sensors do not duplicate it. Set `_unrecorded_attributes = frozenset({"loans"})` on the relevant entity class, using HA's current supported mechanism. Existing entity unique IDs, to-do UIDs and supported_features=0 remain unchanged.

- [x] Add failing actual HA state/service tests: JSON-safe loan attribute contents; independent loan IDs for same record; optional values null; empty response list clears; renewed date/status and returned/new loans update; different entries expose different details and preserve DeviceIDs. Unknown/account-shaped metadata and api_fields excluded; no duplicate rich attrs on other sensors. Exercise Recorder's exclusion path, not only a class constant assertion.
- [x] Add failing todo description assertions for separate Subtitle and accurate Author plus language/subjects/circulation fields where available; preserve provider labels for bibliographic metadata. Keep all mutation services rejected. No new entities or supported write flags.
- [x] Implement the minimal entity changes. No cover requests; use direct URL metadata and text fallback. For the no-cover-request check, keep mocked APIs/local socket guard and assert no HTTP image route is needed to complete setup/refresh.
- [x] Add a documented standard Markdown dashboard card with a state_attr loop, title, author/subtitle distinction, due date, overdue/renewability, optional image. Include missing/unavailable state handling and text independent of image success. Add template examples for lists, overdue and renewable books and a todo.get_items action example. Test the Jinja template with HA's real Template renderer using synthetic data, including absent images and unavailable sensor. Explain browser-provider access, optional/missing images, Recorder exclusion and fields/types.
- [x] Correct stale documentation: owner verified authentication/aggregate sensors and Marketplace install/update; new structured dashboard rendering remains owner-tested later. Explain six-hour status refresh/24-hour catalogue TTL and manual refresh. Run focused RED/GREEN, full target suite, Ruff; commit and report exact evidence.

### Task 3: Validate canonical semantic releases end to end

**Files:** Modify `scripts/check_release.py`, `.github/workflows/release.yaml`, `tests/test_release.py`, `tests/test_marketplace.py`, `custom_components/axiell_libraries/manifest.json`, `README.md`, `CHANGELOG.md`; create `docs/releases/0.3.0.md` and `docs/releases.md` as needed.

**Interfaces:** Canonical numeric input/version `0.3.0`; canonical tag `v0.3.0`. Guard accepts canonical vX.Y.Z tag only, verifies numeric remainder matches a valid numeric manifest SemVer exactly; keeps `add_help=False` and nonzero on invalid/help input. Workflow derives tag from the numeric input safely through an environment variable, validates before any GitHub mutation, creates immutable tag at validated GITHUB_SHA, publishes release title numeric version and reviewed notes file.

- [x] Add failing guard tests for valid prefix/numeric match, invalid/leading-zero/prerelease/mismatched/help/injection-shaped strings; error output must stay static. Add a subprocess test executing the actual workflow publish step with a fake gh executable that records arguments: success creates exact ref at validated SHA then release with the notes file; rejected versions and failed tag creation never publish. Validate main-only/needs-validation binding from parsed workflow. Never call real gh from tests.
- [x] Add actual installed-Core Marketplace tests selecting a mocked published `v0.3.0` release, using its tag archive, extracting numeric `0.3.0` manifest and accepting it. Assert newer/older version comparison and preserve existing metadata/structure/config-flow/floor tests. Use installed code, not a replacement version parser.
- [x] Implement the release guard/workflow, bump manifest to 0.3.0, add reviewed release notes and update release docs. Explain original hash cause, tag versus published release, prefix normalization, immutable tags, update delay/GitHub connection, failure recovery, main-only validated SHA, and why no release has yet been published. Do not publish or create tags in this task.
- [x] Run focused RED/GREEN, full target suite, Ruff and actionlint. Commit green changes and report exact evidence. Controller will run minimum, hassfest and CI, perform final review, update validation ledger and create PR.
