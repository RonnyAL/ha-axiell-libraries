# Catalogue response system statuses

Implement the owner's concrete APK 2026.42 findings: the exact case-sensitive
`d.status` values `sessionexpired`, `LOGINEXPIRED`, and `VALIDATIONREQUIRED`
are JSON body values, including on HTTP 200. The supplied shape is illustrative,
not a captured production response; it does not establish the November 15 cause.

Classify centrally in `SolusClient._catalogue_request` after HTTP parsing and
before read or renewal decoding. Decode serialized `d` using the existing
helper. Per-decoder classification would duplicate policy and risk allowing a
system status to become renewal consent. Unknown values retain existing fallback.

Both expiry values invalidate the client token/authenticated state and raise
`SolusSessionExpired`, with distinct finite reasons `session_expired` and
`login_expired`. This deliberately uses the existing bounded coordinator login
path, not the APK's CheckIsLoggedIn or interactive login flow. Neither is proof
of a rejected PIN, including during setup or login recovery.

`VALIDATIONREQUIRED` raises `SolusSecurityError` with reason
`validation_required`. It must not become an authentication rejection or renewal
prompt, be swallowed by optional catalogue enrichment, or receive accelerated
retries. No reCAPTCHA execution, validation token, or bypass is implemented.

Every renewal sends at most one write. System-status failures retain the existing
unknown-outcome/read-reconciliation behavior; no automatic write replay and no
pending confirmation derived from a system status. Unknown ordinary confirmation
codes keep the explicit-consent behavior.

Preserve v0.5.0 retry limits, Retry-After handling, locks, persistent DeviceID,
entity IDs and all existing security constraints. Diagnostics use only static
classifications and never include statusmessage, Detail or arbitrary body values.
No new release or Home Assistant deployment is requested.

Document the APK distinction: doCatCallForUser handles recovery whereas
doCatCallForUserAsyncSimple throws; no universal APK retry behavior is inferred.
