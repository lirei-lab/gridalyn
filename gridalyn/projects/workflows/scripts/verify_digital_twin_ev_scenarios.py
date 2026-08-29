"""Verify deterministic EV adoption overlays for the digital twin.

Backs ``gridalyn twin verify-scenarios``. Every check answers one question: are
the overlays deterministic from their declared seed, nested as adoption rises,
and independent of building area?

The checks are unchanged from the version that raised ``SystemExit`` inline;
what changed is that :func:`verify_scenario_overlays` **returns** its finding
and ``main`` decides what to do with it. That split is what makes the verifier
verifiable: a script whose only failure channel is process exit cannot be
exercised by a test, which is how three scripts whose whole job is checking
came to have nothing checking them.

Short-circuit order is preserved deliberately. Later checks index data the
earlier ones establish -- a row-count mismatch left uncaught would surface as a
pandas error rather than a located message -- so the first failure still stops
the run, exactly as before.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]

from gridalyn.foundation import ArtifactLayout  # noqa: E402

DEFAULT_LAYOUT = ArtifactLayout(ROOT)
BASE_DIR = DEFAULT_LAYOUT.base
SCENARIO_DIR = DEFAULT_LAYOUT.scenarios

#: Declared adoption percentage per scenario id.
SCENARIOS: dict[str, int] = {"S0": 0, "S1": 10, "S2": 20, "S3": 30, "S4": 40}


class VerificationFailed(Exception):
    """One verification check failed. Carries the located message."""


def _load_json(path: Path) -> dict:
    with path.open("r") as f:
        return json.load(f)


def _expected_count(n_buildings: int, pct: int) -> int:
    return int(round(n_buildings * pct / 100.0))


def _check_assignment_table(assignments: pd.DataFrame, buildings: pd.DataFrame) -> None:
    """Check the assignment table's shape against the base twin.

    Raises:
        VerificationFailed: On the first structural mismatch. Structural
            because every per-scenario check below indexes this frame.
    """
    if "area_m2" in assignments.columns:
        raise VerificationFailed("EV assignment table must not contain area_m2.")
    expected_rows = len(buildings) * len(SCENARIOS)
    if len(assignments) != expected_rows:
        raise VerificationFailed(
            f"expected {expected_rows} assignment rows, found {len(assignments)}."
        )
    if set(assignments["building_id"]) != set(buildings["building_id"]):
        raise VerificationFailed("assignment building ids do not match the base twin.")


def _check_scenario(
    scenario_id: str,
    pct: int,
    assignments: pd.DataFrame,
    n_buildings: int,
    scenario_dir: Path,
) -> set[str]:
    """Check one scenario overlay and return its selected building ids.

    Raises:
        VerificationFailed: On the first failing check for this scenario.
    """
    doc = _load_json(scenario_dir / f"{scenario_id}.json")
    rows = assignments.loc[assignments["scenario_id"] == scenario_id]
    if len(rows) != n_buildings:
        raise VerificationFailed(f"{scenario_id} has {len(rows)} rows.")

    n_ev = int(rows["has_ev"].sum())
    expected = _expected_count(n_buildings, pct)
    if n_ev != expected:
        raise VerificationFailed(
            f"{scenario_id} expected {expected} EVs, found {n_ev}."
        )
    if int(doc["n_ev"]) != expected:
        raise VerificationFailed(
            f"{scenario_id}.json n_ev does not match expected count."
        )
    if doc.get("area_m2_used_for_assignment") is not False:
        raise VerificationFailed(
            f"{scenario_id}.json must declare area_m2_used_for_assignment=false."
        )

    ev_rows = rows.loc[rows["has_ev"]]
    if ev_rows["ev_id"].isna().any():
        raise VerificationFailed(f"{scenario_id} has selected EV rows without ev_id.")
    if ev_rows["ev_id"].nunique() != n_ev:
        raise VerificationFailed(f"{scenario_id} EV ids are not unique.")
    if (rows.loc[~rows["has_ev"], "charger_kw"] != 0.0).any():
        raise VerificationFailed(
            f"{scenario_id} inactive buildings must have charger_kw=0."
        )
    return set(ev_rows["building_id"])


def _check_nesting(selected: dict[str, set[str]]) -> None:
    """Every scenario's EV set must contain the previous one's.

    Raises:
        VerificationFailed: If adoption is not monotone in membership.
    """
    ordered = list(SCENARIOS)
    # strict=False is required, not a shortcut: the two sequences are
    # deliberately of different length (n and n-1), so strict=True would raise
    # on every call. Declared explicitly because B905 is a real guard elsewhere
    # in this repo -- a silently-truncating zip over sequences that were meant
    # to match is a defect CLAUDE.md's anti-patterns section already records.
    for earlier, later in zip(ordered, ordered[1:], strict=False):
        if not selected[earlier].issubset(selected[later]):
            raise VerificationFailed(f"{earlier} EV set must be nested in {later}.")


def _check_seed_policy(
    selected: dict[str, set[str]],
    buildings: pd.DataFrame,
    scenario_dir: Path,
) -> None:
    """The highest-adoption set must be reproducible from the declared seed.

    Raises:
        VerificationFailed: If the overlay does not match the seeded
            permutation, which would mean the study is not reproducible from
            what its scenario documents declare.
    """
    seed = int(_load_json(scenario_dir / "S1.json")["ev_assignment_seed"])
    n_buildings = len(buildings)
    permutation = np.random.default_rng(seed).permutation(n_buildings)
    top = max(SCENARIOS, key=lambda key: SCENARIOS[key])
    take = _expected_count(n_buildings, SCENARIOS[top])
    ordered = buildings.reset_index(drop=True)
    expected = set(ordered.iloc[permutation[:take]]["building_id"])
    if selected[top] != expected:
        raise VerificationFailed(
            f"{top} assignment does not match the deterministic seed policy."
        )


def verify_scenario_overlays(
    *,
    base_dir: Path = BASE_DIR,
    scenario_dir: Path = SCENARIO_DIR,
) -> dict[str, Any]:
    """Verify the EV adoption overlays without printing or exiting.

    Args:
        base_dir: Directory holding the canonical base artifacts.
        scenario_dir: Directory holding the scenario documents and the EV
            assignment table.

    Returns:
        ``{"valid": bool, "error": str | None, "lines": list[str]}``. ``lines``
        holds the per-scenario summary produced up to the point of failure, so
        a caller can show how far the run got.
    """
    lines: list[str] = []
    try:
        buildings = pd.read_parquet(base_dir / "buildings.parquet")
        assignments = pd.read_parquet(scenario_dir / "ev_assignments.parquet")
        n_buildings = len(buildings)
        _check_assignment_table(assignments, buildings)

        selected: dict[str, set[str]] = {}
        for scenario_id, pct in SCENARIOS.items():
            selected[scenario_id] = _check_scenario(
                scenario_id, pct, assignments, n_buildings, scenario_dir
            )
            lines.append(
                f"{scenario_id}: {pct:2d}% -> {len(selected[scenario_id]):4d} EVs"
            )

        _check_nesting(selected)
        _check_seed_policy(selected, buildings, scenario_dir)
    except VerificationFailed as failure:
        return {"valid": False, "error": str(failure), "lines": lines}
    return {"valid": True, "error": None, "lines": lines}


def main() -> None:
    """Run the verification and report it, exiting non-zero on failure."""
    report = verify_scenario_overlays()
    print("=== EV Scenario Overlay Verification ===")
    for line in report["lines"]:
        print(line)
    if not report["valid"]:
        raise SystemExit(f"ERROR: {report['error']}")
    print("OK: scenario overlays are deterministic, nested, and area-independent.")


if __name__ == "__main__":
    main()
