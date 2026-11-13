# Axiell Libraries for Home Assistant

A native, read-only custom integration for loans at Solus-powered libraries,
including libraries using the Axiell Libraries App. Each library/card pair has
its own Home Assistant config entry, persistent DeviceID, session and entities.

This uses an **unofficial, reverse-engineered API**. The complete offline suite
passes on Home Assistant **2026.11.0 (minimum)** and **2026.11.1 (target)** with
Python **3.14.7 locally / 3.14.10 in CI**. Integration version **0.2.0** is
prepared but unpublished.
The owner reports Marketplace installation/update succeeded, but credentialed
setup in HA still fails. The owner's live Python probe verified authentication
and loan/catalogue endpoints; successful live integration setup remains
unverified. See [validation evidence](docs/validation.md).

## Install through Marketplace

The owner has exercised Marketplace installation/update. Successful account
setup still needs an owner-run check after installing this fix and restarting HA.
The first planned published version remains `0.2.0`.

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

Each entry exposes **Active loans**, **Next due date**, **Overdue loans** and a
read-only **Library loans** to-do list. Use standard dashboard sensor/to-do cards
or **To-do lists**; no custom dashboard card is required. Loans retain separate
IDs and due dates even when titles match. The date sensor uses the earliest
known due date, including overdue loans, and is unknown when none is known.
Overdue count uses the provider's flags. Missing dates remain unknown.

Available author, ISBN, description, format and publisher/year metadata appear
in item descriptions. Optional direct cover links come from `RecordGet`; missing
covers stay absent. The integration does not proxy images. Opening a cover link
contacts its provider from your browser. See the [UI guide](docs/home-assistant-ui.md)
for details and `todo.get_items` use.

Loans poll every **six hours**; catalogue records have a per-entry **24-hour**
cache, bounded to 256 records. At most four catalogue requests run concurrently.
HA's standard entity update action can request a manual refresh. A failed loan
update makes entities unavailable while retaining the previous snapshot
internally; a successful empty response displays zero loans. Partial catalogue
failure keeps loans visible with available metadata.

The list cannot complete, edit, create or delete loans. Renewals, returns,
reservations and account changes must be made through the library. Calendar
entities and write actions are outside v1.

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
and do not automatically retry transport failures. Recognized session expiry
permits one recovery login per refresh, using the existing DeviceID.

Do not enable or share HTTP traces containing private data. Do not put card
numbers, PINs, tokens, cookies, account responses or DeviceIDs into chat, issues,
logs or repository files. Do not commit APKs, captures, decompiled code or raw
personal data. Report failures with the UI error and its safe reference (for example,
`bootstrap/http/403`), HA/integration version and affected step. References identify
discovery/manual lookup, routing, bootstrap, pre-session or check-session, and
transport, HTTP, API rejection, response schema, missing token or security errors.
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
2. Request a manual entity update. Check that dates remain correct. Try adding
   the same library/card again and confirm HA rejects the duplicate. If desired,
   add a second account and confirm its entities are separate.
3. Reload the entry and restart HA. Check that the same entities return. Do not
   inspect, copy or share stored credentials to perform this check.
4. When a real PIN change is needed, use Reconfigure or HA's reauthentication
   prompt and confirm existing entities recover. Do not intentionally submit
   repeated bad PINs or force upstream expiry.

Record only the HA/integration version and pass/fail of each step locally,
without titles or account data. Browser rendering, an actual HA process restart,
and the complete live flow were **not run by the implementers**. The owner
has separately reported Marketplace installation/update, with account setup
still failing before this fix.

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
/tmp/axiell-dev-2026111/bin/python scripts/check_release.py 0.2.0
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

Until a matching GitHub release is **published**, Marketplace may display a
commit hash as the installed/update label. A published tag matching the manifest
provides a numeric version label. The first planned version is `0.2.0`; a later
patch could be `0.2.1` after updating the manifest in a reviewed change. Review
[CHANGELOG.md](CHANGELOG.md) when preparing release notes. Do not publish merely
to change the label; complete the owner-run setup check first.

After review and merge to `main`, a maintainer may run **Actions → Release →
Run workflow**, selecting `main` and version `0.2.0` (plain `X.Y.Z`, no `v`).
The workflow runs the full reusable validation first, checks exact manifest/tag
agreement, atomically creates a new tag at the validated dispatch commit, then
publishes a GitHub source release with generated notes. No attached ZIP is
required. Feature-branch dispatches cannot publish, and existing tags are
rejected rather than moved.

For later versions, update the integration manifest in a reviewed change and
supply that exact version to Release after merging. If publishing fails after
tag creation, investigate the run and repository state and recover manually;
do not blindly rerun the workflow or move/delete a tag. Publication and repository
visibility remain separate owner actions; this fix performs neither.
This prepares direct installation, not official Marketplace catalog inclusion.

- [Sanitized protocol and unresolved assumptions](docs/protocol.md)
- [Synthetic fixtures](tests/fixtures/)
- [Approved design](docs/superpowers/specs/2026-11-13-axiell-libraries-design.md)
- [Original implementation plan](docs/superpowers/plans/2026-11-13-axiell-libraries-v1.md)
- [2026.11 and Marketplace plan](docs/superpowers/plans/2026-11-13-ha-2026-11-marketplace.md)
- [Maintainer handoff prompt](CODEX_START.md)
