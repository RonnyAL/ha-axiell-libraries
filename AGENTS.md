# Agent instructions — Axiell Libraries

Use the installed **Superpowers** workflow. Begin with `superpowers:using-superpowers`, read the already-approved design and implementation plan, then use `superpowers:subagent-driven-development` if available (otherwise `superpowers:executing-plans`). Apply `superpowers:test-driven-development`, code review, and `superpowers:verification-before-completion`; do not skip tests.

The owner has already chosen the design: **native Home Assistant custom integration; multiple config entries; persistent DeviceID per entry; read-only v1; Solus API; library discovery with searchable nearby results and manual LocationID**. Do not spend a session re-asking these decisions. The owner has subsequently authorized explicit individual renewal with informed consent, as specified in `docs/superpowers/specs/2026-11-13-loan-renewal-design.md` and its implementation plan. Historical v1 documents remain read-only; the to-do entity remains read-only. No automatic/bulk renewal or live renewal test is authorized. The owner has separately authorized publication of 0.4.0 only; future release publications and live renewal tests require separate explicit instruction.

Read in this order:
1. `docs/superpowers/specs/2026-11-13-axiell-libraries-design.md`
2. `docs/protocol.md`
3. `docs/superpowers/plans/2026-11-13-axiell-libraries-v1.md`
4. `tests/fixtures/*.json`

## Non-negotiable requirements

- Config entry = one **library + card** pair; multiple entries supported. Stable unique ID derived from library AppID and normalized card number; reject duplicate entry **before** attempting a login.
- `DeviceID` = `secrets.token_hex(8)` (16 lowercase hex chars), created exactly once when a config flow begins and persisted in config entry `data` on success. Reuse across config flow retries, refresh, reauth, reconfigure and restart. Do NOT regenerate for every login / coordinator refresh. Do NOT log it unnecessarily. Do not migrate it away on reauth.
- Login only with `LoginPreSession` then `LoginCheckSession` as verified. **Do not use `Cat.asmx/Login`**; that path returned `Failure in reCaptcha` even with verified PIN. Check official upstream protocol carefully if server behavior changes.
- Do not send card, PIN, AuthToken, cookie or HTTP bodies to logs, exception text, error reporting or tests. Reauthentication must never clear the stored DeviceID; PIN is stored in HA config entry data (not in repo).
- Async `aiohttp` through HA-managed session. Restrict credentials/token to HTTPS and expected Solus hostnames from trustworthy locator/HTTPS repo responses; never blindly follow arbitrary hosts. Bound timeouts and retries; do not retry invalid auth in a loop or register a new device.
- Use `LoansGet.dueObject` (.NET `/Date(1795046400000)/` => 2026-11-19) for dates. Avoid parsing `dueDisplay` HTML. `RenewalsRemaining=-1` means unknown, NOT unlimited.
- Enrich only when needed using `RecordGet(RecordID,Source,SearchLimit)`; prefer `RecordGet.Author` over `LoansGet.subtitle` fallback; use `RecordGet.ImageUrl`/`ImageUrlLarge` direct, optional when missing. The `ItemImage.aspx` fallback returned an identical placeholder for all loans and must NOT be the primary image source.
- Keep tests completely offline, use synthetic fixtures. Add config-flow tests for duplicate accounts, multiple accounts, reauth, persistent DeviceID and provider failure; add API tests for malformed dates, empty lists, session expiration, and partial catalogue failure.
- Update docs and keep commits small. Commit only green tests or explicitly explain blockers. Preserve the repository's existing visibility. Publication of release 0.4.0 is explicitly owner-authorized; future release publications require separate explicit instruction.

## Never commit these

`*.apk`, `*.xapk`, APK extraction, decompiled JS, network traces/HAR, `mitmproxy-data`, user-supplied JSON, account numbers, PINs, API tokens, cookies or raw personal data. `research/private/` is gitignored for **local Codex CLI only**. Cloud Codex won't see ignored local files: the checked-in protocol spec and synthetic fixtures must stand alone.

## End-of-task report

For every plan task report: files changed, tests run with outputs, any API assumptions not yet verified, and the next task. Never claim integration works against live API without a real test performed locally by the user (with credentials outside git).
