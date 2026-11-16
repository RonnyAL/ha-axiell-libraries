# Snapshot Restoration Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development and TDD.

**Goal:** Restore one coherent stale account snapshot before provider contact,
with a real refresh timestamp and native read-only refresh control.
**Architecture:** Versioned private atomic HA Store, existing coordinator for all
reads/recovery/locking, shared entities deriving values from its one snapshot.
**Tech Stack:** Python 3.14, HA/Core official harness 2026.11.0 and 2026.11.1.
**Spec:** `docs/superpowers/specs/2026-11-16-snapshot-restoration-design.md`

## Global Constraints

- Preserve v0.5.1 status classification, retries, Retry-After, DeviceID/entity IDs,
  session recovery, renewal consent and authorization; no live provider writes.
- Never mark restored data fresh, manufacture an empty snapshot on error, or use
  restored data/consent as evidence that a renewal succeeded.
- Persist only allowlisted normalized loan/display fields, historical timestamp,
  hashed account binding, entry ID and finite withholding policy. Never persist
  raw responses, auth/client/config dictionaries, api_fields or renewal state.
- Withhold loan content after credential/security failures until a successful
  read, including across reloads. Store failure must not fail a successful read.
- Keep Recorder loan exclusions, sanitized logging and English/Norwegian support.
- Submit a PR and run complete supported CI. Do not merge, release or deploy.

## Review Focus

- Background provider latency/failure must not delay cached platform availability.
- Cache save, cancellation, unload, removal and identity updates must not resurrect
  removed/cross-account data or release the operation lock before save completion.
- Prior security/credential withholding must survive transient errors/reload and
  failed marker persistence; disk-total-failure limits must be explicit.
- A restored empty account differs from invalid/missing cache; duplicate IDs,
  malformed dates/types and hidden authentication fields cannot become valid data.
- Button press time and debouncer completion are not provider-refresh completion;
  concurrent renewal/cooldown/bursts must retain existing bounded read behavior.

### Task 1: Account Store and coordinator startup lifecycle

**Files:** Create `snapshot.py` and `tests/test_snapshot.py` / startup regression
tests; modify `coordinator.py`, `__init__.py` and relevant existing lifecycle tests.
Files are in custom_components/axiell_libraries unless a tests path is stated.

**Interfaces produced:** A `SnapshotStore(hass, entry)` wrapping supported Store
methods, with load/save/mark-withheld/remove and account-identity-match operations;
load returns a validated LibrarySnapshot plus optional finite withheld category.
Coordinator exposes `async_restore_snapshot() -> bool`, `async_remove_snapshot()`,
an identity-match predicate and a read-only closing property usable by entities.
Keep the snapshot helpers separate from transport and pure public model fields.
Engineering may choose exact private helper names and reasonable documented size
bounds; public lifecycle names above remain stable for Task 2.

- [x] Add meaningful failing tests for codec roundtrip/public-field allowlisting,
  aware timestamp/dates/types/duplicates/corruption/identity isolation/empty data.
  Exercise private atomic Store behavior and cleanup using offline HA storage.
- [x] Add failing cold setup/reload tests with saved data and a blocked provider
  coroutine: entities must be forwarded stale before the read is released. Test
  eventual success, transient first failure/recovery, empty replacement, no-cache
  setup retry, independent accounts, removal and identity changes.
- [x] Add auth/security sticky withholding, failed marker-save/removal fallback,
  save failure not corrupting provider freshness, cancellation/drain and renewal
  fresh-preflight/no-consent-restoration regressions. Read Store's public behavior:
  disk write errors may be swallowed, so marker durability needs verification.
- [x] Run new tests RED before production edits. Implement strict storage codec,
  common successful-read persistence, restored-stale initialization, entry-owned
  non-eager background refresh after forwarding, normal no-cache first refresh,
  removal/identity cleanup and sticky withholding with finite per-process fallback.
- [x] Await/drain storage writes under existing operation ownership; use no delayed
  save callbacks that can resurrect removed data. Do not log exception payloads.
- [x] Run focused/full available tests, Ruff/diff checks and commit verified work.
  Document actual environment limits; leave UI additions for Task 2.

### Task 2: Timestamp sensor, refresh button and user-facing privacy contract

**Files:** `sensor.py`, new `button.py`, `todo.py`, `__init__.py` platform list,
strings.json, translations/en.json and nb.json, entity/button/Recorder tests,
README.md, CHANGELOG.md and docs/validation.md.
**Consumes:** Task 1 restored shared snapshot and closing/lifecycle guarantees;
native coordinator async_request_refresh, snapshot_available and diagnostics.
**Produces:** Stable new keys last_successful_refresh and refresh, no ID changes.

- [x] Add failing timestamp diagnostic tests: TIMESTAMP, aware fetched_at, same
  account device, None without data, unchanged across failures/restoration and
  visible when content is withheld. Existing data_freshness enum stays unchanged.
- [x] Add failing ButtonEntity tests for normal press, debounced bursts, stale
  startup, concurrent renewal, provider cooldown and unload. Assert no new client,
  identity or LoanRenew; no success inferred from press or request submission.
- [x] Implement native button Refresh now / Oppdater nå, mdi:refresh, calling
  async_request_refresh only; let native debounce and coordinator lock/cooldown
  govern requests. Timestamp derives directly from snapshot, never entity state
  metadata. Update platforms/translations and existing entity-count expectations.
- [x] Hide loan attributes/to-do content when snapshot_available is false; keep
  stale-but-allowed content coherent. Test Recorder exclusion on restored data.
- [x] Document Store versus RestoreEntity, cached/no-cache startup, first-upgrade
  limitation, possible brief HA teardown windows, local/private-not-encrypted
  cache/backups, removal/identity rules, disk-failure limits, stale age and button
  last-pressed versus actual successful fetch. Never promise renewal success.
- [x] Run focused/full available tests, Ruff/diff checks; commit verified work.
  Update validation with precise RED/GREEN results and remaining target CI gates.

After both tasks and independent review, upload the feature branch from the
v0.5.1 main tree, open a PR and run full supported CI, Marketplace and hassfest.
Fix any CI failures before reporting completion. No release/version bump.
