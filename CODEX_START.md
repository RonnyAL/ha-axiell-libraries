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
> No automatic/bulk renewal, live write test or publication is authorized. Preserve
> device identity through retries, restart and PIN updates. Use offline synthetic
> tests, TDD for behavior changes, independent review and fresh verification.
> Never commit APKs, raw traffic, credentials or personal responses. Keep the
> repository private and do not push, publish or change visibility without the
> owner's explicit instruction. State the tested HA version and remaining live
> assumptions; do not infer compatibility with the latest HA release.

Current runtime targets are Core and official `pytest-homeassistant` 2026.11.1
(target) and 2026.11.0 (minimum), Python 3.14. See `docs/validation.md` for exact
counts and pending final gates. Use `requirements-dev.txt` and
`requirements-min.txt`, both including `requirements-test.txt`. Do not reinstall
the discontinued custom-component harness. Installed Superpowers skills provide
the workflow; original v1 design docs are historical.

The owner has installed the published 0.3.0 release. This branch prepares 0.4.0
with an admin `axiell_libraries.renew_loan` action; no tag or release is created.
See `docs/home-assistant-ui.md` for manual, expiring confirmation IDs and unknown
outcomes. The main-only Release workflow reruns validation, checks the exact
input against the manifest, creates a new tag atomically, then publishes notes.
Investigate partial publication manually; do not blindly rerun or move tags.
Existing live authentication, aggregate sensors and Marketplace installation
have owner verification. Live renewal/provider prompt semantics, browser covers
and a real process restart still need separate owner-run checks. Offline tests
do not establish upstream behavior or public availability.

Optional live validation belongs to the owner in their HA UI: enter card/PIN
there, never in chat, issue comments, scripts or repository files.
