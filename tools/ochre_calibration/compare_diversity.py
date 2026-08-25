"""Compare diversity curves between a uniform and a diversified fleet.

The uniform fleet gives every dwelling the same ERS setback schedule, so its
dominant load -- heating -- is perfectly coincident and the coincident peak per
home barely falls as homes are pooled. The diversified fleet draws a per-
dwelling comfort setpoint, setback depth and setback start/end hour. The gap
between the two curves is the share of the fleet's apparent coincidence that
was a modelling artefact rather than physics.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def _curve(path: Path) -> list[dict[str, float]]:
    """Return the diversity curve recorded in a fleet summary."""
    return json.loads(path.read_text(encoding="utf-8"))["diversity_curve"]


def main(argv: list[str] | None = None) -> int:
    """Plot both diversity curves on one axis and report the gap."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", default=".ochre-calibration/fleet")
    args = parser.parse_args(argv)
    workdir = Path(args.workdir).resolve()

    uniform = _curve(workdir / "fleet_summary_uniform.json")
    diverse = _curve(workdir / "fleet_summary.json")

    fig, axis = plt.subplots(figsize=(9, 5.4))
    for curve, label, style in (
        (uniform, "shared ERS setback (all dwellings identical)", "--"),
        (diverse, "per-dwelling setpoint + setback draw", "-"),
    ):
        homes = [r["homes"] for r in curve]
        axis.plot(
            homes, [r["p50"] for r in curve], style, marker="o", lw=2, label=label
        )
        axis.fill_between(
            homes, [r["p10"] for r in curve], [r["p90"] for r in curve], alpha=0.15
        )
    axis.set_xlabel("homes sharing the transformer")
    axis.set_ylabel("peak kW per home")
    axis.set_title("Thermostat diversity is what bends the coincidence curve")
    axis.legend()
    axis.grid(alpha=0.3)
    fig.tight_layout()
    out = workdir / "figures" / "diversity_comparison.png"
    fig.savefig(out, dpi=140)
    plt.close(fig)

    def drop(curve: list[dict[str, float]]) -> float:
        return (1.0 - curve[-1]["p50"] / curve[0]["p50"]) * 100.0

    report = {
        "uniform": {
            "one_home_kw": uniform[0]["p50"],
            "pooled_kw": uniform[-1]["p50"],
            "drop_pct": round(drop(uniform), 1),
        },
        "diversified": {
            "one_home_kw": diverse[0]["p50"],
            "pooled_kw": diverse[-1]["p50"],
            "drop_pct": round(drop(diverse), 1),
        },
        "figure": str(out),
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
