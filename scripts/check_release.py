"""Refuse publishing unless a plain release tag matches the manifest exactly."""

import argparse
import json
import re
from pathlib import Path


def main() -> int:
    """Validate a maintainer-provided tag before any GitHub write."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument(
        "manifest",
        nargs="?",
        type=Path,
        default=Path("custom_components/axiell_libraries/manifest.json"),
    )
    args = parser.parse_args()
    if (
        re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", args.tag)
        is None
    ):
        print("Release tag must be a plain X.Y.Z version, without a v prefix.")
        return 1
    try:
        version = json.loads(args.manifest.read_text())["version"]
    except OSError, ValueError, KeyError, TypeError:
        print("Cannot read the integration manifest version.")
        return 1
    if args.tag != version:
        print("Release tag must exactly match the integration manifest version.")
        return 1
    print(f"Release tag and manifest agree: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
