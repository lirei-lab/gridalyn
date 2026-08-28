"""CIM-like Parquet source adapter.

CIM is adopted here as *fields and rules over parquet*, never as a
serialization format. There is no RDF/XML parser or writer in this module and
no graph library is imported. ``tests/test_cim_dependency_policy.py`` pins the
resulting dependency posture — real ``rdflib`` imports under ``gridalyn/`` are
0, proven by an AST scan rather than a text grep.

The CGMES **Model Authority Set** and **profile** declarations this adapter
consumes moved to :mod:`gridalyn.twin.adapters.authority` in review cycle 1 of
Phase 11. They lived here, behind an import barrier that
:class:`~gridalyn.twin.adapters.network.SyntheticPandapowerAdapter` could not
cross without a cycle; both producers now reach them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from gridalyn.twin.adapters.authority import (
    ModelAuthoritySet,
    ModelProfile,
    authority_set_partition,
    base_model_profiles,
    cgmes_export_notes,
    model_authority_payload,
    validate_authority_partition,
)
from gridalyn.twin.adapters.network import (
    DEFAULT_NETWORK_ADAPTER_CAPABILITIES,
    NetworkAdapterDescriptor,
    NetworkExportResult,
    describe_network_source_adapter,
    exported_model_identity,
)
from gridalyn.twin.adapters.validation import write_network_adapter_validation_report
from gridalyn.twin.network.metadata import write_base_metadata
from gridalyn.twin.network.model import NetworkModel

CIM_PARQUET_TABLES = {
    "connectivity_nodes": "connectivity_nodes.parquet",
    "ac_line_segments": "ac_line_segments.parquet",
    "power_transformers": "power_transformers.parquet",
    "energy_consumers": "energy_consumers.parquet",
}


@dataclass(frozen=True)
class CimParquetAdapter:
    """Adapter from CIM-like Parquet tables to canonical base Parquet."""

    source_dir: Path
    adapter_id: str = "cim_parquet"
    source_adapter: str = "CimParquetAdapter"
    source_standard: str = "cim"
    source_format: str = "cim-parquet"
    capabilities: tuple[str, ...] = DEFAULT_NETWORK_ADAPTER_CAPABILITIES
    # Unset by default, and that is the honest default: the source is CIM
    # parquet the caller supplies, so its CRS is the SOURCE's to declare, not
    # this adapter's to infer. CGMES carries coordinate-system information the
    # adapter does not read today; a caller who knows their export's CRS passes
    # it here and the snapshot records it as declared rather than assumed.
    geographic_crs: str | None = None

    def describe(self) -> NetworkAdapterDescriptor:
        """Return stable adapter identity and capability metadata."""
        return describe_network_source_adapter(self)

    def authority_sets(self) -> tuple[ModelAuthoritySet, ...]:
        """Return the Model Authority Sets partitioning models this produces.

        Returns:
            The declared partition. Measured today it has exactly one member --
            see
            :data:`~gridalyn.twin.adapters.authority.AUTHORITY_SET_PARTITION_IS_SINGLE_MEMBER`.

        Raises:
            UnknownModelAuthoritySetError: If this adapter declares no set.
        """
        return authority_set_partition(self.adapter_id)

    def profiles(self) -> tuple[ModelProfile, ...]:
        """Return the declared profiles of the base this adapter exports.

        Returns:
            Every profile in
            :data:`~gridalyn.twin.adapters.authority.BASE_MODEL_PROFILES`,
            ordered by profile ID.
        """
        return base_model_profiles()

    def load_snapshot(self) -> NetworkModel:
        """Load CIM-like source tables and normalize them to canonical tables.

        Returns:
            The canonical :class:`NetworkModel`.

        Raises:
            ValueError: If this adapter's declared Model Authority Sets do not
                partition the canonical base artifacts. Checked here, before any
                IO, so the CGMES declarations are consumed on every load rather
                than only when a model is exported.
        """
        validate_authority_partition(self.authority_sets(), adapter_id=self.adapter_id)
        nodes = _read_required(self.source_dir, "connectivity_nodes")
        lines = _read_optional(self.source_dir, "ac_line_segments")
        transformers = _read_optional(self.source_dir, "power_transformers")
        consumers = _read_optional(self.source_dir, "energy_consumers")

        buses = _make_bus_table(nodes)
        # strict=True is safe and load-bearing: _make_bus_table emits exactly one
        # row per node, so a length mismatch means that invariant broke and the
        # lookup would silently lose buses.
        bus_lookup = dict(
            zip(
                nodes["mRID"].astype(str),
                buses["bus_id"].astype(str),
                strict=True,
            )
        )
        return NetworkModel(
            buses=buses,
            lines=_make_line_table(lines, bus_lookup),
            transformers=_make_transformer_table(transformers, bus_lookup),
            buildings=_make_building_table(consumers, bus_lookup),
            connectivity=_make_connectivity_table(consumers, transformers, bus_lookup),
            source_adapter=self.source_adapter,
            source_standard=self.source_standard,
        )

    def export(self, *, out_dir: Path, root: Path) -> NetworkExportResult:
        """Write canonical base artifacts and repository-centric metadata."""
        snapshot = self.load_snapshot()
        artifact_paths = snapshot.write_parquet(out_dir)
        metadata_path = write_base_metadata(
            base_dir=out_dir,
            root=root,
            config_path=self.source_dir / "manifest.json",
            config_hash=_source_hash(self.source_dir),
            cache_dir=self.source_dir,
            adapter_id=self.adapter_id,
            source_adapter=self.source_adapter,
            source_standard=self.source_standard,
            source_format=self.source_format,
            adapter_capabilities=self.capabilities,
            crs=self.geographic_crs,
            adapter_validation_report=out_dir
            / "network_adapter_validation_report.json",
            notes=self._export_notes(),
            model_authority=model_authority_payload(
                self.authority_sets(), self.profiles()
            ),
        )
        validation_report_path = write_network_adapter_validation_report(
            path=out_dir / "network_adapter_validation_report.json",
            base_dir=out_dir,
            root=root,
            adapter_id=self.adapter_id,
            source_adapter=self.source_adapter,
            source_standard=self.source_standard,
            source_format=self.source_format,
            adapter_capabilities=self.capabilities,
            artifact_paths=artifact_paths,
            metadata_path=metadata_path,
        )
        return NetworkExportResult(
            out_dir=out_dir,
            metadata_path=metadata_path,
            validation_report_path=validation_report_path,
            artifact_paths=artifact_paths,
            counts=snapshot.counts,
            identity=exported_model_identity(out_dir),
        )

    def _export_notes(self) -> list[str]:
        """Build the manifest provenance notes, including the CGMES posture.

        The authority-set and profile lines are rendered from the declarations
        themselves rather than retyped, so a manifest cannot describe a
        partition the code does not declare. The structured JSON-native form of
        the same declarations lands in the manifest's ``model_authority`` field.

        Returns:
            Provenance note lines, recorded verbatim in ``metadata.json``.
        """
        return [
            "Source tables use a CIM-like Parquet interchange profile.",
            "This adapter does not parse CIM RDF/XML.",
            *cgmes_export_notes(self.authority_sets()),
        ]


def _read_required(source_dir: Path, table: str) -> pd.DataFrame:
    path = source_dir / CIM_PARQUET_TABLES[table]
    if not path.exists():
        raise FileNotFoundError(f"Missing CIM Parquet table: {path}")
    return pd.read_parquet(path)


def _read_optional(source_dir: Path, table: str) -> pd.DataFrame:
    path = source_dir / CIM_PARQUET_TABLES[table]
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _make_bus_table(nodes: pd.DataFrame) -> pd.DataFrame:
    required = {"mRID"}
    missing = sorted(required - set(nodes.columns))
    if missing:
        raise ValueError(f"connectivity_nodes.parquet missing columns: {missing}")
    rows = []
    for index, row in nodes.reset_index(drop=True).iterrows():
        source_id = str(row["mRID"])
        voltage = _first_value(
            row, ["nominal_voltage_kv", "base_voltage_kv", "voltage_kv"]
        )
        rows.append(
            {
                "bus_id": f"bus:{source_id}",
                "source_id": source_id,
                "name": _first_value(row, ["name"], default=source_id),
                "voltage_kv": float(voltage) if voltage is not None else None,
                "category": _first_value(
                    row, ["category"], default=_category_from_voltage(voltage)
                ),
                "lat": _first_value(row, ["lat", "latitude"]),
                "lon": _first_value(row, ["lon", "longitude"]),
                "in_service": bool(_first_value(row, ["in_service"], default=True)),
                "cim_class": "ConnectivityNode",
                "source_row": int(index),
            }
        )
    return pd.DataFrame(rows)


def _make_line_table(lines: pd.DataFrame, bus_lookup: dict[str, str]) -> pd.DataFrame:
    if lines.empty:
        return pd.DataFrame()
    rows = []
    for index, row in lines.reset_index(drop=True).iterrows():
        source_id = str(_first_value(row, ["mRID", "line_id"], default=f"line:{index}"))
        from_node = str(
            _first_value(row, ["from_connectivity_node", "from_node", "from_mrid"])
        )
        to_node = str(_first_value(row, ["to_connectivity_node", "to_node", "to_mrid"]))
        rows.append(
            {
                "line_id": f"line:{source_id}",
                "source_id": source_id,
                "name": _first_value(row, ["name"], default=source_id),
                "from_bus_id": bus_lookup.get(from_node, f"bus:{from_node}"),
                "to_bus_id": bus_lookup.get(to_node, f"bus:{to_node}"),
                "length_km": _first_value(row, ["length_km", "length"]),
                "cim_class": "ACLineSegment",
            }
        )
    return pd.DataFrame(rows)


def _make_transformer_table(
    transformers: pd.DataFrame,
    bus_lookup: dict[str, str],
) -> pd.DataFrame:
    if transformers.empty:
        return pd.DataFrame()
    rows = []
    for index, row in transformers.reset_index(drop=True).iterrows():
        source_id = str(
            _first_value(row, ["mRID", "transformer_id"], default=f"tx:{index}")
        )
        high_node = str(
            _first_value(row, ["high_connectivity_node", "hv_node", "high_mrid"])
        )
        low_node = str(
            _first_value(row, ["low_connectivity_node", "lv_node", "low_mrid"])
        )
        rows.append(
            {
                "transformer_id": f"transformer:{source_id}",
                "source_id": source_id,
                "name": _first_value(row, ["name"], default=source_id),
                "hv_bus_id": bus_lookup.get(high_node, f"bus:{high_node}"),
                "lv_bus_id": bus_lookup.get(low_node, f"bus:{low_node}"),
                "rated_s_mva": _first_value(row, ["rated_s_mva", "rated_mva"]),
                "cim_class": "PowerTransformer",
            }
        )
    return pd.DataFrame(rows)


def _make_building_table(
    consumers: pd.DataFrame,
    bus_lookup: dict[str, str],
) -> pd.DataFrame:
    if consumers.empty:
        return pd.DataFrame()
    rows = []
    for index, row in consumers.reset_index(drop=True).iterrows():
        source_id = str(
            _first_value(row, ["mRID", "consumer_id"], default=f"consumer:{index}")
        )
        node = str(_first_value(row, ["connectivity_node", "node", "node_mrid"]))
        building_id = _first_value(
            row, ["building_id"], default=f"building:{source_id}"
        )
        load_id = _first_value(row, ["load_id"], default=f"load:{source_id}")
        rows.append(
            {
                "building_id": str(building_id),
                "source_id": source_id,
                "load_id": str(load_id),
                "name": _first_value(row, ["name"], default=source_id),
                "lv_bus_id": bus_lookup.get(node, f"bus:{node}"),
                "p_kw": _first_value(row, ["p_kw", "p_mw"]),
                "cim_class": "EnergyConsumer",
            }
        )
    return pd.DataFrame(rows)


def _make_connectivity_table(
    consumers: pd.DataFrame,
    transformers: pd.DataFrame,
    bus_lookup: dict[str, str],
) -> pd.DataFrame:
    if consumers.empty:
        return pd.DataFrame()
    transformer_by_low_bus = _transformer_by_low_bus(transformers, bus_lookup)
    rows = []
    for index, row in consumers.reset_index(drop=True).iterrows():
        source_id = str(
            _first_value(row, ["mRID", "consumer_id"], default=f"consumer:{index}")
        )
        node = str(_first_value(row, ["connectivity_node", "node", "node_mrid"]))
        bus_id = bus_lookup.get(node, f"bus:{node}")
        building_id = str(
            _first_value(row, ["building_id"], default=f"building:{source_id}")
        )
        load_id = str(_first_value(row, ["load_id"], default=f"load:{source_id}"))
        rows.append(
            {
                "building_id": building_id,
                "load_id": load_id,
                "load_bus_id": bus_id,
                "lv_bus_id": bus_id,
                "lv_transformer_id": transformer_by_low_bus.get(bus_id),
                "feeder_id": _first_value(row, ["feeder_id"]),
                "connectivity_status": "ok",
            }
        )
    return pd.DataFrame(rows)


def _transformer_by_low_bus(
    transformers: pd.DataFrame,
    bus_lookup: dict[str, str],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if transformers.empty:
        return mapping
    for index, row in transformers.reset_index(drop=True).iterrows():
        source_id = str(
            _first_value(row, ["mRID", "transformer_id"], default=f"tx:{index}")
        )
        low_node = str(
            _first_value(row, ["low_connectivity_node", "lv_node", "low_mrid"])
        )
        mapping[bus_lookup.get(low_node, f"bus:{low_node}")] = (
            f"transformer:{source_id}"
        )
    return mapping


def _first_value(row: pd.Series, columns: list[str], default: Any = None) -> Any:
    for column in columns:
        if column in row.index and pd.notna(row[column]):
            return row[column]
    return default


def _category_from_voltage(voltage: Any) -> str:
    if voltage is None or pd.isna(voltage):
        return "UNKNOWN"
    value = float(voltage)
    if value < 1.0:
        return "LV"
    if value < 100.0:
        return "MV"
    return "HV"


def _source_hash(source_dir: Path) -> str:
    payload: dict[str, str | None] = {}
    for table, filename in sorted(CIM_PARQUET_TABLES.items()):
        path = source_dir / filename
        payload[table] = _file_hash(path) if path.exists() else None
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def _file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
