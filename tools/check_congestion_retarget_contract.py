"""Static source-contract check for the Phase-14 compute_congestion.py retarget.

Asserts (by reading the stage source as text — no execution, no cache needed)
that the design-day transformer-overload retarget preserves the downstream
``firm_hosting.json`` 5-key contract, reads K from the array (never ``config.K``),
drops the orphaned annual imports, emits the CONG-03 risk artifacts + the
``divergence_note``, and keeps GUARD-02 clean. Exits 1 on any miss with a located
message so the executor sees exactly which contract element regressed.

Used by Phase-14 plan 14-01 Task 2 verification.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "projects/ev_hosting_flex/scripts/pipeline/compute_congestion.py"


def main() -> int:
    """Return 0 if every contract condition holds, else print misses and return 1."""
    src = STAGE.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    misses: list[str] = []

    # Retarget wiring.
    if "firm_transformer_count" not in code:
        misses.append("missing import/call of firm_transformer_count")
    if "q_real.shape[0]" not in code.replace(" ", "") and "q_real.shape[0]" not in code:
        misses.append("K must be read from q_real.shape[0], not config.K")

    # Orphaned annual symbols must be gone from the retargeted body.
    for dead in ("allocate_ev_per_bus", "blend_ev_per_bus", "proxy_loading",
                 "firm_pcong_count"):
        if dead in code:
            misses.append(f"orphaned annual symbol still referenced: {dead}")

    # Preserved 5-key firm_hosting.json contract (read by Phase 15/16).
    for key in ("firm_ev_count", "firm_penetration", "downstream_home_count",
                "feeder_key", "feeder_transformer_modeled_kw"):
        if f'"{key}"' not in code:
            misses.append(f"firm_hosting.json missing preserved key: {key}")

    # New transformer-framing keys present; old unread keys dropped.
    for newk in ("p_overload_curve", "ev_sweep"):
        if f'"{newk}"' not in code:
            misses.append(f"missing new firm_hosting.json key: {newk}")
    for oldk in ("p_cong", "p_cong_at_firm", "penetration_sweep"):
        if f'"{oldk}"' in code:
            misses.append(f"old unread key not dropped: {oldk}")

    # CONG-03 artifacts + framing-shift note.
    for artifact in ("transformer_risk.parquet", "p_overload_curve.json",
                     "divergence_note"):
        if artifact not in code:
            misses.append(f"missing CONG-03 artifact/field: {artifact}")

    # GUARD-02: no module-scope heavy import.
    if re.search(r"^import (pandapower|geopandas|lightsim2grid)", code, re.MULTILINE):
        misses.append("GUARD-02 violation: module-scope heavy import")

    if misses:
        print("compute_congestion.py contract FAILED:")
        for m in misses:
            print(f"  - {m}")
        return 1
    print("compute_congestion.py retarget contract OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
