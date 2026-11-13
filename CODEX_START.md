# Maintainer prompt for Codex

The v1 implementation is present. Start with the current validation ledger and
repository state rather than repeating the implementation from Task 1.

> Maintain **Axiell Libraries** as a native read-only Home Assistant custom
> integration using **Superpowers**. Read `AGENTS.md`, then the approved design,
> `docs/protocol.md`, the task-by-task plan and `docs/validation.md`. Check the
> actual branch and pending review items before choosing the next task.
>
> The design decisions are final: native HA, one entry per library/card,
> persistent `secrets.token_hex(8)` DeviceID, nearby results and manual LocationID,
> Solus `LoginPreSession` then `LoginCheckSession`, and read-only v1. Preserve
> device identity through retries, restart and PIN updates. Use offline synthetic
> tests, TDD for behavior changes, independent review and fresh verification.
> Never commit APKs, raw traffic, credentials or personal responses. Keep the
> repository private and do not push, publish or change visibility without the
> owner's explicit instruction. State the tested HA version and remaining live
> assumptions; do not infer compatibility with the latest HA release.

Current verification uses Python 3.14.7 locally / 3.14.10 in CI, Core and official
`pytest-homeassistant`
2026.11.1 (target) and 2026.11.0 (minimum), 171 offline tests on each. Use
`requirements-dev.txt` and `requirements-min.txt`; both include shared
`requirements-test.txt`. Do not reinstall the discontinued custom-component
harness. See the 2026.11/Marketplace spec and plan under `docs/superpowers/`.
Official hassfest, Ruff and workflow checks are recorded in the validation
ledger; the 2026.2.3 evidence is historical. Installed Superpowers skills provide
the workflow.

Version 0.2.0 is prepared, not published. Direct public Marketplace installation
requires merge, an owner visibility decision and a matching GitHub release.
The main-only Release workflow reruns validation, checks the exact input against
the manifest, creates a new tag atomically, then publishes a source release.
Investigate partial publication manually; do not blindly rerun or move tags.
Marketplace install/update, browser rendering, real process restart and complete
live Solus operation remain owner-run checks. Preserve the protocol assumptions
already documented; offline packaging tests do not prove public availability.

Optional live validation belongs to the owner in their HA UI: enter card/PIN
there, never in chat, issue comments, scripts or repository files.
