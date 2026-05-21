from __future__ import annotations

import ast
from pathlib import Path


def test_asset_modeling_does_not_import_solver_or_datagen_layers() -> None:
    forbidden_prefixes = (
        "gridalyn.assets.datagen",
        "gridalyn.operations",
        "gridalyn.projects",
        "gridalyn.simulation",
        "pandapower",
    )
    violations: list[str] = []
    for path in sorted(Path("gridalyn/assets/modeling").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                if any(
                    module == prefix or module.startswith(f"{prefix}.")
                    for prefix in forbidden_prefixes
                ):
                    violations.append(f"{path}: {module}")

    assert violations == []


def test_assets_facade_does_not_export_solver_mappings() -> None:
    from gridalyn import assets

    assert not hasattr(assets, "build_radial_pandapower_feeder")
    assert not hasattr(assets, "build_voltage_control_feeder")
    assert not hasattr(assets, "apply_pv_generation_to_pandapower")
    assert not hasattr(assets, "apply_battery_dispatch_to_pandapower")
