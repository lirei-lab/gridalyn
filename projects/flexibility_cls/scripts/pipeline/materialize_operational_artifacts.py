#!/usr/bin/env python3
"""Materialize utility-operation artifacts for the EV capacity project."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.foundation import ArtifactLayout
from gridalyn.operations import materialize_flexibility_operation_artifacts
from projects.flexibility_cls.scripts._serialize import json_default, relpath

DEFAULT_LAYOUT = ArtifactLayout(ROOT)
DEFAULT_FLEX_DIR = DEFAULT_LAYOUT.flexibility
DEFAULT_OUT_DIR = ROOT / "projects" / "flexibility_cls" / "outputs" / "operations"
DEFAULT_REPORT_PATH = (
    ROOT
    / "projects"
    / "flexibility_cls"
    / "outputs"
    / "reports"
    / "operational_kpi_report.json"
)
DEFAULT_CATALOG_PATH = (
    ROOT
    / "projects"
    / "flexibility_cls"
    / "outputs"
    / "operations"
    / "operations_catalog.json"
)


def materialize_operational_artifacts(
    *,
    root: Path = ROOT,
    scenario_id: str = "S4",
    flexibility_dir: Path | None = None,
    out_dir: Path | None = None,
    report_path: Path | None = None,
    catalog_path: Path | None = None,
) -> dict[str, Path]:
    """Write project-local operational Parquet artifacts and KPI report."""

    return materialize_flexibility_operation_artifacts(
        root=root,
        project_id="flexibility_cls",
        scenario_id=scenario_id,
        flexibility_dir=flexibility_dir,
        out_dir=out_dir,
        report_path=report_path,
        catalog_path=catalog_path,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--scenario-id", default="S4")
    parser.add_argument("--flexibility-dir", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--report-path", type=Path, default=None)
    parser.add_argument("--catalog-path", type=Path, default=None)
    args = parser.parse_args()

    paths = materialize_operational_artifacts(
        root=args.root,
        scenario_id=args.scenario_id,
        flexibility_dir=args.flexibility_dir,
        out_dir=args.out_dir,
        report_path=args.report_path,
        catalog_path=args.catalog_path,
    )
    print(
        json.dumps(
            {name: relpath(path, args.root) for name, path in paths.items()},
            indent=2,
            sort_keys=True,
            default=json_default,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
