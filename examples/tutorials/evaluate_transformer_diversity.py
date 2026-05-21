"""Summarize transformer diversity from platform synthetic-network artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from gridalyn.interfaces.cli.environment import configure_cli_environment

configure_cli_environment()

from gridalyn import simulation
from gridalyn.foundation.data import datasets


OUTPUT_DIR = Path("examples/generated/outputs/transformer_diversity")


def main() -> None:
    result = simulation.build_synthetic_network_from_geojson(
        footprints_path=datasets.get_dataset_path("buildings_inside_polygon.geojson"),
        config_path=Path("configs/grid/config.json"),
        out_dir=OUTPUT_DIR,
        write_cache=True,
        run_powerflow=True,
    )

    net = result.net
    load_kw = float(net.load.p_mw.sum() * 1000.0)
    trafo_kva = float(net.trafo.sn_mva.sum() * 1000.0)
    summary = {
        "load_kw": load_kw,
        "installed_transformer_kva": trafo_kva,
        "aggregate_utilization_pct": 100.0 * load_kw / trafo_kva if trafo_kva else 0.0,
        "transformer_count": int(len(net.trafo)),
    }
    report_path = OUTPUT_DIR / "transformer_diversity_summary.json"
    report_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Transformer diversity summary: {report_path}")


if __name__ == "__main__":
    main()
