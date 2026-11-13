"""Exercise the release guard and actual publication shell entirely offline."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SHA = "1234567890abcdef1234567890abcdef12345678"


@pytest.mark.parametrize(
    ("tag", "version", "allowed"),
    [
        ("v0.3.0", "0.3.0", True),
        ("v0.0.0", "0.0.0", True),
        ("v12.34.56", "12.34.56", True),
        ("v0.3.1", "0.3.0", False),
        ("0.3.0", "0.3.0", False),
        ("vv0.3.0", "0.3.0", False),
        ("v00.3.0", "00.3.0", False),
        ("v0.03.0", "0.03.0", False),
        ("v0.3.00", "0.3.00", False),
        ("v0.3.0-rc.1", "0.3.0-rc.1", False),
        ("v0.3.0+build", "0.3.0+build", False),
        ("v0.3.0", "v0.3.0", False),
        ("v0.3.0", 0.3, False),
        ("v0.3.0", None, False),
        ("v0.3.0; touch injected", "0.3.0", False),
        ("v0.3.0$(touch injected)", "0.3.0", False),
        ("v0.3.0`touch injected`", "0.3.0", False),
        ("v0.3.0\n", "0.3.0", False),
        (" v0.3.0", "0.3.0", False),
        ("../main", "../main", False),
        ("", "", False),
        ("-h", "0.3.0", False),
        ("--help", "0.3.0", False),
        ("--unsafe-private-input", "0.3.0", False),
    ],
)
def test_release_requires_canonical_tag_and_numeric_manifest(
    tmp_path, tag, version, allowed
):
    """Loose parsing or echoing rejected input must not reach publication."""
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"version": version}))
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_release.py"), tag, str(manifest)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if allowed:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0
        assert result.stdout + result.stderr in {
            "Release tag must be canonical vX.Y.Z.\n",
            "Release tag must match the canonical numeric manifest version.\n",
            "Invalid release validation arguments.\n",
        }
    assert not (tmp_path / "injected").exists()


@pytest.mark.parametrize("content", [None, "{", "{}", "[]", '"0.3.0"'])
def test_release_rejects_unreadable_manifest(tmp_path, content):
    """Missing or malformed manifest data must fail with a static error."""
    manifest = tmp_path / "manifest.json"
    if content is not None:
        manifest.write_text(content)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/check_release.py"),
            "v0.3.0",
            str(manifest),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert result.stdout == "Cannot read the integration manifest version.\n"
    assert not result.stderr


@pytest.fixture
def publish_shell(tmp_path):
    """Run the checked-in workflow shell with a recording fake gh, never GitHub."""
    workflow = yaml.load(
        (ROOT / ".github/workflows/release.yaml").read_text(), Loader=yaml.BaseLoader
    )
    step = next(
        step
        for step in workflow["jobs"]["publish"]["steps"]
        if step.get("name") == "Create tag and publish source release"
    )
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/check_release.py", tmp_path / "scripts")
    manifest = tmp_path / "custom_components/axiell_libraries/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"version": "0.3.0"}')
    notes = tmp_path / "docs/releases/0.3.0.md"
    notes.parent.mkdir(parents=True)
    notes.write_text("Reviewed synthetic notes.\n")
    calls = tmp_path / "calls.jsonl"
    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    gh = bin_path / "gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "with open(os.environ['FAKE_GH_CALLS'], 'a') as stream:\n"
        "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1] == 'api' and os.environ.get('FAIL_TAG') == '1':\n"
        "    sys.exit(1)\n"
    )
    gh.chmod(0o755)

    def run(version="0.3.0", **extra_env):
        result = subprocess.run(
            [
                "bash",
                "--noprofile",
                "--norc",
                "-e",
                "-o",
                "pipefail",
                "-c",
                step["run"],
            ],
            cwd=tmp_path,
            env={
                **os.environ,
                "PATH": os.pathsep.join(
                    [
                        str(bin_path),
                        str(Path(sys.executable).parent),
                        os.environ["PATH"],
                    ]
                ),
                "RELEASE_VERSION": version,
                "GITHUB_REPOSITORY": "synthetic/library",
                "GITHUB_SHA": SHA,
                "GH_TOKEN": "offline-fake",
                "FAKE_GH_CALLS": str(calls),
                **extra_env,
            },
            capture_output=True,
            text=True,
            timeout=10,
        )
        recorded = (
            [json.loads(line) for line in calls.read_text().splitlines()]
            if calls.exists()
            else []
        )
        return result, recorded

    return run, notes


def test_workflow_creates_immutable_tag_then_reviewed_release(publish_shell):
    """Wrong tag, commit, title, notes or ordering changes the publication contract."""
    run, _ = publish_shell
    result, calls = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == [
        [
            "api",
            "--method",
            "POST",
            "repos/synthetic/library/git/refs",
            "-f",
            "ref=refs/tags/v0.3.0",
            "-f",
            f"sha={SHA}",
        ],
        [
            "release",
            "create",
            "v0.3.0",
            "--verify-tag",
            "--title",
            "0.3.0",
            "--notes-file",
            "docs/releases/0.3.0.md",
        ],
    ]


@pytest.mark.parametrize(
    "version",
    [
        "0.3.1",
        "v0.3.0",
        "00.3.0",
        "0.3.0-rc.1",
        "--help",
        "-h",
        "",
        "0.3.0\n",
        "0.3.0; touch injected",
        "$(touch injected)",
        "`touch injected`",
    ],
)
def test_workflow_rejects_version_before_any_github_write(publish_shell, version):
    """Removing the guard from the publication step would allow unsafe writes."""
    run, notes = publish_shell
    result, calls = run(version)
    assert result.returncode != 0
    assert calls == []
    assert not (notes.parents[2] / "injected").exists()


def test_workflow_failed_atomic_tag_creation_cannot_publish(publish_shell):
    """An existing tag or GitHub ref failure must stop before release creation."""
    run, _ = publish_shell
    result, calls = run(FAIL_TAG="1")
    assert result.returncode != 0
    assert len(calls) == 1
    assert calls[0][:3] == ["api", "--method", "POST"]


@pytest.mark.parametrize("missing", [True, False])
def test_workflow_requires_reviewed_notes_before_tag_creation(publish_shell, missing):
    """Missing/empty notes must not leave an orphaned tag."""
    run, notes = publish_shell
    if missing:
        notes.unlink()
    else:
        notes.write_text("")
    result, calls = run()
    assert result.returncode != 0
    assert calls == []


def test_workflow_rejects_invalid_commit_before_tag_creation(publish_shell):
    """A malformed commit cannot become the release target."""
    run, _ = publish_shell
    result, calls = run(GITHUB_SHA="main")
    assert result.returncode != 0
    assert calls == []


def test_workflow_only_publishes_main_after_full_validation():
    """A feature ref or skipped validation must have no write-enabled path."""
    workflow = yaml.load(
        (ROOT / ".github/workflows/release.yaml").read_text(), Loader=yaml.BaseLoader
    )
    validate = workflow["jobs"]["validate"]
    publish = workflow["jobs"]["publish"]
    assert validate["if"] == publish["if"] == "github.ref == 'refs/heads/main'"
    assert validate["uses"] == "./.github/workflows/validate.yaml"
    assert publish["needs"] == "validate"
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {}
    assert validate["permissions"] == {"contents": "read"}
    assert publish["permissions"] == {"contents": "write"}
    assert publish["env"]["RELEASE_VERSION"] == "${{ inputs.version }}"
    assert publish["steps"][0]["with"]["ref"] == "${{ github.sha }}"
    for step in publish["steps"]:
        assert "${{" not in step.get("run", "")
    validation_workflow = yaml.load(
        (ROOT / ".github/workflows/validate.yaml").read_text(), Loader=yaml.BaseLoader
    )
    assert "workflow_call" in validation_workflow["on"]
    assert set(validation_workflow["jobs"]) == {"hassfest", "lint", "tests"}
    assert {
        entry["core"]
        for entry in validation_workflow["jobs"]["tests"]["strategy"]["matrix"][
            "include"
        ]
    } == {"2026.11.0", "2026.11.1"}
