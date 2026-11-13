# Home Assistant 2026.11 and Marketplace update

The existing approved native, read-only integration design remains binding. This
update targets Home Assistant 2026.11.1 and direct GitHub installation through
Settings → Marketplace → Add from link. Official catalog inclusion is out of scope.

## Compatibility and verification

- Use Python 3.14 and the official `pytest-homeassistant` package matching each
  tested Core version. The old custom-component harness is discontinued and
  incompatible with Core 2026.11. Do not override its dependencies or patch Core
  internals to make tests appear compatible.
- Verify the complete offline suite on actual Core 2026.11.1 and 2026.11.0;
  declare 2026.11.0 as the minimum only after both pass.
- Review current config-flow, coordinator, sensor, to-do and schema interfaces.
  Make only changes justified by current documentation or failing tests.
- Preserve the config entry schema and persisted DeviceID through loading an
  existing entry after an upgrade. Retain all authentication, discovery,
  multiple-account, date, sensor and failure tests.

## Distribution

- Keep exactly one integration at `custom_components/axiell_libraries/`.
- Add root `hacs.json` with the verified minimum and integration name; use
  standard source distribution, without an unnecessary release ZIP.
- Prepare integration version `0.2.0`, matching future release tag `0.2.0`.
- Correct all official hassfest failures, including manifest ordering and
  translation selector keys. Use the installed Core Marketplace implementation
  for meaningful offline metadata/structure validation where feasible.
- Add push/PR CI: official `home-assistant/actions/hassfest@master`, Ruff check
  and format check, and the full pytest suite on both supported Core versions.
- Add a versioned release workflow, gated by the same validation and strict
  manifest/tag agreement. Publishing is a maintainer action after merging.
- README must describe Add from link, configuration, updates/restarts, minimum
  version, GitHub connection for update polling, and release maintenance.

## Publication boundary

The existing repository is private, and AGENTS.md explicitly prohibits changing
visibility. Prepare and open the requested pull request, run GitHub Actions, and
report that public direct installation needs the owner to make the reviewed
repository public and publish a release. Do not change visibility or merge.
Do not claim a live Marketplace install or live Solus validation occurred.

## Sources checked

- https://contributors.home-assistant.io/marketplace/
- https://contributors.home-assistant.io/marketplace/guides/integrations/
- https://contributors.home-assistant.io/marketplace/guides/releases/
- https://contributors.home-assistant.io/marketplace/reference/hacs-json/
- https://contributors.home-assistant.io/marketplace/reference/validation/
- https://github.com/home-assistant/core/tree/2026.11.1/packages/pytest-homeassistant

The old harness README explicitly directs users to the official Core package.
PyPI reports matching official test packages for this release family.
