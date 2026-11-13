"""Check our source distribution with the installed Core Marketplace offline."""

import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogithubapi.models.release import GitHubReleaseModel
from homeassistant.components.marketplace.repositories.base import (
    RepositoryArchive,
    RepositoryManifest,
)
from homeassistant.components.marketplace.repositories.integration import (
    IntegrationRepository,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def source_archive_bytes():
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
    return content.getvalue()


@pytest.fixture
def source_archive(source_archive_bytes):
    """Open the exact archive supplied by the simulated GitHub download."""
    return RepositoryArchive(source_archive_bytes)


async def test_marketplace_installs_loadable_self_contained_source(
    hass, tmp_path, source_archive, source_archive_bytes
):
    """A missing hacs.json, extra integration or omitted module breaks install."""
    archive_requests = []

    async def download_file(remote, **kwargs):
        archive_requests.append(str(remote))
        return source_archive_bytes

    release = GitHubReleaseModel(
        {
            "id": 30,
            "tag_name": "v0.4.0",
            "target_commitish": "main",
            "name": "0.4.0",
            "draft": False,
            "prerelease": False,
            "published_at": "2026-11-13T12:00:00Z",
            "assets": [],
            "body": "Synthetic reviewed release notes.",
        }
    )
    marketplace = SimpleNamespace(
        hass=hass,
        core=SimpleNamespace(config_path=str(tmp_path)),
        githubapi=SimpleNamespace(
            repos=SimpleNamespace(releases=SimpleNamespace(list=object()))
        ),
        async_github_api_method=AsyncMock(return_value=SimpleNamespace(data=[release])),
        async_download_file=download_file,
    )
    repository = IntegrationRepository(marketplace, "RonnyAL/ha-axiell-libraries")
    await repository._async_update_releases()
    assert repository.display_available_version == "v0.4.0"
    assert repository.version_to_install() == "v0.4.0"
    assert repository.data.published_tags == ["v0.4.0"]
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
    repository.ref = f"tags/{repository.version_to_install()}"
    await repository.download_repository_zip()
    assert archive_requests == [
        "RonnyAL/ha-axiell-libraries/archive/refs/tags/v0.4.0.zip"
    ]
    await repository.async_check_written_content()

    # Import only the extracted package, away from the checkout. This catches
    # missing runtime files and dependencies accidentally placed at repo root.
    imported = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from custom_components.axiell_libraries import "
            "config_flow, sensor, services, todo",
            str(tmp_path),
        ],
        cwd=tmp_path,
        timeout=30,
        capture_output=True,
        text=True,
    )
    assert imported.returncode == 0, imported.stderr
    installed = Path(repository.localpath)
    assert json.loads((installed / "manifest.json").read_text())["version"] == "0.4.0"
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


@pytest.mark.parametrize(
    ("installed_version", "installed_commit", "pending"),
    [
        ("v0.2.0", None, True),
        ("0.3.0", None, True),
        ("v0.3.0", None, True),
        ("0.4.0", None, False),
        ("v0.4.0", None, False),
        ("v0.5.0", None, False),
        (None, "abcdef0", True),
    ],
)
def test_marketplace_compares_published_release_to_installed_version(
    installed_version, installed_commit, pending
):
    """The prefixed release must update old versions/hashes without downgrades."""
    repository = IntegrationRepository(
        SimpleNamespace(core=SimpleNamespace(config_path="/unused")),
        "RonnyAL/ha-axiell-libraries",
    )
    repository.data.installed = True
    repository.data.releases = True
    repository.data.installed_version = installed_version
    repository.data.installed_commit = installed_commit
    repository.data.last_version = "v0.4.0"
    assert repository.pending_update is pending
