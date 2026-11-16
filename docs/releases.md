# Maintainer releases

Version **0.6.0** adds account-bound snapshot restoration, a diagnostic refresh
timestamp and a native Refresh now button, preserving existing IDs, recovery and
renewal safeguards. The owner explicitly requested release on 2026-11-16,
superseding the snapshot feature's earlier PR-only restriction for this release
only. This authorizes publication of 0.6.0; later publications and live renewal
tests require separate instruction. No live renewal
or provider prompt sequence has been verified. Repository visibility stays unchanged.

## Why Marketplace displays a commit hash

The original commit label came from the absence of a **published GitHub
Release**, even though the manifest already contained a numeric version. A Git
tag alone does not supply Marketplace's published-release source. Editing the
manifest alone therefore does not replace the old commit label. The label can
remain until a release is published and that version is installed.

Use numeric manifest version `0.6.0`, canonical Git tag `v0.6.0`, and release
title `0.6.0`. Home Assistant 2026.11.1 Marketplace code selects the
published tag unchanged and downloads `archive/refs/tags/v0.6.0.zip`; its version
comparison normalizes the prefix, so numeric manifest `0.6.0` is accepted.
Supported-runtime offline tests exercise that implementation, actual source
extraction and loadability. The official guide does not explicitly document prefix
normalization; offline evidence alone does not establish a live 0.6.0 install.
No attached ZIP asset is required.

For direct-link installs, connect GitHub in Marketplace for periodic GitHub
update checks (the documented interval is 48 hours). Catalog propagation has a
separate delay. A published release is not necessarily displayed immediately.
Back up HA and restart after installing an integration update.

## Publication workflow

The 0.6.0 release also has a single-version publication workflow because this
session's GitHub connector cannot dispatch workflows and local CLI networking is
unavailable. It only responds to a push on `main` that changes
`.github/workflows/publish-0.6.0.yaml` and carries `[publish-v0.6.0]` in the commit
message. Both jobs enforce that gate; publication requires the complete reusable
validation, checks the exact checkout SHA, and can create only `v0.6.0`. It shares
the ordinary release concurrency group and atomic tag safeguards. Ordinary pushes
and PRs do not publish. The general Release workflow below remains manual.

1. Review the feature changes, [changelog](../CHANGELOG.md),
   [0.6.0 notes](releases/0.6.0.md) and owner-run limits. Require independent
   review, full supported Core 2026.11.0/2026.11.1 suites, pinned Ruff and hassfest
   on the exact release PR head. Verify that `v0.6.0` does not already exist.
2. Squash-merge the exact reviewed head to `main` with `[publish-v0.6.0]` in
   the merge commit message. The workflow rename supplies the required path
   change. Watch both validation and publication; do not infer success from merge.
3. The workflow reruns complete reusable validation at the exact merge
   `github.sha`. Both jobs enforce main, push and marker gates; publication
   needs successful validation. Checkout and tag target use that same full SHA.
4. The publication shell safely derives `v0.6.0` from the fixed numeric version,
   validates strict canonical SemVer and exact manifest agreement, and checks
   nonempty notes and a full SHA before GitHub writes. It atomically creates
   the tag ref, then publishes title `0.6.0` with `--verify-tag` and
   `--notes-file docs/releases/0.6.0.md`.
5. Verify the tag targets the validated merge SHA, the published release is
   neither draft nor prerelease, and its notes and source manifest match 0.6.0.

The general **Actions → Release → Run workflow** remains available on `main`
with numeric input `0.6.0` (no `v`). It runs the same complete reusable validation
and publication shell at its dispatch SHA. Inspect state before using it after
an attempted publication; it cannot reuse an existing tag. Later releases need
new owner instructions and reviewed manifest/notes changes.

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
