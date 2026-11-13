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

The tested environment is Python 3.13 / HA 2026.2.3; see
`requirements-dev.txt`. Installed Superpowers skills provide the workflow.
Optional live validation belongs to the owner in their HA UI: enter card/PIN
there, never in chat, issue comments, scripts or repository files.
