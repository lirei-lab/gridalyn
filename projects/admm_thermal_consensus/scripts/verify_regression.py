"""Compare current study_results.json against the pinned baseline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT))

from projects.admm_thermal_consensus.scripts import config as C

BASELINE = C.PROJECT_ROOT / "baselines" / "results_baseline.json"
CURRENT = C.JSON_DIR / "study_results.json"
RTOL = 1e-3


def _peak(d: dict, key: str) -> float:
    return float(d["aggregate_kpis"][key]["peak_kw"])


def main() -> int:
    if not BASELINE.exists():
        print("no baseline; run with --update to create it")
        if "--update" in sys.argv:
            BASELINE.write_text(CURRENT.read_text(), encoding="utf-8")
            print(f"baseline written to {BASELINE}")
            return 0
        return 1
    base = json.loads(BASELINE.read_text())
    cur = json.loads(CURRENT.read_text())
    failures = []
    for key in ("uncoordinated", "coordinated_ideal"):
        b, c = _peak(base, key), _peak(cur, key)
        if abs(b - c) > RTOL * max(abs(b), 1.0):
            failures.append(f"{key} peak_kw: baseline {b} vs current {c}")
    if "--update" in sys.argv:
        BASELINE.write_text(CURRENT.read_text(), encoding="utf-8")
        print("baseline updated")
        return 0
    if failures:
        print("REGRESSION:", "; ".join(failures))
        return 1
    print("regression OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
