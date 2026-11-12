# Axiell Libraries for Home Assistant

Development bootstrap for a **read-only, native Home Assistant custom integration** for libraries powered by the Solus API (including Axiell Libraries App). This is **not yet an installable integration**: implementation will be carried out using Codex + Superpowers.

## Scope of v1

- Add multiple configuration entries, **one per library-card account**.
- Generate a random 16-character hexadecimal `DeviceID` once per configuration entry, persist it, and reuse it for every API call, restart, reload, and reauthentication. Never create a new upstream "device" on normal refresh.
- Discover nearby libraries using Solus Locator; searchable choice among returned options plus a manual `LocationID` fallback. Do not claim that Solus exposes a verified global typeahead endpoint.
- Authenticate through the **verified** `LoginPreSession` -> `LoginCheckSession` path and fetch `LoansGet` (the older `Login` method returned a reCAPTCHA error).
- Fetch `RecordGet` metadata for ISBN, author, description, and **direct cover URLs** (`ImageUrl`/`ImageUrlLarge`). Never use `ItemImage.aspx` for covers: observed to return a generic placeholder.
- Expose useful read-only sensors (active loans, nearest due date, overdue count), plus a read-only todo entity containing each loan and its due date; calendar events are optional after the core features pass tests.
- Support reauthentication, caching, failure handling, and sensible refresh intervals.

No renew/return/book reservations in v1. Do not commit user credentials, session tokens, account responses, captures, APKs, or decompiled code.

## Kick off Codex

The project is ready for Codex to implement. Read `AGENTS.md`, the design in `docs/superpowers/specs/`, and the plan in `docs/superpowers/plans/` before writing product code. A copy-paste starting prompt is in [`CODEX_START.md`](CODEX_START.md).

## Create the private GitHub repository

From this folder, with the [GitHub CLI](https://cli.github.com/) installed and authenticated:

```bash
gh repo create ha-axiell-libraries --private --source=. --remote=origin --push
```

The supplied archive already contains an initial Git commit on `main`. If you rename the project, adjust the repository name in the command. Do not make the repository public until the implementation and its references have been reviewed.

## Reference material

- [`docs/protocol.md`](docs/protocol.md) - sanitized verified HTTP flow and data mappings.
- [`tests/fixtures/`](tests/fixtures/) - synthetic API data to anchor offline tests.
- [`docs/superpowers/specs/2026-11-13-axiell-libraries-design.md`](docs/superpowers/specs/2026-11-13-axiell-libraries-design.md) - agreed v1 requirements.
- [`docs/superpowers/plans/2026-11-13-axiell-libraries-v1.md`](docs/superpowers/plans/2026-11-13-axiell-libraries-v1.md) - TDD-oriented execution plan.

This integration uses reverse-engineered, **unofficial** API endpoints. They may change and should not be represented as officially supported by Solus or Axiell. All network traffic must be HTTPS.
