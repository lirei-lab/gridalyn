"""Declared column contract for the canonical base network artifacts.

This module is the **single** place the base tables' columns are declared. The
repository resolves every column through it instead of guessing at read time,
which is what lets ``validate_integrity`` tell an *absent* artifact from an
*intact* one: without a declaration, "no file" and "no rows" are the same
observation.

**Why Python and not JSON Schema.** ``gridalyn/projects/schemas/*.json`` is the
repo's JSON-Schema precedent, and it earns its keep there: those schemas
validate *user-authored* YAML, where a language-neutral, quotable schema is the
point. This contract validates *machine-produced* parquet frames, and its two
load-bearing ideas -- an **ordered alias set** per column role, and **which
columns reference the bus table** -- have no JSON Schema vocabulary; they would
become convention encoded in custom keys, i.e. guessing moved one level up.
Declaring it as a module also makes the Phase-2 packaging defect structurally
impossible: a ``.py`` file ships under ``include = ["gridalyn*"]``, so it can
never be resolved at runtime from a wheel that does not contain it, and no
``[tool.setuptools.package-data]`` entry or installed-layout gate is needed.

**Alias sets are evidence, not tolerance.** Every spelling listed below is
written by an in-repo producer or a committed artifact; spellings that no
producer writes were dropped rather than carried forward as defensive noise.
See the plan 11-03 report for the producer-by-producer measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd

from gridalyn.twin.network.model import BASE_TABLE_FILENAMES

GRID_BUSES = "grid_buses"
GRID_LINES = "grid_lines"
GRID_TRANSFORMERS = "grid_transformers"
BUILDINGS = "buildings"
BUILDING_GRID_CONNECTIVITY = "building_grid_connectivity"

ROLE_IDENTITY = "identity"
ROLE_BUS = "bus"
ROLE_FROM_BUS = "from_bus"
ROLE_TO_BUS = "to_bus"
ROLE_HV_BUS = "hv_bus"
ROLE_LV_BUS = "lv_bus"
ROLE_LOAD = "load"
ROLE_TRANSFORMER = "transformer"
ROLE_FEEDER = "feeder"
ROLE_FEEDER_HEAD_BUS = "feeder_head_bus"
ROLE_FEEDER_CLUSTER = "feeder_cluster"
ROLE_LATITUDE = "latitude"
ROLE_LONGITUDE = "longitude"

ColumnDtype = Literal["string", "integer"]


@dataclass(frozen=True)
class ColumnSpec:
    """One column of a canonical base table, declared by the role it plays.

    Attributes:
        role: What the column *is* to a consumer -- the table's own identity,
            the bus it hangs off, the transformer that feeds it. Queries ask
            for a role, never for a spelling.
        spellings: Accepted column names **in resolution order**. More than one
            entry means different in-repo producers genuinely write different
            names for the same role; the first present spelling wins, and that
            order is behaviour, not decoration.
        dtype: Declared value type. ``"string"`` for identifiers, which are
            compared with ``astype(str)`` on both sides; ``"integer"`` for
            producer-local numeric labels.
        required: Whether a non-empty frame must carry one of ``spellings``.
            Only set where **every** in-repo producer writes the column.
        references: Canonical artifact whose identity column this column points
            at, or ``None``. Drives the bus-endpoint integrity check, which
            needs the *union* of bus-referencing columns rather than a single
            resolved one.
    """

    role: str
    spellings: tuple[str, ...]
    dtype: ColumnDtype = "string"
    required: bool = False
    references: str | None = None

    @property
    def canonical(self) -> str:
        """Return the preferred spelling, used when naming the column in errors."""
        return self.spellings[0]


@dataclass(frozen=True)
class TableSchema:
    """The declared column contract for one canonical base artifact.

    Attributes:
        artifact: Canonical artifact name, a key of
            :data:`gridalyn.twin.network.model.BASE_TABLE_FILENAMES`.
        columns: Declared columns, in the order the bus-endpoint check should
            visit them.
    """

    artifact: str
    columns: tuple[ColumnSpec, ...]

    @property
    def filename(self) -> str:
        """Return the on-disk file name, single-sourced from the model module."""
        return BASE_TABLE_FILENAMES[self.artifact]

    @property
    def roles(self) -> tuple[str, ...]:
        """Return every declared role, in declaration order."""
        return tuple(column.role for column in self.columns)

    def spec(self, role: str) -> ColumnSpec:
        """Return the column declared for ``role``.

        Args:
            role: One of :attr:`roles`.

        Returns:
            The declared :class:`ColumnSpec`.

        Raises:
            ValueError: If ``role`` is not declared for this table.
        """
        for column in self.columns:
            if column.role == role:
                return column
        raise ValueError(
            f"{self.filename}: no column declared for role {role!r} "
            f"(declared roles: {', '.join(self.roles)}); add it to "
            f"gridalyn.twin.network.schema.BASE_TABLE_SCHEMAS[{self.artifact!r}] "
            "rather than reading the column directly"
        )

    def spellings(self, role: str) -> tuple[str, ...]:
        """Return the accepted spellings for ``role``, in resolution order."""
        return self.spec(role).spellings

    def resolve(self, frame: pd.DataFrame, role: str) -> str | None:
        """Return the first declared spelling of ``role`` present in ``frame``.

        Args:
            frame: Loaded table to resolve against.
            role: Declared role to resolve.

        Returns:
            The column name to read, or ``None`` when the frame carries none of
            the declared spellings.
        """
        columns = set(frame.columns)
        return next(
            (name for name in self.spellings(role) if name in columns),
            None,
        )

    def require(self, frame: pd.DataFrame, role: str, *, path: Path) -> str:
        """Resolve ``role`` in ``frame`` or raise a located, remediating error.

        Args:
            frame: Loaded table to resolve against.
            role: Declared role to resolve.
            path: On-disk path of ``frame``, used to locate the failure.

        Returns:
            The column name to read.

        Raises:
            ValueError: If the frame carries none of the declared spellings.
        """
        return self.require_any(frame, (role,), path=path)

    def require_any(
        self,
        frame: pd.DataFrame,
        roles: tuple[str, ...],
        *,
        path: Path,
    ) -> str:
        """Resolve the first of ``roles`` present in ``frame``, or raise.

        Args:
            frame: Loaded table to resolve against.
            roles: Declared roles to try, in resolution order. More than one
                role means the concept is spelled across roles that differ in
                kind -- a feeder is keyed by an identifier or, failing that, by
                a producer-local integer cluster label.
            path: On-disk path of ``frame``, used to locate the failure.

        Returns:
            The column name to read.

        Raises:
            ValueError: If the frame carries none of the declared spellings.
        """
        for role in roles:
            column = self.resolve(frame, role)
            if column is not None:
                return column
        declared = dict.fromkeys(
            name for role in roles for name in self.spellings(role)
        )
        raise ValueError(
            f"{path}: {self.artifact} carries no {'/'.join(roles)} column; the "
            f"declared spellings are {', '.join(declared)} "
            f"(present columns: {_present_columns(frame)}); rebuild the base "
            "with `gridalyn twin base`, or export it through a source adapter "
            "that writes the declared contract"
        )

    def reference_spellings(self, target: str) -> tuple[str, ...]:
        """Return every spelling of every column that points at ``target``.

        The bus-endpoint check needs the union rather than a single resolved
        column: a connectivity row can name both the bus its load sits on and
        the head of its LV feeder, and both must resolve to a real bus.

        Args:
            target: Canonical artifact name the columns reference.

        Returns:
            Spellings in declaration order, deduplicated.
        """
        names: list[str] = []
        for column in self.columns:
            if column.references != target:
                continue
            names.extend(name for name in column.spellings if name not in names)
        return tuple(names)

    def absent_required_roles(self, frame: pd.DataFrame) -> tuple[str, ...]:
        """Return the canonical spelling of every required role ``frame`` lacks.

        Args:
            frame: Loaded table to check. An empty frame is *not* checked here;
                an empty frame carries no columns at all, and "present but
                empty" is a distinct outcome the caller reports separately.

        Returns:
            Canonical spellings of the required roles that resolve to nothing.
        """
        return tuple(
            column.canonical
            for column in self.columns
            if column.required and self.resolve(frame, column.role) is None
        )


def _present_columns(frame: pd.DataFrame) -> str:
    """Render a frame's columns for an error message, or say there are none."""
    if len(frame.columns) == 0:
        return "none"
    return ", ".join(str(name) for name in frame.columns)


BASE_TABLE_SCHEMAS: dict[str, TableSchema] = {
    GRID_BUSES: TableSchema(
        artifact=GRID_BUSES,
        columns=(
            ColumnSpec(ROLE_IDENTITY, ("bus_id",), required=True),
            # One spelling each. Both in-repo producers -- SyntheticPandapower
            # Adapter and CimParquetAdapter -- write `lat`/`lon`; the
            # `latitude`/`longitude` pair in the CIM adapter is an alias it
            # *reads* off the source frame, never one it writes, so carrying it
            # here would be tolerance rather than evidence.
            #
            # Deliberately not required: an electrical model is complete
            # without geography, and `validate_integrity` should not start
            # failing a base that never claimed to be located. Absent
            # coordinates are reported by `resolve_network_geography` as an
            # unlocated model, which is a different statement from an invalid
            # one.
            ColumnSpec(ROLE_LATITUDE, ("lat",)),
            ColumnSpec(ROLE_LONGITUDE, ("lon",)),
        ),
    ),
    GRID_LINES: TableSchema(
        artifact=GRID_LINES,
        columns=(
            ColumnSpec(ROLE_IDENTITY, ("line_id",), required=True),
            ColumnSpec(
                ROLE_FROM_BUS, ("from_bus_id",), required=True, references=GRID_BUSES
            ),
            ColumnSpec(
                ROLE_TO_BUS, ("to_bus_id",), required=True, references=GRID_BUSES
            ),
        ),
    ),
    GRID_TRANSFORMERS: TableSchema(
        artifact=GRID_TRANSFORMERS,
        columns=(
            ColumnSpec(ROLE_IDENTITY, ("transformer_id",), required=True),
            ColumnSpec(
                ROLE_HV_BUS, ("hv_bus_id",), required=True, references=GRID_BUSES
            ),
            ColumnSpec(
                ROLE_LV_BUS, ("lv_bus_id",), required=True, references=GRID_BUSES
            ),
        ),
    ),
    BUILDINGS: TableSchema(
        artifact=BUILDINGS,
        columns=(
            ColumnSpec(ROLE_IDENTITY, ("building_id",), required=True),
            ColumnSpec(ROLE_LOAD, ("load_id",), required=True),
            # Truthfully a bus reference, but *not* endpoint-checked today:
            # `validate_integrity` checks lines, transformers and connectivity
            # only, and widening that set would be a behaviour change outside
            # plan 11-03. Declaring it honestly is still right -- the repository
            # reads these spellings for `get_connected_equipment`.
            ColumnSpec(
                ROLE_BUS,
                ("lv_bus_id", "load_bus_id", "bus_id"),
                references=GRID_BUSES,
            ),
            # Building POINTS, not footprints. The GeoJSON ingest starts from
            # Polygon/MultiPolygon features (`PowerGridGraph.extract_building_
            # centers_and_areas` filters on exactly that), but only the
            # centroid and the area survive into this table. A consumer that
            # wants footprints must go back to the source layer; nothing
            # downstream of the base snapshot can reconstruct them.
            ColumnSpec(ROLE_LATITUDE, ("lat",)),
            ColumnSpec(ROLE_LONGITUDE, ("lon",)),
        ),
    ),
    BUILDING_GRID_CONNECTIVITY: TableSchema(
        artifact=BUILDING_GRID_CONNECTIVITY,
        columns=(
            ColumnSpec(ROLE_IDENTITY, ("building_id",), required=True),
            ColumnSpec(ROLE_LOAD, ("load_id",), required=True),
            ColumnSpec(
                ROLE_BUS,
                ("load_bus_id", "lv_bus_id", "bus_id"),
                required=True,
                references=GRID_BUSES,
            ),
            # One spelling only: both in-repo producers -- SyntheticPandapower
            # Adapter and CimParquetAdapter -- write `lv_transformer_id`, and
            # neither writes `transformer_id` or `constraint_zone_id`.
            ColumnSpec(ROLE_TRANSFORMER, ("lv_transformer_id",)),
            # A real producer split: CimParquetAdapter writes `feeder_id`,
            # SyntheticPandapowerAdapter writes `lv_feeder_bus_id` plus the
            # integer `lv_cluster` label it was derived from. All three are kept
            # and the resolution order is the historical one.
            ColumnSpec(ROLE_FEEDER, ("feeder_id", "lv_feeder_bus_id")),
            ColumnSpec(
                ROLE_FEEDER_HEAD_BUS, ("lv_feeder_bus_id",), references=GRID_BUSES
            ),
            ColumnSpec(ROLE_FEEDER_CLUSTER, ("lv_cluster",), dtype="integer"),
        ),
    ),
}

FEEDER_QUERY_ROLES: tuple[str, ...] = (ROLE_FEEDER, ROLE_FEEDER_CLUSTER)
"""Roles ``get_feeder`` resolves, in order.

``lv_cluster`` is a producer-local integer label rather than an identifier, so
it is declared as its own role and consulted last -- which is exactly the
historical fallback order ``feeder_id``, ``lv_feeder_bus_id``, ``lv_cluster``.
"""


def table_schema(artifact: str) -> TableSchema:
    """Return the declared contract for a canonical base artifact.

    Args:
        artifact: Canonical artifact name, e.g. ``"building_grid_connectivity"``.

    Returns:
        The declared :class:`TableSchema`.

    Raises:
        ValueError: If ``artifact`` is not a canonical base artifact.
    """
    try:
        return BASE_TABLE_SCHEMAS[artifact]
    except KeyError:
        raise ValueError(
            f"unknown base artifact {artifact!r} "
            f"(declared: {', '.join(sorted(BASE_TABLE_SCHEMAS))})"
        ) from None


def declared_filenames() -> tuple[str, ...]:
    """Return every declared base artifact file name, sorted."""
    return tuple(sorted(schema.filename for schema in BASE_TABLE_SCHEMAS.values()))
