# Home Assistant entities

After adding an Axiell Libraries account under **Settings → Devices & services**,
open its device to see **Active loans**, **Next due date**, **Overdue loans**,
**Library loans**, **Data freshness**, **Last successful refresh** and **Refresh now**. Add another integration entry for another library/card pair.
If two devices have the same library name, rename them in Home Assistant to tell
the accounts apart; card numbers are never included in device or entity names.

**Active loans** has a numeric count and a structured `loans` attribute for
dashboards and automations. Only this sensor carries the rich dictionaries.
**Next due date** is the earliest known due date, including overdue loans,
independent of the HA timezone. It is unknown when no due dates are known.
**Overdue loans** counts the provider's flags, including loans with unknown
dates, rather than comparing dates with the local clock.

## Standard dashboard card

Add a standard **Markdown** card and paste this YAML in its code editor. Replace
`sensor.synthetic_library_active_loans` with your account's Active loans entity
ID. Title, author, subtitle and due/status text are separate from the optional
image, so they remain readable when an image is missing or fails to load.
Provider text and HTML attributes are escaped with `e`.

```yaml
type: markdown
title: Library loans
content: |
  {% set entity = 'sensor.synthetic_library_active_loans' %}
  {% if states(entity) in ['unknown', 'unavailable'] %}
  Library data is unavailable.
  {% else %}
  {% set loans = state_attr(entity, 'loans') or [] %}
  {% for loan in loans %}
  <p><strong>{{ loan.title | e }}</strong><br>
  Author: {{ (loan.author or 'Unknown') | e }}<br>
  {% if loan.subtitle %}Subtitle: {{ loan.subtitle | e }}<br>{% endif %}
  Due: {{ (loan.due_date or 'Unknown') | e }}<br>
  Overdue: {{ 'Yes' if loan.overdue else 'No' }}<br>
  Renewable: {{ 'Yes' if loan.can_renew else 'No' }}</p>
  {% if loan.image_url %}
  <p><img src="{{ loan.image_url | e }}" alt="Cover" width="100"></p>
  {% endif %}
  {% else %}
  No active loans.
  {% endfor %}
  {% endif %}
```

Covers use optional direct HTTPS URLs from catalogue/loan metadata. The
integration never downloads, probes or proxies them. Your browser contacts the
external provider; no library credentials are forwarded. A URL does not prove
that a cover is reachable: provider access rules, blocking or a missing image
may prevent browser display. No `ItemImage.aspx` placeholder is used. The to-do
API has no image field; use this card for inline covers.

## Structured loan fields

Each dictionary represents one issued copy, keyed by `loan_id`. Two copies can
share a `record_id` and title while retaining different due dates and statuses.
All 23 keys below are present; optional unknown values are `null` (Jinja `none`).

| Fields | Type and meaning |
| --- | --- |
| `loan_id`, `record_id`, `title`, `source` | Strings; loan ID identifies the copy. |
| `item_id`, `subtitle`, `author`, `isbn`, `description`, `format`, `image_url` | Optional strings. Subtitle remains separate from author. Author prefers catalogue Author, then loan author, then null. |
| `due_date` | ISO `YYYY-MM-DD` string or null, from `dueObject`; never parsed from display HTML. |
| `overdue`, `can_renew` | Booleans from provider flags. Renewable describes provider eligibility; explicit renewal can still be rejected. |
| `overdue_specified` | Boolean or null. |
| `renewal_count`, `renewals_remaining` | Nonnegative integers or null; `-1` means unknown, not unlimited. |
| `renewal_cost` | Finite nonnegative number or null, without an inferred currency. |
| `publisher`, `publication_year`, `language`, `subjects` | Optional strings. Year/subject text is preserved without splitting or interpreting it. |
| `main_metadata` | Dictionary of recognized bibliographic labels and string values, retaining provider spelling. |

Supported bibliographic labels are `Utgiver`/`Publisher`, `Utgitt`/`Year`/
`Publication year`, `Språk`/`Language`, and `Emne`/`Emner`/`Subject`/`Subjects`,
case-insensitively. Labels beyond observed `Utgiver`, `Utgitt` and `Språk` are
defensive aliases, not confirmation that every provider supplies them. Arbitrary metadata,
internal original API fields, account credentials and DeviceID are excluded.

Home Assistant's Recorder excludes the `loans` attribute through the entity's
supported exclusion mechanism. Counts retain their normal history; book details
are current state, not historical book records. No Recorder configuration is
needed. State attributes and `todo.get_items` still reveal reading history to
users who can access this account's HA entities; protect access accordingly.

Use these templates in **Developer tools → Template** or in automations. Replace
the entity ID as above. Each returns a JSON list of titles and returns an empty
list when the sensor is unavailable. For complete dictionaries, omit
`map(attribute='title')`.

All active titles:

```jinja
{% set entity = 'sensor.synthetic_library_active_loans' %}
{{ ((state_attr(entity, 'loans') or []) if states(entity) not in ['unknown', 'unavailable'] else []) | map(attribute='title') | list | to_json }}
```

Overdue titles (including loans with unknown dates):

```jinja
{% set entity = 'sensor.synthetic_library_active_loans' %}
{{ ((state_attr(entity, 'loans') or []) if states(entity) not in ['unknown', 'unavailable'] else []) | selectattr('overdue', 'eq', true) | map(attribute='title') | list | to_json }}
```

Renewable titles:

```jinja
{% set entity = 'sensor.synthetic_library_active_loans' %}
{{ ((state_attr(entity, 'loans') or []) if states(entity) not in ['unknown', 'unavailable'] else []) | selectattr('can_renew', 'eq', true) | map(attribute='title') | list | to_json }}
```

## Read-only to-do list

Open **To-do lists → Library loans**, or select the account's list in a standard
to-do dashboard card. Items retain their loan IDs and due dates. Descriptions
contain available subtitle, author, ISBN, format, circulation data, bibliographic
metadata, description text and direct cover link. Bibliographic labels retain
the provider's spelling. Description visibility varies by frontend view; the
read-only item editor may hide it. Use the Markdown card above or the
`todo.get_items` action to access the details consistently.

In **Developer tools → Actions**, run this with your to-do entity ID:

```yaml
action: todo.get_items
target:
  entity_id: todo.synthetic_library_library_loans
data:
  status: needs_action
```

The response contains `items` under the entity ID, with `uid`, `summary`,
`status`, and available `due`/`description`. The list cannot complete, edit,
create or delete loans; mutation actions are rejected. Returns and
reservations must be done through the library. Renewal uses the separate
account-authorized action below; the to-do list remains read-only.

## Renew one loan

Version **0.4.0** adds this action; the owner's installed published 0.3.0
does not include it. Renewal has offline coverage only. No live renewal or
provider challenge acknowledgement has been verified.

The action requires control permission for an Axiell Libraries entity on the
selected account. Administrators can open **Developer tools → Actions**, choose
**Axiell Libraries: Renew loan**, and select the library/card account. The account
must be loaded; there is no default account. Trusted HA system contexts may
also call the action. In **Developer tools → States**, find that account's
Active loans sensor, then copy the issued copy's `loan_id` from its `loans`
attribute. Use `loan_id`, never `record_id`, title or another account's ID.
The account selector supplies `config_entry_id`; use YAML mode to see its value.

Ordinary non-admin users may call this action from a dashboard using the same
fields. Authorization uses the server-provided HA identity and checks current
control permission on every call, including confirmation. Read-only users cannot
renew. Renaming entities does not change account selection.

HA's default **Users** group grants control of all entities, so ordinary users
can normally renew across all configured library accounts. Account restrictions
require HA permission policies that actually restrict those entities. Hiding a
dashboard or card is not access control. This integration provides no custom ACL
UI and does not grant or modify permissions.

First call, with synthetic placeholders replaced by the selected account and loan:

```yaml
action: axiell_libraries.renew_loan
data:
  config_entry_id: YOUR_SELECTED_ENTRY_ID
  loan_id: loan-a
```

A known positive `renewal_cost` requires confirmation before any write. The
amount has no inferred currency. The library may also return a fee or another
prompt, including after local cost consent. Read **each** message and decide
whether to accept it. Only if you accept, make a second, manual call using the
same account and loan plus the returned local ID:

```yaml
action: axiell_libraries.renew_loan
data:
  config_entry_id: YOUR_SELECTED_ENTRY_ID
  loan_id: loan-a
  confirm: true
  confirmation_id: COPY_THE_LOCAL_CONFIRMATION_ID
```

Both confirmation fields must be supplied together. IDs expire after ten
minutes, are single-use, and are cleared by reload/restart. They are bound to
that account, copy and original circulation state. A changed loan requires a
fresh request and review. Each new provider prompt returns a new ID; repeated
or excessive prompts stop the action. Do not automate acceptance of prompts.
The action never accepts raw provider acknowledgement codes from callers.

Callers requesting response data receive `status: renewed`, `loan_id`,
`message` and `refreshed`, or `status: confirmation_required` with `message`,
`confirmation_id` and `expires_in` (seconds). Response support is optional.
Ordinary callers see the prompt and local ID in a translated validation error;
this signals pending consent, not a completed renewal. Provider rejection is
also an error with its sanitized message.

After a successful write, loan data refreshes immediately. `status: renewed`
with `refreshed: false` means the library accepted renewal but HA's subsequent
read failed. Ordinary callers get an explicit partial-success error. Use
**Refresh now** or **Update entity** on the account sensor; **do not renew again
just to refresh**.
An unknown-outcome error means the write's result could not be established;
check the account with the library before deciding on another explicit action.
A changed due date after reconciliation is not proof that this request succeeded.
There is no automatic write retry. Invalid credentials request reauthentication.

Provider messages have HTML/control characters removed, known account/session
secrets redacted, and a length limit. This cannot identify arbitrary personal
text a provider may include. Treat messages and responses as private; review
before sharing screenshots or traces. No account snapshot or raw provider code
is returned. Existing library authentication uses the stored persistent DeviceID.

## Refresh and verification

Loans refresh every **six hours**, updating membership, due dates and renewal
status. Catalogue metadata is cached for **24 hours** per account and may be
retained stale after a temporary catalogue failure without extending its expiry.
New records trigger enrichment; a failed record does not hide the loan. Press
the account's native **Refresh now** button (**Oppdater nå** in Norwegian), or
use HA's **Update entity** action (`homeassistant.update_entity`) on its sensor.
Both request a loan read through the existing coordinator and reuse unexpired
catalogue data, the same session and DeviceID. Native debounce can coalesce a
burst into one trailing request; provider cooldowns still apply. Reads serialize
with renewal, and unload closes the refresh control. The button never renews a
loan or indicates renewal success.

The native button state is its **last-pressed time**, set before refresh completes.
A queued request or failed read can therefore advance it. **Last successful
refresh** is the timezone-aware timestamp of the last actual loan read, not the
button time or entity `last_changed`/`last_updated`. It remains historical during
failures, restoration and withheld content, and is unknown without a snapshot.
**Data freshness** remains `fresh`, `stale`, or `unavailable`; a successful last
read can still be old. Check both age and freshness.

A temporary provider failure keeps the last allowed snapshot visible. A valid
local account snapshot restores all entities coherently as stale before a
background read; no age limit silently drops it. Without a valid snapshot, setup
waits for a successful first read using HA's normal retry/reauthentication path.
The first upgrade cannot restore a snapshot until a read has saved one. A
successful empty response clears the list and displays zero loans. Credential or
security failure withholds loan attributes and to-do content until a successful
read; safe diagnostics and the refresh control remain visible. Reauthentication
is still required when HA requests it. PIN updates, reload and restart reuse the
stored DeviceID and entry identity. Use **Reconfigure** for a proactive PIN update;
changing the card or library requires another entry.

The snapshot uses a shared account Store, not per-entity `RestoreEntity` state or
Recorder history. Counts, dates and loan details share one fetched timestamp;
brief HA entity teardown/reload windows can still occur. Store files have private
permissions and atomic writes, **not encryption**; local access and HA backups
can expose normalized reading history. Raw API/auth data and renewal state are
excluded, and restored data/consent never supplies renewal authorization. Rich
loan attributes remain excluded from Recorder, including when restored.

Unloading retains the cache; entry removal deletes it, and account identity changes
discard it. PIN/options changes retain the account binding. Storage failure does
not fail a successful read but can leave older history. Saves are skipped during
HA stopping to prevent deferred writes resurrecting removed data; unsafe-account
failures then attempt removal. If all marker writes/removals fail, the runtime
withholding block survives reload in that process but cannot guarantee protection
after process loss. See [privacy and recovery details](../README.md#pin-changes-and-privacy).

The owner confirms live Home Assistant authentication, all three aggregate
sensors, and Marketplace installation/update. The new structured attributes and
copyable templates are covered offline with real HA state/service and template
rendering tests; browser layout and cover display still need an owner-run check.
Automated tests use synthetic data and do not establish live provider behavior.
A separate HA process restart and Norwegian selector labels remain owner-run
checks. See the [installation and local smoke-test guide](../README.md).
