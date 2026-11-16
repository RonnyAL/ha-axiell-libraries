# Polling recovery and freshness

Implement the user's November 15 reliability requirements without changing account,
DeviceID, entity identity, consent, or renewal-write semantics. The incident's
trigger cannot be determined from the supplied generic log and reload outcome.
Code inspection establishes a six-hour recovery gap, discarded error categories,
and repeated session expiry incorrectly triggering reauthentication.

Use the existing DataUpdateCoordinator scheduler. After recoverable failed reads,
allow three early recovery cycles at 60, 120 and 240 seconds plus 0–25% jitter;
then resume the configured interval until a successful snapshot resets the budget.
Each cycle makes one snapshot attempt, with at most one relogin/re-read for explicit
session expiry. No transport retry loops or sleeps hold the operation lock.
Retry-After sets a minimum wait, including manual refreshes and renewal preflight.
Credential rejection alone requests reauthentication. Protocol failures can receive
the bounded recovery schedule; security violations get no accelerated retries.
Keep HTTPS/origin/redirect restrictions and never replay LoanRenew automatically.

Retain an in-memory successful snapshot through temporary failures. Expose
last_successful_refresh, data_stale and last_update_error on existing entities;
add a visible diagnostic freshness sensor (fresh/stale/unavailable). Credentials
or security failures make loan entities unavailable, with diagnostics still visible.
Zero loans is exclusively a successfully fetched empty list. Snapshot timestamps
refer to authoritative loans; optional catalogue enrichment remains best-effort.

Options Flow stores update_interval in minutes, integer 30–1440, default 360.
Old entries without options keep 360. Update listeners apply changes to the live
coordinator and its scheduled poll, preserving any recovery/rate-limit deadline.
No reload, login, migration or DeviceID generation is needed for an option change.
