#!/usr/bin/env python3
"""Generate pandapower finite-difference labels for network impact surrogate training."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]

from gridalyn.foundation import ArtifactLayout

DEFAULT_LAYOUT = ArtifactLayout(ROOT)

from gridalyn.simulation.analytics.network_impact.perturbation_sampler import (
    build_baseline_matrices,
    build_perturbation_matrices,
    build_physics_labels,
    build_sampler_report,
    select_perturbation_samples,
    write_sampler_artifacts,
)
from gridalyn.projects.workflows.flexibility.spatial_powerflow_validation import (
    DEFAULT_CACHE_DIR,
    _load_net,
    _load_s4_inputs,
)
from gridalyn.projects.workflows.scripts.generate_provider_selection_shadow_report import (
    _constraints_from_overload_report,
    _fallback_constraints,
)
from gridalyn.projects.workflows.scripts.run_digital_twin_ev_powerflow import _run_powerflow


DEFAULT_PROVIDERS = DEFAULT_LAYOUT.flexibility / "provider_registry.parquet"
DEFAULT_PREDICTIONS = DEFAULT_LAYOUT.flexibility / "network_impact_predictions.parquet"
DEFAULT_DISPATCH = DEFAULT_LAYOUT.flexibility / "market_dispatch_timeseries.parquet"
DEFAULT_TRANSFORMERS = DEFAULT_LAYOUT.base / "grid_transformers.parquet"
DEFAULT_OVERLOAD_REPORT = DEFAULT_LAYOUT.reports / "mv_lv_transformer_overload_report.json"
DEFAULT_OUT_DIR = DEFAULT_LAYOUT.flexibility


def _relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-id", default="S4")
    parser.add_argument("--provider-path", type=Path, default=DEFAULT_PROVIDERS)
    parser.add_argument("--predictions-path", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--dispatch-path", type=Path, default=DEFAULT_DISPATCH)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--overload-report-path", type=Path, default=DEFAULT_OVERLOAD_REPORT)
    parser.add_argument("--transformers-path", type=Path, default=DEFAULT_TRANSFORMERS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--constraint-id", action="append", dest="constraint_ids")
    parser.add_argument("--top-constraints", type=int, default=3)
    parser.add_argument(
        "--perturbation-kw",
        type=float,
        action="append",
        default=None,
        help="Perturbation size in kW. Repeat for multiple sizes.",
    )
    parser.add_argument("--max-providers-per-constraint", type=int, default=8)
    parser.add_argument("--max-timesteps", type=int, default=12)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.scenario_id != "S4":
        raise ValueError("Current perturbation sampler supports scenario_id='S4'")

    providers = pd.read_parquet(args.provider_path)
    predictions = pd.read_parquet(args.predictions_path)
    dispatch = pd.read_parquet(args.dispatch_path)

    constraint_ids = args.constraint_ids or _constraints_from_overload_report(
        overload_report_path=args.overload_report_path,
        transformers_path=args.transformers_path,
        scenario_id=args.scenario_id,
        top_n=args.top_constraints,
    )
    if not constraint_ids:
        constraint_ids = _fallback_constraints(providers, args.scenario_id, args.top_constraints)
    if not constraint_ids:
        raise ValueError(f"No constraints available for scenario {args.scenario_id}")

    samples = select_perturbation_samples(
        providers,
        predictions,
        dispatch,
        scenario_id=args.scenario_id,
        constraint_ids=constraint_ids,
        perturbation_kw=args.perturbation_kw or [5.0],
        max_providers_per_constraint=args.max_providers_per_constraint,
        max_timesteps=args.max_timesteps,
    )
    if samples.empty:
        raise ValueError("No perturbation samples selected")

    _buildings, _registry, building_kw, ev_kw, _soft_kw, _hard_kw, _rebound_kw = _load_s4_inputs(
        cache_dir=args.cache_dir,
        market_dispatch_path=args.dispatch_path,
    )
    unique_timesteps = sorted(samples["timestep"].astype(int).unique().tolist())
    baseline_row_by_timestep = {timestep: idx for idx, timestep in enumerate(unique_timesteps)}
    baseline_matrices = build_baseline_matrices(
        building_kw=building_kw,
        ev_kw=ev_kw,
        timesteps=unique_timesteps,
    )
    perturbation_matrices = build_perturbation_matrices(
        building_kw=building_kw,
        ev_kw=ev_kw,
        samples=samples,
    )
    samples = samples.copy()
    samples["actual_perturbation_kw"] = perturbation_matrices["actual_perturbation_kw"]

    baseline_results = _run_powerflow(
        _load_net(args.cache_dir),
        baseline_matrices["p_total_mw"],
        baseline_matrices["q_total_mvar"],
    )
    perturbed_results = _run_powerflow(
        _load_net(args.cache_dir),
        perturbation_matrices["p_total_mw"],
        perturbation_matrices["q_total_mvar"],
    )

    transformers = pd.read_parquet(args.transformers_path)
    transformer_lookup = {
        str(row["transformer_id"]): int(row["pandapower_trafo"])
        for row in transformers.to_dict("records")
    }
    labels = build_physics_labels(
        samples,
        baseline_results=baseline_results,
        perturbed_results=perturbed_results,
        baseline_row_by_timestep=baseline_row_by_timestep,
        transformer_lookup=transformer_lookup,
    )
    report = build_sampler_report(
        labels=labels,
        scenario_id=args.scenario_id,
        constraint_ids=constraint_ids,
        perturbation_kw=float(max(args.perturbation_kw or [5.0])),
    )
    report["perturbation_kw_values"] = [float(value) for value in (args.perturbation_kw or [5.0])]
    report["inputs"] = {
        "provider_registry": _relpath(args.provider_path),
        "network_impact_predictions": _relpath(args.predictions_path),
        "dispatch": _relpath(args.dispatch_path),
        "overload_report": _relpath(args.overload_report_path),
        "grid_transformers": _relpath(args.transformers_path),
    }
    paths = write_sampler_artifacts(args.out_dir, labels=labels, report=report)

    print(
        json.dumps(
            {
                "scenario_id": args.scenario_id,
                "constraint_ids": constraint_ids,
                "summary": report["summary"],
                "paths": {name: _relpath(path) for name, path in paths.items()},
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
