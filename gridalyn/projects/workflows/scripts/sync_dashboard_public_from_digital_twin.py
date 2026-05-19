"""
Sync legacy dashboard/public Kepler Parquet files from digital-twin outputs.

The dashboard now reads scenario-aware data directly from digital_twin/, but the
legacy Kepler files are still used by consistency checks and static notebooks.
This script keeps those files derived from the same source of truth.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_BASE_DIR = ROOT / "digital_twin" / "base"
DEFAULT_TIMESERIES_DIR = ROOT / "digital_twin" / "timeseries"
DEFAULT_PUBLIC_DIR = ROOT / "dashboard" / "public"


def sync_dashboard_public(
    base_dir: Path,
    timeseries_dir: Path,
    public_dir: Path,
    scenario_id: str,
) -> None:
    public_dir.mkdir(parents=True, exist_ok=True)

    nodes = pd.read_parquet(timeseries_dir / f"{scenario_id}_powerflow_nodes.parquet")
    nodes = nodes[["timestamp", "bus_idx", "lon", "lat", "v_pu", "category"]]
    nodes.to_parquet(public_dir / "kepler_timeseries_nodes.parquet", index=False)

    buses = pd.read_parquet(base_dir / "grid_buses.parquet")
    bus_ref = buses[["pandapower_bus", "lon", "lat"]].rename(
        columns={"pandapower_bus": "bus_idx"}
    )
    line_ref = pd.read_parquet(base_dir / "grid_lines.parquet")
    line_ref = line_ref[["pandapower_line", "category"]].rename(
        columns={"pandapower_line": "line_idx"}
    )

    lines = pd.read_parquet(timeseries_dir / f"{scenario_id}_powerflow_lines.parquet")
    lines = lines.merge(line_ref, on="line_idx", how="left")
    lines = lines.merge(
        bus_ref.rename(columns={"bus_idx": "from_bus", "lon": "lon_from", "lat": "lat_from"}),
        on="from_bus",
        how="left",
    )
    lines = lines.merge(
        bus_ref.rename(columns={"bus_idx": "to_bus", "lon": "lon_to", "lat": "lat_to"}),
        on="to_bus",
        how="left",
    )
    lines = lines[
        [
            "timestamp",
            "line_idx",
            "lon_from",
            "lat_from",
            "lon_to",
            "lat_to",
            "loading_percent",
            "category",
        ]
    ]
    lines.to_parquet(public_dir / "kepler_timeseries_lines.parquet", index=False)

    power = pd.read_parquet(timeseries_dir / f"{scenario_id}_powerflow_power.parquet")
    power = power.rename(columns={"pandapower_load": "bus_idx", "p_total_mw": "p_mw"})
    power = power[["timestamp", "bus_idx", "p_mw", "temperature_c"]]
    power.to_parquet(public_dir / "kepler_timeseries_power.parquet", index=False)

    print(f"Synced {scenario_id} legacy dashboard Parquet files to {public_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync dashboard/public Kepler Parquet files from digital_twin outputs."
    )
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument("--timeseries-dir", type=Path, default=DEFAULT_TIMESERIES_DIR)
    parser.add_argument("--public-dir", type=Path, default=DEFAULT_PUBLIC_DIR)
    parser.add_argument("--scenario", default="S0")
    parser.add_argument(
        "--allow-legacy-dashboard-public",
        action="store_true",
        help="Opt into writing legacy dashboard/public Kepler files.",
    )
    args = parser.parse_args()
    if not args.allow_legacy_dashboard_public:
        raise SystemExit(
            "Refusing to write dashboard/public by default. The current dashboard "
            "uses digital_twin/dashboard/catalog.json and digital_twin/timeseries. "
            "Pass --allow-legacy-dashboard-public for archived demos."
        )

    sync_dashboard_public(
        base_dir=args.base_dir,
        timeseries_dir=args.timeseries_dir,
        public_dir=args.public_dir,
        scenario_id=args.scenario,
    )


if __name__ == "__main__":
    main()
