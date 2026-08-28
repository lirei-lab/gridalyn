"""Network source adapters for canonical digital-twin snapshots."""

from __future__ import annotations

import hashlib
import json
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandapower as pp
import pandas as pd

from gridalyn.foundation import ArtifactLayout
from gridalyn.twin.adapters.authority import (
    ModelAuthoritySet,
    ModelProfile,
    authority_set_partition,
    base_model_profiles,
    cgmes_export_notes,
    model_authority_payload,
    validate_authority_partition,
)
from gridalyn.twin.adapters.pandapower_builder import build_power_grid_and_network
from gridalyn.twin.adapters.validation import write_network_adapter_validation_report
from gridalyn.twin.core.graph import PowerGridGraph
from gridalyn.twin.network.geography import DEFAULT_GEOGRAPHIC_CRS
from gridalyn.twin.network.metadata import write_base_metadata
from gridalyn.twin.network.model import (
    BASE_TABLE_FILENAMES,
    ModelIdentity,
    NetworkModel,
)
from gridalyn.twin.network.repository import NetworkModelRepository
from gridalyn.twin.network.schema import (
    BUILDING_GRID_CONNECTIVITY,
    BUILDINGS,
    table_schema,
)

__all__ = [
    "BASE_EXPORT_NOTES",
    "BASE_TABLE_FILENAMES",
    "DEFAULT_NETWORK_ADAPTER_CAPABILITIES",
    "NetworkAdapterDescriptor",
    "NetworkExportResult",
    "NetworkSourceAdapter",
    "PandapowerTopologyAdapter",
    "SyntheticPandapowerAdapter",
    "TOPOLOGY_ONLY_EXPORT_NOTES",
    "describe_network_source_adapter",
    "exported_model_identity",
]

BASE_EXPORT_NOTES = [
    "Building area is exported as metadata only.",
    "Load generation remains independent of area_m2.",
    "Connectivity is derived from pandapower load buses and LV cluster labels.",
]

DEFAULT_NETWORK_ADAPTER_CAPABILITIES = (
    "load_snapshot",
    "export_base_parquet",
    "write_base_metadata",
    "write_validation_report",
)


@dataclass(frozen=True)
class NetworkAdapterDescriptor:
    """Stable identity and capability metadata for a network source adapter."""

    adapter_id: str
    adapter_name: str
    source_standard: str
    source_format: str
    capabilities: tuple[str, ...]
    geographic_crs: str | None = None
    contract_version: str = "1"


class NetworkSourceAdapter(Protocol):
    """Contract for adapters that can produce canonical network snapshots.

    Declared as read-only properties, not plain attributes: every known
    implementer (``SyntheticPandapowerAdapter``, ``CimParquetAdapter``) is a
    frozen dataclass, so a plain ``name: type`` declaration -- which Protocol
    structural matching treats as requiring a settable attribute -- flags a
    false-positive mismatch against both. Nothing ever assigns to these
    fields; read-only is what every implementer already is.
    """

    @property
    def adapter_id(self) -> str:
        """Stable identifier of the network source adapter."""

    @property
    def source_adapter(self) -> str:
        """Class name of the producing source adapter."""

    @property
    def source_standard(self) -> str:
        """Source data standard, e.g. ``"pandapower"``."""

    @property
    def source_format(self) -> str:
        """Source serialization format."""

    @property
    def capabilities(self) -> tuple[str, ...]:
        """Capabilities this adapter declares."""

    @property
    def geographic_crs(self) -> str | None:
        """CRS the ``lat``/``lon`` columns this adapter writes are measured in.

        A declaration of what the adapter *produces*, exactly like
        :attr:`source_standard` and :attr:`source_format`, not an inference
        about the data it happened to read. ``None`` means the adapter makes no
        claim, and a reader then falls back to
        :data:`~gridalyn.twin.network.geography.DEFAULT_GEOGRAPHIC_CRS` and
        reports the value as *assumed* rather than declared.
        """

    def load_snapshot(self) -> NetworkModel:
        """Load a source model into the canonical in-memory tables."""

    def export(self, *, out_dir: Path, root: Path) -> "NetworkExportResult":
        """Write canonical base artifacts and metadata."""


@dataclass(frozen=True)
class NetworkExportResult:
    """Result of exporting a canonical base network snapshot.

    Attributes:
        out_dir: Directory the canonical artifacts were written to.
        metadata_path: Path of the ``metadata.json`` manifest written.
        validation_report_path: Path of the adapter validation report.
        artifact_paths: Canonical artifact name to the path written.
        counts: Row counts per canonical table.
        identity: Identity of the model just exported, read back through the
            repository read path rather than assembled by the producer -- see
            :func:`exported_model_identity`.
    """

    out_dir: Path
    metadata_path: Path
    validation_report_path: Path
    artifact_paths: dict[str, Path]
    counts: dict[str, int]
    identity: ModelIdentity


def exported_model_identity(out_dir: Path) -> ModelIdentity:
    """Read an export's own manifest back and return the model identity.

    This is the export post-condition, and the one production caller of
    ``provenance="require"``. An export that wrote its artifacts but not a
    manifest a reader can resolve is a failed export, not a successful one that
    happens to be unidentifiable -- and the producer is the last place able to
    say so. Reading it back through :class:`NetworkModelRepository` rather than
    trusting the payload just handed to the writer is what makes producer and
    consumer agree on the same manifest.

    Args:
        out_dir: The directory the export wrote its manifest into.

    Returns:
        The :class:`ModelIdentity` the manifest declares.

    Raises:
        FileNotFoundError: If no manifest is present -- raised by the
            ``"require"`` provenance policy, which names the remedy.
        ValueError: If the manifest is present but is not a JSON object.
        RuntimeError: If the manifest parsed but declared no identity.
    """
    repository = NetworkModelRepository.from_parquet(out_dir, provenance="require")
    identity = repository.load_model().identity
    if identity is None:  # pragma: no cover - "require" raises before this
        raise RuntimeError(
            f"{out_dir}: the exported manifest parsed but declared no model "
            "identity; regenerate it with "
            "gridalyn.twin.network.metadata.write_base_metadata"
        )
    return identity


@dataclass(frozen=True)
class SyntheticPandapowerAdapter:
    """Adapter from synthetic pandapower/Gridalyn objects to base Parquet.

    Two sources, chosen by whether ``footprints_path`` is set:

    * unset (default): ``load_snapshot`` normalizes an already-built network
      it reads from ``cache_dir``'s ``pp_net_cache.pkl``/``pg_graph_cache.pkl``
      -- the historical, adapt-only path.
    * set: ``load_snapshot`` builds the network fresh from the building
      footprints via
      :func:`~gridalyn.twin.adapters.pandapower_builder.build_power_grid_and_network`
      (Phase 29, 2026-08-19) -- no ``gridalyn.simulation`` dependency, no
      cache required. This is what gives ``gridalyn.twin`` a real
      construction capability instead of only ever adapting a network
      someone else already built.
    """

    cache_dir: Path
    config_path: Path
    footprints_path: Path | None = None
    adapter_id: str = "synthetic_pandapower"
    source_adapter: str = "SyntheticPandapowerAdapter"
    source_standard: str = "pandapower"
    source_format: str = "pandapower-cache"
    capabilities: tuple[str, ...] = DEFAULT_NETWORK_ADAPTER_CAPABILITIES
    # Longitude/latitude degrees. Measured, not assumed: the geoprocess layer
    # sets or asserts EPSG:4326 on every ingest path, the synthetic generator
    # stamps CRS84 into the GeoJSON it emits, and
    # `build_pandapower_from_geojson` documents that graph geodata stays
    # lon/lat while clustering happens in a projected CRS. An adapter fed a
    # differently-projected source overrides this on construction.
    geographic_crs: str | None = DEFAULT_GEOGRAPHIC_CRS

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
        """Build or load the synthetic grid and normalize it to base tables.

        Builds fresh from ``footprints_path`` when set (Phase 29); otherwise
        loads ``cache_dir``'s pickled net/graph, the historical adapt-only
        path.

        Returns:
            The canonical :class:`NetworkModel`.

        Raises:
            ValueError: If this adapter's declared Model Authority Sets do not
                partition the canonical base artifacts. Checked here, before any
                IO, so the declarations are consumed on the path that actually
                produces the committed base rather than only on the CIM path.
        """
        validate_authority_partition(self.authority_sets(), adapter_id=self.adapter_id)
        if self.footprints_path is not None:
            config = _load_json(self.config_path)
            pg, net = build_power_grid_and_network(
                footprints_path=self.footprints_path, config=config
            )
        else:
            net, pg = _load_cache(self.cache_dir)
        buses = _make_bus_table(net)
        lines = _make_line_table(net, buses)
        transformers = _make_transformer_table(net, buses)
        buildings, connectivity = _make_buildings_and_connectivity(
            net,
            pg,
            buses,
            transformers,
        )
        if len(buildings) != len(net.load):
            raise RuntimeError(
                "Building twin row count does not match pandapower loads."
            )
        if (connectivity["connectivity_status"] != "ok").any():
            missing = connectivity.loc[connectivity["connectivity_status"] != "ok"]
            raise RuntimeError(
                f"Connectivity export has {len(missing)} missing transformer mappings."
            )
        return NetworkModel(
            buses=buses,
            lines=lines,
            transformers=transformers,
            buildings=buildings,
            connectivity=connectivity,
            source_adapter=self.source_adapter,
            source_standard=self.source_standard,
        )

    def export(self, *, out_dir: Path, root: Path) -> NetworkExportResult:
        """Write base network artifacts and repository-centric metadata."""
        config = _load_json(self.config_path)
        snapshot = self.load_snapshot()
        artifact_paths = snapshot.write_parquet(out_dir)
        validation_report_path = _validation_report_path(out_dir=out_dir, root=root)
        metadata_path = write_base_metadata(
            base_dir=out_dir,
            root=root,
            config_path=self.config_path,
            config_hash=_config_hash(config),
            cache_dir=self.cache_dir,
            adapter_id=self.adapter_id,
            source_adapter=self.source_adapter,
            source_standard=self.source_standard,
            source_format=self.source_format,
            adapter_capabilities=self.capabilities,
            adapter_validation_report=validation_report_path,
            crs=self.geographic_crs,
            notes=self._export_notes(),
            model_authority=model_authority_payload(
                self.authority_sets(), self.profiles()
            ),
        )
        write_network_adapter_validation_report(
            path=validation_report_path,
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

        The CGMES lines are rendered from the declarations themselves rather
        than retyped, so the committed base -- a synthetic export -- carries the
        same posture as a CIM export instead of leaving
        ``gridalyn:mas:synthetic-pandapower`` invisible to every reader of the
        artifact.

        Returns:
            Provenance note lines, recorded verbatim in ``metadata.json``.
        """
        return [*BASE_EXPORT_NOTES, *cgmes_export_notes(self.authority_sets())]


TOPOLOGY_ONLY_EXPORT_NOTES = [
    "This source has no building-footprint layer (no PowerGridGraph): "
    "buildings and building_grid_connectivity are exported empty, not "
    "fabricated. NetworkModelRepository.validate_integrity() treats a "
    "present-but-empty artifact as a warning, not an error -- this is the "
    "documented shape for a source adapter that legitimately lacks one.",
]


@dataclass(frozen=True)
class PandapowerTopologyAdapter:
    """Adapter from an in-memory pandapower net to base Parquet, topology only.

    For feeders with no building-footprint layer -- built directly from
    ``gridalyn.assets.modeling.feeders.RadialFeederSpec`` or hand-rolled
    pandapower, as in ``der_voltage_optimization``, ``prosumer_battery_market``,
    ``rl_voltage_control_lightsim`` and ``admm_thermal_consensus`` -- where
    ``SyntheticPandapowerAdapter`` does not apply: it requires a
    ``PowerGridGraph`` (``pg.building_data``/``pg.labels_lv``) that these
    sources never have. This adapter reuses the same bus/line/transformer
    normalization and exports ``buildings``/``building_grid_connectivity``
    empty rather than fabricating building-level data that does not exist in
    the source -- see :data:`TOPOLOGY_ONLY_EXPORT_NOTES`.

    Unlike ``SyntheticPandapowerAdapter``, the net is handed in directly
    (``net``), not read from a cache directory or built from footprints: none
    of these sources persist a cache pickle, and there is no footprint file to
    build from.
    """

    net: pp.pandapowerNet
    config_path: Path
    # No geographic claim, deliberately. This adapter serves feeders with no
    # footprint layer -- RadialFeederSpec and hand-rolled pandapower -- whose
    # coordinates are SCHEMATIC: `der_voltage_optimization` writes buses at
    # (0,0), (1,0.2), (2,0.4), (3,0). Calling those EPSG:4326 would place the
    # feeder in the Gulf of Guinea. `None` makes a reader report the snapshot
    # as unlocated, which is the truth.
    geographic_crs: str | None = None
    adapter_id: str = "pandapower_topology"
    source_adapter: str = "PandapowerTopologyAdapter"
    source_standard: str = "pandapower"
    source_format: str = "pandapower-net"
    capabilities: tuple[str, ...] = DEFAULT_NETWORK_ADAPTER_CAPABILITIES

    def describe(self) -> NetworkAdapterDescriptor:
        """Return stable adapter identity and capability metadata."""
        return describe_network_source_adapter(self)

    def authority_sets(self) -> tuple[ModelAuthoritySet, ...]:
        """Return the Model Authority Sets partitioning models this produces.

        Returns:
            The declared partition -- see
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
        """Normalize the handed-in net to base tables; buildings/connectivity empty.

        Returns:
            The canonical :class:`NetworkModel`.

        Raises:
            ValueError: If this adapter's declared Model Authority Sets do not
                partition the canonical base artifacts.
        """
        validate_authority_partition(self.authority_sets(), adapter_id=self.adapter_id)
        buses = _make_bus_table(self.net)
        lines = _make_line_table(self.net, buses)
        transformers = _make_transformer_table(self.net, buses)
        return NetworkModel(
            buses=buses,
            lines=lines,
            transformers=transformers,
            buildings=_empty_buildings_table(),
            connectivity=_empty_connectivity_table(),
            source_adapter=self.source_adapter,
            source_standard=self.source_standard,
        )

    def export(self, *, out_dir: Path, root: Path) -> NetworkExportResult:
        """Write base network artifacts and repository-centric metadata."""
        config = _load_json(self.config_path)
        snapshot = self.load_snapshot()
        artifact_paths = snapshot.write_parquet(out_dir)
        validation_report_path = _validation_report_path(out_dir=out_dir, root=root)
        metadata_path = write_base_metadata(
            base_dir=out_dir,
            root=root,
            config_path=self.config_path,
            config_hash=_config_hash(config),
            cache_dir=None,
            adapter_id=self.adapter_id,
            source_adapter=self.source_adapter,
            source_standard=self.source_standard,
            source_format=self.source_format,
            adapter_capabilities=self.capabilities,
            adapter_validation_report=validation_report_path,
            crs=self.geographic_crs,
            notes=self._export_notes(),
            model_authority=model_authority_payload(
                self.authority_sets(), self.profiles()
            ),
        )
        write_network_adapter_validation_report(
            path=validation_report_path,
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

        Returns:
            Provenance note lines, recorded verbatim in ``metadata.json``.
        """
        return [*TOPOLOGY_ONLY_EXPORT_NOTES, *cgmes_export_notes(self.authority_sets())]


def _empty_buildings_table() -> pd.DataFrame:
    schema = table_schema(BUILDINGS)
    return pd.DataFrame(columns=[spec.canonical for spec in schema.columns])


def _empty_connectivity_table() -> pd.DataFrame:
    schema = table_schema(BUILDING_GRID_CONNECTIVITY)
    return pd.DataFrame(columns=[spec.canonical for spec in schema.columns])


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r") as f:
        return json.load(f)


def describe_network_source_adapter(
    adapter: NetworkSourceAdapter | type,
) -> NetworkAdapterDescriptor:
    """Describe an adapter using the platform network source contract.

    Accepts either an adapter instance or the adapter class itself, because
    :meth:`~gridalyn.twin.adapters.registry.NetworkAdapterRegistry.register`
    describes a factory before anything is constructed.

    Args:
        adapter: Adapter instance or adapter class declaring the identity
            attributes of the network source contract.

    Returns:
        The adapter's stable identity and capability metadata.

    Raises:
        ValueError: If the adapter declares neither ``adapter_id`` nor
            ``source_adapter``, so no stable ID can be derived.
    """
    # Resolve the fallback name for a class and an instance alike. Reading
    # ``adapter.__class__.__name__`` off a class yields the metaclass name --
    # literally ``"type"`` -- which used to register every under-declared
    # adapter under the ID ``'type'`` without raising.
    default_name = (
        adapter.__name__ if isinstance(adapter, type) else adapter.__class__.__name__
    )
    adapter_name = getattr(adapter, "source_adapter", default_name)
    declared_id = getattr(adapter, "adapter_id", None)
    if declared_id is None and not hasattr(adapter, "source_adapter"):
        raise ValueError(
            f"{default_name} declares neither 'adapter_id' nor 'source_adapter', "
            "so it has no stable registry ID -- declare 'adapter_id' on the "
            "adapter (as SyntheticPandapowerAdapter and CimParquetAdapter do), "
            "or pass descriptor= explicitly to NetworkAdapterRegistry.register"
        )
    source_standard = getattr(adapter, "source_standard", "unknown")
    return NetworkAdapterDescriptor(
        adapter_id=declared_id or _adapter_id_from_name(adapter_name),
        adapter_name=adapter_name,
        source_standard=source_standard,
        source_format=getattr(adapter, "source_format", source_standard),
        capabilities=tuple(
            getattr(adapter, "capabilities", DEFAULT_NETWORK_ADAPTER_CAPABILITIES)
        ),
        geographic_crs=getattr(adapter, "geographic_crs", None),
    )


def _adapter_id_from_name(adapter_name: str) -> str:
    name = adapter_name
    if name.endswith("Adapter"):
        name = name[: -len("Adapter")]
    chars: list[str] = []
    for index, char in enumerate(name):
        if char.isupper() and index > 0 and not name[index - 1].isupper():
            chars.append("_")
        chars.append(char.lower())
    return "".join(chars).strip("_")


def _validation_report_path(*, out_dir: Path, root: Path) -> Path:
    layout = ArtifactLayout(root)
    try:
        out_dir.resolve().relative_to(layout.base.resolve())
        return layout.reports / "network_adapter_validation_report.json"
    except ValueError:
        return out_dir / "network_adapter_validation_report.json"


def _config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(config, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _load_cache(cache_dir: Path) -> tuple[pp.pandapowerNet, PowerGridGraph]:
    with (cache_dir / "pp_net_cache.pkl").open("rb") as f:
        net = pickle.load(f)
    with (cache_dir / "pg_graph_cache.pkl").open("rb") as f:
        pg = pickle.load(f)
    return net, pg


def _coords_from_geo(geo: Any) -> tuple[float | None, float | None]:
    if pd.isna(geo):
        return None, None
    if isinstance(geo, str):
        try:
            data = json.loads(geo.replace("'", '"'))
            coords = data.get("coordinates", [None, None])
            # Existing source stores [latitude, longitude].
            return float(coords[0]), float(coords[1])
        except Exception:
            return None, None
    return None, None


def _bus_category(name: str, vn_kv: float) -> str:
    if name.startswith("lv_") or np.isclose(vn_kv, 0.4):
        return "LV"
    if name.startswith("mv_") or np.isclose(vn_kv, 25.0):
        return "MV"
    if name.startswith("hv_") or vn_kv >= 100.0:
        return "HV"
    return "UNKNOWN"


def _parse_building_idx(load_name: str) -> int:
    prefix = "Load_building_"
    if not load_name.startswith(prefix):
        raise ValueError(f"Unexpected load name format: {load_name}")
    return int(load_name.removeprefix(prefix))


def _make_bus_table(net: pp.pandapowerNet) -> pd.DataFrame:
    rows = []
    for bus_idx, row in net.bus.iterrows():
        name = str(row["name"])
        vn_kv = float(row["vn_kv"])
        lat, lon = _coords_from_geo(row.get("geo"))
        category = _bus_category(name, vn_kv)
        rows.append(
            {
                "bus_id": f"bus:{int(bus_idx)}",
                "pandapower_bus": int(bus_idx),
                "name": name,
                "voltage_kv": vn_kv,
                "category": category,
                "lat": lat,
                "lon": lon,
                "in_service": bool(row.get("in_service", True)),
                "cim_class": "ConnectivityNode",
            }
        )
    return pd.DataFrame(rows)


def _make_line_table(net: pp.pandapowerNet, buses: pd.DataFrame) -> pd.DataFrame:
    bus_lookup = buses.set_index("pandapower_bus")
    rows = []
    for line_idx, row in net.line.iterrows():
        from_bus = int(row["from_bus"])
        to_bus = int(row["to_bus"])
        from_name = str(bus_lookup.at[from_bus, "name"])
        category = _bus_category(
            from_name, float(bus_lookup.at[from_bus, "voltage_kv"])
        )
        rows.append(
            {
                "line_id": f"line:{int(line_idx)}",
                "pandapower_line": int(line_idx),
                "name": str(row["name"]),
                "from_bus_id": f"bus:{from_bus}",
                "to_bus_id": f"bus:{to_bus}",
                "length_km": float(row["length_km"]),
                "std_type": str(row["std_type"]),
                "max_i_ka": float(row["max_i_ka"]),
                "r_ohm_per_km": float(row["r_ohm_per_km"]),
                "x_ohm_per_km": float(row["x_ohm_per_km"]),
                "category": category,
                "in_service": bool(row.get("in_service", True)),
                "cim_class": "ACLineSegment",
            }
        )
    return pd.DataFrame(rows)


def _make_transformer_table(net: pp.pandapowerNet, buses: pd.DataFrame) -> pd.DataFrame:
    bus_lookup = buses.set_index("pandapower_bus")
    rows = []
    for trafo_idx, row in net.trafo.iterrows():
        hv_bus = int(row["hv_bus"])
        lv_bus = int(row["lv_bus"])
        hv_category = str(bus_lookup.at[hv_bus, "category"])
        lv_category = str(bus_lookup.at[lv_bus, "category"])
        rows.append(
            {
                "transformer_id": f"transformer:{int(trafo_idx)}",
                "pandapower_trafo": int(trafo_idx),
                "name": str(row["name"]),
                "std_type": str(row["std_type"]),
                "hv_bus_id": f"bus:{hv_bus}",
                "lv_bus_id": f"bus:{lv_bus}",
                "hv_category": hv_category,
                "lv_category": lv_category,
                "sn_mva": float(row["sn_mva"]),
                "vn_hv_kv": float(row["vn_hv_kv"]),
                "vn_lv_kv": float(row["vn_lv_kv"]),
                "vk_percent": float(row["vk_percent"]),
                "vkr_percent": float(row["vkr_percent"]),
                "tap_pos": (
                    None if pd.isna(row.get("tap_pos")) else float(row.get("tap_pos"))
                ),
                "in_service": bool(row.get("in_service", True)),
                "cim_class": "PowerTransformer",
            }
        )
    return pd.DataFrame(rows)


def _make_buildings_and_connectivity(
    net: pp.pandapowerNet,
    pg: PowerGridGraph,
    buses: pd.DataFrame,
    transformers: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    bus_lookup = buses.set_index("pandapower_bus")
    trafo_by_lv_bus = transformers.set_index("lv_bus_id")["transformer_id"].to_dict()
    building_data = pg.building_data.reset_index(drop=True)
    labels_lv = np.asarray(pg.labels_lv)

    buildings = []
    connectivity = []

    for load_idx, load_row in net.load.iterrows():
        building_idx = _parse_building_idx(str(load_row["name"]))
        bus_idx = int(load_row["bus"])
        bus_id = f"bus:{bus_idx}"
        lv_cluster = int(labels_lv[building_idx])
        lv_feeder_bus_name = f"lv_feeder_{lv_cluster}"
        feeder_bus = buses.loc[buses["name"] == lv_feeder_bus_name]
        lv_feeder_bus_id = None
        lv_transformer_id = None
        if not feeder_bus.empty:
            lv_feeder_bus_id = str(feeder_bus.iloc[0]["bus_id"])
            lv_transformer_id = trafo_by_lv_bus.get(lv_feeder_bus_id)

        source = (
            building_data.iloc[building_idx]
            if building_idx < len(building_data)
            else {}
        )
        area_m2 = source.get("Area (sq. meters)") if hasattr(source, "get") else None
        source_building_id = (
            source.get("Building ID") if hasattr(source, "get") else None
        )
        lat = (
            source.get("Latitude")
            if hasattr(source, "get")
            else bus_lookup.at[bus_idx, "lat"]
        )
        lon = (
            source.get("Longitude")
            if hasattr(source, "get")
            else bus_lookup.at[bus_idx, "lon"]
        )

        building_id = f"building:{building_idx}"
        load_id = f"load:{int(load_idx)}"
        buildings.append(
            {
                "building_id": building_id,
                "source_building_id": (
                    None if pd.isna(source_building_id) else int(source_building_id)
                ),
                "load_id": load_id,
                "pandapower_load": int(load_idx),
                "lv_bus_id": bus_id,
                "lat": None if pd.isna(lat) else float(lat),
                "lon": None if pd.isna(lon) else float(lon),
                "area_m2": None if pd.isna(area_m2) else float(area_m2),
                "static_p_mw": float(load_row["p_mw"]),
                "static_q_mvar": float(load_row["q_mvar"]),
                "load_seed_base": 42 + building_idx,
                "thermal_seed_base": 42 + building_idx,
                "scenario_id": "BASE",
                "ontology_class": "Building",
            }
        )
        connectivity.append(
            {
                "building_id": building_id,
                "load_id": load_id,
                "load_bus_id": bus_id,
                "lv_cluster": lv_cluster,
                "lv_feeder_bus_id": lv_feeder_bus_id,
                "lv_transformer_id": lv_transformer_id,
                "connectivity_status": (
                    "ok" if lv_transformer_id is not None else "missing_transformer"
                ),
            }
        )

    return pd.DataFrame(buildings), pd.DataFrame(connectivity)
