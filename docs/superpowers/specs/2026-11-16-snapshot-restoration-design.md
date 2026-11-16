# Account snapshot restoration and refresh controls

Implement the owner's requested follow-up on v0.5.1. Submit a PR; no merge,
release, deployment, live renewal or actual library mutation is requested.
The recorder windows supplied by the owner are consistent with reloads, but do
not prove each initiating cause. Current setup waits for a first provider read
before loading entities, and current snapshots exist only in memory.

## Chosen approach

Use one account-scoped Home Assistant `Store` for the coordinator's normalized
snapshot. `RestoreEntity` would restore entities independently and cannot recover
the complete coherent to-do list from the existing Recorder-excluded loan
attributes. A Store allows counts, dates, loan details and the historical fetch
timestamp to come from the same authoritative read. This choice follows the
owner's preference for coherent restoration; the implementation details below
are engineering decisions within the requested behavior.

Use supported Store methods with `private=True`, `atomic_writes=True`, a versioned
schema and a key derived only from domain and config-entry ID. File permissions
are not encryption: loan details reside in `.storage` and HA backups. Do not put
loan data in Recorder, logs, exception text or entity identifiers.

## Snapshot contract and privacy

- Persist a strict allowlist of normalized public Loan fields, filtered public
  bibliographic metadata, and the timezone-aware original `fetched_at`.
- Do not serialize dataclasses wholesale, `api_fields`, raw API responses,
  credential/config-entry dictionaries, PIN/card numbers, DeviceIDs, tokens,
  cookies, session IDs, circulation fingerprints or renewal confirmation state.
- Bind the data to a digest of canonical AppID/card identity and the entry ID;
  no raw account identifier in the file. PIN changes preserve identity/cache.
- Validate the whole payload before use: schema/types, nonempty unique loan IDs
  and titles, aware timestamp, ISO dates, booleans, finite nonnegative counts/cost,
  safe optional URL, supported metadata labels and bounded payload sizes. Reject
  the entire malformed snapshot rather than inventing an empty or partial list.
- Missing, corrupt, incompatible or identity-mismatched cache behaves as no
  snapshot. Clear invalid/mismatched account data safely. Preserve a successful
  empty loan list as a valid authoritative snapshot.
- Persist a finite credential/security withholding marker with the retained
  snapshot when such a failure occurs, so reload cannot expose data previously
  withheld. This is diagnostic policy state, never authentication material.
  Clear it only after a successful authoritative read. Preserve the historical
  timestamp even when loan content is withheld.
- Withholding is sticky through later transient errors until a successful read.
  Keep a finite per-entry in-process marker as well. Store can swallow disk-write
  failures, so verify a blocking-marker write using a fresh Store load; if it did
  not persist, attempt cache removal and retain the in-process block. A reload
  cannot remove this block. If every durable write/removal fails, no software can
  guarantee the marker across complete process loss; document that disk-failure
  limitation explicitly and log static diagnostics without account data.

## Lifecycle

Load the Store before contacting the provider. If valid, set coordinator data
directly and `last_update_success=False` before platform forwarding; do not call
`async_set_updated_data` to restore, because it asserts success. Apply any saved
withholding policy and existing in-process Retry-After deadline. Forward entities
and schedule one config-entry-owned, non-eager background refresh through the
existing coordinator. Do not await provider access before making restored entities
available. A transient startup failure remains loaded/stale and uses the existing
bounded recovery timers. Credential/security errors keep the existing reauth or
withholding behavior, and never silently expose restored content.

With no valid snapshot, retain `async_config_entry_first_refresh` and native HA
setup retry behavior. This prevents failed reads from manufacturing zero loans.

Persist every successful assembled snapshot at the common read-success boundary,
including renewal preflight/reconciliation reads, before releasing operation
ownership. Never persist a failed/partial read or interpret restored data as a
renewal result. Existing fresh preflight/consent/authorization remain mandatory.
Storage failures must not reclassify successful provider reads as failed; use
sanitized, rate-limited logging. Drain any outstanding save during cancellation,
unload/removal so it cannot race cache deletion or reappear afterward.

Unload retains the cache. Account removal drains the coordinator and removes its
Store and cooldown entry, including entries not currently loaded. A changed
AppID/card identity invalidates the old Store before reuse; the update listener
must reload an actively changed identity, while ordinary options and PIN handling
retain the existing behavior. The account device and existing entity IDs remain
unchanged.

## Entities and manual refresh

Keep the `data_freshness` enum and its three values unchanged. Add diagnostic
sensor key `last_successful_refresh`, `SensorDeviceClass.TIMESTAMP`, on the same
device, native value `data.fetched_at` or None. It remains available and retains
that historical time across failed refreshes/restoration, including a withheld
snapshot. Never use entity last_updated/last_changed.

Add one native button key `refresh`, English `Refresh now`, Norwegian
`Oppdater nå`, icon `mdi:refresh`, on the same device. Request read-only
`async_request_refresh()`; use Core's debouncer and existing operation lock and
Retry-After checks. Do not create a second scheduler, login identity, or direct
Solus call. Guard unload; it must be usable with stale data/provider cooldown.
No new success flag or refresh timestamp is set by pressing it. Core's button
state is last-pressed, including queued/failed requests, not refresh completion;
document the distinction and use freshness/error/timestamp diagnostics for results.
Native debounce can coalesce a burst into an immediate and one trailing refresh;
there must be no concurrent or per-press duplicate provider calls.

Preserve Recorder exclusion of loan attributes. Do not expose withheld loan
attributes/to-do items merely because they are retained in the coordinator.
Safe timestamp/error diagnostics may remain visible while content is unavailable.
Add English/Norwegian translations and usage/privacy documentation.

## Verification and limits

Offline tests must cover cached cold startup before an awaited provider response,
successful and failed first reads, recovery timers, reload, fresh/stale/timestamp
transitions, empty replacement, multiple accounts, removal/identity changes,
corruption/schema privacy, auth/security withholding across reload, storage
failure/cancellation, renewal preflight and no restored consent, native button
normal/debounced/concurrent-renewal/cooldown behavior, and Recorder exclusions.
Run the full supported 2026.11.0/2026.11.1 CI matrix, pinned Ruff and hassfest.

Limitations to document: the first upgrade has no cache until a successful read;
HA entity teardown/recreation during reload can still produce brief unavailable
history entries, although provider latency no longer extends them when a valid
cache exists. Store failure or a crash before a completed save can retain an
older snapshot. Old data stays explicitly stale without an arbitrary expiry.
No cache means ordinary setup retry/unavailable behavior. Store data is private
local loan data included in backups, not encrypted, and is not renewal evidence.
