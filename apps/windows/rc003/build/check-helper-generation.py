"""Fail a build when HID helper sources change without a new HELPER_GENERATION.

Installed copies reuse a helper whenever the manifest generation matches the
running build. If the helper binary changes but the generation does not, every
upgrade silently keeps the previous helper. Build this guard into the release
pipeline so that mistake stops the build instead of shipping.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

RC003_ROOT = Path(__file__).resolve().parents[1]
RECORD_PATH = RC003_ROOT / "build" / "helper-generation.json"
HELPER_SOURCE = RC003_ROOT / "src" / "ovb_rc003" / "hid_elevation_windows.py"

sys.path.insert(0, str(RC003_ROOT / "build"))
from native_inventory import helper_source_files


def _generation() -> int:
    text = HELPER_SOURCE.read_text(encoding="utf-8")
    match = re.search(r"^HELPER_GENERATION = (\d+)$", text, re.MULTILINE)
    if match is None:
        raise SystemExit("HELPER_GENERATION not found in hid_elevation_windows.py")
    return int(match.group(1))


def _source_digest() -> str:
    entries = []
    for path in helper_source_files(RC003_ROOT):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append(f"{digest}  {path.relative_to(RC003_ROOT).as_posix()}")
    return hashlib.sha256("\n".join(sorted(entries)).encode("utf-8")).hexdigest()


def _load_record() -> tuple[int, str]:
    record = json.loads(RECORD_PATH.read_text(encoding="utf-8"))
    return int(record["generation"]), str(record["source_digest"]).strip().lower()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--update",
        action="store_true",
        help="record the current helper sources as the release baseline",
    )
    args = parser.parse_args()

    generation = _generation()
    digest = _source_digest()

    if args.update:
        RECORD_PATH.write_text(
            json.dumps({"generation": generation, "source_digest": digest}, indent=2)
            + "\n",
            encoding="utf-8",
        )
        print(
            "check-helper-generation: recorded generation "
            f"{generation} ({digest[:12]})"
        )
        return 0

    try:
        recorded_generation, recorded_digest = _load_record()
    except (OSError, ValueError, KeyError, TypeError):
        print(f"check-helper-generation: baseline record is missing or invalid: {RECORD_PATH}")
        print("- run `python build/check-helper-generation.py --update` once the helper change is reviewed")
        return 1

    if generation < recorded_generation:
        print(
            "check-helper-generation: HELPER_GENERATION "
            f"{generation} is lower than the recorded {recorded_generation}"
        )
        return 1

    if generation == recorded_generation and digest != recorded_digest:
        print("check-helper-generation: HID helper sources changed but HELPER_GENERATION is unchanged")
        print(f"- recorded generation {recorded_generation}, source digest {recorded_digest[:12]}")
        print(f"- current source digest {digest[:12]}")
        print(
            "- raise HELPER_GENERATION in src/ovb_rc003/hid_elevation_windows.py, then run "
            "`python build/check-helper-generation.py --update`"
        )
        return 1

    if generation > recorded_generation:
        print("check-helper-generation: HELPER_GENERATION was raised; record the new baseline")
        print("- run `python build/check-helper-generation.py --update` and commit build/helper-generation.json")
        return 1

    print("check-helper-generation: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
