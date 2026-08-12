import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from gridalyn.twin.network.metadata import build_base_metadata, write_base_metadata

_REPO_ROOT = Path(__file__).resolve().parents[1]
_COMMITTED_BASE_METADATA = (
    _REPO_ROOT / "instances" / "default" / "digital_twin" / "base" / "metadata.json"
)

_BASE_ARTIFACT_NAMES = (
    "grid_buses",
    "grid_lines",
    "grid_transformers",
    "buildings",
    "building_grid_connectivity",
)

# Keys whose value is a single workspace-relative path.
_PATH_KEYS = ("config_path", "cache_dir", "base_dir", "adapter_validation_report")


def declared_paths(manifest: dict) -> list[tuple[str, str]]:
    """Return every ``(contract key, workspace-relative path)`` a manifest declares.

    Args:
        manifest: Parsed contents of a base ``metadata.json``.

    Returns:
        Pairs of contract path and declared path, skipping keys carried as
        explicitly absent (``null``).
    """
    found = [(key, str(manifest[key])) for key in _PATH_KEYS if manifest.get(key)]
    for name, entry in (manifest.get("artifacts") or {}).items():
        if isinstance(entry, dict) and entry.get("path"):
            found.append((f"artifacts.{name}.path", str(entry["path"])))
    return found


def stale_declared_paths(manifest: dict, root: Path) -> list[str]:
    """Return one message per declared path that is not rooted in a live tree.

    A declared path is sound when it exists, or when only its leaf is missing
    inside a directory that still exists — the base Parquet artifacts are
    gitignored, so their leaves are legitimately absent in a clean checkout.
    A path whose *parent directory* is gone points at a deleted or renamed
    tree, which is the rot this gate exists to catch.

    Args:
        manifest: Parsed contents of a base ``metadata.json``.
        root: Workspace root the declared paths are relative to.

    Returns:
        Human-readable failure messages, empty when every path is sound.
    """
    stale = []
    for key, relative in declared_paths(manifest):
        path = root / relative
        if path.exists() or path.parent.is_dir():
            continue
        stale.append(
            f"{key} = {relative!r}, whose parent directory "
            f"{Path(relative).parent.as_posix()!r} does not exist"
        )
    return stale


class CommittedBaseMetadataStalenessTest(unittest.TestCase):
    """Gate the tracked base manifest against declaring paths that no longer exist.

    The committed manifest named ``projects/flexibility_cls/`` for three months
    after that study was retired (2026-08-03), because nothing read it. This
    asserts every declared input still resolves rather than asserting a
    freshness window, which would turn red on the calendar instead of on a defect.
    """

    def setUp(self) -> None:
        self.assertTrue(
            _COMMITTED_BASE_METADATA.is_file(),
            f"{_COMMITTED_BASE_METADATA}: tracked base manifest is missing; "
            "regenerate it with gridalyn.twin.network.metadata.write_base_metadata",
        )
        self.manifest = json.loads(_COMMITTED_BASE_METADATA.read_text())

    def test_declares_the_full_manifest_contract(self):
        # Without this, a manifest that declares nothing would pass the path
        # gate below vacuously -- which is how the pre-Phase-11 stub survived.
        missing = sorted(
            {"schema_version", "created_at", "model_version_id", "artifacts", "counts"}
            - set(self.manifest)
        )
        self.assertEqual(
            missing,
            [],
            f"{_COMMITTED_BASE_METADATA}: manifest is missing {missing} "
            f"(present keys: {sorted(self.manifest)}); regenerate it with "
            "gridalyn.twin.network.metadata.write_base_metadata",
        )
        self.assertEqual(
            sorted(self.manifest["artifacts"]), sorted(_BASE_ARTIFACT_NAMES)
        )

    def test_every_declared_path_is_rooted_in_a_directory_that_still_exists(self):
        stale = stale_declared_paths(self.manifest, _REPO_ROOT)
        self.assertEqual(
            stale,
            [],
            f"{_COMMITTED_BASE_METADATA}: declares "
            + "; ".join(stale)
            + "; regenerate it with "
            "gridalyn.twin.network.metadata.write_base_metadata so it describes "
            "the tree as it actually is",
        )


class DigitalTwinBaseMetadataTest(unittest.TestCase):
    def _write_base_model(self, base: Path) -> None:
        pd.DataFrame(
            [
                {"bus_id": "bus:0", "category": "MV"},
                {"bus_id": "bus:1", "category": "LV"},
            ]
        ).to_parquet(base / "grid_buses.parquet")
        pd.DataFrame(
            [{"line_id": "line:0", "from_bus_id": "bus:0", "to_bus_id": "bus:1"}]
        ).to_parquet(base / "grid_lines.parquet")
        pd.DataFrame(
            [
                {
                    "transformer_id": "transformer:0",
                    "hv_bus_id": "bus:0",
                    "lv_bus_id": "bus:1",
                }
            ]
        ).to_parquet(base / "grid_transformers.parquet")
        pd.DataFrame(
            [{"building_id": "building:0", "load_id": "load:0", "lv_bus_id": "bus:1"}]
        ).to_parquet(base / "buildings.parquet")
        pd.DataFrame(
            [{"building_id": "building:0", "load_id": "load:0", "load_bus_id": "bus:1"}]
        ).to_parquet(base / "building_grid_connectivity.parquet")

    def test_builds_repository_centric_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "instances" / "default" / "digital_twin" / "base"
            base.mkdir(parents=True)
            self._write_base_model(base)

            metadata = build_base_metadata(
                base_dir=base,
                root=root,
                config_path=root / "config.json",
                config_hash="abc123",
                cache_dir=root / "cache",
                source_adapter="SyntheticPandapowerAdapter",
                adapter_validation_report=root
                / "reports"
                / "network_adapter_validation_report.json",
            )

        self.assertEqual(metadata["schema_version"], "1.0")
        self.assertEqual(metadata["source_adapter"], "SyntheticPandapowerAdapter")
        self.assertEqual(metadata["source_standard"], "pandapower")
        self.assertTrue(metadata["model_version"]["id"].startswith("model:sha256:"))
        self.assertEqual(metadata["model_version_id"], metadata["model_version"]["id"])
        self.assertEqual(
            metadata["model_version"]["source_adapter"], "SyntheticPandapowerAdapter"
        )
        self.assertEqual(metadata["model_version"]["source_standard"], "pandapower")
        self.assertEqual(metadata["model_version"]["validation_status"], "valid")
        self.assertIn("grid_buses", metadata["model_version"]["artifact_hashes"])
        self.assertEqual(metadata["counts"]["buses"], 2)
        self.assertEqual(metadata["counts"]["loads"], 1)
        self.assertTrue(metadata["validation"]["valid"])
        self.assertIn("grid_buses", metadata["artifacts"])
        self.assertEqual(metadata["artifacts"]["grid_buses"]["row_count"], 2)
        self.assertTrue(metadata["artifacts"]["grid_buses"]["sha256"])
        self.assertEqual(
            metadata["adapter_validation_report"],
            "reports/network_adapter_validation_report.json",
        )

    def test_write_base_metadata_materializes_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "instances" / "default" / "digital_twin" / "base"
            base.mkdir(parents=True)
            self._write_base_model(base)

            path = write_base_metadata(
                base_dir=base,
                root=root,
                config_path=root / "config.json",
                config_hash="abc123",
                cache_dir=root / "cache",
            )

            metadata = json.loads(path.read_text())

        self.assertEqual(path.name, "metadata.json")
        self.assertEqual(metadata["counts"]["buildings"], 1)
        self.assertEqual(metadata["validation"]["errors"], [])


if __name__ == "__main__":
    unittest.main()
