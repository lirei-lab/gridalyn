#!/usr/bin/env python3
"""Retrain the packaged LightGBM macro weights from the Hydro-Québec set.

The driver that produced `gridalyn/assets/datagen/models/weights/*.pkl` was
deleted before its inputs were recorded anywhere, so for a while the trained
heart of the load generator had no stated provenance at all. This script exists
to name them.

It cannot run without `datasets/hq`, which is private metered Hydro-Québec data
and is gitignored. That is a real limit and the script says so with a located
error rather than failing obscurely -- a driver that refuses for a stated reason
is more reproducible than no driver.

Read `gridalyn/assets/datagen/models/weights/PROVENANCE.md` before running this.
Retraining replaces the inputs of **every** governed CI baseline in the
repository, so it is a deliberate act with a re-base behind it, never a cleanup.

Usage:
    python tools/train_macro_weights.py --check     # report inputs, train nothing
    python tools/train_macro_weights.py --i-know-this-rebases-every-baseline
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HQ_DIR = REPO_ROOT / "datasets" / "hq"
WEIGHTS_DIR = REPO_ROOT / "gridalyn" / "assets" / "datagen" / "models" / "weights"

#: The three tables the fit consumes, and what each supplies.
INPUTS: dict[str, str] = {
    "consumption.h5": "total metered load, (35041, 1000) at 15 min; background "
    "target is the per-step mean of consumption minus heating",
    "heating.h5": "metered heating load, same shape; heating target is its "
    "per-step mean across the 1000 dwellings",
    "meteo.h5": "weather, (105121, 9) at 5 min; DryBulb resampled to 15 min "
    "supplies the temperature feature",
}


def describe_inputs() -> int:
    """Report which inputs the fit needs and whether they are present.

    Returns:
        0 when every input is present, 1 when any is missing.
    """
    print(f"training inputs, expected under {HQ_DIR}:\n")
    missing = 0
    for name, role in INPUTS.items():
        path = HQ_DIR / name
        mark = "present" if path.is_file() else "MISSING"
        if not path.is_file():
            missing += 1
        print(f"  [{mark}] {name}")
        print(f"           {role}")
    print("\ncurrent packaged weights:")
    for name in ("lgbm_heating_macro.pkl", "lgbm_bg_macro.pkl"):
        path = WEIGHTS_DIR / name
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            print(f"  {name}  sha256 {digest}")
        else:
            print(f"  {name}  MISSING")
    if missing:
        print(
            f"\n{missing} input(s) absent. datasets/hq is private metered "
            "Hydro-Quebec data, is gitignored, and cannot be redistributed; "
            "retraining is possible only where it is held. See "
            "gridalyn/assets/datagen/models/weights/PROVENANCE.md.",
            file=sys.stderr,
        )
    return 1 if missing else 0


def train() -> int:
    """Refit both macro models and overwrite the packaged weights.

    Returns:
        0 on success, 1 when an input is missing.

    Raises:
        FileNotFoundError: If a required table is absent, naming it and the
            reason it cannot be shipped.
    """
    import pandas as pd

    from gridalyn.assets.datagen.load_profiles import ParametricArxGenerator

    for name in INPUTS:
        path = HQ_DIR / name
        if not path.is_file():
            raise FileNotFoundError(
                f"{path} not found. This is private metered Hydro-Quebec data, "
                "gitignored and not redistributable, so the packaged weights "
                "cannot be re-derived outside the machines that hold it. See "
                "gridalyn/assets/datagen/models/weights/PROVENANCE.md for what "
                "the shipped weights were trained on."
            )

    consumption = pd.read_hdf(HQ_DIR / "consumption.h5") / 1000.0
    heating = pd.read_hdf(HQ_DIR / "heating.h5") / 1000.0
    meteo = pd.read_hdf(HQ_DIR / "meteo.h5")
    background = consumption - heating

    print(
        f"fitting on {consumption.shape[1]} dwellings, "
        f"{consumption.shape[0]} steps, "
        f"{consumption.index[0]} -> {consumption.index[-1]}"
    )
    ParametricArxGenerator(random_seed=42).fit(meteo, heating, background)
    print("\nweights rewritten. New digests:")
    for name in ("lgbm_heating_macro.pkl", "lgbm_bg_macro.pkl"):
        digest = hashlib.sha256((WEIGHTS_DIR / name).read_bytes()).hexdigest()
        print(f"  {name}  {digest}")
    print(
        "\nUpdate PROVENANCE.md and tests/test_macro_weights_provenance.py with "
        "these digests, and re-base every governed baseline deliberately."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the weights driver.

    Args:
        argv: Command-line arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="report the inputs and current digests, train nothing",
    )
    parser.add_argument(
        "--i-know-this-rebases-every-baseline",
        action="store_true",
        help="actually refit and overwrite the packaged weights",
    )
    args = parser.parse_args(argv)
    if args.i_know_this_rebases_every_baseline:
        return train()
    if not args.check:
        parser.print_help()
        print(
            "\nRefusing to retrain without the explicit flag: these weights are "
            "the inputs of every governed baseline in the repository."
        )
        return 2
    return describe_inputs()


if __name__ == "__main__":
    raise SystemExit(main())
