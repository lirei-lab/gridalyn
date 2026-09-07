"""Build the base Monte-Carlo set once, so four stages can read it concurrently.

``base_mc_by_size.npz`` holds K annual base realizations per distinct home
count, and four stages need it: ``analyze_congestion_risk``,
``analyze_fleet_triage``, ``analyze_nonwires_value`` and
``analyze_locational_contracts``. Each used to call ``_ensure_base_mc_cache``,
which regenerates on a miss, and the file was keyed on the CALLER's ``k_base``
-- so the two K groups invalidated each other on every alternation and a full
run regenerated the set four times: 3.73 h of a 4.51 h run, of which 2.49 h was
recomputing realizations that already existed (bd lx7, fixed in 7f8cbb03).

That fix made the four share one set. It did not make the sharing SAFE under
concurrency, and that is what this stage is for. ``analyze_fleet_triage`` and
``analyze_nonwires_value`` sit in the same wave with no edge between them, so
any wave-level scheduler runs them together; both writing the same ``.npz``
races on a non-atomic ``np.savez``, and the overlap that motivated the
concurrency would be spent generating the set twice (bd c7f.2.1). Hoisting the
write into one stage that the four declare under ``needs:`` makes the sharing
explicit in the DAG and leaves the consumers as readers, which cannot race.

It also moves the work earlier. This stage needs only the topology cache and
the pinned TMY -- not the annual Monte-Carlo -- so it sits beside
``generate_annual_mc`` rather than after it, where the ~75 min it costs can
overlap with the rest of that wave instead of extending the chain.
"""

from __future__ import annotations

import argparse
import pickle
from typing import Any

from projects.ev_hosting_flex.scripts._annual import day_mean_temps, load_annual_tmy
from projects.ev_hosting_flex.scripts.pipeline.analyze_congestion_risk import (
    _MAX_K_BASE,
    _ensure_base_mc_cache,
)
from projects.ev_hosting_flex.scripts.pipeline.validate_powerflow import (
    size_network_to_load,
)

# SEAL-01: the BLAS thread cap lives in projects/ev_hosting_flex/scripts/__init__.py.


def feeder_home_counts(script: Any) -> list[int]:
    """Return the distinct downstream home counts across the LV fleet.

    Derived exactly as ``analyze_congestion_risk`` derives it -- the same net,
    the same design-day sizing -- so the set this stage builds covers precisely
    the sizes its consumers ask for.

    Args:
        script: The project workspace handle.

    Returns:
        Sorted distinct home counts served by LV transformers.

    Raises:
        ValueError: If the sizing yields no LV transformer, which means the
            topology cache is not the study's feeder.
    """
    import numpy as np

    with open(script.cache_dir / "pp_net_cache.pkl", "rb") as handle:
        net = pickle.load(handle)
    feeder_idx = int(
        script.read_json("outputs/cache/feeder_selection.json")[
            "feeder_transformer_idx"
        ]
    )
    temp = load_annual_tmy()
    # The same day-mean helper the consumers use, so this stage's design day is
    # the one they would have computed rather than a parallel definition.
    design_day = int(np.argmin(day_mean_temps(temp)))
    sizing = size_network_to_load(net, script, temp, design_day, feeder_idx)
    size_by_trafo = sizing["size_by_trafo"]
    lv = net.trafo.index[net.trafo["vn_lv_kv"] < 1.0]
    sizes = sorted({int(size_by_trafo[int(t)]) for t in lv})
    if not sizes:
        raise ValueError(
            f"{script.cache_dir / 'pp_net_cache.pkl'} yielded no LV transformer. "
            "Remediation: regenerate the topology cache."
        )
    return sizes


def derive_base_mc_cache(script: Any) -> dict[str, Any]:
    """Build (or confirm) the shared base-MC set and return its summary.

    Args:
        script: The project workspace handle.

    Returns:
        Dict with ``artifact_paths`` and the report ``summary``.
    """
    sizes = feeder_home_counts(script)
    temp = load_annual_tmy()
    base_mc = _ensure_base_mc_cache(script.data_dir, temp, sizes, _MAX_K_BASE)
    path = script.data_dir / "base_mc_by_size.npz"
    return {
        "artifact_paths": [path],
        "summary": {
            "k_base": int(_MAX_K_BASE),
            "n_sizes": len(sizes),
            "home_counts": sizes,
            "n_realizations": int(_MAX_K_BASE) * len(sizes),
            "n_steps": int(base_mc[sizes[0]].shape[1]),
            "bytes": int(path.stat().st_size),
        },
    }


def run_stage() -> dict[str, Any]:
    """Run the shared base-MC build and emit the platform report.

    Returns:
        The platform report payload written via ``script.write_report``.
    """
    from gridalyn.projects.scripting import project_script

    script = project_script()
    derived = derive_base_mc_cache(script)
    return script.write_report(
        "base_mc_cache_report",
        artifacts=[script.file_reference(p) for p in derived["artifact_paths"]],
        summary=derived["summary"],
        validation={
            "valid": True,
            "errors": [],
            "warnings": [
                "This stage is the ONLY writer of base_mc_by_size.npz. Its four "
                "consumers read it through load_base_mc_cache, which raises "
                "rather than regenerating, so a missing or stale cache fails "
                "the reader loudly instead of being rebuilt four times.",
            ],
        },
    )


def main() -> None:
    """CLI entry point for the shared base-MC cache stage."""
    argparse.ArgumentParser(description=__doc__).parse_args()
    summary = run_stage()["summary"]
    print(
        f"Base-MC cache: K={summary['k_base']} x {summary['n_sizes']} sizes = "
        f"{summary['n_realizations']} realizations, {summary['n_steps']} steps, "
        f"{summary['bytes'] / 1e6:.1f} MB"
    )


if __name__ == "__main__":
    main()
