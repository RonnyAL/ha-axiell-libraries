# Maintainer prompt for Codex

The v1 implementation is present. Start with the current validation ledger and
repository state rather than repeating the implementation from Task 1.

> Maintain **Axiell Libraries** as a native Home Assistant custom
> integration using **Superpowers**. Read `AGENTS.md`, then the approved design,
> `docs/protocol.md`, the task-by-task plan and `docs/validation.md`. Check the
> actual branch and pending review items before choosing the next task.
>
> The design decisions are final: native HA, one entry per library/card,
> persistent `secrets.token_hex(8)` DeviceID, nearby results and manual LocationID,
> Solus `LoginPreSession` then `LoginCheckSession`, and read-only v1. The owner
> later authorized explicit individual renewal with informed consent; follow
> the approved loan-renewal spec and plan. The to-do entity stays read-only.
> The owner explicitly authorized publication of 0.5.1 on 2026-11-16. Future
> publications and live renewal tests require separate explicit instruction;
> automatic/bulk renewal remains unauthorized. Preserve device identity through
> retries, restart and PIN updates. Use offline synthetic tests, TDD for behavior
> changes, independent review and fresh verification.
> Never commit APKs, raw traffic, credentials or personal responses. Keep the
> repository visibility unchanged and push or publish only within the owner's
> explicit instructions. State the tested HA version and remaining live
> assumptions; do not infer compatibility with the latest HA release.

Current runtime targets are Core and official `pytest-homeassistant` 2026.11.1
(target) and 2026.11.0 (minimum), Python 3.14. See `docs/validation.md` for exact
counts and pending final gates. Use `requirements-dev.txt` and
`requirements-min.txt`, both including `requirements-test.txt`. Do not reinstall
the discontinued custom-component harness. Installed Superpowers skills provide
the workflow; original v1 design docs are historical.

Version 0.5.1 fixes catalogue body session-expiry and validation-required
statuses while retaining bounded polling recovery, interval options and freshness. It retains the `axiell_libraries.renew_loan` action introduced in 0.4.0. Current authorization requires control of an
Axiell entity on the selected account for every user invocation, including
confirmation. Non-admin dashboard calls use the same server-side check. Default
HA Users control all entities; hiding a dashboard/card does not restrict accounts.
Restricting accounts requires actual HA entity permission policies.
The canonical 0.5.1 tag is `v0.5.1`; the manifest version and release title are
`0.5.1`. Publication of 0.5.1 is owner-authorized on 2026-11-16.
See `docs/home-assistant-ui.md` for manual, expiring confirmation IDs and unknown
outcomes. The main-only Release workflow and the single-version 0.5.1 publication workflow
rerun full validation and check the exact
input against the manifest, creates a new tag atomically, then publishes notes.
Investigate partial publication manually; do not blindly rerun or move tags.
Existing live authentication, aggregate sensors and Marketplace installation
have owner verification. Live renewal/provider prompt semantics, browser covers
and a real process restart still need separate owner-run checks. Offline tests
do not establish upstream behavior or public availability.

Optional live validation belongs to the owner in their HA UI: enter card/PIN
there, never in chat, issue comments, scripts or repository files.
