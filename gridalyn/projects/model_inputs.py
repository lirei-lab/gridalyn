"""Project input loaders for Gridalyn asset and simulation contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import numpy as np

from gridalyn.assets.modeling.der_dispatch import DERDispatchAsset
from gridalyn.assets.modeling.energy_assets import BatteryAsset, ProsumerAsset, PVAsset
from gridalyn.assets.modeling.feeders import (
    RadialFeederSpec,
    validate_radial_feeder_spec,
)
from gridalyn.assets.modeling.voltage_control import (
    VoltageControlDERSpec,
    validate_voltage_control_der,
)
from gridalyn.projects.loader import load_project
from gridalyn.projects.models import StudyProject

ProjectRef = StudyProject | Path | str


def _project(project_or_path: ProjectRef) -> StudyProject:
    if isinstance(project_or_path, StudyProject):
        return project_or_path
    path = Path(project_or_path)
    if path.is_dir():
        path = path / "project.yaml"
    return load_project(path)


def _inputs(project: StudyProject) -> Mapping[str, Any]:
    inputs = project.raw.get("spec", {}).get("inputs", {})
    if not isinstance(inputs, Mapping):
        raise ValueError(
            f"{project.path}: spec.inputs must be a mapping, "
            f"found {type(inputs).__name__}"
        )
    return inputs


def _available_keys(inputs: Mapping[str, Any]) -> str:
    keys = sorted(str(key) for key in inputs)
    return ", ".join(keys) if keys else "none declared"


def project_input(project_or_path: ProjectRef, key: str) -> Mapping[str, Any]:
    """Return one named mapping from a project ``spec.inputs`` contract."""
    project = _project(project_or_path)
    inputs = _inputs(project)
    value = inputs.get(key)
    if not isinstance(value, Mapping):
        if key not in inputs:
            raise ValueError(
                f"{project.path}: spec.inputs.{key} not found "
                f"(available inputs: {_available_keys(inputs)})"
            )
        raise ValueError(
            f"{project.path}: spec.inputs.{key} must be a mapping, "
            f"found {type(value).__name__}"
        )
    return value


def _model_mapping(project_or_path: ProjectRef, key: str) -> Mapping[str, Any]:
    project = _project(project_or_path)
    value = project_input(project, key)
    model = value.get("model", value)
    if not isinstance(model, Mapping):
        raise ValueError(
            f"{project.path}: spec.inputs.{key}.model must be a mapping, "
            f"found {type(model).__name__}"
        )
    return model


def _required(mapping: Mapping[str, Any], key: str, context: str = "") -> Any:
    if key not in mapping:
        location = f"{context}.{key}" if context else key
        present = ", ".join(sorted(str(item) for item in mapping)) or "none"
        raise ValueError(
            f"missing required model input field: {location} "
            f"(present fields: {present})"
        )
    return mapping[key]


def _float_mapping(mapping: Mapping[Any, Any]) -> dict[int, float]:
    return {int(key): float(value) for key, value in mapping.items()}


def load_radial_feeder_spec(
    project_or_path: ProjectRef,
    input_key: str = "sourceNetwork",
) -> RadialFeederSpec:
    """Load a ``RadialFeederSpec`` from ``spec.inputs.<input_key>.model``."""
    project = _project(project_or_path)
    model = _model_mapping(project, input_key)
    context = f"{project.path}: spec.inputs.{input_key}.model"
    if model.get("type") != "radial_feeder":
        raise ValueError(
            f"{context}.type must be 'radial_feeder', found {model.get('type')!r}"
        )

    metadata = dict(model.get("metadata", {}))
    metadata.setdefault("source", f"project.yaml:{input_key}")
    spec = RadialFeederSpec(
        name=str(_required(model, "name", context)),
        bus_count=int(_required(model, "busCount", context)),
        sn_mva=float(_required(model, "snMva", context)),
        base_voltage_kv=float(_required(model, "baseVoltageKv", context)),
        slack_vm_pu=float(_required(model, "slackVmPu", context)),
        loads_mw=_float_mapping(_required(model, "loadsMw", context)),
        q_to_p_ratio=float(model.get("qToPRatio", 0.30)),
        line_length_km=float(model.get("lineLengthKm", 0.5)),
        line_lengths_km=_float_mapping(model.get("lineLengthsKm", {})),
        line_r_ohm_per_km=float(model.get("lineROhmPerKm", 0.5)),
        line_x_ohm_per_km=float(model.get("lineXOhmPerKm", 0.3)),
        line_c_nf_per_km=float(model.get("lineCNfPerKm", 5.0)),
        line_max_i_ka=float(model.get("lineMaxIKa", 0.2)),
        bus_y_step=float(model.get("busYStep", 0.2)),
        metadata=metadata,
    )
    validate_radial_feeder_spec(spec)
    return spec


def load_der_dispatch_assets(
    project_or_path: ProjectRef,
    input_key: str = "derAssets",
) -> tuple[DERDispatchAsset, ...]:
    """Load DER dispatch assets from a project input list."""
    project = _project(project_or_path)
    inputs = _inputs(project)
    context = f"{project.path}: spec.inputs.{input_key}"
    values = inputs.get(input_key, [])
    if not isinstance(values, list):
        raise ValueError(f"{context} must be a list, found {type(values).__name__}")
    assets: list[DERDispatchAsset] = []
    for index, item in enumerate(values):
        if not isinstance(item, Mapping):
            raise ValueError(
                f"{context}[{index}] must be a mapping, found {type(item).__name__}"
            )
        item_context = f"{context}[{index}]"
        assets.append(
            DERDispatchAsset(
                der_id=str(_required(item, "id", item_context)),
                bus_id=int(_required(item, "busId", item_context)),
                pv_available_mw=float(_required(item, "pvAvailableMw", item_context)),
                battery_charge_power_mw=float(
                    _required(item, "batteryChargePowerMw", item_context)
                ),
            )
        )
    return tuple(assets)


def _battery_from_mapping(
    mapping: Mapping[str, Any], context: str = ""
) -> BatteryAsset:
    return BatteryAsset(
        asset_id=str(_required(mapping, "id", context)),
        power_mw=float(_required(mapping, "powerMw", context)),
        capacity_mwh=float(_required(mapping, "capacityMwh", context)),
        initial_soc_mwh=float(_required(mapping, "initialSocMwh", context)),
        min_soc_mwh=float(_required(mapping, "minSocMwh", context)),
    )


def load_prosumer_assets(
    project_or_path: ProjectRef,
    input_key: str = "prosumerAssets",
) -> tuple[ProsumerAsset, ...]:
    """Load prosumer PV+battery assets from a project input list."""
    project = _project(project_or_path)
    inputs = _inputs(project)
    context = f"{project.path}: spec.inputs.{input_key}"
    values = inputs.get(input_key, [])
    if not isinstance(values, list):
        raise ValueError(f"{context} must be a list, found {type(values).__name__}")
    assets: list[ProsumerAsset] = []
    for index, item in enumerate(values):
        if not isinstance(item, Mapping):
            raise ValueError(
                f"{context}[{index}] must be a mapping, found {type(item).__name__}"
            )
        item_context = f"{context}[{index}]"
        pv = item.get("pv")
        battery = item.get("battery")
        if not isinstance(pv, Mapping) or not isinstance(battery, Mapping):
            raise ValueError(
                f"{item_context} requires 'pv' and 'battery' mappings "
                f"(present fields: {', '.join(sorted(str(field) for field in item))})"
            )
        assets.append(
            ProsumerAsset(
                prosumer_id=str(_required(item, "id", item_context)),
                bus_id=int(_required(item, "busId", item_context)),
                pv=PVAsset(
                    asset_id=str(_required(pv, "id", f"{item_context}.pv")),
                    capacity_mw=float(
                        _required(pv, "capacityMw", f"{item_context}.pv")
                    ),
                ),
                battery=_battery_from_mapping(battery, f"{item_context}.battery"),
                offer_price_usd_per_mwh=float(
                    _required(item, "offerPriceUsdPerMwh", item_context)
                ),
            )
        )
    return tuple(assets)


def load_voltage_control_der_spec(
    project_or_path: ProjectRef,
    input_key: str = "voltageControlDer",
    feeder: RadialFeederSpec | None = None,
) -> VoltageControlDERSpec:
    """Load a voltage-control DER contract from a project input mapping."""
    project = _project(project_or_path)
    mapping = project_input(project, input_key)
    context = f"{project.path}: spec.inputs.{input_key}"
    battery = mapping.get("battery")
    if not isinstance(battery, Mapping):
        raise ValueError(
            f"{context}.battery must be a mapping, found {type(battery).__name__}"
        )
    spec = VoltageControlDERSpec(
        asset_id=str(_required(mapping, "id", context)),
        controlled_bus_id=int(_required(mapping, "controlledBusId", context)),
        pv_bus_id=int(_required(mapping, "pvBusId", context)),
        battery_bus_id=int(_required(mapping, "batteryBusId", context)),
        pv_capacity_mw=float(_required(mapping, "pvCapacityMw", context)),
        battery=_battery_from_mapping(battery, f"{context}.battery"),
        max_soc_mwh=float(_required(mapping, "maxSocMwh", context)),
        action_space_mw=tuple(
            float(value) for value in _required(mapping, "actionSpaceMw", context)
        ),
    )
    if feeder is not None:
        validate_voltage_control_der(feeder, spec)
    return spec


_POWERFLOW_SCENARIO_PARAMETERS = {
    "loadMultiplier",
    "pvBuses",
    "pvMwPerBus",
    "evBuses",
    "evMwPerBus",
}


def load_standard_powerflow_scenarios(project_or_path: ProjectRef) -> tuple[Any, ...]:
    """Build ``StandardPowerflowScenario`` objects from ``spec.problem.scenarios``.

    Scenario ``parameters`` may declare ``loadMultiplier``, ``pvBuses``,
    ``pvMwPerBus``, ``evBuses``, and ``evMwPerBus``; omitted values fall back
    to the neutral defaults of ``StandardPowerflowScenario``.
    """
    from gridalyn.simulation import StandardPowerflowScenario

    project = _project(project_or_path)
    scenarios = []
    for spec in project.problem.scenarios:
        parameters = spec.parameters or {}
        unknown = sorted(set(parameters) - _POWERFLOW_SCENARIO_PARAMETERS)
        if unknown:
            supported = ", ".join(sorted(_POWERFLOW_SCENARIO_PARAMETERS))
            raise ValueError(
                f"{project.path}: spec.problem.scenarios[{spec.id}].parameters "
                f"has unsupported keys: {', '.join(unknown)} (supported: {supported})"
            )
        scenarios.append(
            StandardPowerflowScenario(
                scenario_id=spec.id,
                description=spec.description,
                load_multiplier=float(parameters.get("loadMultiplier", 1.0)),
                pv_buses=tuple(int(bus) for bus in parameters.get("pvBuses", ())),
                pv_mw_per_bus=float(parameters.get("pvMwPerBus", 0.0)),
                ev_buses=tuple(int(bus) for bus in parameters.get("evBuses", ())),
                ev_mw_per_bus=float(parameters.get("evMwPerBus", 0.0)),
            )
        )
    return tuple(scenarios)


_LOAD_GENERATION_KEYS = {
    "generator",
    "nUnits",
    "seed",
    "day",
    "durationHours",
    "resolutionMinutes",
    "weather",
    "multipliers",
}
_LOAD_GENERATION_MULTIPLIER_KEYS = {
    "intervals",
    "peakMultiplier",
    "intervalMinutes",
    "window",
}


def _load_generation_mapping(
    project: StudyProject, input_key: str
) -> Mapping[str, Any]:
    mapping = project_input(project, input_key)
    context = f"{project.path}: spec.inputs.{input_key}"
    unknown = sorted(set(mapping) - _LOAD_GENERATION_KEYS)
    if unknown:
        supported = ", ".join(sorted(_LOAD_GENERATION_KEYS))
        raise ValueError(
            f"{context} has unsupported keys: {', '.join(unknown)} "
            f"(supported: {supported})"
        )
    return mapping


def load_generated_load_profiles(
    project_or_path: ProjectRef,
    input_key: str = "loadGeneration",
) -> Any:
    """Generate per-unit load profiles declared in ``spec.inputs.<input_key>``.

    Returns the kW DataFrame from
    :func:`gridalyn.assets.datagen.generate_residential_load_profiles`.
    ``weather`` defaults to ``"synthetic"`` in project context so results are
    byte-stable across environments.
    """
    from gridalyn.assets.datagen import generate_residential_load_profiles

    project = _project(project_or_path)
    mapping = _load_generation_mapping(project, input_key)
    context = f"{project.path}: spec.inputs.{input_key}"
    return generate_residential_load_profiles(
        int(_required(mapping, "nUnits", context)),
        day=str(mapping.get("day", "peak")),
        duration_hours=int(mapping.get("durationHours", 24)),
        resolution_minutes=int(mapping.get("resolutionMinutes", 15)),
        seed=int(_required(mapping, "seed", context)),
        generator=str(mapping.get("generator", "parametric")),
        weather=str(mapping.get("weather", "synthetic")),
    )


def load_generated_load_multipliers(
    project_or_path: ProjectRef,
    input_key: str = "loadGeneration",
) -> np.ndarray:
    """Build a normalized multiplier series from a ``loadGeneration`` input.

    Requires the ``multipliers`` sub-block (``intervals`` and
    ``peakMultiplier``); the generated aggregate shape is scaled so its
    maximum equals the declared ``peakMultiplier``.
    """
    from gridalyn.assets.datagen import aggregate_load_multipliers

    project = _project(project_or_path)
    mapping = _load_generation_mapping(project, input_key)
    context = f"{project.path}: spec.inputs.{input_key}"
    multipliers = mapping.get("multipliers")
    if not isinstance(multipliers, Mapping):
        raise ValueError(
            f"{context}.multipliers must be a mapping with 'intervals' and "
            f"'peakMultiplier', found {type(multipliers).__name__}"
        )
    unknown = sorted(set(multipliers) - _LOAD_GENERATION_MULTIPLIER_KEYS)
    if unknown:
        supported = ", ".join(sorted(_LOAD_GENERATION_MULTIPLIER_KEYS))
        raise ValueError(
            f"{context}.multipliers has unsupported keys: {', '.join(unknown)} "
            f"(supported: {supported})"
        )
    multiplier_context = f"{context}.multipliers"
    interval_minutes = multipliers.get("intervalMinutes")
    profiles = load_generated_load_profiles(project, input_key)
    return aggregate_load_multipliers(
        profiles,
        intervals=int(_required(multipliers, "intervals", multiplier_context)),
        interval_minutes=(
            int(interval_minutes) if interval_minutes is not None else None
        ),
        peak_multiplier=float(
            _required(multipliers, "peakMultiplier", multiplier_context)
        ),
        window=str(multipliers.get("window", "full")),
    )


def load_generated_bus_loads_mw(
    project_or_path: ProjectRef,
    input_key: str = "loadGeneration",
    *,
    anchor_loads_mw: Mapping[int, float],
) -> dict[int, float]:
    """Return a diversified coincident-peak ``loads_mw`` snapshot.

    Per-bus shares come from the generated profiles; the system total is
    anchored to ``sum(anchor_loads_mw)`` so the declared operating point is
    preserved.
    """
    from gridalyn.assets.datagen import coincident_peak_loads_mw

    profiles = load_generated_load_profiles(project_or_path, input_key)
    return coincident_peak_loads_mw(profiles, anchor_loads_mw)


def load_numeric_profile_array(
    project_or_path: ProjectRef,
    input_key: str,
) -> np.ndarray:
    """Load a numeric project input list as a float numpy array."""
    project = _project(project_or_path)
    inputs = _inputs(project)
    values = inputs.get(input_key)
    if not isinstance(values, list):
        if input_key not in inputs:
            raise ValueError(
                f"{project.path}: spec.inputs.{input_key} not found "
                f"(available inputs: {_available_keys(inputs)})"
            )
        raise ValueError(
            f"{project.path}: spec.inputs.{input_key} must be a list, "
            f"found {type(values).__name__}"
        )
    return np.array([float(value) for value in values], dtype=float)


def _simulation(project: StudyProject) -> Mapping[str, Any]:
    spec = project.raw.get("spec", {})
    simulation = spec.get("simulation", {}) if isinstance(spec, Mapping) else {}
    if not isinstance(simulation, Mapping):
        raise ValueError(
            f"{project.path}: spec.simulation must be a mapping, "
            f"found {type(simulation).__name__}"
        )
    return simulation


def load_simulation_seed(project_or_path: ProjectRef, stream: str) -> int:
    """Load one named RNG stream from ``spec.simulation.seeds``.

    A stage that owns an RNG stream reads its seed through here instead of
    hardcoding one, so the value in the manifest is the value the stage used.
    Declaring a seed a stage never reads is worse than declaring none: the
    manifest then looks reproducible while the run is governed by a literal
    buried in a script.

    Args:
        project_or_path: Loaded project, project directory, or ``project.yaml``.
        stream: Name of the declared stream, e.g. ``"policy"``.

    Returns:
        The declared integer seed.

    Raises:
        ValueError: If ``spec.simulation.seeds`` is missing, is not a mapping of
            integers, or does not declare ``stream``. The message lists the
            streams the study does declare.
    """
    project = _project(project_or_path)
    streams = _simulation(project).get("seeds")
    if not isinstance(streams, Mapping) or not streams:
        raise ValueError(
            f"{project.path}: spec.simulation.seeds must declare the named RNG "
            f"streams this study draws from, including {stream!r}; found "
            f"{type(streams).__name__}"
        )
    if stream not in streams:
        available = ", ".join(sorted(str(key) for key in streams))
        raise ValueError(
            f"{project.path}: spec.simulation.seeds does not declare "
            f"{stream!r} (declared streams: {available})"
        )
    value = streams[stream]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(
            f"{project.path}: spec.simulation.seeds.{stream} must be an "
            f"integer, found {type(value).__name__}"
        )
    return value


def load_powerflow_backend_by_stage(project_or_path: ProjectRef) -> dict[str, str]:
    """Load the per-stage backend overrides a study declares.

    A study whose stages solve with different engines cannot be described by a
    single scalar. ``ev_hosting_flex`` is the motivating case: its full-network
    voltage path runs on lightsim2grid while every other solve runs on
    pandapower native, so recording one ID named an engine some stage did not
    use -- the failure ``provenance.powerflow_backend`` exists to prevent.

    Args:
        project_or_path: Loaded project, project directory, or ``project.yaml``.

    Returns:
        Stage ID to backend ID, empty when the study declares no overrides.

    Raises:
        ValueError: If the mapping is malformed, names an unregistered backend,
            or keys a stage the workflow does not define. The stage check
            matters most: a renamed stage would otherwise leave a stale
            override that silently stops applying while still being recorded.
    """
    project = _project(project_or_path)
    declared = _simulation(project).get("powerflowBackendByStage")
    if declared is None:
        return {}
    if not isinstance(declared, Mapping) or not declared:
        raise ValueError(
            f"{project.path}: spec.simulation.powerflowBackendByStage must be a "
            f"non-empty mapping of stage ID to backend ID, found "
            f"{type(declared).__name__}"
        )
    registered = _registered_backend_ids()
    stage_ids = {stage.id for stage in project.workflow.stages}
    overrides: dict[str, str] = {}
    for stage_id, backend_id in declared.items():
        if not isinstance(backend_id, str) or not backend_id.strip():
            raise ValueError(
                f"{project.path}: spec.simulation.powerflowBackendByStage"
                f".{stage_id} must be a non-empty string, found "
                f"{type(backend_id).__name__}"
            )
        if stage_id not in stage_ids:
            raise ValueError(
                f"{project.path}: spec.simulation.powerflowBackendByStage keys "
                f"stage {stage_id!r}, which the workflow does not define "
                f"(defined stages: {', '.join(sorted(stage_ids))})"
            )
        resolved = backend_id.strip()
        if resolved not in registered:
            raise ValueError(
                f"{project.path}: spec.simulation.powerflowBackendByStage"
                f".{stage_id} names an unregistered backend {resolved!r} "
                f"(registered: {', '.join(sorted(registered))})"
            )
        overrides[str(stage_id)] = resolved
    return overrides


def _registered_backend_ids() -> list[str]:
    from gridalyn.simulation.backends.registry import default_powerflow_backend_registry

    return [
        descriptor.backend_id
        for descriptor in default_powerflow_backend_registry().list_descriptors()
    ]


def load_powerflow_backend_id(
    project_or_path: ProjectRef, stage_id: str | None = None
) -> str:
    """Load the power-flow backend ID a study declares in ``spec.simulation``.

    Every stage that solves power flow through ``pandapower.runpp`` resolves
    through this ID rather than calling the solver itself (the one exemption is
    ``runpp_3ph``, which the backend contract does not model), so that what a
    run solved with is what ``provenance.powerflow_backend`` records. A study
    that declares nothing gets the registry default, which needs no optional
    extra.

    Args:
        project_or_path: Loaded project, project directory, or ``project.yaml``.
        stage_id: Workflow stage being resolved for. When given, a matching
            ``powerflowBackendByStage`` override wins over the study default.

    Returns:
        The declared backend ID, or ``DEFAULT_POWERFLOW_BACKEND_ID`` when the
        study declares none.

    Raises:
        ValueError: If ``spec.simulation.powerflowBackend`` is present but is
            not a non-empty string, or names a backend the repository does not
            register. The message lists the registered IDs.
    """
    from gridalyn.simulation.backends.contract import DEFAULT_POWERFLOW_BACKEND_ID

    project = _project(project_or_path)
    if stage_id is not None:
        override = load_powerflow_backend_by_stage(project).get(stage_id)
        if override is not None:
            return override
    declared = _simulation(project).get("powerflowBackend")
    if declared is None:
        return DEFAULT_POWERFLOW_BACKEND_ID
    if not isinstance(declared, str) or not declared.strip():
        raise ValueError(
            f"{project.path}: spec.simulation.powerflowBackend must be a "
            f"non-empty string, found {type(declared).__name__}"
        )
    backend_id = declared.strip()
    registered = _registered_backend_ids()
    if backend_id not in registered:
        raise ValueError(
            f"{project.path}: spec.simulation.powerflowBackend names an "
            f"unregistered backend {backend_id!r} "
            f"(registered: {', '.join(sorted(registered))})"
        )
    return backend_id


__all__ = [
    "load_der_dispatch_assets",
    "load_generated_bus_loads_mw",
    "load_generated_load_multipliers",
    "load_generated_load_profiles",
    "load_numeric_profile_array",
    "load_powerflow_backend_by_stage",
    "load_powerflow_backend_id",
    "load_simulation_seed",
    "load_prosumer_assets",
    "load_radial_feeder_spec",
    "load_standard_powerflow_scenarios",
    "load_voltage_control_der_spec",
    "project_input",
]
