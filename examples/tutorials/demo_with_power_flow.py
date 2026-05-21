"""Run a platform-level synthetic feeder power-flow example."""

from __future__ import annotations

from pathlib import Path

from gridalyn.interfaces.cli.environment import configure_cli_environment

configure_cli_environment()

from gridalyn import simulation
from gridalyn.foundation.data import datasets


OUTPUT_DIR = Path("examples/generated/outputs/demo_with_power_flow")


def main() -> None:
    result = simulation.build_synthetic_network_from_geojson(
        footprints_path=datasets.get_dataset_path("buildings_inside_polygon.geojson"),
        config_path=Path("configs/grid/config.json"),
        out_dir=OUTPUT_DIR,
        write_cache=True,
        run_powerflow=True,
    )

    report = result.validation_report
    counts = report["counts"]
    powerflow = report["powerflow"]
    print(
        "Power-flow demo complete: "
        f"{counts['pandapower_buses']} buses, "
        f"{counts['pandapower_lines']} lines, "
        f"converged={powerflow['converged']}."
    )
    print(f"Validation report: {result.report_path}")


if __name__ == "__main__":
    main()
