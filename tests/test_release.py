"""Exercise the release gate as a maintainer workflow would."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("tag", "version", "allowed"),
    [
        ("0.2.0", "0.2.0", True),
        ("0.3.0", "0.3.0", True),
        ("0.2.0", "0.1.0", False),
        ("v0.2.0", "0.2.0", False),
        ("0.2.0; touch injected", "0.2.0", False),
        ("0.2.0\n", "0.2.0", False),
        ("../main", "../main", False),
        ("", "", False),
    ],
)
def test_release_requires_exact_plain_version(tmp_path, tag, version, allowed):
    """A mismatched, prefixed or shell-shaped version must block publication."""
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"version": version}))
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_release.py"), tag, str(manifest)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == (0 if allowed else 1), result.stdout + result.stderr
    assert not (tmp_path / "injected").exists()


@pytest.mark.parametrize("tag", ["-h", "--help"])
def test_release_workflow_rejects_help_arguments(tag):
    """Help flags must fail the workflow gate before any publication step."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yaml").read_text())
    command = next(
        step["run"]
        for step in workflow["jobs"]["publish"]["steps"]
        if step.get("name") == "Require exact manifest and tag agreement"
    )
    result = subprocess.run(
        ["bash", "-e", "-c", command],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
            "RELEASE_VERSION": tag,
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "the following arguments are required: tag" in result.stderr
    assert not result.stdout
