# Individual loan details and semantic releases

## Intent and authority

The owner now confirms live Home Assistant authentication and all three aggregate
sensors work. Extend the approved native, read-only architecture to make each
loan's bibliographic and circulation data usable in dashboards and automations.
The owner delegated the representation choice; the choices below are engineering
decisions, not additional decisions attributed to the owner.

## Approach

Keep the existing three sensors and read-only to-do entity. Add a structured
`loans` attribute to **Active loans**, with one dictionary per `loanID`. This is
directly usable with `state_attr` and standard templated Markdown cards. Exclude
that rich attribute from Recorder using HA's `_unrecorded_attributes`, preserving
count history without repeatedly storing book descriptions. The current to-do
API has no image field; retain useful descriptions and direct cover links.

Alternatives considered: individual sensors/images per loan would cause entity
churn as books are returned; a calendar adds a second date presentation without
solving metadata access. Neither is needed here. No custom frontend is required.

## Data contract

`LoansGet` remains authoritative for current membership, title, loan and record
identities, due date and circulation status. `dueObject` yields a Python `date`;
public attributes serialize it as ISO date or null. Never parse `dueDisplay`.
`loanID` identifies a loan even if several copies share a record or title.

Preserve subtitle separately. Author preference is nonempty `RecordGet.Author`,
then nonempty `LoansGet.author`, then unknown; subtitle is never inferred to be
an author. Add item ID, renewal count, renewal cost and overdue-specified fields.
Negative counts (including -1) and malformed counts mean unknown. Cost must be
a finite nonnegative number, never a boolean; no currency is inferred.

Retain relevant original scalar API fields in immutable, explicitly allowlisted
`api_fields` on Loan and CatalogueRecord, internally only. Never retain entire
responses or credentials. Preserve MainMetadata internally; exported metadata
is limited to recognized bibliographic labels. Normalize publisher, publication
year, language and subjects from supported Norwegian/English labels; preserve
the original value as a string, without inventing subject delimiters or dates.
These label aliases are defensive handling, not proof of every provider schema.

Public loan dictionaries have stable keys: `loan_id`, `record_id`, `item_id`,
`title`, `subtitle`, `author`, `due_date`, `overdue`, `overdue_specified`,
`can_renew`, `renewal_count`, `renewals_remaining`, `renewal_cost`, `source`,
`isbn`, `image_url`, `description`, `format`, `publisher`, `publication_year`,
`language`, `subjects`, `main_metadata`. Optional values are null; metadata is
a dictionary. Do not expose internal `api_fields`, account fields, tokens,
DeviceID, or arbitrary unknown metadata keys.

Prefer a valid HTTPS `RecordGet.ImageUrlLarge`, then `ImageUrl`, then an existing
valid loan cover. Reject malformed URLs, credentials, control/whitespace or
backslash characters, invalid ports, and ItemImage.aspx. Do not download, probe
or proxy covers. An unavailable image cannot break loan refresh; a standard
dashboard example must retain title/due text when an image is absent or fails.
The browser contacts external cover providers; loading a URL is not proof that
an image is reachable. Browser rendering still requires an owner-run check.

## Refresh and isolation

Keep the per-entry cache keyed by `(record_id, source)`, 24-hour TTL, 256-record
bound and four concurrent metadata calls. Poll loans every six hours as before.
Reuse catalogue data while refreshing due dates, renewal state and membership;
new records trigger enrichment. Expired metadata refreshes; temporary errors may
retain stale metadata without renewing its expiry. One failed record must not
hide loans. Separate entries retain separate caches, sessions and DeviceIDs.

## Release contract

Prepare numeric manifest version `0.3.0`, canonical Git tag `v0.3.0` and release
title `0.3.0`. Validate that the tag's numeric part exactly matches manifest
SemVer. Test both actual HA Marketplace selection of the v-prefixed published
release and extraction/loading of its numeric manifest. HA's version comparison
normalizes the prefix; the source archive must use the actual Git tag.

The existing commit labels are caused by **no published GitHub Release**, not
by missing manifest version. A tag alone does not change Marketplace's release
source. Keep a manually dispatched, main-only release workflow gated on the
complete reusable CI, pinned to its validated SHA and refusing existing tags.
Use reviewed release notes. Do not auto-publish on pushes or pull requests.
The owner's earlier release hold remains in force for this implementation PR;
publication is a distinct final action after reviewing/testing the new features.
Until publication and installation of that release, the old commit label can
remain. Explain this explicitly rather than claim a metadata edit fixes it.

## Constraints and acceptance

- Target Home Assistant 2026.11.1; minimum 2026.11.0, both actually tested.
- Exactly one library/card per entry; persistent `secrets.token_hex(8)` DeviceID.
- Preserve working async authentication; no new endpoints or write operations.
- Offline synthetic tests only; never commit account data, credentials or captures.
- Use Superpowers TDD, task reviews and a final branch review; create a PR.
- Test parsing/enrichment/author distinctions, invalid/missing covers, independent
  loans/accounts, cache/return/renewal refresh, HA attributes and read-only todo,
  recorder exclusion, release guard failures and real Marketplace version paths.
- Run pytest on both Core versions, Ruff, official hassfest, and CI. Record exact
  results and distinguish owner-verified live authentication from new UI coverage.

References: [HA to-do entity](https://contributors.home-assistant.io/core/entities/todo/),
[Marketplace releases](https://contributors.home-assistant.io/marketplace/guides/releases/),
and installed Home Assistant 2026.11.1 source (todo, entity, recorder, marketplace).
