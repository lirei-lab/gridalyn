"""Gate the observation producer registry: two real producers, one contract.

Five behaviours are held here:

(a) the default registry lists exactly the two shipped producers --
    ``measured-ingest`` (measured) and ``powerflow`` (simulated) -- sorted by
    ID;
(b) ``resolve`` hands back the real producer callables by identity, never
    wrappers -- the deliberate divergence from the adapter registry's
    ``create``, stated in the registry's own docstring;
(c) an unknown ID is a located error naming the available IDs, and a
    duplicate registration without ``replace=True`` is a ``ValueError``;
(d) the module imports nothing from ``entry_points`` / ``importlib.metadata``
    -- explicit IDs only, Phase 10's recorded rule that ambient plugins
    change results without appearing in provenance;
(e) end-to-end, both resolved producers emit through the one observation
    contract: the measured producer stamps ``provenance="measured"`` with a
    non-``None`` ``as_of`` from the datum, and the simulated producer stamps
    ``provenance="simulated"`` off a solved IEEE-33.

Behaviour (d) is an :mod:`ast` scan over Import/ImportFrom nodes, never a
grep: the forbidden strings legitimately appear in the registry's docstring
*stating* the rule (and in this one), so a text search would fail forever
regardless of the code -- RETRO item 11, AST over text for "written in
source".

This file is the replacement gate for the registry half of Phase 11's
``test_no_state_producer_registry_was_built`` (retired by plan 12-03 when the
measured ingest landed): the deferral's stated reason -- "one producer plus a
placeholder is the speculative abstraction 10-03 declined" -- ended the day
the second real producer existed, and behaviour (e) is that end, executed.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from gridalyn.simulation.backends.contract import PANDAPOWER_NATIVE_BACKEND_ID
from gridalyn.simulation.backends.registry import solve_power_flow
from gridalyn.simulation.simulators.powerflow.benchmarks import (
    build_ieee33_benchmark_feeder,
)
from gridalyn.twin.observation.contract import NetworkObservation, observe_network
from gridalyn.twin.observation.ingest import EntityJoin, read_measured_observations
from gridalyn.twin.observation.registry import (
    ObservationProducerDescriptor,
    ObservationProducerRegistry,
    UnknownObservationProducerError,
    default_observation_producer_registry,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The registry module the AST scan of behaviour (d) reads.
REGISTRY_SOURCE = REPO_ROOT / "gridalyn/twin/observation/registry.py"

#: A fixed 2018 instant, deliberately far from any wall clock this suite runs
#: under: equality against it proves ``as_of`` came from the datum.
FIXTURE_INSTANT = "2018-01-15T06:00:00+00:00"


def _noop_producer() -> tuple[NetworkObservation, ...]:
    """Stand-in producer for registration-mechanics tests; never called."""
    return ()


def _descriptor(producer_id: str) -> ObservationProducerDescriptor:
    """Build a minimal descriptor for registration-mechanics tests.

    Args:
        producer_id: Stable ID for the registration under test.

    Returns:
        A descriptor with fixed provenance and summary.
    """
    return ObservationProducerDescriptor(
        producer_id=producer_id,
        provenance="simulated",
        summary="test-only producer",
    )


# --------------------------------------------------------------------------
# (a) the default registry lists exactly the two shipped producers
# --------------------------------------------------------------------------


def test_default_registry_lists_exactly_the_two_shipped_producers() -> None:
    """IDs are ['measured-ingest', 'powerflow'] with measured/simulated."""
    descriptors = default_observation_producer_registry().list_descriptors()

    assert [d.producer_id for d in descriptors] == ["measured-ingest", "powerflow"]
    assert [d.provenance for d in descriptors] == ["measured", "simulated"]
    for descriptor in descriptors:
        assert descriptor.summary, descriptor.producer_id


def test_get_descriptor_returns_the_registered_metadata() -> None:
    """``get_descriptor`` and ``list_descriptors`` agree per ID."""
    registry = default_observation_producer_registry()

    for descriptor in registry.list_descriptors():
        assert registry.get_descriptor(descriptor.producer_id) == descriptor


# --------------------------------------------------------------------------
# (b) resolve hands back the real producers by identity
# --------------------------------------------------------------------------


def test_resolve_returns_the_real_producers_not_wrappers() -> None:
    """The registry hands back the registered callables themselves.

    Identity, not equality: a wrapper with the same behaviour would still be
    a second object, and the registry's contract is that ``resolve`` replaces
    the adapter registry's ``create`` precisely because producers are
    functions with nothing to instantiate.
    """
    registry = default_observation_producer_registry()

    assert registry.resolve("powerflow") is observe_network
    assert registry.resolve("measured-ingest") is read_measured_observations


# --------------------------------------------------------------------------
# (c) located errors: unknown ID, duplicate registration
# --------------------------------------------------------------------------


def test_unknown_producer_id_names_the_available_ids() -> None:
    """An unknown ID raises the registry's own error, listing what exists."""
    registry = default_observation_producer_registry()

    with pytest.raises(UnknownObservationProducerError) as excinfo:
        registry.resolve("scada-stream")

    message = str(excinfo.value)
    assert "scada-stream" in message
    assert "measured-ingest" in message
    assert "powerflow" in message


def test_unknown_id_on_an_empty_registry_says_none() -> None:
    """An empty registry still locates the failure and says what exists."""
    with pytest.raises(UnknownObservationProducerError, match="none"):
        ObservationProducerRegistry().get_descriptor("powerflow")


def test_duplicate_registration_without_replace_is_an_error() -> None:
    """A duplicate ID fails loudly; ``replace=True`` overwrites deliberately."""
    registry = ObservationProducerRegistry()
    registry.register(_noop_producer, descriptor=_descriptor("powerflow"))

    with pytest.raises(ValueError, match="already registered: powerflow"):
        registry.register(observe_network, descriptor=_descriptor("powerflow"))

    registry.register(
        observe_network, descriptor=_descriptor("powerflow"), replace=True
    )
    assert registry.resolve("powerflow") is observe_network


# --------------------------------------------------------------------------
# (d) explicit IDs only: no entry_points, no importlib.metadata
# --------------------------------------------------------------------------


def _import_targets(source: str) -> list[str]:
    """Return every module or name imported by ``source``.

    Walks Import/ImportFrom nodes rather than matching text: the forbidden
    strings appear in the registry's docstring stating the rule, so a grep
    answers a different question than the one asked.

    Args:
        source: Python source of a module to scan.

    Returns:
        Dotted names, one per imported module and one per imported symbol
        (``module.name`` for ``from module import name``).
    """
    targets: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            targets.append(module)
            targets.extend(f"{module}.{alias.name}" for alias in node.names)
    return targets


def test_registry_imports_no_entry_point_machinery() -> None:
    """No Import/ImportFrom node reaches entry_points or importlib.metadata."""
    targets = _import_targets(REGISTRY_SOURCE.read_text(encoding="utf-8"))

    offenders = [
        target
        for target in targets
        if "entry_points" in target or target.startswith("importlib.metadata")
    ]
    assert not offenders, (
        f"registry.py imports plugin-discovery machinery: {offenders}; "
        "producers register by explicit ID only, because ambient plugins "
        "change results without appearing in provenance"
    )


def test_the_import_scan_would_catch_the_forbidden_machinery() -> None:
    """The scan is not vacuous: it finds both forms it exists to forbid."""
    assert _import_targets("from importlib.metadata import entry_points") == [
        "importlib.metadata",
        "importlib.metadata.entry_points",
    ]
    assert _import_targets("import importlib.metadata") == ["importlib.metadata"]
    # Prose naming the machinery is not an import of it.
    assert _import_targets("# entry_points and importlib.metadata are banned") == []


# --------------------------------------------------------------------------
# (e) end-to-end: two producers, one contract, executed
# --------------------------------------------------------------------------


def test_resolved_measured_producer_emits_measured_observations() -> None:
    """The measured producer, resolved by ID, stamps measured + a real as_of."""
    frame = pd.DataFrame(
        [
            (FIXTURE_INSTANT, "meter_a", "voltage_pu", 0.97),
            (FIXTURE_INSTANT, "meter_b", "voltage_pu", 1.02),
        ],
        columns=["timestamp", "entity_id", "quantity", "value"],
    )
    join = EntityJoin.from_mapping({"meter_a": "bus_1", "meter_b": "bus_2"})
    producer = default_observation_producer_registry().resolve("measured-ingest")

    (observation,) = producer(frame, join=join)

    assert observation.provenance == "measured"
    assert observation.as_of is not None
    assert observation.as_of == datetime(2018, 1, 15, 6, 0, tzinfo=timezone.utc)
    assert list(observation.bus_ids) == ["bus_1", "bus_2"]


def test_resolved_powerflow_producer_emits_simulated_observations() -> None:
    """The simulated producer, resolved by ID, reads a solved IEEE-33."""
    net = build_ieee33_benchmark_feeder()
    solve_power_flow(net, backend_id=PANDAPOWER_NATIVE_BACKEND_ID)
    producer = default_observation_producer_registry().resolve("powerflow")

    observation = producer(net)

    assert isinstance(observation, NetworkObservation)
    assert observation.provenance == "simulated"
    assert observation.converged is True
    assert len(observation.bus_voltage_pu) == 33
