# Release 0.6.0

The owner explicitly requested "release it" after PR #10 was implemented,
independently reviewed and passed 873 tests on each supported Core version.
This authorizes preparing, merging and publishing that feature as 0.6.0. The
minor version reflects new snapshot persistence and native entities.

Use manifest/title 0.6.0 and immutable tag v0.6.0. Reuse the existing main-only,
single-version publication workflow pattern: changed publish-0.6.0.yaml plus
explicit [publish-v0.6.0] merge marker, complete reusable validation, exact-SHA
checkout, canonical version/notes checks, atomic new tag, then source release.
The connector has no workflow-dispatch/release-create capability; retain the
general manual Release workflow as well. Do not weaken or redesign safeguards.

Keep feature behavior, runtime requirements, identity, renewal safeguards and
repository visibility unchanged. No live library or HA operations are authorized.
Preserve prior release notes and historical evidence. Document startup/cache,
privacy and owner-run verification limits in the new release notes. The previous
PR-only restriction is superseded for this release only; later releases need new
owner instructions.

Before merging, verify release-specific offline tests, full supported CI, lint,
hassfest, release notes and independent review. Merge the exact reviewed PR head
with the explicit publication marker. Verify the resulting workflow, tag target,
published non-draft/non-prerelease release, notes and manifest. If publication
partly fails, inspect state before any retry; never move an existing tag.
