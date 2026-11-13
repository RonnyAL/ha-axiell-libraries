# Axiell Libraries for Home Assistant

A native, read-only custom integration for loans at Solus-powered libraries,
including libraries using the Axiell Libraries App. Each library/card pair has
its own Home Assistant config entry, persistent DeviceID, session and entities.

This uses an **unofficial, reverse-engineered API**. The implementation has been
tested offline with Home Assistant **2026.2.3 and Python 3.13**; compatibility
with newer HA releases and a live account has not been established. The owner's
earlier protocol probe verified authentication and loan/catalogue endpoints,
not this complete integration. See [validation evidence](docs/validation.md).

## Install from this private repository

1. Obtain source from your authorized private checkout or a private archive.
   Keep the repository private. No HACS or automatic update process is provided.
2. Copy the entire `custom_components/axiell_libraries` directory into your Home
   Assistant configuration directory, creating `custom_components` if needed.
   The resulting path must be
   `<HA config>/custom_components/axiell_libraries/manifest.json`. For HA OS this
   is normally `/config/custom_components/axiell_libraries/manifest.json`.
   Include `translations`; copy the integration directory rather than the whole
   repository. No YAML credentials or separate service is needed.
3. Restart Home Assistant, then open **Settings → Devices & services → Add
   integration** and choose **Axiell Libraries**. If it is absent, check directory
   nesting and restart completion; a browser reload may also help.
4. For updates, back up your HA configuration, replace that integration directory
   from the reviewed private source, and restart HA. Test version compatibility
   locally before relying on an update.

## Add library accounts

The first screen offers nearby libraries using HA's configured latitude and
longitude. Search filters those returned choices; it is not a global library
name search. Select a library or **Enter LocationID manually**. If coordinates
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
personal data. Report failures with only the generic UI error, HA/integration
version and affected step. Strict routing and unverified response variants may
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
newer HA releases, and the complete live flow were **not run by the implementers**.

## Development references

All automated tests are offline with synthetic data. Install the pinned
`requirements-dev.txt` in a Python 3.13 virtual environment, then run
`python -m pytest -q`, `ruff check .`, `ruff format --check .` and
`git diff --check`. The full HA source-tree `hassfest` tool is not supplied by the
installed HA package; available loader/translation checks are recorded in the
[validation ledger](docs/validation.md), without claiming hassfest passed.

- [Sanitized protocol and unresolved assumptions](docs/protocol.md)
- [Synthetic fixtures](tests/fixtures/)
- [Approved design](docs/superpowers/specs/2026-11-13-axiell-libraries-design.md)
- [Implementation plan](docs/superpowers/plans/2026-11-13-axiell-libraries-v1.md)
- [Maintainer handoff prompt](CODEX_START.md)
