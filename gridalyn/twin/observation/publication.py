"""Whether this deployment is a digital shadow, and how a consumer can tell.

``gridalyn.twin`` is a canonical, identified, schema-declared digital *model*.
It becomes a digital **shadow** for a given deployment when that deployment's
operator feeds it their own measured data through
:mod:`gridalyn.twin.observation.ingest`. :attr:`NetworkObservation.provenance`
is where that distinction lives inside the contract -- a required field, so no
producer can leave the question unanswered.

Outside the contract, nothing answered it. The dashboard read scenario
timeseries and nothing else; the catalog named no observation artifact; and no
rendered number said where it came from. A deployment fed real data had no way
to show it, and a deployment fed none looked exactly the same.

This module resolves the answer from the instance on disk, and it answers even
when the answer is "no". That is deliberate and is the difference from
:mod:`gridalyn.twin.semantic.publication`, whose block is *absent* for a twin
with no ontology: "this twin publishes no ontology" is a fact about what was
built, but "is anything here measured?" is a question every consumer must be
able to ask of every instance. Omitting the key would make "no measured data"
and "this catalog is too old to say" the same observation.

**What the SDK ships is the path, not the data.** No instance in this
repository carries measured observations, and none should: the measurements
belong to whoever operates the observed system.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

from gridalyn.twin.observation.contract import ObservationProvenance
from gridalyn.twin.observation.ingest import (
    JOIN_COLUMNS,
    MEASUREMENT_COLUMNS,
    SUPPORTED_QUANTITIES,
)

#: Provenance of a value read from a solved network -- what every artifact this
#: repository ships carries.
PROVENANCE_SIMULATED = "simulated"

#: Provenance of a value ingested from a deployment's own measurements.
PROVENANCE_MEASURED = "measured"

#: The contract's full provenance set, DERIVED from
#: :data:`~gridalyn.twin.observation.contract.ObservationProvenance` rather
#: than restated, so a third provenance added to the contract reaches the
#: catalog without this module being edited -- and cannot silently disagree
#: with the field it describes. Published so a client renders the distinction
#: from the twin's vocabulary rather than from its own.
PROVENANCE_VALUES: tuple[str, ...] = get_args(ObservationProvenance)

#: Base name of the declared entity-to-bus join inside an observations
#: directory. The join is user-supplied configuration the ingest refuses to
#: infer, so it is named rather than discovered: a file that is not this one is
#: a measurement export, and a directory with exports but no join is reported
#: as incomplete instead of silently half-read.
ENTITY_JOIN_STEM = "entity_join"

#: Suffixes :func:`gridalyn.twin.observation.ingest.load_measurements` reads.
MEASUREMENT_SUFFIXES: tuple[str, ...] = (".csv", ".parquet")

#: Why an instance carries no measured observations. Held as a constant so the
#: reason travels with the value rather than living only in a docstring.
MEASURED_ABSENT_REASON = (
    "this instance carries no measured observations; the SDK ships the ingest "
    "path, not measured data -- place tidy measurement exports and the "
    f"declared {ENTITY_JOIN_STEM} in the observations directory named here to "
    "feed a deployment's own AMI/SCADA data through "
    "gridalyn.twin.observation.ingest, which is what makes a deployment a "
    "digital shadow rather than a model"
)

#: Why measurement exports are present but unusable. Distinct from
#: :data:`MEASURED_ABSENT_REASON`: telling an operator to add data they have
#: already added would be the wrong remedy.
JOIN_ABSENT_REASON = (
    "measurement exports are present but no entity join is declared beside "
    f"them; add {ENTITY_JOIN_STEM}.csv (or .parquet) with columns "
    f"{', '.join(JOIN_COLUMNS)} -- which measured entity sits on which bus is "
    "a fact only the operator knows, and the ingest refuses to invent it"
)


@dataclass(frozen=True)
class ObservationPublication:
    """What a consumer needs in order to say where a number came from.

    Attributes:
        measured_sources: Measurement exports found, in sorted order. Empty
            when the instance carries none.
        entity_join: The declared entity-to-bus join, or ``None``.
        directory: Where measured observations are read from, whether or not
            any are there. Named even when absent, so "there are none" is
            distinguishable from "I looked somewhere else".
    """

    measured_sources: tuple[Path, ...]
    entity_join: Path | None
    directory: Path

    @property
    def available(self) -> bool:
        """Whether this instance can be observed as a shadow.

        Both halves are required: exports without the declared join cannot be
        ingested at all, because the ingest refuses to infer which entity sits
        on which bus.
        """
        return bool(self.measured_sources) and self.entity_join is not None

    @property
    def absent_reason(self) -> str | None:
        """Why there is no measured state, or ``None`` when there is."""
        if self.available:
            return None
        if self.measured_sources:
            return JOIN_ABSENT_REASON
        return MEASURED_ABSENT_REASON

    @property
    def provenance(self) -> str:
        """Provenance of what a consumer renders for this instance today.

        ``"measured"`` only once measured observations are actually ingestible.
        Everything this repository ships is ``"simulated"``, and saying so is
        the point: a number from a solved scenario and a number from a meter
        must not look identical.
        """
        return PROVENANCE_MEASURED if self.available else PROVENANCE_SIMULATED

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-native payload for a catalog or report."""
        return {
            "provenance": self.provenance,
            "provenance_values": list(PROVENANCE_VALUES),
            "measured": {
                "available": self.available,
                "absent_reason": self.absent_reason,
                # The contract the exports must satisfy, published so an
                # operator reads it off the catalog rather than off the source.
                "columns": list(MEASUREMENT_COLUMNS),
                "quantities": sorted(SUPPORTED_QUANTITIES),
                "join_columns": list(JOIN_COLUMNS),
            },
        }


def resolve_observation_publication(
    observations_dir: Path | str,
) -> ObservationPublication:
    """Resolve an instance's measured-state surface from its directory.

    Args:
        observations_dir: Where this instance's measured observations are read
            from. A directory that does not exist is not an error -- it is the
            normal state of every instance this repository ships.

    Returns:
        The resolved :class:`ObservationPublication`. Never raises: an
        unreadable or absent directory resolves to "no measured observations",
        which is a legitimate deployment, not a failure.
    """
    directory = Path(observations_dir)
    if not directory.is_dir():
        return ObservationPublication(
            measured_sources=(),
            entity_join=None,
            directory=directory,
        )
    join: Path | None = None
    sources: list[Path] = []
    for candidate in sorted(directory.iterdir()):
        if not candidate.is_file() or candidate.suffix.lower() not in (
            MEASUREMENT_SUFFIXES
        ):
            continue
        if candidate.stem == ENTITY_JOIN_STEM:
            # First declared spelling wins, in the sorted order above, so a
            # directory holding both .csv and .parquet joins resolves the same
            # way on every machine.
            join = join or candidate
            continue
        sources.append(candidate)
    return ObservationPublication(
        measured_sources=tuple(sources),
        entity_join=join,
        directory=directory,
    )


__all__ = [
    "ENTITY_JOIN_STEM",
    "JOIN_ABSENT_REASON",
    "MEASURED_ABSENT_REASON",
    "MEASUREMENT_SUFFIXES",
    "PROVENANCE_MEASURED",
    "PROVENANCE_SIMULATED",
    "PROVENANCE_VALUES",
    "ObservationPublication",
    "resolve_observation_publication",
]
