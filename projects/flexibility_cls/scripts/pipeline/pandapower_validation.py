"""Validate the study CLS grid with Gridalyn's transformer peak checker."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.simulation import (
    TransformerPeakValidationConfig,
    validate_transformer_peak_scenarios,
)
from projects.flexibility_cls.scripts.config import (
    GRID_CONFIG,
    PF,
    S_RATED_KVA,
    S_RATED_MVA,
    THETA_MAX,
)
from projects.flexibility_cls.scripts.thermal_forecast import (
    build_thermal_forecast,
    thermal_forecast_metadata,
)

DATA_DIR = ROOT / "projects" / "flexibility_cls" / "outputs" / "data"
JSON_DIR = ROOT / "projects" / "flexibility_cls" / "outputs" / "json"
JSON_DIR.mkdir(parents=True, exist_ok=True)


def _dispatch_step_count(default: int = 336) -> int:
    dispatch_path = DATA_DIR / "market_dispatch_timeseries.parquet"
    if not dispatch_path.exists():
        return default

    import pandas as pd

    return len(pd.read_parquet(dispatch_path))


def _status_label(scenario: dict[str, object]) -> str:
    if scenario["congested_dynamic"]:
        return "CONGESTION (dyn)"
    if scenario["congested_static"]:
        return "Static overload"
    return "OK"


def main() -> None:
    print("=" * 60)
    print("  Pandapower Validation: Custom Transformer + CLS Scenarios")
    print("=" * 60)

    summary_path = JSON_DIR / "ev_summary_results.json"
    if not summary_path.exists():
        print(f"  Missing {summary_path.name}, run pipeline first.")
        return
    with open(summary_path, encoding="utf-8") as f:
        ev_summary = json.load(f)

    validation_config = TransformerPeakValidationConfig(
        s_rated_mva=S_RATED_MVA,
        s_rated_kva=S_RATED_KVA,
        theta_max_c=THETA_MAX,
        power_factor=PF,
        hv_voltage_kv=GRID_CONFIG["buses"]["hv"]["voltage_kv"],
        mv_voltage_kv=GRID_CONFIG["buses"]["mv"]["voltage_kv"],
        winter_design_ambient_c=-22.5,
    )
    scenarios = {
        label: data for label, data in ev_summary.items() if isinstance(data, dict)
    }
    results = validate_transformer_peak_scenarios(
        scenarios=scenarios,
        config=validation_config,
    )

    transformer = results["transformer"]
    p_dynamic = transformer["dynamic_limit_winter_design_mw"]
    thermal_forecast = build_thermal_forecast(_dispatch_step_count())
    results["transformer"].update(
        thermal_forecast_metadata(
            thermal_forecast,
            winter_design_limit_mw=p_dynamic,
        )
    )

    print(f"\n  Transformer: {S_RATED_MVA:.0f} MVA, theta_max={THETA_MAX:.0f} degC")
    print(f"  P_static = {transformer['p_static_mw']:.2f} MW")
    print(f"  K(-22.5 degC) = {transformer['k_cold']:.3f}")
    print(f"  P_dynamic = {transformer['p_dynamic_mw']:.2f} MW")
    print()

    header = (
        f"{'Scn':>8} {'EV%':>4} {'P_MW':>7} {'Static%':>8} "
        f"{'Dyn%':>8} {'V_pu':>7} {'Status':>18}"
    )
    print(f"  {header}")
    print(f"  {'-' * len(header)}")
    for scenario in results["scenarios"]:
        print(
            f"  {scenario['label']:>8} {scenario['ev_pct']:>3}% "
            f"{scenario['p_peak_mw']:>6.2f} "
            f"{scenario['static_loading_pct']:>7.1f}% "
            f"{scenario['dynamic_loading_pct']:>7.1f}% "
            f"{scenario['voltage_pu']:>6.4f} {_status_label(scenario):>18}"
        )

    out_path = JSON_DIR / "pandapower_validation.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n  Saved {out_path}")

    n_dyn_congested = sum(
        1 for scenario in results["scenarios"] if scenario["congested_dynamic"]
    )
    n_static_overload = sum(
        1 for scenario in results["scenarios"] if scenario["congested_static"]
    )
    print("\n  Summary:")
    print(
        "    Scenarios with STATIC overload (>100% nameplate): "
        f"{n_static_overload}/{len(results['scenarios'])}"
    )
    print(
        "    Scenarios with DYNAMIC congestion (>100% IEEE):   "
        f"{n_dyn_congested}/{len(results['scenarios'])}"
    )
    print("    This confirms the transformer operates within IEEE C57.91")
    print("    dynamic limits at winter ambient until EV penetration")
    print(f"    pushes load beyond P_dynamic = {p_dynamic:.1f} MW.")


if __name__ == "__main__":
    main()
