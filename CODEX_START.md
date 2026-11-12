# Starting prompt for Codex

Paste the following message in a Codex session opened in the root of this checkout (Codex CLI or Codex app):

> Implement **Axiell Libraries** as a native read-only Home Assistant custom integration, using **Superpowers**. The design is approved. First read `AGENTS.md`, `docs/protocol.md`, `docs/superpowers/specs/2026-11-13-axiell-libraries-design.md`, and the task-by-task plan in `docs/superpowers/plans/2026-11-13-axiell-libraries-v1.md`.
>
> Use `superpowers:subagent-driven-development` when supported, otherwise `superpowers:executing-plans`. Follow TDD and review each task. Start with Task 1. Do not ask again whether to use MQTT, multiple cards, generated DeviceIDs, or a native integration: those decisions are final. Preserve a persistent `secrets.token_hex(8)` DeviceID per config entry, never per login. Never commit an APK, raw traffic or personal credentials. Build testable, async Home Assistant code with offline mocked API tests. Show verified test results before claiming any task is complete.

Codex + Superpowers is a separate development environment from this chat. Install/check the Superpowers plugin in Codex CLI with `/plugins`, or in the Codex app via Plugins. See <https://github.com/obra/superpowers#installation>.

No credentials are included in the repository. For optional live validation, ask the owner to enter a library card number and PIN in Home Assistant, not into issue comments or committed code.
