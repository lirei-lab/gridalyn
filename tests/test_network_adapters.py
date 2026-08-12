import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from gridalyn.projects.workflows.scripts.export_digital_twin_base import (
    export_base_twin,
)
from gridalyn.twin import NetworkModelRepository
from gridalyn.twin.adapters.cim import CimParquetAdapter
from gridalyn.twin.adapters.network import (
    NetworkExportResult,
    SyntheticPandapowerAdapter,
    describe_network_source_adapter,
    exported_model_identity,
)
from gridalyn.twin.adapters.registry import (
    NetworkAdapterRegistry,
    UnknownNetworkAdapterError,
    default_network_adapter_registry,
)
from gridalyn.twin.adapters.validation import (
    build_network_adapter_validation_report,
    write_network_adapter_validation_report,
)
from gridalyn.twin.network.model import ModelIdentity, NetworkModel


class NetworkAdaptersTest(unittest.TestCase):
    def _snapshot(self) -> NetworkModel:
        return NetworkModel(
            buses=pd.DataFrame(
                [
                    {"bus_id": "bus:0", "category": "MV"},
                    {"bus_id": "bus:1", "category": "LV"},
                ]
            ),
            lines=pd.DataFrame(
                [{"line_id": "line:0", "from_bus_id": "bus:0", "to_bus_id": "bus:1"}]
            ),
            transformers=pd.DataFrame(
                [
                    {
                        "transformer_id": "transformer:0",
                        "hv_bus_id": "bus:0",
                        "lv_bus_id": "bus:1",
                    }
                ]
            ),
            buildings=pd.DataFrame(
                [
                    {
                        "building_id": "building:0",
                        "load_id": "load:0",
                        "lv_bus_id": "bus:1",
                    }
                ]
            ),
            connectivity=pd.DataFrame(
                [
                    {
                        "building_id": "building:0",
                        "load_id": "load:0",
                        "load_bus_id": "bus:1",
                    }
                ]
            ),
            source_adapter="SyntheticPandapowerAdapter",
            source_standard="pandapower",
        )

    def _write_cim_parquet_source(self, source_dir: Path) -> None:
        source_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            [
                {
                    "mRID": "cn-mv",
                    "name": "MV node",
                    "nominal_voltage_kv": 25.0,
                    "category": "MV",
                },
                {
                    "mRID": "cn-lv",
                    "name": "LV node",
                    "nominal_voltage_kv": 0.4,
                    "category": "LV",
                },
            ]
        ).to_parquet(source_dir / "connectivity_nodes.parquet", index=False)
        pd.DataFrame(
            [
                {
                    "mRID": "line-1",
                    "name": "Line 1",
                    "from_connectivity_node": "cn-mv",
                    "to_connectivity_node": "cn-lv",
                    "length_km": 0.25,
                }
            ]
        ).to_parquet(source_dir / "ac_line_segments.parquet", index=False)
        pd.DataFrame(
            [
                {
                    "mRID": "tx-1",
                    "name": "Transformer 1",
                    "high_connectivity_node": "cn-mv",
                    "low_connectivity_node": "cn-lv",
                    "rated_s_mva": 0.5,
                }
            ]
        ).to_parquet(source_dir / "power_transformers.parquet", index=False)
        pd.DataFrame(
            [
                {
                    "mRID": "ec-1",
                    "name": "Customer 1",
                    "connectivity_node": "cn-lv",
                    "building_id": "building:cim:1",
                    "load_id": "load:cim:1",
                    "p_kw": 8.0,
                    "feeder_id": "feeder:demo",
                }
            ]
        ).to_parquet(source_dir / "energy_consumers.parquet", index=False)

    def test_network_snapshot_is_removed_not_aliased(self):
        # Proven by import, not by grep: a grep would match this very comment.
        with self.assertRaises(ImportError):
            from gridalyn.twin.adapters.network import NetworkSnapshot  # noqa: F401

        import gridalyn.twin.adapters as adapters
        import gridalyn.twin.adapters.network as network_module

        self.assertFalse(hasattr(network_module, "NetworkSnapshot"))
        self.assertFalse(hasattr(adapters, "NetworkSnapshot"))
        self.assertNotIn("NetworkSnapshot", adapters.__all__)

    def test_both_adapters_return_the_one_canonical_model_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "cim_source"
            self._write_cim_parquet_source(source_dir)
            cim_snapshot = CimParquetAdapter(source_dir=source_dir).load_snapshot()

        self.assertIsInstance(cim_snapshot, NetworkModel)
        self.assertIsInstance(self._snapshot(), NetworkModel)
        self.assertEqual(cim_snapshot.source_standard, "cim")

    def test_canonical_model_writes_repository_compatible_parquets(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "base"
            artifacts = self._snapshot().write_parquet(out_dir)
            repo = NetworkModelRepository.from_parquet(out_dir, provenance="ignore")
            model = repo.load_model()
            validation = repo.validate_integrity()

        self.assertEqual(
            set(artifacts),
            {
                "grid_buses",
                "grid_lines",
                "grid_transformers",
                "buildings",
                "building_grid_connectivity",
            },
        )
        self.assertEqual(model.counts["loads"], 1)
        self.assertTrue(validation.valid)

    def test_synthetic_pandapower_adapter_declares_platform_identity(self):
        adapter = SyntheticPandapowerAdapter(
            cache_dir=Path("examples/generated/outputs"),
            config_path=Path("configs/grid/config.json"),
        )

        descriptor = describe_network_source_adapter(adapter)

        self.assertEqual(descriptor.adapter_id, "synthetic_pandapower")
        self.assertEqual(adapter.source_adapter, "SyntheticPandapowerAdapter")
        self.assertEqual(adapter.source_standard, "pandapower")
        self.assertEqual(descriptor.source_format, "pandapower-cache")
        self.assertIn("export_base_parquet", descriptor.capabilities)

    def test_default_registry_exposes_synthetic_pandapower_adapter(self):
        registry = default_network_adapter_registry()

        descriptor = registry.get_descriptor("synthetic_pandapower")
        descriptors = registry.list_descriptors()

        self.assertEqual(descriptor.adapter_id, "synthetic_pandapower")
        self.assertEqual(descriptor.source_format, "pandapower-cache")
        self.assertIn("synthetic_pandapower", [item.adapter_id for item in descriptors])

    def test_registry_creates_adapter_from_id(self):
        registry = default_network_adapter_registry()

        adapter = registry.create(
            "synthetic_pandapower",
            cache_dir=Path("examples/generated/outputs"),
            config_path=Path("configs/grid/config.json"),
        )

        self.assertIsInstance(adapter, SyntheticPandapowerAdapter)
        self.assertEqual(adapter.adapter_id, "synthetic_pandapower")

    def test_default_registry_exposes_cim_parquet_adapter(self):
        registry = default_network_adapter_registry()

        descriptor = registry.get_descriptor("cim_parquet")

        self.assertEqual(descriptor.adapter_id, "cim_parquet")
        self.assertEqual(descriptor.source_standard, "cim")
        self.assertEqual(descriptor.source_format, "cim-parquet")

    def test_cim_parquet_adapter_exports_repository_compatible_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "cim_source"
            out_dir = root / "base"
            self._write_cim_parquet_source(source_dir)

            adapter = CimParquetAdapter(source_dir=source_dir)
            result = adapter.export(out_dir=out_dir, root=root)
            repo = NetworkModelRepository.from_parquet(out_dir)
            model = repo.load_model()
            validation = repo.validate_integrity()
            metadata = json.loads(result.metadata_path.read_text())

        self.assertTrue(validation.valid, validation.errors)
        self.assertEqual(model.counts["buses"], 2)
        self.assertEqual(model.counts["lines"], 1)
        self.assertEqual(model.counts["transformers"], 1)
        self.assertEqual(model.counts["buildings"], 1)
        self.assertEqual(model.counts["loads"], 1)
        self.assertEqual(metadata["adapter_id"], "cim_parquet")
        self.assertEqual(metadata["source_standard"], "cim")
        self.assertEqual(metadata["source_format"], "cim-parquet")

    def test_export_base_twin_can_use_cim_parquet_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "cim_source"
            out_dir = root / "base"
            self._write_cim_parquet_source(source_dir)

            export_base_twin(
                cache_dir=Path("unused-cache"),
                config_path=Path("unused-config.json"),
                out_dir=out_dir,
                adapter_id="cim_parquet",
                source_dir=source_dir,
            )
            repo = NetworkModelRepository.from_parquet(out_dir)
            validation = repo.validate_integrity()
            metadata = json.loads((out_dir / "metadata.json").read_text())

        self.assertTrue(validation.valid, validation.errors)
        self.assertEqual(metadata["adapter_id"], "cim_parquet")

    def test_registry_raises_clear_error_for_unknown_adapter(self):
        registry = NetworkAdapterRegistry()

        with self.assertRaisesRegex(UnknownNetworkAdapterError, "missing_adapter"):
            registry.get_descriptor("missing_adapter")

    def test_builds_valid_network_adapter_validation_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out_dir = root / "base"
            artifact_paths = self._snapshot().write_parquet(out_dir)
            metadata_path = out_dir / "metadata.json"
            metadata_path.write_text(json.dumps({"model_version": "sha256:test"}))

            report = build_network_adapter_validation_report(
                base_dir=out_dir,
                root=root,
                source_adapter="SyntheticPandapowerAdapter",
                source_standard="pandapower",
                artifact_paths=artifact_paths,
                metadata_path=metadata_path,
            )

        self.assertEqual(report["report_id"], "network_adapter_validation")
        self.assertEqual(report["source_adapter"], "SyntheticPandapowerAdapter")
        self.assertEqual(report["source_standard"], "pandapower")
        self.assertTrue(report["validation"]["valid"])
        self.assertEqual(report["summary"]["counts"]["loads"], 1)
        self.assertEqual(report["lineage"]["metadata_path"], "base/metadata.json")
        self.assertIn("grid_buses", report["artifacts"])
        self.assertEqual(report["adapter"]["adapter_id"], "synthetic_pandapower")
        self.assertEqual(report["adapter"]["source_format"], "pandapower-cache")
        self.assertIn("write_validation_report", report["adapter"]["capabilities"])

    def test_adapter_validation_report_marks_broken_endpoint_invalid(self):
        snapshot = NetworkModel(
            buses=pd.DataFrame([{"bus_id": "bus:0", "category": "MV"}]),
            lines=pd.DataFrame(
                [
                    {
                        "line_id": "line:bad",
                        "from_bus_id": "bus:0",
                        "to_bus_id": "bus:missing",
                    }
                ]
            ),
            transformers=pd.DataFrame(),
            buildings=pd.DataFrame(),
            connectivity=pd.DataFrame(),
            source_adapter="TestAdapter",
            source_standard="test",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out_dir = root / "base"
            artifact_paths = snapshot.write_parquet(out_dir)
            metadata_path = out_dir / "metadata.json"
            metadata_path.write_text(json.dumps({"model_version": "sha256:test"}))

            path = write_network_adapter_validation_report(
                path=root / "reports" / "network_adapter_validation_report.json",
                base_dir=out_dir,
                root=root,
                source_adapter="TestAdapter",
                source_standard="test",
                artifact_paths=artifact_paths,
                metadata_path=metadata_path,
            )
            report = json.loads(path.read_text())

        self.assertFalse(report["validation"]["valid"])
        self.assertIn("bus:missing", " ".join(report["validation"]["errors"]))

    def test_exported_model_identity_refuses_a_base_without_a_manifest(self):
        """The export post-condition fails loudly, and names the remedy.

        This is the one production caller of ``provenance="require"``. An export
        whose artifacts landed but whose manifest did not is a failed export;
        without this it returned a result claiming success for a base no reader
        could identify.
        """
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "base"
            self._snapshot().write_parquet(out_dir)

            with self.assertRaises(FileNotFoundError) as caught:
                exported_model_identity(out_dir)

        self.assertIn("metadata.json", str(caught.exception))
        self.assertIn("write_base_metadata", str(caught.exception))

    def test_export_base_twin_delegates_to_synthetic_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "base"
            metadata_path = out_dir / "metadata.json"

            class FakeAdapter:
                adapter_id = "synthetic_pandapower"
                source_adapter = "SyntheticPandapowerAdapter"
                source_standard = "pandapower"
                source_format = "pandapower-cache"
                capabilities = ("export_base_parquet",)

                def __init__(self, *, cache_dir, config_path):
                    self.cache_dir = cache_dir
                    self.config_path = config_path

                def export(self, *, out_dir, root):
                    out_dir.mkdir(parents=True)
                    metadata_path.write_text(
                        json.dumps(
                            {
                                "counts": {"buses": 1},
                                "source_adapter": self.source_adapter,
                            }
                        )
                    )
                    return NetworkExportResult(
                        out_dir=out_dir,
                        metadata_path=metadata_path,
                        validation_report_path=out_dir / "validation.json",
                        artifact_paths={},
                        counts={"buses": 1},
                        identity=ModelIdentity(id="model:sha256:fake"),
                    )

            registry = NetworkAdapterRegistry()
            registry.register(FakeAdapter)

            with patch(
                "gridalyn.projects.workflows.scripts.export_digital_twin_base.default_network_adapter_registry",
                return_value=registry,
            ):
                export_base_twin(
                    cache_dir=Path("cache"),
                    config_path=Path("config.json"),
                    out_dir=out_dir,
                )

            self.assertTrue(metadata_path.exists())

    @unittest.skipUnless(
        Path("examples/generated/outputs").is_dir(),
        "examples/generated/outputs is a local artifact of running the examples; "
        "it is not committed, so this export test is operator-verified",
    )
    def test_synthetic_adapter_export_writes_validation_report_and_links_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out_dir = root / "base"
            adapter = SyntheticPandapowerAdapter(
                cache_dir=Path("examples/generated/outputs"),
                config_path=Path("configs/grid/config.json"),
            )

            result = adapter.export(out_dir=out_dir, root=Path.cwd())
            metadata = json.loads(result.metadata_path.read_text())
            report = json.loads(result.validation_report_path.read_text())

            self.assertTrue(result.validation_report_path.exists())
            self.assertEqual(
                metadata["adapter_validation_report"],
                str(result.validation_report_path.resolve()),
            )
            self.assertEqual(metadata["adapter_id"], "synthetic_pandapower")
            self.assertEqual(metadata["source_format"], "pandapower-cache")
            self.assertTrue(report["validation"]["valid"])


if __name__ == "__main__":
    unittest.main()
