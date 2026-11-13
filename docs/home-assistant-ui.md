# Home Assistant entities

After adding an Axiell Libraries account under **Settings → Devices & services**,
open its device to see **Active loans**, **Next due date**, **Overdue loans**, and
**Library loans**. Add another integration entry for another library/card pair.
If two devices have the same library name, rename them in Home Assistant to tell
the accounts apart; card numbers are never included in device or entity names.

Add the sensors to a dashboard using standard Home Assistant cards. **Next due
date** is a calendar date, independent of the HA timezone. It is the earliest
known due date among active loans, including overdue loans. Unknown dates are
excluded; if every due date is unknown or there are no loans, this sensor is
unknown. **Overdue loans** counts the provider's `Overdue` flags, including loans
with unknown dates, rather than comparing dates with the local clock.

Open **To-do lists → Library loans**, or add a standard to-do list dashboard card
and select this account's list. Each loan keeps its own due date and loan ID,
even if two copies have the same title. Expand an item to see available author,
ISBN, format, description, publisher/year metadata and a direct cover link.
Publisher/year fields retain the provider's bibliographic labels (`Utgiver` and
`Utgitt` in Norwegian); unknown metadata keys are not exposed. Covers and all
other enrichment are optional. The integration does not download or proxy cover
images and never forwards account credentials to an image provider. Opening a
cover link contacts its external provider from your browser.

The list is read-only: completing, editing, creating or deleting items is not
supported. Returns, renewals and reservations must be done through the library.
The standard `todo.get_items` action can read items and descriptions for an
account; mutation actions are rejected.

Loans refresh every six hours. A provider failure makes these entities
unavailable while retaining the previous snapshot internally; an actual
successful empty response shows zero loans and an empty list. A credential
failure requests reauthentication. Updating the PIN and reloading preserve the
entry's stored DeviceID, entity IDs and account identity. Unloading one account
releases its session independently of the other accounts.

This UI behavior is verified with offline tests against Home Assistant 2026.2.3.
It does not establish compatibility with a live Solus account; the owner must
perform a local credentialed check outside Git before making that claim.
