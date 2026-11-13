# Authentication probe parity and setup diagnostics

The owner supplied a live-tested Python probe on 2026-11-13. It bootstrapped
Auth.aspx, authenticated with LoginPreSession, established LoginCheckSession,
and fetched loans and catalogue metadata. Its active API host remained
`process-m-eu1.sol.us`; no live server switch was observed. This is evidence
for the request contract, not evidence that the current HA client works.

## Confirmed differences

The HA implementation starts with an empty session identifier instead of the
zero UUID, uses the card rather than an empty outer UserID for LoginCheckSession,
reuses bootstrap metadata instead of the distinct catalogue metadata, omits the
probe's browser headers and full bootstrap Referer, uses different platform
values, and requires fresh account details from LoginCheckSession. The probe
retains the authenticated details if that response supplies none. The probe also
decodes UTF-8 with an optional BOM and accepts case-insensitive success status.
Any of these request/response differences can be reproduced offline; the precise
one that caused the owner's displayed error still needs an HA test.

## Scope and decisions

Match the probe's request shape, session lifecycle and HTTP behavior while
retaining async HA-managed aiohttp, isolated CookieJar instances, stable entry
DeviceIDs, strict HTTPS routing and read-only operation. Separate bootstrap and
session metadata. Use the verified Android protocol profile and a generic
`Home Assistant` model label, rather than making the owner's phone model a
requirement. That model label remains an explicitly unverified metadata value.
Do not copy the probe's credential prompts, per-invocation DeviceID generation,
raw API error printing, permissive malformed-data handling or redirect following.

Add finite diagnostic stage/reason references to setup failures, never raw
provider text. Distinguish discovery, routing, bootstrap, LoginPreSession,
LoginCheckSession, transport/HTTP, API rejection, malformed responses, missing
tokens, and unsafe session destinations. A missing cookie is not by itself an
error: upstream cookie requirements remain unknown. Test real cookie transport
against a local synthetic server and make no live account requests.

Nearby discovery currently displays all returned unique LocationIDs. An
anonymous sample with the probe's headers returned only Skjervoy; exact Malselv
lookup succeeded. Neither locator response contained a name field. No complete
directory endpoint or alternative name field is verified. Preserve manual
lookup, show supplied names when available and explain that the list may omit
libraries. Do not invent names, endpoints, radius parameters or global search.

The existing workflow already publishes numeric tags matching manifest 0.2.0.
Prepare unreleased notes and explain commit-hash labels until first publication.
The owner explicitly wants to test first: do not create a tag, draft/published
release, or dispatch Release. Keep the manifest version unchanged.

## Acceptance

- Offline HTTP-boundary tests fail against the old client for the confirmed
  request and response mismatches, then pass after the smallest corrections.
- An HA config flow completes with the probe-shaped synthetic responses and
  persists its original DeviceID; retries and PIN changes retain identity.
- Errors expose only fixed stage/reason codes and validated numeric HTTP status.
  No secrets, cookies, URLs, HTTP bodies, device IDs or exception text escape.
- Full pytest passes on actual Core 2026.11.0 and 2026.11.1; Ruff and hassfest pass.
- Documentation distinguishes verified PoC behavior, offline integration tests,
  anonymous discovery and remaining owner-run live integration validation.

## Approaches

Correct the existing client using the supplied reference (selected): preserves
architecture and provides direct regression evidence. Replacing the client or
guessing new API methods would obscure the known differences and is out of scope.
