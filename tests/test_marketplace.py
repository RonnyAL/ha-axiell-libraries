"""Check our source distribution with the installed Core Marketplace offline."""

import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from homeassistant.components.marketplace.repositories.base import (
    RepositoryArchive,
    RepositoryManifest,
)
from homeassistant.components.marketplace.repositories.integration import (
    IntegrationRepository,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def source_archive():
    """Model a GitHub source archive using non-ignored repository files."""
    paths = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
        )
        .decode()
        .split("\0")
    )
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        for path in sorted(set(paths) - {""}):
            archive.write(ROOT / path, f"repository-source/{path}")
    return RepositoryArchive(content.getvalue())


async def test_marketplace_installs_loadable_self_contained_source(
    hass, tmp_path, source_archive
):
    """A missing hacs.json, extra integration or omitted module breaks install."""
    marketplace = SimpleNamespace(
        hass=hass,
        core=SimpleNamespace(config_path=str(tmp_path)),
    )
    repository = IntegrationRepository(marketplace, "RonnyAL/ha-axiell-libraries")
    repository.repository_manifest = RepositoryManifest.from_dict(
        json.loads(source_archive.read("hacs.json"))
    )
    repository.tree = source_archive.tree
    repository.treefiles = [entry.path for entry in repository.tree]
    domains = {
        entry.path
        for entry in repository.tree
        if entry.type == "tree"
        and entry.path.startswith("custom_components/")
        and entry.path.count("/") == 1
    }
    assert domains == {"custom_components/axiell_libraries"}
    repository.resolve_content()
    assert repository.try_resolve_content()
    assert not repository.should_try_releases  # No release ZIP asset needed.
    repository._use_integration_manifest(
        json.loads(
            source_archive.read(f"{repository.content.path.remote}/manifest.json")
        )
    )
    assert repository.validate.success
    assert repository.data.config_flow
    assert repository.display_name == "Axiell Libraries"
    assert not await repository.async_replaces_built_in()
    repository.content.path.local = repository.localpath
    await repository._async_extract_archive(source_archive)
    await repository.async_check_written_content()

    # Import only the extracted package, away from the checkout. This catches
    # missing runtime files and dependencies accidentally placed at repo root.
    imported = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from custom_components.axiell_libraries import config_flow, sensor, todo",
            str(tmp_path),
        ],
        cwd=tmp_path,
        timeout=30,
        capture_output=True,
        text=True,
    )
    assert imported.returncode == 0, imported.stderr
    installed = Path(repository.localpath)
    for locale in ("en", "nb"):
        assert json.loads((installed / "translations" / f"{locale}.json").read_text())
    assert not (tmp_path / "tests").exists()


@pytest.mark.parametrize(
    ("core_version", "can_install"),
    [("2026.10.5", False), ("2026.11.0", True), ("2026.11.1", True)],
)
def test_marketplace_minimum_blocks_older_core(core_version, can_install):
    """Missing/invalid floor metadata must not silently allow an older Core."""
    repository = IntegrationRepository(
        SimpleNamespace(
            core=SimpleNamespace(config_path="/unused"),
            version=SimpleNamespace(string=core_version),
        ),
        "RonnyAL/ha-axiell-libraries",
    )
    repository.repository_manifest = RepositoryManifest.from_dict(
        json.loads((ROOT / "hacs.json").read_text())
    )
    repository.data.releases = True
    assert repository.can_install is can_install
