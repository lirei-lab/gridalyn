"""Model Authority Sets and profile declarations for the canonical base.

The CGMES parts this repository adopts — **Model Authority Sets** and **profile
declarations** — are adopted as *fields and rules over parquet*, never as a
serialization format. There is no RDF/XML writer here and no graph library is
imported.

**Why this is its own module.** These declarations were written into
``gridalyn/twin/adapters/cim.py`` by plan 11-05. ``cim.py`` imports
``gridalyn/twin/adapters/network.py``, and ``network.py`` does not import
``cim.py``; so the set declared for ``SyntheticPandapowerAdapter`` — which lives
in ``network.py`` — sat behind an import barrier its only possible consumer
could not cross without a cycle. It was declared and enforced by nothing, on the
path that produces the committed base. This module imports only from
``gridalyn/twin/network/``, so both producers reach it and neither reaches the
other.

Phase 9 deleted ``gridalyn/twin/io/cim.py`` because it was a dead RDF/XML
exporter with zero importers and zero tests, and dropped ``rdflib`` because that
exporter was its only consumer. The reasoning was *"no consumer"*, not *"CIM is
wrong"*. The declarations below therefore have real consumers: they are
validated on **every** ``load_snapshot`` of **both** producers, and rendered
into the manifest of every export.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from gridalyn.twin.network.metadata import BASE_METADATA_SCHEMA_VERSION
from gridalyn.twin.network.model import BASE_PROFILE_ID, BASE_TABLE_FILENAMES
from gridalyn.twin.network.schema import table_schema

CANONICAL_ARTIFACTS: tuple[str, ...] = tuple(BASE_TABLE_FILENAMES)
"""The canonical base artifacts an authority-set partition must cover exactly.

Single-sourced from :data:`gridalyn.twin.network.model.BASE_TABLE_FILENAMES`, so
declaring a sixth canonical table leaves every partition incomplete until an
owner is declared for it. That drift is what :func:`validate_authority_partition`
exists to catch.

**No :class:`ModelAuthoritySet` may be declared with this object as its
``artifacts``.** Plan 11-05 declared both sets as ``artifacts=CANONICAL_ARTIFACTS``
— the same object, not a copy — which made the rule ask whether
``CANONICAL_ARTIFACTS`` partitions ``CANONICAL_ARTIFACTS``. A reviewer added a
sixth canonical table and the rule did not fire. Every set below therefore writes
its artifacts out as a literal, and
``test_no_authority_set_aliases_the_canonical_artifact_list`` gates that.
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
        artifacts: Canonical artifacts this authority owns, **written out as a
            literal**. Must be a subset of :data:`CANONICAL_ARTIFACTS`; the
            partition as a whole must cover it exactly and without overlap.
            Aliasing :data:`CANONICAL_ARTIFACTS` here is what made the rule
            tautological in plan 11-05 -- see that constant's docstring.
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
        artifacts=(
            "grid_buses",
            "grid_lines",
            "grid_transformers",
            "buildings",
            "building_grid_connectivity",
        ),
    ),
    "cim_parquet": ModelAuthoritySet(
        authority_set_id="gridalyn:mas:cim-parquet",
        authority="CimParquetAdapter",
        adapter_id="cim_parquet",
        source_standard="cim",
        artifacts=(
            "grid_buses",
            "grid_lines",
            "grid_transformers",
            "buildings",
            "building_grid_connectivity",
        ),
    ),
}
"""Every declared Model Authority Set, keyed by producing ``adapter_id``.

These are **alternatives**, not co-owners: a model is produced by one adapter,
so :func:`authority_set_partition` returns exactly one of them. See
:data:`AUTHORITY_SET_PARTITION_IS_SINGLE_MEMBER` for the measurement behind
that, and for what is consequently untested.

Both producers genuinely emit all five canonical artifacts, so both literals
above list all five. That is a measurement, not a placeholder: fabricating a
split neither producer performs would be the decorative modelling this milestone
removes. What the literals buy is that a *sixth* canonical artifact is owned by
nobody until someone claims it.
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
            "gridalyn.twin.adapters.authority.MODEL_AUTHORITY_SETS, or export "
            "the model through an adapter that already declares one"
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
    ``load_snapshot`` of **both** producers rather than at export time only.

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
        "`artifacts` tuples in "
        "gridalyn.twin.adapters.authority.MODEL_AUTHORITY_SETS "
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
    """A profile declaration over the canonical base artifacts.

    A CGMES profile composes the dataset exchanged for one purpose. Here the
    analogue is a canonical artifact set, and the dependencies are **derived**
    from :data:`gridalyn.twin.network.schema.BASE_TABLE_SCHEMAS` -- a profile
    depends on another exactly when one of its declared columns ``references``
    that artifact. Nothing here is hand-declared, so a dependency cannot be
    invented and cannot go stale against the schema.

    **``depends_on`` is not CGMES ``Model.DependentOn``.** That header field
    references other *model instances* by mRID; this repository produces exactly
    one model per base, so there is no second model to reference and the CGMES
    field has no analogue here. What this field holds is *profile IDs* -- a
    dependency between profiles, which is a different relation -- and it is
    named, and serialized, for what it holds. Plan 11-05 serialized it under the
    key ``dependent_on``, which dressed profile IDs as the header field; that
    rename is undone.

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
            it serializes with :func:`json.dumps` without a custom encoder. The
            ``depends_on`` key matches the field name: these are profile IDs,
            not CGMES ``Model.DependentOn`` model references.
        """
        return {
            "profile_id": self.profile_id,
            "version": self.version,
            "artifacts": list(self.artifacts),
            "depends_on": list(self.depends_on),
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
the five per-artifact profiles; each per-artifact profile's ``depends_on`` is
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


def base_model_profiles() -> tuple[ModelProfile, ...]:
    """Return every declared base profile, ordered by profile ID."""
    return tuple(BASE_MODEL_PROFILES[key] for key in sorted(BASE_MODEL_PROFILES))


def cgmes_export_notes(authority_sets: Sequence[ModelAuthoritySet]) -> list[str]:
    """Render the CGMES posture lines recorded in a base manifest.

    The lines are rendered from the declarations themselves rather than retyped,
    so a manifest cannot describe a partition the code does not declare. Both
    producers call this, so the committed base carries the same posture as a CIM
    export.

    Args:
        authority_sets: The producing adapter's declared partition.

    Returns:
        Note lines, recorded verbatim in ``metadata.json``'s ``notes``.
    """
    root = BASE_MODEL_PROFILES[BASE_PROFILE_ID]
    owners = ", ".join(
        f"{item.authority_set_id} owns {'/'.join(item.artifacts)}"
        for item in authority_sets
    )
    return [
        f"CGMES Model Authority Sets: {owners}.",
        f"CGMES profile: {root.profile_id}:{root.version}, composed of "
        f"{', '.join(root.depends_on)}.",
        AUTHORITY_SET_PARTITION_IS_SINGLE_MEMBER,
    ]


def model_authority_payload(
    authority_sets: Sequence[ModelAuthoritySet],
    profiles: Sequence[ModelProfile],
) -> dict[str, Any]:
    """Build the structured manifest payload for a producer's declarations.

    ``notes`` is a ``list[str]`` contract, so plan 11-05 could only render this
    as prose. This is the JSON-native form that lands in ``metadata.json``'s
    ``model_authority`` field, which is what a machine reader queries.

    Args:
        authority_sets: The producing adapter's declared partition.
        profiles: The profiles of the base it exports.

    Returns:
        A JSON-native mapping, serializable with a bare :func:`json.dumps`.
    """
    return {
        "authority_sets": [item.as_dict() for item in authority_sets],
        "profiles": [item.as_dict() for item in profiles],
    }
