# Changelog

## Unreleased

- Match the owner-verified Python probe's bootstrap/session request contract,
  browser headers, UTF-8 BOM decoding and case-insensitive success handling.
- Retain pre-session users/token when check-session omits user details.
- Show safe setup stage/reason references, including missing authentication
  tokens, without exposing provider text or account/device data.
- Treat anonymous routing/bootstrap HTTP rejection as a provider error.
- Explain incomplete nearby discovery, manual LocationID fallback, Norwegian
  directory mapping limits and numeric version labels after release publication.

The first planned published version remains **0.2.0**. Marketplace install/update
is owner-reported; successful live integration authentication remains unverified.
