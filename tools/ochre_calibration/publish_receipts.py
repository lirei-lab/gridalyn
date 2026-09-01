#!/usr/bin/env python3
"""Copy the OCHRE/EnergyPlus result receipts into the tracked repository.

The harness itself cannot run in CI -- its toolchain is roughly 1.6 GB and its
dependencies pin numpy below this repository's floor -- so ``.ochre-calibration/``
is gitignored and rebuilt out of process. That is the right call for a working
tree. It is the wrong call for the *evidence*: the measured error bound, the
holdout flexibility result and the coincidence curves are a few kilobytes each,
and while they live only in an ignored directory nobody outside this machine
can see that the validation happened at all.

This script publishes those few files, so the receipts are reviewable without
the toolchain and a substitution is visible in a diff.

Usage:
    python tools/ochre_calibration/publish_receipts.py            # publish
    python tools/ochre_calibration/publish_receipts.py --check    # verify only
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORK_ROOT = REPO_ROOT / ".ochre-calibration"
RECEIPTS_DIR = Path(__file__).resolve().parent / "receipts"

#: Working-tree path -> published name. Deliberately a short, curated list:
#: these are the files that carry a *result* plus the provenance to read it.
#: Per-dwelling run scratch under ``fleet/work/`` is not evidence and is not
#: published.
PUBLISHED: dict[str, str] = {
    "fleet/rc_error_bound.json": "rc_error_bound.json",
    "fleet/flex/flexbound.json": "flexbound.json",
    "fleet/scaling_validation.json": "scaling_validation.json",
    "fleet/hq_split_targets.json": "hq_split_targets.json",
    "fleet/fleet_summary.json": "fleet_summary.json",
    "feasibility_report.json": "feasibility_report.json",
}


def publish(check_only: bool = False) -> int:
    """Copy each published receipt, or report which ones disagree.

    Args:
        check_only: When true, report differences and copy nothing.

    Returns:
        A process exit code: 0 when the tracked receipts match the working
        tree, 1 when they differ (``--check``) or a source is missing.
    """
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []
    stale: list[str] = []
    for relative, name in PUBLISHED.items():
        source = WORK_ROOT / relative
        target = RECEIPTS_DIR / name
        if not source.is_file():
            missing.append(f"{source} (published copy: {target.name})")
            continue
        if target.is_file() and filecmp.cmp(source, target, shallow=False):
            continue
        stale.append(name)
        if not check_only:
            shutil.copy2(source, target)

    if missing:
        print(
            "the OCHRE working tree does not carry these sources; the tracked\n"
            "receipts are the only copy, which is expected on a machine that\n"
            "has not run the harness:",
            file=sys.stderr,
        )
        for item in missing:
            print(f"  {item}", file=sys.stderr)
    if stale:
        verb = "differ from" if check_only else "updated from"
        print(f"{len(stale)} receipt(s) {verb} the working tree:")
        for name in sorted(stale):
            print(f"  {name}")
    elif not missing:
        print(f"all {len(PUBLISHED)} receipts match the working tree")
    return 1 if (check_only and stale) else 0


def main(argv: list[str] | None = None) -> int:
    """Run the receipt publisher.

    Args:
        argv: Command-line arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="report receipts that differ from the working tree, copy nothing",
    )
    args = parser.parse_args(argv)
    return publish(check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
