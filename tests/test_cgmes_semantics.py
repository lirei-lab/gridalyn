"""Pins for the CGMES semantics adopted over parquet (Phase 11, plan 11-05).

Model Authority Sets and profile declarations are adopted as **fields and
rules** over the canonical parquet artifacts, never as a serialization format.
They are enforced on **both** producers: plan 11-05 declared them inside
``adapters/cim.py``, where ``SyntheticPandapowerAdapter`` could not reach them
without an import cycle, so the set declared for the producer of the committed
base was checked by nothing. Review cycle 1 moved them to
``adapters/authority.py`` and wired the second producer.

The dependency-posture pin -- real ``rdflib`` imports under ``gridalyn/`` are
0 -- deliberately does **not** live here. It lives with its siblings in
``tests/test_cim_dependency_policy.py``, which already owned the CIM dependency
posture before this plan; splitting one policy across two files is how it
drifts out of agreement with itself.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from gridalyn.twin.adapters import authority
from gridalyn.twin.adapters.authority import (
    AUTHORITY_SET_PARTITION_IS_SINGLE_MEMBER,
    BASE_MODEL_PROFILES,
    CANONICAL_ARTIFACTS,
    MODEL_AUTHORITY_SETS,
    ModelAuthoritySet,
    ModelProfile,
    UnknownModelAuthoritySetError,
    UnknownModelProfileError,
    authority_set_partition,
    model_authority_set,
    model_profile,
    validate_authority_partition,
)
from gridalyn.twin.adapters.cim import CimParquetAdapter
from gridalyn.twin.adapters.network import SyntheticPandapowerAdapter
from gridalyn.twin.adapters.registry import default_network_adapter_registry
from gridalyn.twin.network.model import BASE_PROFILE_ID, BASE_TABLE_FILENAMES
from gridalyn.twin.network.schema import table_schema


def _write_cim_source(source_dir: Path) -> None:
    """Write a minimal but complete CIM-like parquet source."""
    source_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"mRID": "cn-mv", "name": "MV node", "nominal_voltage_kv": 25.0},
            {"mRID": "cn-lv", "name": "LV node", "nominal_voltage_kv": 0.4},
        ]
    ).to_parquet(source_dir / "connectivity_nodes.parquet", index=False)
    pd.DataFrame(
        [
            {
                "mRID": "line-1",
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
                "connectivity_node": "cn-lv",
                "building_id": "building:cim:1",
                "load_id": "load:cim:1",
                "p_kw": 8.0,
                "feeder_id": "feeder:demo",
            }
        ]
    ).to_parquet(source_dir / "energy_consumers.parquet", index=False)


# --- (a) the declared authority sets match the measured partition ------------


def test_an_authority_set_is_declared_for_every_registered_producer() -> None:
    """The declared authorities are the measured producers, not a guess.

    The producer set was measured two ways for plan 11-05: an AST scan for
    classes defining ``load_snapshot`` under ``gridalyn/``, and the default
    network adapter registry. Both name exactly ``synthetic_pandapower`` and
    ``cim_parquet``. This pins the second to the declarations, so registering a
    third producer without declaring who owns its artifacts turns red.
    """
    registered = {
        descriptor.adapter_id
        for descriptor in default_network_adapter_registry().list_descriptors()
    }

    assert registered == set(MODEL_AUTHORITY_SETS)


def test_every_producer_partition_has_exactly_one_member_owning_everything() -> None:
    """The measured partition: one member, all five canonical artifacts.

    Measured 2026-08-12 by running both producers: each fills all five
    canonical tables (3626/3430/195/3235/3235 rows and 2/1/1/1/1 rows), neither
    fills a proper subset, and one model is exported through one adapter. A
    multi-member partition would be fabrication, so the single-member outcome
    is asserted rather than padded.
    """
    for adapter_id in sorted(MODEL_AUTHORITY_SETS):
        partition = authority_set_partition(adapter_id)

        assert len(partition) == 1, adapter_id
        assert partition[0].artifacts == CANONICAL_ARTIFACTS, adapter_id
        assert partition[0].adapter_id == adapter_id

    assert CANONICAL_ARTIFACTS == tuple(BASE_TABLE_FILENAMES)


def test_the_untested_multi_member_case_is_declared_not_implied() -> None:
    """The honest limitation is recorded in the module, not only in a report."""
    assert "SINGLE member" in AUTHORITY_SET_PARTITION_IS_SINGLE_MEMBER
    assert "UNTESTED" in AUTHORITY_SET_PARTITION_IS_SINGLE_MEMBER


def test_no_authority_set_aliases_the_canonical_artifact_list() -> None:
    """The partition rule must not be asked whether a list partitions itself.

    Plan 11-05 declared both sets as ``artifacts=CANONICAL_ARTIFACTS`` -- the
    same object, not a copy -- so ``validate_authority_partition`` compared
    ``CANONICAL_ARTIFACTS`` against ``CANONICAL_ARTIFACTS`` and could not fail.
    A reviewer added a sixth canonical table and the rule did not fire. Identity
    is the assertion, not equality: equality is expected and correct, because
    both producers genuinely emit all five artifacts.
    """
    for adapter_id, authority_set in sorted(MODEL_AUTHORITY_SETS.items()):
        assert authority_set.artifacts is not CANONICAL_ARTIFACTS, adapter_id
        assert authority_set.artifacts == CANONICAL_ARTIFACTS, adapter_id


def test_a_sixth_canonical_artifact_is_unowned_and_turns_the_partition_red(
    monkeypatch,
) -> None:
    """The drift the rule exists to catch, exercised rather than asserted.

    This is the reviewer's experiment in miniature: widen the canonical artifact
    list without giving the new entry an owner, and every declared partition
    must go red. Widening :data:`CANONICAL_ARTIFACTS` directly rather than
    editing ``BASE_TABLE_FILENAMES`` keeps the check on the partition rule --
    editing the filename map also trips ``schema.py``'s ``table_schema()``,
    which raises first and masks this result.

    This does *not* subsume
    ``test_no_authority_set_aliases_the_canonical_artifact_list``: rebinding the
    name leaves an aliased set pointing at the old tuple, so an aliased
    declaration goes red here too. Only the identity assertion catches the alias
    on the real, unpatched list.
    """
    monkeypatch.setattr(
        authority,
        "CANONICAL_ARTIFACTS",
        CANONICAL_ARTIFACTS + ("weather_timeseries",),
    )

    for adapter_id in sorted(MODEL_AUTHORITY_SETS):
        with pytest.raises(ValueError) as excinfo:
            validate_authority_partition(
                authority_set_partition(adapter_id), adapter_id=adapter_id
            )

        assert "'weather_timeseries' has no declared owner" in str(excinfo.value)


def test_partition_rule_rejects_an_artifact_with_no_owner() -> None:
    incomplete = ModelAuthoritySet(
        authority_set_id="test:mas:partial",
        authority="TestAdapter",
        adapter_id="test_adapter",
        source_standard="test",
        artifacts=CANONICAL_ARTIFACTS[:-1],
    )

    with pytest.raises(ValueError) as excinfo:
        validate_authority_partition([incomplete], adapter_id="test_adapter")

    message = str(excinfo.value)
    assert "test_adapter" in message
    assert f"{CANONICAL_ARTIFACTS[-1]!r} has no declared owner" in message
    assert "MODEL_AUTHORITY_SETS" in message


def test_partition_rule_rejects_two_authorities_claiming_one_artifact() -> None:
    first = ModelAuthoritySet(
        authority_set_id="test:mas:first",
        authority="First",
        adapter_id="test_adapter",
        source_standard="test",
        artifacts=CANONICAL_ARTIFACTS,
    )
    second = ModelAuthoritySet(
        authority_set_id="test:mas:second",
        authority="Second",
        adapter_id="test_adapter",
        source_standard="test",
        artifacts=(CANONICAL_ARTIFACTS[0],),
    )

    with pytest.raises(ValueError) as excinfo:
        validate_authority_partition([first, second], adapter_id="test_adapter")

    message = str(excinfo.value)
    assert "test:mas:first" in message
    assert "test:mas:second" in message
    assert "claimed by both" in message


def test_partition_rule_rejects_an_artifact_that_is_not_canonical() -> None:
    stray = ModelAuthoritySet(
        authority_set_id="test:mas:stray",
        authority="Stray",
        adapter_id="test_adapter",
        source_standard="test",
        artifacts=CANONICAL_ARTIFACTS + ("weather_timeseries",),
    )

    with pytest.raises(ValueError) as excinfo:
        validate_authority_partition([stray], adapter_id="test_adapter")

    message = str(excinfo.value)
    assert "'weather_timeseries', which is not a canonical base artifact" in message
    assert "grid_buses" in message


def test_load_snapshot_consumes_the_partition_rule(monkeypatch) -> None:
    """The declarations are checked on every load, not only on export.

    This is the criterion Phase 9 applied when it deleted the dead RDF/XML
    exporter: a declaration with no consumer is dead weight. The check runs
    before any IO, so a non-existent source directory is enough to prove which
    failure comes first.
    """
    monkeypatch.setitem(
        MODEL_AUTHORITY_SETS,
        "cim_parquet",
        ModelAuthoritySet(
            authority_set_id="gridalyn:mas:cim-parquet",
            authority="CimParquetAdapter",
            adapter_id="cim_parquet",
            source_standard="cim",
            artifacts=CANONICAL_ARTIFACTS[:2],
        ),
    )
    adapter = CimParquetAdapter(source_dir=Path("does-not-exist"))

    with pytest.raises(ValueError) as excinfo:
        adapter.load_snapshot()

    assert "do not partition the canonical base artifacts" in str(excinfo.value)


def test_the_synthetic_producer_consumes_the_partition_rule(monkeypatch) -> None:
    """The producer of the committed base checks its own declaration.

    Until review cycle 1 this was impossible: the declarations lived in
    ``adapters/cim.py``, which imports ``adapters/network.py`` and not the other
    way round, so ``gridalyn:mas:synthetic-pandapower`` was declared where its
    only possible consumer was structurally barred from reaching it. The check
    runs before any IO, so a non-existent cache directory is enough to prove
    which failure comes first.
    """
    monkeypatch.setitem(
        MODEL_AUTHORITY_SETS,
        "synthetic_pandapower",
        ModelAuthoritySet(
            authority_set_id="gridalyn:mas:synthetic-pandapower",
            authority="SyntheticPandapowerAdapter",
            adapter_id="synthetic_pandapower",
            source_standard="pandapower",
            artifacts=CANONICAL_ARTIFACTS[:2],
        ),
    )
    adapter = SyntheticPandapowerAdapter(
        cache_dir=Path("does-not-exist"),
        config_path=Path("does-not-exist.json"),
    )

    with pytest.raises(ValueError) as excinfo:
        adapter.load_snapshot()

    assert "do not partition the canonical base artifacts" in str(excinfo.value)


def test_the_synthetic_producer_declares_the_same_surface_as_the_cim_one() -> None:
    """Both producers expose the declaration, not just the one that ships CIM."""
    adapter = SyntheticPandapowerAdapter(
        cache_dir=Path("unused"),
        config_path=Path("unused.json"),
    )

    assert [item.authority_set_id for item in adapter.authority_sets()] == [
        "gridalyn:mas:synthetic-pandapower"
    ]
    assert [item.profile_id for item in adapter.profiles()] == sorted(
        BASE_MODEL_PROFILES
    )


def test_unknown_authority_set_error_enumerates_the_declared_ids() -> None:
    with pytest.raises(UnknownModelAuthoritySetError) as excinfo:
        model_authority_set("iec_61850_scl")

    message = str(excinfo.value)
    assert "iec_61850_scl" in message
    assert "cim_parquet, synthetic_pandapower" in message
    assert "MODEL_AUTHORITY_SETS" in message


def test_export_records_the_authority_set_and_profile_in_the_manifest() -> None:
    """The declaration reaches the artifact a reader actually opens."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_cim_source(root / "cim_source")

        adapter = CimParquetAdapter(source_dir=root / "cim_source")
        result = adapter.export(out_dir=root / "base", root=root)
        manifest = json.loads(result.metadata_path.read_text())

    notes = manifest["notes"]
    joined = " ".join(notes)
    assert "gridalyn:mas:cim-parquet" in joined
    assert BASE_PROFILE_ID in joined
    assert "does not parse CIM RDF/XML" in joined
    assert AUTHORITY_SET_PARTITION_IS_SINGLE_MEMBER in notes


def test_export_records_the_structured_payload_not_only_prose() -> None:
    """A machine reader gets fields, not a sentence it has to parse.

    ``notes`` is a ``list[str]``, so plan 11-05 could only render the
    declarations as prose and recorded the structured form as a hand-off. This
    pins the field that closed it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_cim_source(root / "cim_source")

        adapter = CimParquetAdapter(source_dir=root / "cim_source")
        result = adapter.export(out_dir=root / "base", root=root)
        manifest = json.loads(result.metadata_path.read_text())

    payload = manifest["model_authority"]
    assert [item["authority_set_id"] for item in payload["authority_sets"]] == [
        "gridalyn:mas:cim-parquet"
    ]
    assert payload["authority_sets"][0]["artifacts"] == list(CANONICAL_ARTIFACTS)
    assert [item["profile_id"] for item in payload["profiles"]] == sorted(
        BASE_MODEL_PROFILES
    )


def test_export_returns_the_identity_it_read_back_off_disk() -> None:
    """The export post-condition: a base without a resolvable manifest fails.

    ``provenance="require"`` had no production caller until review cycle 1; this
    is it. The identity is read back through ``NetworkModelRepository`` rather
    than assembled by the producer, so producer and consumer are proven to agree
    on the manifest that was just written.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_cim_source(root / "cim_source")

        adapter = CimParquetAdapter(source_dir=root / "cim_source")
        result = adapter.export(out_dir=root / "base", root=root)
        manifest = json.loads(result.metadata_path.read_text())

    assert result.identity.id == manifest["model_version_id"]
    assert result.identity.profile == f"{BASE_PROFILE_ID}:1.0"
    assert "base/grid_buses.parquet" in result.identity.artifact_paths


# --- (b) profile dependencies name only profiles that exist -----------------


def test_profile_dependencies_name_only_declared_profiles() -> None:
    for profile in BASE_MODEL_PROFILES.values():
        for dependency in profile.depends_on:
            assert (
                dependency in BASE_MODEL_PROFILES
            ), f"{profile.profile_id} depends on undeclared {dependency!r}"
            assert dependency != profile.profile_id


def test_every_profile_carries_only_canonical_artifacts() -> None:
    for profile in BASE_MODEL_PROFILES.values():
        assert profile.artifacts, profile.profile_id
        assert set(profile.artifacts) <= set(CANONICAL_ARTIFACTS)


def test_root_profile_composes_every_per_artifact_profile() -> None:
    root = model_profile(BASE_PROFILE_ID)

    assert root.artifacts == CANONICAL_ARTIFACTS
    assert len(root.depends_on) == len(CANONICAL_ARTIFACTS)
    assert set(root.depends_on) == set(BASE_MODEL_PROFILES) - {BASE_PROFILE_ID}


def test_profile_dependencies_are_derived_from_the_declared_schema() -> None:
    """``dependentOn`` is computed from schema references, never hand-written.

    A hand-written dependency list is exactly the decorative modelling this
    milestone removes: it would look CGMES-shaped and drift silently from the
    columns the tables actually carry.
    """
    for artifact in CANONICAL_ARTIFACTS:
        expected = {
            column.references
            for column in table_schema(artifact).columns
            if column.references is not None and column.references != artifact
        }
        profile = model_profile(f"{BASE_PROFILE_ID}/{artifact}")

        assert {
            dependency.split("/")[-1] for dependency in profile.depends_on
        } == expected, artifact

    assert model_profile(f"{BASE_PROFILE_ID}/grid_buses").depends_on == ()


def test_adapter_exposes_its_authority_sets_and_profiles() -> None:
    adapter = CimParquetAdapter(source_dir=Path("unused"))

    assert [item.authority_set_id for item in adapter.authority_sets()] == [
        "gridalyn:mas:cim-parquet"
    ]
    assert [item.profile_id for item in adapter.profiles()] == sorted(
        BASE_MODEL_PROFILES
    )


def test_unknown_profile_error_enumerates_the_declared_ids() -> None:
    with pytest.raises(UnknownModelProfileError) as excinfo:
        model_profile("gridalyn:digital-twin-base/weather")

    message = str(excinfo.value)
    assert "gridalyn:digital-twin-base/weather" in message
    assert "gridalyn:digital-twin-base/grid_buses" in message
    assert "BASE_TABLE_SCHEMAS" in message


# --- (c) descriptors are JSON-serializable without a custom encoder ----------


def _descriptors() -> list[ModelAuthoritySet | ModelProfile]:
    return [*MODEL_AUTHORITY_SETS.values(), *BASE_MODEL_PROFILES.values()]


def test_descriptors_serialize_without_a_custom_encoder() -> None:
    """``as_dict`` must land in a manifest with a bare ``json.dumps``.

    ``default=`` and ``allow_nan`` are both withheld: a descriptor that needs
    either is not JSON-native, and the manifest writer
    (``twin/network/metadata.py``) passes neither.
    """
    for descriptor in _descriptors():
        payload = descriptor.as_dict()

        text = json.dumps(payload, sort_keys=True, allow_nan=False)

        assert json.loads(text) == payload


def test_profile_dependencies_serialize_under_their_own_name() -> None:
    """A profile ID list must not be serialized as CGMES ``Model.DependentOn``.

    Plan 11-05's ``as_dict`` renamed ``depends_on`` to ``dependent_on`` on the
    way out, which dressed *profile IDs* as the CGMES header field that
    references other *models* by mRID. There is one model per base here, so that
    field has nothing to point at; the key now matches the attribute.
    """
    for profile in BASE_MODEL_PROFILES.values():
        payload = profile.as_dict()

        assert payload["depends_on"] == list(profile.depends_on)
        assert "dependent_on" not in payload


def test_descriptor_values_are_strings_or_lists_of_strings() -> None:
    for descriptor in _descriptors():
        for key, value in descriptor.as_dict().items():
            assert isinstance(key, str)
            if isinstance(value, list):
                assert all(isinstance(item, str) for item in value)
            else:
                assert isinstance(value, str), (descriptor, key, value)
