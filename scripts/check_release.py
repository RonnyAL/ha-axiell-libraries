"""Refuse publishing unless a canonical vX.Y.Z tag matches the numeric manifest."""

import argparse
import json
import re
from pathlib import Path

SEMVER = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"


class ReleaseArgumentParser(argparse.ArgumentParser):
    """Reject invalid arguments without echoing untrusted input."""

    def error(self, message: str) -> None:
        """Keep help/argument failure output static and nonzero."""
        self.exit(2, "Invalid release validation arguments.\n")


def main() -> int:
    """Validate a maintainer-provided tag before any GitHub write."""
    parser = ReleaseArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("tag")
    parser.add_argument(
        "manifest",
        nargs="?",
        type=Path,
        default=Path("custom_components/axiell_libraries/manifest.json"),
    )
    args = parser.parse_args()
    if re.fullmatch("v" + SEMVER, args.tag) is None:
        print("Release tag must be canonical vX.Y.Z.")
        return 1
    try:
        version = json.loads(args.manifest.read_text())["version"]
    except OSError, ValueError, KeyError, TypeError:
        print("Cannot read the integration manifest version.")
        return 1
    if (
        not isinstance(version, str)
        or re.fullmatch(SEMVER, version) is None
        or args.tag[1:] != version
    ):
        print("Release tag must match the canonical numeric manifest version.")
        return 1
    print(f"Release tag and manifest agree: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
