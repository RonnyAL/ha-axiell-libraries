# Changelog

## 0.4.0

- Add the administrator action `axiell_libraries.renew_loan` for one explicitly
  selected account and loan; preserve read-only to-do entities.
- Require manual, expiring confirmation for known fees and each provider prompt;
  bind single-use consent to the account, issued copy and circulation state.
- Serialize polling and renewal; drain writes before unload. Reconcile uncertain
  outcomes without automatically repeating renewal.
- Return optional small action responses or informative translated errors for
  pending consent, rejection, uncertain results and successful renewal with a
  failed HA refresh. Redact known secrets from bounded provider messages.
- Document manual action usage, privacy limits and existing AppID/TemplateID
  assumption. Use manifest `0.4.0`, canonical tag `v0.4.0` and release title `0.4.0`.

No live renewal or provider acknowledgement has been tested. The owner has
explicitly authorized publication of 0.4.0 only; future publications and live
renewal tests require separate explicit instruction. Preserve repository visibility.

## 0.3.0 — published; installed by the owner

- Expose structured individual loans on Active loans, including separate
  subtitle/author, due date, circulation status and optional catalogue metadata.
- Keep rich book data out of Recorder while retaining count history; preserve
  three sensors, the read-only to-do list and existing entity identities.
- Add useful to-do descriptions and standard Markdown dashboard examples with
  optional direct covers and readable title/due text when images are absent.
- Preserve independent loan/account state through status refreshes, returned
  loans, catalogue cache reuse and partial metadata failures.
- Match the owner-verified Python probe's bootstrap/session request contract,
  browser headers, UTF-8 BOM decoding and case-insensitive success handling.
- Retain pre-session users/token when check-session omits user details; preserve
  DeviceID across authentication and account refreshes.
- Show safe setup stage/reason references without provider text or account data,
  and classify anonymous routing/bootstrap rejection as a provider error.
- Explain nearby discovery limits and manual LocationID fallback.
- Validate numeric manifest `0.3.0`, immutable tag `v0.3.0` and reviewed release
  notes behind full main-only CI. Test real installed Marketplace selection,
  source extraction and version comparison entirely offline.

The owner has verified live authentication, all three aggregate sensors and
Marketplace installation/update. New structured dashboard rendering and covers
still require owner-run verification. The owner subsequently installed the
published 0.3.0 release. See
[release preparation and recovery](docs/releases.md).
