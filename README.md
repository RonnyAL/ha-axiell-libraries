# Axiell Libraries for Home Assistant

A native custom integration for loans at Solus-powered libraries,
including libraries using the Axiell Libraries App. Each library/card pair has
its own Home Assistant config entry, persistent DeviceID, session and entities.

This uses an **unofficial, reverse-engineered API**. Runtime targets are
Home Assistant **2026.11.0 (minimum)** and **2026.11.1 (target)** with
Python **3.14.7 locally / 3.14.10 in CI**. Version **0.6.0** adds persistent loan
snapshots, a diagnostic refresh timestamp and a native Refresh now button,
preserving bounded recovery and single-write renewal.
The owner confirmed live Home Assistant authentication, all three aggregate
sensors, and Marketplace installation/update on earlier releases. Installation
and live behavior of 0.6.0 remain owner-run checks. New structured loan attributes
and dashboard templates have offline coverage; browser rendering and covers
still need an owner-run check. See [validation evidence](docs/validation.md).

## Install through Marketplace

The owner has exercised Marketplace installation/update and account setup.
Check the new loan details after installing this change and restarting HA.
Version `0.6.0` preserves existing accounts, DeviceIDs and entity IDs. It restores
previously saved loan snapshots as stale while a background read refreshes them;
the first upgrade needs a successful read before a snapshot exists.

1. On Home Assistant **2026.11.0 or later** (tested target **2026.11.1**), open
   **Settings → Marketplace → Add from link** and enter
   `https://github.com/RonnyAL/ha-axiell-libraries`.
2. Install Axiell Libraries and restart Home Assistant when prompted.
3. Open **Settings → Devices & services → Add integration** and choose
   **Axiell Libraries**, then follow [Add library accounts](#add-library-accounts).
   Enter card/PIN only in Home Assistant; no YAML credentials or extra service
   is needed.
4. Connect GitHub in Marketplace for periodic update checks. Back up HA before
   updating; an update to a loaded integration requires a Home Assistant restart
   to load the new code.

### Manual installation

Obtain the reviewed source from an authorized checkout or archive. Copy the entire
`custom_components/axiell_libraries` directory, including `translations`, into
HA's configuration directory. The resulting path must be
`<HA config>/custom_components/axiell_libraries/manifest.json` (normally
`/config/custom_components/axiell_libraries/manifest.json` on HA OS).
Restart HA, then add the integration under **Settings → Devices & services**.
For manual updates, back up HA, replace that integration directory with reviewed
source and restart. Manual copies do not establish Marketplace update behavior.

## Add library accounts

The first screen offers nearby libraries using HA's configured latitude and
longitude. Search filters those returned choices; it is not a global library
name search. The provider list can omit libraries even when exact lookup works.
Names supplied by Solus are retained; otherwise the LocationID is displayed.
See [discovery evidence and the Norwegian directory investigation](docs/library-discovery.md).
Select a library or **Enter LocationID manually**. If coordinates
are missing, discovery fails, or no libraries are returned, the manual screen
opens directly. Enter the exact Solus `LocationID` supplied by your library
(for example, `Malselv`); a display name is not necessarily its LocationID.

Enter your card number and PIN **in Home Assistant**. Card normalization removes
whitespace while preserving case and leading zeros. Duplicate library/card
pairs abort before login. Add the integration again for another card or library;
entries operate independently. Rename their HA devices if library names alone
do not distinguish your accounts.

A random 16-character lowercase hexadecimal DeviceID is generated once at the
start of a new flow, reused across its retries, and saved on success. Refresh,
reload, restart and PIN updates reuse it. Deleting and recreating an entry starts
a new device identity; use reauthentication or reconfiguration for PIN changes.
Credential validation and entry setup may each log in, using the same DeviceID.

## Use the entities

Each entry exposes **Active loans**, **Next due date**, **Overdue loans**, a
read-only **Library loans** to-do list, diagnostic **Data freshness** and
**Last successful refresh** sensors, and a **Refresh now** button. Use standard
dashboard sensor/to-do cards or **To-do lists**; no custom dashboard card is required. Loans retain separate
IDs and due dates even when titles match. The date sensor uses the earliest
known due date, including overdue loans, and is unknown when none is known.
Overdue count uses the provider's flags. Missing dates remain unknown.

**Active loans** exposes a structured `loans` attribute with one dictionary per
issued copy: title, separate subtitle and author, due date, circulation status
and optional catalogue details. Recorder excludes this rich attribute while
retaining normal count history. The [UI guide](docs/home-assistant-ui.md) provides
a standard Markdown card, filters and `todo.get_items` action example.
To-do descriptions also carry these details; their visibility depends on the
frontend view. Direct covers are optional and loaded by your browser from the
provider; title/due text remains readable when an image fails. The integration
does not download or proxy images.

Loans poll every **six hours** by default, including existing installations.
Change **Update interval (minutes)** in the entry's **Configure** options under
**Settings → Devices & services → Axiell Libraries**: **30–1440 minutes** (24 hours),
with **360 minutes** recommended. Changes apply to the running coordinator without
reload, another login, changed entity IDs, or a new DeviceID. Catalogue records
have a per-entry **24-hour** cache bounded to 256 records, with at most four
concurrent catalogue requests. Use **Refresh now** or HA's standard entity
update action for a manual refresh, subject to native debouncing and provider
cooldowns. The button reuses this account's coordinator, session and DeviceID.
Its last-pressed time records the request, before completion, even when a request
is queued or fails. Check **Last successful refresh** and **Data freshness** for
the actual result; pressing the button never renews loans.

After a temporary failed refresh, the last successful loans and to-do list remain
visible. Every entity exposes `last_successful_refresh`, `data_stale`, and a safe
`last_update_error` identifier such as `server/loans/http/503`. **Data freshness**
is `fresh` when the last authoritative loan read succeeded, `stale` when a later
read failed, or `unavailable` when no usable snapshot exists or credentials/security
failed. Freshness describes the last completed read, not continuous provider
connectivity; check the timestamp for age, especially when polling is disabled.
A successfully fetched empty list is **zero loans**; failed reads never invent
zero loans. **Last successful refresh** is the historical, timezone-aware loan
fetch time, remains visible when loan content is withheld, and is unknown without
a snapshot. Partial catalogue failure keeps loans visible with available metadata;
the refresh timestamp describes loans, not the age of optional catalogue details.

The integration saves a coherent normalized display snapshot in Home Assistant's
local Store after successful loan reads, including a confirmed empty list. On
reload/restart, a valid account-bound snapshot immediately restores the counts,
loan details and to-do list as **stale**, then a background read attempts to
replace it. No maximum age silently discards known loans: check the timestamp.
With no valid cache, setup still needs a successful first read and uses HA's
normal retry/reauthentication behavior. The first upgrade has no stored snapshot
until a successful read; Recorder history cannot supply it. This shared account
Store restores all entities coherently, rather than using individual entities'
`RestoreEntity` state. HA can briefly remove entities during reload/teardown;
restoration does not eliminate those windows.

Credential or security failures withhold loan content until a successful read,
including across reload/restart when the withholding marker is durably stored.
Other failures keep allowed stale content visible. Restored loans and old renewal
consent never authorize renewal: renewal still performs its fresh preflight and
requires current, explicit consent.

Recoverable failures get **three early recovery cycles**, waiting **60, 120, and
240 seconds plus 0–25% jitter**. After that, normal polling resumes; only a
successful snapshot resets this budget. Before the first snapshot, HA's native
setup backoff applies instead. Each cycle attempts a read and, on explicit
session expiry, at most one recovery login and reread. A newly constructed or
unauthenticated client also needs its initial login. A repeated expiry remains a
provider/session failure, not a reason to change your PIN. Security violations and
nonrecoverable HTTP errors receive no accelerated retries. Genuine credential
rejection stops automatic polling and requests reauthentication.

A valid HTTP `Retry-After` (seconds or HTTP date) sets the minimum wait, even when
it exceeds the configured interval. It also applies to manual refresh, option
changes, setup retries, and read reconciliation after a renewal. Scheduling may add
about a second to avoid running early. Cooldowns survive entry reloads in memory,
but not a HA process restart. Scheduled recovery respects HA's polling-disabled
setting and is cancelled on unload. No renewal write is automatically repeated.

The to-do list cannot complete, edit, create or delete loans. Users with control
permission for an Axiell Libraries entity on the selected account can explicitly
renew one loan with `axiell_libraries.renew_loan`; every known
fee or provider prompt requires manual consent. See the
[renewal action guide](docs/home-assistant-ui.md#renew-one-loan). Returns,
reservations and account changes remain library operations. There are no
automatic or bulk renewals. Live renewal remains unverified.

HA's default Users group grants control of all entities, including all library
accounts. Restricting accounts requires HA permission policies that restrict
those entities; hiding a dashboard or card is not access control. This
integration adds no permission editor and does not change HA permissions.

## PIN changes and privacy

If HA requests reauthentication, enter the new PIN in that entry's prompt. To
change it proactively, use the entry menu's **Reconfigure** action. Both flows
update only the PIN and reload the entry, preserving the card, library, DeviceID
and entity identity. Add another entry to change the library or card. Provider
errors may require waiting or checking the LocationID; repeatedly submitting
credentials is not a remedy for an unknown protocol response.

The card, PIN and DeviceID are stored in **HA config entry data**. This is not a
dedicated secrets vault; protect access to HA configuration and backups. Tokens
and cookies stay in memory in isolated per-account sessions. Requests have a
20-second timeout, use HTTPS and validated Solus destinations, reject redirects,
and never automatically repeat a renewal write. Read recovery uses the bounded
scheduler described above and always reuses the existing DeviceID.

The per-account snapshot under HA's `.storage` contains allowlisted normalized
loan/catalogue display fields, the historical fetch timestamp, an account identity
hash and a finite withholding category. It excludes raw API/authentication data
and renewal state. Core Store uses private file permissions and atomic writes;
this is **not encryption**. Protect local HA access and backups, which can contain
reading history. Recorder still excludes rich loan attributes; that exclusion
does not prevent the separate local snapshot or its backups.

Unloading an account retains its snapshot; removing the entry deletes it. A changed
account identity discards the old cache; PIN/options changes retain it. Storage
failure does not fail a successful read and may leave an older stored snapshot.
A read finishing while HA is stopping also may leave an older snapshot, because
saves are skipped to avoid deferred writes recreating removed data. Unsafe
credential/security failures during stopping attempt cache removal. If every
marker write and removal fails, a runtime block protects reloads in that HA
process, but cannot guarantee withholding after process loss.

Do not enable or share HTTP traces containing private data. Do not put card
numbers, PINs, tokens, cookies, account responses or DeviceIDs into chat, issues,
logs or repository files. Do not commit APKs, captures, decompiled code or raw
personal data. Report failures with the UI error and its safe reference (for example,
`bootstrap/http/403`), HA/integration version and affected step. References identify
discovery/manual lookup, routing, bootstrap, pre-session, check-session, loans,
catalogue or renewal, and transport, timeout, HTTP, API rejection, response schema,
missing token or security errors. Repeated failures log once per outage; diagnostic
attributes continue to show the latest category, and successful recovery is logged.
Routing/bootstrap HTTP rejection does not mean your PIN was rejected.
Strict routing and unverified response variants may
cause a safe provider error; [protocol assumptions](docs/protocol.md#client-implementation-contract-and-remaining-assumptions)
describe what still needs validation.

## Optional owner-run live smoke test

Run this locally through your own Home Assistant UI. Enter card/PIN only in HA's
credential forms, never in chat, issues, scripts or test files. Do not capture
network bodies or enable credential-bearing debug logging.

1. Install, restart, add your library through discovery or exact LocationID and
   sign in. Check current loan titles and dates against your library account.
   Check optional metadata/cover links where available.
2. Press **Refresh now** and check **Last successful refresh** and **Data freshness**.
   Request a manual entity update if desired. Check that dates remain correct.
   Try adding the same library/card again and confirm HA rejects the duplicate. If desired,
   add a second account and confirm its entities are separate.
3. Reload the entry and restart HA. Check that the same entities return. Do not
   inspect, copy or share stored credentials to perform this check.
4. When a real PIN change is needed, use Reconfigure or HA's reauthentication
   prompt and confirm existing entities recover. Do not intentionally submit
   repeated bad PINs or force upstream expiry.

Record only the HA/integration version and pass/fail of each step locally,
without titles or account data. The owner has verified live authentication,
aggregate sensors, and Marketplace installation/update. The implementers use
offline synthetic tests; new dashboard rendering/covers, an actual HA process
restart and the remaining lifecycle smoke checks need owner-run verification.

## Development and validation

Use Python **3.14** and a clean environment for each Core version. The official
`pytest-homeassistant` now replaces the discontinued
`pytest-homeassistant-custom-component`; never install both or override Core
dependencies to force compatibility. Shared tools are in
`requirements-test.txt`, included by both runtime requirements files. Pytest's
`-p no:respx` bootstrap setting is already in `pyproject.toml`.

From the repository root:

```bash
python3.14 -m venv /tmp/axiell-dev-2026111
/tmp/axiell-dev-2026111/bin/python -m pip install -r requirements-dev.txt
/tmp/axiell-dev-2026111/bin/python -m pytest -q
/tmp/axiell-dev-2026111/bin/ruff check .
/tmp/axiell-dev-2026111/bin/ruff format --check .
python3.14 -m venv /tmp/axiell-dev-2026110
/tmp/axiell-dev-2026110/bin/python -m pip install -r requirements-min.txt
/tmp/axiell-dev-2026110/bin/python -m pytest -q

docker run --rm -v "$PWD:/github/workspace:ro" ghcr.io/home-assistant/hassfest:latest
actionlint
/tmp/axiell-dev-2026111/bin/python scripts/check_release.py v0.6.0
git diff --check
```

Docker and actionlint are separate prerequisites. The validation ledger records
the exact hassfest image digest and installed tool/runtime versions used locally.
All automated API tests use synthetic data and offline network guards. The small
`tests/http.py` adapter accommodates aioresponses 0.7.9's missing aiohttp 3.14.5
constructor argument without patching Core/aiohttp; remove it when upstream
supports that interface. Five upstream deprecation warnings remain visible.

Push and pull-request **Validate** CI runs official hassfest, Ruff lint/format,
and the complete suite on Python 3.14 with exact Core/official-harness pairs
`2026.11.0` and `2026.11.1`. It prints and asserts actual runtime versions.
CI needs no account credentials. See the [validation ledger](docs/validation.md)
for local and hosted evidence and the remaining owner-run checks.

## Maintainer releases

The canonical release identifiers are manifest `0.6.0`, Git tag `v0.6.0`
and release title `0.6.0`. The owner has explicitly authorized publication of
0.6.0 on November 16, 2026; future publications and live renewal tests require
separate explicit instruction. Preserve repository visibility.

For the authorized 0.6.0 publication, a one-time workflow additionally requires
an explicit `[publish-v0.6.0]` marker on the merge commit, a change to that workflow,
and `main`; it runs the same complete validation before publishing only 0.6.0.
The ordinary manual workflow remains available as an alternative on `main`,
using **Actions → Release** with numeric input `0.6.0`. Inspect publication state
before dispatching after a merge that triggered the one-time workflow. Full reusable validation,
tag/manifest agreement and reviewed notes gate atomic tag creation at the
validated dispatch SHA. Existing tags are refused. No attached ZIP is required.
See [release preparation and failure recovery](docs/releases.md) and the
[0.6.0 notes](docs/releases/0.6.0.md). If publishing fails after tag creation,
inspect the validated SHA and repository state before authorized recovery;
never blindly rerun or move/delete the tag. Direct-link update checks require
a GitHub connection and can take up to the documented 48-hour interval. This
does not establish official Marketplace catalog inclusion.

- [Sanitized protocol and unresolved assumptions](docs/protocol.md)
- [Synthetic fixtures](tests/fixtures/)
- [Approved design](docs/superpowers/specs/2026-11-13-axiell-libraries-design.md)
- [Original implementation plan](docs/superpowers/plans/2026-11-13-axiell-libraries-v1.md)
- [2026.11 and Marketplace plan](docs/superpowers/plans/2026-11-13-ha-2026-11-marketplace.md)
- [Maintainer handoff prompt](CODEX_START.md)
