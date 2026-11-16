# Maintainer releases

Version **0.5.1** fixes catalogue body session-expiry and validation-required
statuses while preserving bounded recovery and single-write renewal. The owner explicitly
requested release on 2026-11-16. This authorizes publication of 0.5.1; future
publications and live renewal tests require separate instruction. No live renewal
or provider prompt sequence has been verified. Repository visibility stays unchanged.

## Why Marketplace displays a commit hash

The original commit label came from the absence of a **published GitHub
Release**, even though the manifest already contained a numeric version. A Git
tag alone does not supply Marketplace's published-release source. Editing the
manifest alone therefore does not replace the old commit label. The label can
remain until a release is published and that version is installed.

Use numeric manifest version `0.5.1`, canonical Git tag `v0.5.1`, and release
title `0.5.1`. Installed Home Assistant 2026.11.1 Marketplace code selects the
published tag unchanged and downloads `archive/refs/tags/v0.5.1.zip`; its version
comparison normalizes the prefix, so numeric manifest `0.5.1` is accepted.
Offline tests exercise that installed implementation, actual source extraction
and loadability. The official guide does not explicitly document prefix
normalization; offline evidence alone does not establish a live 0.5.1 install.
No attached ZIP asset is required.

For direct-link installs, connect GitHub in Marketplace for periodic GitHub
update checks (the documented interval is 48 hours). Catalog propagation has a
separate delay. A published release is not necessarily displayed immediately.
Back up HA and restart after installing an integration update.

## Publication workflow

The 0.5.1 release also has a single-version publication workflow because this
session's GitHub connector cannot dispatch workflows and local CLI networking is
unavailable. It only responds to a push on `main` that changes
`.github/workflows/publish-0.5.1.yaml` and carries `[publish-v0.5.1]` in the commit
message. Both jobs enforce that gate; publication requires the complete reusable
validation, checks the exact checkout SHA, and can create only `v0.5.1`. It shares
the ordinary release concurrency group and atomic tag safeguards. Ordinary pushes
and PRs do not publish. The general Release workflow below remains manual.


1. Review the feature changes, [changelog](../CHANGELOG.md) and
   [0.5.1 notes](releases/0.5.1.md), complete the remaining owner-run checks or
   explicitly record their limits, and merge to `main`. The owner authorized
   publication of 0.5.1 on 2026-11-16; obtain separate instruction for later versions.
2. Run **Actions → Release → Run workflow**, selecting `main` and numeric
   input `0.5.1` (no `v`). This workflow remains manual; ordinary pushes and pull requests only validate. Prepare a reviewed manifest/notes change first for later versions.
3. The release workflow runs the complete reusable validation: official
   hassfest, Ruff and both Home Assistant test versions. Both jobs require
   `main`, and publishing needs successful validation. Checkout and tag target
   use the same dispatch `github.sha`; a newer main commit cannot replace it.
4. The publication shell safely derives `v0.5.1` from the input environment
   variable, validates strict canonical SemVer and exact numeric manifest
   agreement, checks nonempty notes and a full commit SHA before GitHub writes.
   It atomically creates the tag ref, then publishes title `0.5.1` with
   `--verify-tag` and `--notes-file docs/releases/0.5.1.md`.

Never move an existing release tag. Atomic ref creation fails if the tag already
exists, even when it points to the same commit. A failed tag creation stops
before release publication. Validation failures, help arguments, malformed
input and missing notes also stop before any GitHub write.

If release publication fails after creating its tag, inspect the failed run,
notes and repository state. Do not blindly rerun, force-update, move or delete
the tag. After checking that the existing tag points at the validated SHA and
that all gates passed, an authorized maintainer can complete publication at
that same tag using the reviewed notes; inconsistent content requires a new
version and reviewed change. No automatic cleanup or tag reuse is performed.

References: [official Marketplace release guide](https://contributors.home-assistant.io/marketplace/guides/releases/),
[Core 2026.11.1 release selection and archives](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/marketplace/repositories/base.py),
[manifest loadability](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/marketplace/repositories/integration.py),
[version comparison](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/marketplace/utils/version.py).
