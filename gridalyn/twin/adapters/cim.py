"""CIM-like Parquet source adapter, and the repository's CGMES semantics.

The CGMES parts this repository adopts — ``FullModel`` identity (plan 11-01),
**Model Authority Sets** and **profile declarations** (this module) — are
adopted as *fields and rules over parquet*, never as a serialization format.
There is no RDF/XML writer here and no graph library is imported.

Phase 9 deleted ``gridalyn/twin/io/cim.py`` because it was a dead RDF/XML
exporter with zero importers and zero tests, and dropped ``rdflib`` because
that exporter was its only consumer. The reasoning was *"no consumer"*, not
*"CIM is wrong"*. The declarations below therefore have a real consumer: they
are validated on **every** :meth:`CimParquetAdapter.load_snapshot`, not
written once and forgotten. ``tests/test_cim_dependency_policy.py`` pins the
resulting dependency posture — real ``rdflib`` imports under ``gridalyn/`` are
0, proven by an AST scan rather than a text grep.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from gridalyn.twin.adapters.network import (
    DEFAULT_NETWORK_ADAPTER_CAPABILITIES,
    NetworkAdapterDescriptor,
    NetworkExportResult,
    describe_network_source_adapter,
)
from gridalyn.twin.adapters.validation import write_network_adapter_validation_report
from gridalyn.twin.network.metadata import (
    BASE_METADATA_SCHEMA_VERSION,
    write_base_metadata,
)
from gridalyn.twin.network.model import (
    BASE_PROFILE_ID,
    BASE_TABLE_FILENAMES,
    NetworkModel,
)
from gridalyn.twin.network.schema import table_schema

CIM_PARQUET_TABLES = {
    "connectivity_nodes": "connectivity_nodes.parquet",
    "ac_line_segments": "ac_line_segments.parquet",
    "power_transformers": "power_transformers.parquet",
    "energy_consumers": "energy_consumers.parquet",
}

CANONICAL_ARTIFACTS: tuple[str, ...] = tuple(BASE_TABLE_FILENAMES)
"""The canonical base artifacts an authority-set partition must cover exactly.

Single-sourced from :data:`gridalyn.twin.network.model.BASE_TABLE_FILENAMES`,
so declaring a sixth canonical table leaves every partition incomplete until an
owner is declared for it. That drift is what :func:`validate_authority_partition`
exists to catch.
"""

AUTHORITY_SET_PARTITION_IS_SINGLE_MEMBER = (
    "Measured 2026-08-12 against every in-repo producer: the two classes that "
    "define load_snapshot -- SyntheticPandapowerAdapter and CimParquetAdapter "
    "-- each produce all five canonical artifacts (3626/3430/195/3235/3235 and "
    "2/1/1/1/1 rows respectively), neither produces a proper subset, and "
    "export_base_twin selects exactly one of them per model. gridalyn/twin/"
    "geoprocess/ produces no canonical artifact at all: its building footprints "
    "reach the model as an *input* to PowerGridGraph.building_data, inside the "
    "synthetic authority set, not beside it. The partition of any model is "
    "therefore a SINGLE member owning all five artifacts. The multi-member case "
    "this mechanism supports is UNTESTED against a real second owner."
)


class UnknownModelAuthoritySetError(KeyError):
    """Raised when no Model Authority Set is declared for a producer."""


class UnknownModelProfileError(KeyError):
    """Raised when a requested model profile is not declared."""


@dataclass(frozen=True)
class ModelAuthoritySet:
    """A CGMES Model Authority Set expressed over the canonical parquet tables.

    In CGMES a Model Authority Set is the disjoint set of objects one party
    owns, so an interconnection model can be assembled from parts with
    different owners. Here the "objects" are canonical base artifacts and the
    "party" is the source adapter that produced them.

    Attributes:
        authority_set_id: Stable identifier, the CGMES ``Model.modelingAuthority
            Set`` analogue. Never derived from a class name at run time, so
            renaming a class cannot silently repartition a model.
        authority: Name of the party that owns the artifacts -- the producing
            adapter class.
        adapter_id: Stable adapter ID this set is keyed by, matching
            ``metadata.json``'s ``adapter_id`` and the network adapter registry.
        source_standard: Source data standard the authority publishes in.
        artifacts: Canonical artifacts this authority owns. Must be a subset of
            :data:`CANONICAL_ARTIFACTS`; the partition as a whole must cover it
            exactly and without overlap.
    """

    authority_set_id: str
    authority: str
    adapter_id: str
    source_standard: str
    artifacts: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """Render the set as JSON-native values.

        Returns:
            A mapping of ``str`` keys to ``str``/``list[str]`` values only, so
            it serializes with :func:`json.dumps` without a custom encoder and
            can land in a manifest as-is.
        """
        return {
            "authority_set_id": self.authority_set_id,
            "authority": self.authority,
            "adapter_id": self.adapter_id,
            "source_standard": self.source_standard,
            "artifacts": list(self.artifacts),
        }


MODEL_AUTHORITY_SETS: dict[str, ModelAuthoritySet] = {
    "synthetic_pandapower": ModelAuthoritySet(
        authority_set_id="gridalyn:mas:synthetic-pandapower",
        authority="SyntheticPandapowerAdapter",
        adapter_id="synthetic_pandapower",
        source_standard="pandapower",
        artifacts=CANONICAL_ARTIFACTS,
    ),
    "cim_parquet": ModelAuthoritySet(
        authority_set_id="gridalyn:mas:cim-parquet",
        authority="CimParquetAdapter",
        adapter_id="cim_parquet",
        source_standard="cim",
        artifacts=CANONICAL_ARTIFACTS,
    ),
}
"""Every declared Model Authority Set, keyed by producing ``adapter_id``.

These are **alternatives**, not co-owners: a model is produced by one adapter,
so :func:`authority_set_partition` returns exactly one of them. See
:data:`AUTHORITY_SET_PARTITION_IS_SINGLE_MEMBER` for the measurement behind
that, and for what is consequently untested.
"""


def model_authority_set(adapter_id: str) -> ModelAuthoritySet:
    """Return the Model Authority Set declared for a producing adapter.

    Args:
        adapter_id: Stable adapter ID, e.g. ``"cim_parquet"``.

    Returns:
        The declared :class:`ModelAuthoritySet`.

    Raises:
        UnknownModelAuthoritySetError: If no set is declared for ``adapter_id``.
    """
    try:
        return MODEL_AUTHORITY_SETS[adapter_id]
    except KeyError:
        declared = ", ".join(sorted(MODEL_AUTHORITY_SETS)) or "none declared"
        raise UnknownModelAuthoritySetError(
            f"no Model Authority Set declared for adapter {adapter_id!r} "
            f"(declared: {declared}); add one to "
            "gridalyn.twin.adapters.cim.MODEL_AUTHORITY_SETS, or export the "
            "model through an adapter that already declares one"
        ) from None


def authority_set_partition(adapter_id: str) -> tuple[ModelAuthoritySet, ...]:
    """Return the authority-set partition of a model produced by one adapter.

    Args:
        adapter_id: Stable adapter ID of the producing adapter.

    Returns:
        The sets that partition that model. Measured today this is always a
        one-tuple -- see :data:`AUTHORITY_SET_PARTITION_IS_SINGLE_MEMBER`.

    Raises:
        UnknownModelAuthoritySetError: If no set is declared for ``adapter_id``.
    """
    return (model_authority_set(adapter_id),)


def validate_authority_partition(
    authority_sets: Sequence[ModelAuthoritySet],
    *,
    adapter_id: str,
) -> None:
    """Check that ``authority_sets`` partition the canonical artifacts exactly.

    This is the rule the CGMES adoption exists for, and it runs on every
    :meth:`CimParquetAdapter.load_snapshot` rather than at export time only.

    Args:
        authority_sets: Declared sets to check.
        adapter_id: Producing adapter, used to locate the failure.

    Raises:
        ValueError: If any artifact is owned twice, owned by nobody, or is not
            a canonical base artifact.
    """
    problems = _partition_problems(authority_sets)
    if not problems:
        return
    declared = ", ".join(item.authority_set_id for item in authority_sets) or "none"
    raise ValueError(
        f"adapter {adapter_id!r}: declared Model Authority Sets ({declared}) do "
        f"not partition the canonical base artifacts: {'; '.join(problems)} "
        f"(canonical artifacts: {', '.join(CANONICAL_ARTIFACTS)}); fix the "
        "`artifacts` tuples in gridalyn.twin.adapters.cim.MODEL_AUTHORITY_SETS "
        "so every canonical artifact has exactly one owner"
    )


def _partition_problems(authority_sets: Sequence[ModelAuthoritySet]) -> list[str]:
    """Return one message per partition defect, or an empty list when clean."""
    owned: dict[str, str] = {}
    problems: list[str] = []
    for authority_set in authority_sets:
        for artifact in authority_set.artifacts:
            problem = _claim_artifact(owned, authority_set, artifact)
            if problem is not None:
                problems.append(problem)
    problems.extend(
        f"{artifact!r} has no declared owner"
        for artifact in CANONICAL_ARTIFACTS
        if artifact not in owned
    )
    return problems


def _claim_artifact(
    owned: dict[str, str],
    authority_set: ModelAuthoritySet,
    artifact: str,
) -> str | None:
    """Record one artifact claim in ``owned``, or describe why it is invalid."""
    if artifact not in CANONICAL_ARTIFACTS:
        return (
            f"{authority_set.authority_set_id} claims {artifact!r}, "
            "which is not a canonical base artifact"
        )
    if artifact in owned:
        return (
            f"{artifact!r} is claimed by both {owned[artifact]} and "
            f"{authority_set.authority_set_id}"
        )
    owned[artifact] = authority_set.authority_set_id
    return None


@dataclass(frozen=True)
class ModelProfile:
    """A CGMES profile declaration over the canonical base artifacts.

    A CGMES profile composes the dataset exchanged for one purpose, and
    ``dependentOn`` names the profiles it cannot be read without. Here the
    analogue is a canonical artifact set, and the dependencies are **derived**
    from :data:`gridalyn.twin.network.schema.BASE_TABLE_SCHEMAS` -- a profile
    depends on another exactly when one of its declared columns ``references``
    that artifact. Nothing here is hand-declared, so a dependency cannot be
    invented and cannot go stale against the schema.

    Attributes:
        profile_id: Stable identifier, e.g.
            ``"gridalyn:digital-twin-base/grid_lines"``.
        version: Manifest schema version the profile is declared against.
        artifacts: Canonical artifacts the profile carries.
        depends_on: Profile IDs this profile cannot be read without. Every entry
            is a key of :data:`BASE_MODEL_PROFILES`.
    """

    profile_id: str
    version: str
    artifacts: tuple[str, ...]
    depends_on: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """Render the profile as JSON-native values.

        Returns:
            A mapping of ``str`` keys to ``str``/``list[str]`` values only, so
            it serializes with :func:`json.dumps` without a custom encoder.
        """
        return {
            "profile_id": self.profile_id,
            "version": self.version,
            "artifacts": list(self.artifacts),
            "dependent_on": list(self.depends_on),
        }


def _artifact_profile_id(artifact: str) -> str:
    """Return the profile ID that carries a single canonical artifact."""
    return f"{BASE_PROFILE_ID}/{artifact}"


def _artifact_profile_dependencies(artifact: str) -> tuple[str, ...]:
    """Derive one artifact's profile dependencies from the declared schema."""
    referenced = dict.fromkeys(
        column.references
        for column in table_schema(artifact).columns
        if column.references is not None and column.references != artifact
    )
    return tuple(_artifact_profile_id(target) for target in referenced)


def _build_base_model_profiles() -> dict[str, ModelProfile]:
    """Build the base profile set: one per artifact, plus the composed root."""
    profiles: dict[str, ModelProfile] = {}
    for artifact in CANONICAL_ARTIFACTS:
        profile_id = _artifact_profile_id(artifact)
        profiles[profile_id] = ModelProfile(
            profile_id=profile_id,
            version=BASE_METADATA_SCHEMA_VERSION,
            artifacts=(artifact,),
            depends_on=_artifact_profile_dependencies(artifact),
        )
    profiles[BASE_PROFILE_ID] = ModelProfile(
        profile_id=BASE_PROFILE_ID,
        version=BASE_METADATA_SCHEMA_VERSION,
        artifacts=CANONICAL_ARTIFACTS,
        depends_on=tuple(_artifact_profile_id(a) for a in CANONICAL_ARTIFACTS),
    )
    return profiles


BASE_MODEL_PROFILES: dict[str, ModelProfile] = _build_base_model_profiles()
"""Declared profiles for the canonical base, keyed by ``profile_id``.

The root :data:`gridalyn.twin.network.model.BASE_PROFILE_ID` profile composes
the five per-artifact profiles; each per-artifact profile's ``dependent_on`` is
derived from the column ``references`` declared in
:mod:`gridalyn.twin.network.schema`.
"""


def model_profile(profile_id: str) -> ModelProfile:
    """Return a declared model profile.

    Args:
        profile_id: A key of :data:`BASE_MODEL_PROFILES`.

    Returns:
        The declared :class:`ModelProfile`.

    Raises:
        UnknownModelProfileError: If ``profile_id`` is not declared.
    """
    try:
        return BASE_MODEL_PROFILES[profile_id]
    except KeyError:
        declared = ", ".join(sorted(BASE_MODEL_PROFILES)) or "none declared"
        raise UnknownModelProfileError(
            f"unknown model profile {profile_id!r} (declared: {declared}); "
            "profiles are derived from "
            "gridalyn.twin.network.schema.BASE_TABLE_SCHEMAS, so declare the "
            "artifact's schema rather than adding a profile by hand"
        ) from None


@dataclass(frozen=True)
class CimParquetAdapter:
    """Adapter from CIM-like Parquet tables to canonical base Parquet."""

    source_dir: Path
    adapter_id: str = "cim_parquet"
    source_adapter: str = "CimParquetAdapter"
    source_standard: str = "cim"
    source_format: str = "cim-parquet"
    capabilities: tuple[str, ...] = DEFAULT_NETWORK_ADAPTER_CAPABILITIES

    def describe(self) -> NetworkAdapterDescriptor:
        """Return stable adapter identity and capability metadata."""
        return describe_network_source_adapter(self)

    def authority_sets(self) -> tuple[ModelAuthoritySet, ...]:
        """Return the Model Authority Sets partitioning models this produces.

        Returns:
            The declared partition. Measured today it has exactly one member --
            see :data:`AUTHORITY_SET_PARTITION_IS_SINGLE_MEMBER`.

        Raises:
            UnknownModelAuthoritySetError: If this adapter declares no set.
        """
        return authority_set_partition(self.adapter_id)

    def profiles(self) -> tuple[ModelProfile, ...]:
        """Return the declared profiles of the base this adapter exports.

        Returns:
            Every profile in :data:`BASE_MODEL_PROFILES`, ordered by profile ID.
        """
        return tuple(BASE_MODEL_PROFILES[key] for key in sorted(BASE_MODEL_PROFILES))

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
            adapter_validation_report=out_dir
            / "network_adapter_validation_report.json",
            notes=self._export_notes(),
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
        )

    def _export_notes(self) -> list[str]:
        """Build the manifest provenance notes, including the CGMES posture.

        The authority-set and profile lines are rendered from the declarations
        themselves rather than retyped, so a manifest cannot describe a
        partition the code does not declare. ``notes`` is a ``list[str]``
        contract owned by ``twin/network/metadata.py``; the JSON-native
        :meth:`ModelAuthoritySet.as_dict` payload has no manifest field to land
        in yet, which is recorded as a hand-off rather than forced into prose.

        Returns:
            Provenance note lines, recorded verbatim in ``metadata.json``.
        """
        root = BASE_MODEL_PROFILES[BASE_PROFILE_ID]
        owners = ", ".join(
            f"{item.authority_set_id} owns {'/'.join(item.artifacts)}"
            for item in self.authority_sets()
        )
        return [
            "Source tables use a CIM-like Parquet interchange profile.",
            "This adapter does not parse CIM RDF/XML.",
            f"CGMES Model Authority Sets: {owners}.",
            f"CGMES profile: {root.profile_id}:{root.version}, dependent on "
            f"{', '.join(root.depends_on)}.",
            AUTHORITY_SET_PARTITION_IS_SINGLE_MEMBER,
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
