"""Exercise the release gate as a maintainer workflow would."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

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
