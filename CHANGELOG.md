# Changelog

## 0.3.0 — prepared, unpublished

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
still require owner-run verification. No tag or release has been published for
this change; the owner's publication hold remains in force. See
[release preparation and recovery](docs/releases.md).
