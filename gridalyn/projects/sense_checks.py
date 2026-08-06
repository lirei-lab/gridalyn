"""Objective-level verification for Gridalyn demo projects."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from gridalyn.foundation.platform.reports import ReportMetadata, write_report
from gridalyn.projects.loader import load_project
from gridalyn.projects.models import StudyProject

CheckList = list[dict[str, Any]]


def project_sense_check(path: Path | str, write: bool = True) -> dict[str, Any]:
    """Run objective-specific plausibility checks for a project.

    These checks complement project validation. Project validation answers
    whether required artifacts exist and reports follow the platform schema.
    Sense checks answer whether the generated values make sense for the demo's
    stated objective.

    The returned dict keeps the flat legacy shape (top-level ``valid``,
    ``score``, ``checks``, ...) that ``project_verify`` and the CLI read; the
    on-disk report is routed through the platform ``write_report`` helper and
    carries the governed envelope only (audit section 5.3).
    """

    project = load_project(_project_file(path))
    checks: CheckList = []
    _common_artifact_checks(project, checks)
    declared_checks = _declarative_sense_checks(project, checks)
    checker = _PROJECT_CHECKERS.get(project.name)
    if checker is None and declared_checks == 0:
        _record(
            checks,
            "project_has_registered_sense_checks",
            False,
            "error",
            project.name,
            f"one of {sorted(_PROJECT_CHECKERS)}",
        )
    elif checker is not None and (missing := _missing_objective_artifacts(project)):
        _record(
            checks,
            "missing_objective_artifact",
            False,
            "error",
            missing,
            "all objective artifacts exist",
            "Run the project workflow before objective-level sense checks.",
        )
    elif checker is not None:
        checker(project, checks)

    error_failures = [
        item for item in checks if item["severity"] == "error" and not item["passed"]
    ]
    passed_count = sum(1 for item in checks if item["passed"])
    score = passed_count / len(checks) if checks else 0.0
    summary: dict[str, Any] = {
        "checked_count": len(checks),
        "passed_count": passed_count,
        "failed_count": len(checks) - passed_count,
        "error_count": len(error_failures),
        "score": score,
    }
    validation: dict[str, Any] = {
        "valid": not error_failures,
        "errors": [item["id"] for item in error_failures],
        "warnings": [
            item["id"]
            for item in checks
            if item["severity"] == "warning" and not item["passed"]
        ],
    }
    payload = {
        "report_id": "project_sense_check_report",
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_domain": "project_verification",
        "project": project.name,
        "inputs": [],
        "artifacts": [],
        "summary": summary,
        "validation": validation,
        "valid": not error_failures,
        "checked_count": len(checks),
        "passed_count": passed_count,
        "failed_count": len(checks) - passed_count,
        "error_count": len(error_failures),
        "score": score,
        "checks": checks,
    }
    if write:
        out = project.root / "outputs" / "reports" / "project_sense_check_report.json"
        write_report(
            out,
            metadata=ReportMetadata(
                report_id="project_sense_check_report",
                source_domain="project_verification",
                project={"name": project.name},
            ),
            inputs=[],
            artifacts=[],
            summary=summary,
            validation=validation,
        )
    return payload


def _project_file(path: Path | str) -> Path:
    candidate = Path(path)
    if candidate.name == "project.yaml":
        return candidate
    return candidate / "project.yaml"


def _read_json(project: StudyProject, relative: str) -> dict[str, Any]:
    return json.loads((project.root / relative).read_text(encoding="utf-8"))


def _summary(project: StudyProject, relative: str) -> dict[str, Any]:
    return _read_json(project, relative).get("summary", {})


def _csv(project: StudyProject, relative: str) -> pd.DataFrame:
    return pd.read_csv(project.root / relative)


def _record(
    checks: CheckList,
    check_id: str,
    passed: bool,
    severity: str,
    observed: Any,
    expected: Any,
    message: str | None = None,
) -> None:
    checks.append(
        {
            "id": check_id,
            "severity": severity,
            "passed": bool(passed),
            "observed": _json_safe(observed),
            "expected": _json_safe(expected),
            "message": message or check_id.replace("_", " "),
        }
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    return value


def _check(
    checks: CheckList,
    check_id: str,
    condition: bool,
    observed: Any,
    expected: Any,
    severity: str = "error",
) -> None:
    _record(checks, check_id, condition, severity, observed, expected)


def _between(value: float | int | None, low: float, high: float) -> bool:
    return value is not None and low <= float(value) <= high


def _common_artifact_checks(project: StudyProject, checks: CheckList) -> None:
    _check(
        checks,
        "project_manifest_exists",
        (project.root / "outputs/manifests/project_run_manifest.json").exists(),
        "outputs/manifests/project_run_manifest.json",
        "existing run manifest",
    )
    required = project.raw.get("spec", {}).get("validation", {})
    for index, relative in enumerate(required.get("requiredReports", []), start=1):
        _check(
            checks,
            f"required_report_{index}_exists",
            (project.base_dir / relative).exists(),
            relative,
            "existing report",
        )
    for index, relative in enumerate(required.get("requiredFigures", []), start=1):
        figure = project.base_dir / relative
        _check(
            checks,
            f"required_figure_{index}_exists",
            figure.exists() and figure.stat().st_size > 0,
            relative,
            "existing non-empty figure",
        )


def _declarative_sense_checks(project: StudyProject, checks: CheckList) -> int:
    declared = project.raw.get("spec", {}).get("validation", {}).get("senseChecks", [])
    if not isinstance(declared, list):
        _record(
            checks,
            "declared_sense_checks_shape",
            False,
            "error",
            type(declared).__name__,
            "list",
        )
        return 1

    for index, rule in enumerate(declared, start=1):
        _run_declarative_sense_check(project, checks, rule, index)
    return len(declared)


def _run_declarative_sense_check(
    project: StudyProject,
    checks: CheckList,
    rule: dict[str, Any],
    index: int,
) -> None:
    check_id = str(rule.get("id") or f"declared_sense_check_{index}")
    severity = str(rule.get("severity", "error"))
    report_path = rule.get("report")
    field = rule.get("field")
    if not report_path or not field:
        _record(
            checks,
            check_id,
            False,
            severity,
            {"report": report_path, "field": field},
            "rule with report and field",
            rule.get("message"),
        )
        return

    try:
        payload = json.loads(
            (project.base_dir / str(report_path)).read_text(encoding="utf-8")
        )
        observed = _resolve_field(payload, str(field))
    except Exception as exc:
        _record(
            checks,
            check_id,
            False,
            severity,
            str(exc),
            f"{report_path}:{field}",
            rule.get("message"),
        )
        return

    passed, expected = _evaluate_declarative_rule(observed, rule)
    _record(
        checks,
        check_id,
        passed,
        severity,
        observed,
        expected,
        rule.get("message"),
    )


def _resolve_field(payload: dict[str, Any], field: str) -> Any:
    value: Any = payload
    for part in field.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            raise KeyError(field)
    return value


def _evaluate_declarative_rule(observed: Any, rule: dict[str, Any]) -> tuple[bool, Any]:
    expectations = []
    if "equals" in rule:
        expected = rule["equals"]
        expectations.append((observed == expected, f"== {expected!r}"))
    numeric_ops = [
        ("min", lambda value, limit: value >= limit, ">="),
        ("max", lambda value, limit: value <= limit, "<="),
        ("gt", lambda value, limit: value > limit, ">"),
        ("gte", lambda value, limit: value >= limit, ">="),
        ("lt", lambda value, limit: value < limit, "<"),
        ("lte", lambda value, limit: value <= limit, "<="),
    ]
    for key, predicate, label in numeric_ops:
        if key in rule:
            limit = float(rule[key])
            try:
                observed_number = float(observed)
            except (TypeError, ValueError):
                expectations.append((False, f"{label} {limit}"))
            else:
                expectations.append(
                    (predicate(observed_number, limit), f"{label} {limit}")
                )
    if not expectations:
        return False, "one of equals, min, max, gt, gte, lt, lte"
    return all(item[0] for item in expectations), " and ".join(
        item[1] for item in expectations
    )


def _missing_objective_artifacts(project: StudyProject) -> list[str]:
    return [
        relative
        for relative in _PROJECT_OBJECTIVE_ARTIFACTS.get(project.name, ())
        if not (project.root / relative).exists()
    ]


def _check_minimal(project: StudyProject, checks: CheckList) -> None:
    report = _summary(project, "outputs/reports/minimal_grid_report.json")
    buses = _csv(project, "outputs/data/buses.csv")
    lines = _csv(project, "outputs/data/lines.csv")
    loads = _csv(project, "outputs/data/loads.csv")
    _check(
        checks,
        "minimal_intent_is_explicit",
        report.get("project_intent") == "minimal_grid_hello_world",
        report.get("project_intent"),
        "minimal_grid_hello_world",
    )
    _check(
        checks,
        "minimal_bus_count",
        report.get("bus_count") == 5 and len(buses) == 5,
        {"report": report.get("bus_count"), "csv": len(buses)},
        5,
    )
    _check(
        checks,
        "minimal_line_count",
        report.get("line_count") == 4 and len(lines) == 4,
        {"report": report.get("line_count"), "csv": len(lines)},
        4,
    )
    _check(
        checks,
        "minimal_load_count",
        report.get("load_count") == 4 and len(loads) == 4,
        {"report": report.get("load_count"), "csv": len(loads)},
        4,
    )
    _check(
        checks,
        "minimal_powerflow_converges",
        report.get("powerflow_converged") is True,
        report.get("powerflow_converged"),
        True,
    )
    _check(
        checks,
        "minimal_voltage_is_near_nominal",
        _between(report.get("min_voltage_pu"), 0.98, 1.02),
        report.get("min_voltage_pu"),
        "0.98 <= min_voltage_pu <= 1.02",
    )
    _check(
        checks,
        "minimal_not_overloaded",
        float(report.get("max_line_loading_pct", 999)) < 20.0,
        report.get("max_line_loading_pct"),
        "< 20%",
    )
    _check(
        checks,
        "minimal_has_positive_load",
        float(report.get("total_load_mw", 0)) > 0,
        report.get("total_load_mw"),
        "> 0 MW",
    )


def _check_ieee33(project: StudyProject, checks: CheckList) -> None:
    base = _summary(project, "outputs/reports/ieee33_powerflow_report.json")
    scenario = _summary(
        project, "outputs/reports/ieee33_scenario_comparison_report.json"
    )
    results = _csv(project, "outputs/data/scenario_results.csv").set_index(
        "scenario_id"
    )
    expected_ids = {
        "baseline",
        "load_growth_20",
        "pv_midday",
        "ev_evening_peak",
        "pv_plus_ev",
    }
    _check(
        checks,
        "ieee33_bus_count",
        base.get("bus_count") == 33,
        base.get("bus_count"),
        33,
    )
    _check(
        checks,
        "ieee33_line_count",
        base.get("line_count") == 37,
        base.get("line_count"),
        "37 pandapower case33bw branches",
    )
    _check(
        checks,
        "ieee33_single_slack",
        base.get("slack_count") == 1,
        base.get("slack_count"),
        1,
    )
    _check(
        checks,
        "ieee33_baseline_converges",
        base.get("converged") is True,
        base.get("converged"),
        True,
    )
    _check(
        checks,
        "ieee33_has_expected_scenarios",
        set(scenario.get("scenario_ids", [])) == expected_ids,
        scenario.get("scenario_ids"),
        sorted(expected_ids),
    )
    _check(
        checks,
        "ieee33_scenario_count",
        scenario.get("scenario_count") == 5,
        scenario.get("scenario_count"),
        5,
    )
    _check(
        checks,
        "ieee33_load_growth_worsens_voltage",
        results.loc["load_growth_20", "min_voltage_pu"]
        <= results.loc["baseline", "min_voltage_pu"],
        float(results.loc["load_growth_20", "min_voltage_pu"]),
        "<= baseline",
    )
    _check(
        checks,
        "ieee33_ev_peak_increases_net_demand",
        results.loc["ev_evening_peak", "net_demand_mw"]
        > results.loc["baseline", "net_demand_mw"],
        float(results.loc["ev_evening_peak", "net_demand_mw"]),
        "> baseline",
    )
    _check(
        checks,
        "ieee33_pv_reduces_net_demand",
        results.loc["pv_midday", "net_demand_mw"]
        < results.loc["baseline", "net_demand_mw"],
        float(results.loc["pv_midday", "net_demand_mw"]),
        "< baseline",
    )
    _check(
        checks,
        "ieee33_voltage_range_plausible",
        _between(scenario.get("min_voltage_pu"), 0.85, 1.08),
        scenario.get("min_voltage_pu"),
        "0.85 <= min_voltage_pu <= 1.08",
    )


def _check_synthetic_geojson(project: StudyProject, checks: CheckList) -> None:
    footprint = _summary(project, "outputs/reports/building_footprints_report.json")
    report = _summary(project, "outputs/reports/synthetic_geojson_feeder_report.json")
    validation = _read_json(
        project, "outputs/reports/synthetic_network_validation_report.json"
    )
    buses = _csv(project, "outputs/data/buses.csv")
    lines = _csv(project, "outputs/data/lines.csv")
    loads = _csv(project, "outputs/data/loads.csv")
    _check(
        checks,
        "geojson_building_count",
        footprint.get("building_count") == 9 and report.get("building_count") == 9,
        {
            "input": footprint.get("building_count"),
            "network": report.get("building_count"),
        },
        9,
    )
    _check(
        checks,
        "geojson_loads_match_buildings",
        report.get("pandapower_load_count")
        == report.get("building_count")
        == len(loads),
        {"report_loads": report.get("pandapower_load_count"), "csv_loads": len(loads)},
        "one load per building",
    )
    _check(
        checks,
        "geojson_network_has_transformers",
        int(report.get("pandapower_transformer_count", 0)) >= 1,
        report.get("pandapower_transformer_count"),
        ">= 1",
    )
    _check(
        checks,
        "geojson_powerflow_converges",
        report.get("powerflow_converged") is True,
        report.get("powerflow_converged"),
        True,
    )
    _check(
        checks,
        "geojson_validation_report_valid",
        validation.get("valid") is True,
        validation.get("valid"),
        True,
    )
    _check(
        checks,
        "geojson_no_isolated_nodes",
        validation.get("topology", {}).get("isolated_nodes_total") == 0,
        validation.get("topology", {}).get("isolated_nodes_total"),
        0,
    )
    _check(
        checks,
        "geojson_voltage_plausible",
        _between(report.get("min_voltage_pu"), 0.90, 1.05),
        report.get("min_voltage_pu"),
        "0.90 <= min_voltage_pu <= 1.05",
    )
    _check(
        checks,
        "geojson_tables_non_empty",
        not buses.empty and not lines.empty and not loads.empty,
        {"buses": len(buses), "lines": len(lines), "loads": len(loads)},
        "non-empty tables",
    )


def _check_prosumer(project: StudyProject, checks: CheckList) -> None:
    feeder = _summary(project, "outputs/reports/synthetic_feeder_report.json")
    market = _summary(project, "outputs/reports/prosumer_realtime_market_report.json")
    dispatch = _csv(project, "outputs/operations/battery_dispatch.csv")
    prosumers = _csv(project, "outputs/data/prosumers.csv")
    _check(
        checks,
        "prosumer_feeder_converges",
        feeder.get("converged") is True,
        feeder.get("converged"),
        True,
    )
    _check(
        checks,
        "prosumer_count_positive",
        int(market.get("prosumer_count", 0)) > 0
        and len(prosumers) == int(market.get("prosumer_count", 0)),
        {"report": market.get("prosumer_count"), "csv": len(prosumers)},
        "> 0 and consistent",
    )
    horizon = int(market.get("forecast_horizon_intervals", 0))
    intervals = int(market.get("interval_count", 0))
    _check(
        checks,
        "prosumer_horizon_tiles_intervals",
        horizon > 0 and intervals % horizon == 0,
        {"horizon": horizon, "intervals": intervals},
        "rolling horizon divides interval count",
    )
    _check(
        checks,
        "prosumer_cleared_not_above_required",
        float(market.get("total_cleared_mwh", 0))
        <= float(market.get("total_required_mwh", 0)) + 1e-9,
        market.get("total_cleared_mwh"),
        "<= total_required_mwh",
    )
    _check(
        checks,
        "prosumer_peak_import_not_increased",
        float(market.get("peak_import_after_mw", 999))
        <= float(market.get("peak_import_before_mw", 0)) + 1e-9,
        market.get("peak_import_after_mw"),
        "<= before",
    )
    _check(
        checks,
        "prosumer_voltage_after_safe",
        float(market.get("min_voltage_after_pu", 0)) >= 0.95,
        market.get("min_voltage_after_pu"),
        ">= 0.95",
    )
    _check(
        checks,
        "prosumer_line_loading_after_safe",
        float(market.get("max_line_loading_after_percent", 999)) < 100.0,
        market.get("max_line_loading_after_percent"),
        "< 100%",
    )
    _check(
        checks,
        "prosumer_dispatch_non_negative",
        (dispatch["dispatch_mwh"] >= -1e-9).all(),
        float(dispatch["dispatch_mwh"].min()),
        ">= 0",
    )


def _check_der(project: StudyProject, checks: CheckList) -> None:
    feeder = _summary(project, "outputs/reports/der_feeder_report.json")
    opt = _summary(project, "outputs/reports/der_voltage_optimization_report.json")
    dispatch = _csv(project, "outputs/operations/der_dispatch.csv")
    _check(
        checks,
        "der_feeder_converges",
        feeder.get("converged") is True,
        feeder.get("converged"),
        True,
    )
    _check(
        checks,
        "der_solver_optimal",
        opt.get("solver_status") in {"optimal", "optimal_inaccurate"},
        opt.get("solver_status"),
        "optimal or optimal_inaccurate",
    )
    available = float(opt.get("total_pv_available_mw", 0))
    accounted = float(opt.get("total_pv_dispatch_mw", 0)) + float(
        opt.get("total_pv_curtailment_mw", 0)
    )
    _check(
        checks,
        "der_energy_accounting_balances",
        abs(accounted - available) <= 1e-5,
        {"available": available, "dispatch_plus_curtailment": accounted},
        "dispatch + curtailment ~= available",
    )
    _check(
        checks,
        "der_max_voltage_reduced",
        float(opt.get("verified_max_voltage_after_pu", 9))
        <= float(opt.get("verified_max_voltage_before_pu", 0)) + 1e-9,
        opt.get("verified_max_voltage_after_pu"),
        "<= before",
    )
    _check(
        checks,
        "der_voltage_upper_limit_met",
        float(opt.get("verified_max_voltage_after_pu", 9)) <= 1.05 + 1e-6,
        opt.get("verified_max_voltage_after_pu"),
        "<= 1.05",
    )
    _check(
        checks,
        "der_voltage_lower_limit_met",
        float(opt.get("verified_min_voltage_after_pu", 0)) >= 0.95 - 1e-6,
        opt.get("verified_min_voltage_after_pu"),
        ">= 0.95",
    )
    _check(
        checks,
        "der_dispatch_within_availability",
        (dispatch["pv_dispatch_mw"] <= dispatch["pv_available_mw"] + 1e-6).all()
        and (dispatch["pv_dispatch_mw"] >= -1e-6).all(),
        "dispatch bounds",
        "0 <= dispatch <= available",
    )


def _check_rl(project: StudyProject, checks: CheckList) -> None:
    feeder = _summary(project, "outputs/reports/rl_feeder_report.json")
    report = _summary(project, "outputs/reports/rl_voltage_control_report.json")
    q_table = _csv(project, "outputs/operations/q_table.csv")
    policy = _csv(project, "outputs/operations/learned_policy.csv")
    _check(
        checks,
        "rl_engine_is_lightsim2grid",
        feeder.get("simulation_engine") == "lightsim2grid"
        and report.get("simulation_engine") == "lightsim2grid",
        {
            "feeder": feeder.get("simulation_engine"),
            "control": report.get("simulation_engine"),
        },
        "lightsim2grid",
    )
    _check(
        checks,
        "rl_algorithm_is_q_learning",
        report.get("algorithm") == "tabular_q_learning_voltage_control",
        report.get("algorithm"),
        "tabular_q_learning_voltage_control",
    )
    _check(
        checks,
        "rl_training_has_enough_episodes",
        int(report.get("episode_count", 0)) >= 50,
        report.get("episode_count"),
        ">= 50",
    )
    _check(
        checks,
        "rl_evaluation_is_day_profile",
        report.get("evaluation_step_count") == 24,
        report.get("evaluation_step_count"),
        24,
    )
    _check(
        checks,
        "rl_reward_improves",
        float(report.get("total_reward_last_episode", -1e9))
        > float(report.get("total_reward_first_episode", 1e9)),
        {
            "first": report.get("total_reward_first_episode"),
            "last": report.get("total_reward_last_episode"),
        },
        "last > first",
    )
    _check(
        checks,
        "rl_control_reduces_violations",
        int(report.get("voltage_violation_count_controlled", 999))
        <= int(report.get("voltage_violation_count_uncontrolled", 0)),
        report.get("voltage_violation_count_controlled"),
        "<= uncontrolled",
    )
    _check(
        checks,
        "rl_control_reduces_voltage_deviation",
        float(report.get("controlled_voltage_deviation_sum", 999))
        < float(report.get("uncontrolled_voltage_deviation_sum", 0)),
        report.get("controlled_voltage_deviation_sum"),
        "< uncontrolled",
    )
    _check(
        checks,
        "rl_action_space_has_charge_neutral_discharge",
        set(round(float(v), 2) for v in q_table["action_mw"].unique()).issuperset(
            {-0.12, 0.0, 0.12}
        ),
        sorted(q_table["action_mw"].unique()),
        "charge, neutral, discharge",
    )
    _check(
        checks,
        "rl_policy_tables_non_empty",
        not q_table.empty and not policy.empty,
        {"q_table": len(q_table), "policy": len(policy)},
        "non-empty",
    )


_PROJECT_CHECKERS: dict[str, Callable[[StudyProject, CheckList], None]] = {
    "minimal_grid_project": _check_minimal,
    "ieee_33_bus_demo": _check_ieee33,
    "synthetic_geojson_feeder": _check_synthetic_geojson,
    "prosumer_battery_market": _check_prosumer,
    "der_voltage_optimization": _check_der,
    "rl_voltage_control_lightsim": _check_rl,
}

_PROJECT_OBJECTIVE_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "minimal_grid_project": (
        "outputs/reports/minimal_grid_report.json",
        "outputs/data/buses.csv",
        "outputs/data/lines.csv",
        "outputs/data/loads.csv",
    ),
    "ieee_33_bus_demo": (
        "outputs/reports/ieee33_powerflow_report.json",
        "outputs/reports/ieee33_scenario_comparison_report.json",
        "outputs/data/scenario_results.csv",
    ),
    "synthetic_geojson_feeder": (
        "outputs/reports/building_footprints_report.json",
        "outputs/reports/synthetic_geojson_feeder_report.json",
        "outputs/reports/synthetic_network_validation_report.json",
        "outputs/data/buses.csv",
        "outputs/data/lines.csv",
        "outputs/data/loads.csv",
    ),
    "prosumer_battery_market": (
        "outputs/reports/synthetic_feeder_report.json",
        "outputs/reports/prosumer_realtime_market_report.json",
        "outputs/operations/battery_dispatch.csv",
        "outputs/data/prosumers.csv",
    ),
    "der_voltage_optimization": (
        "outputs/reports/der_feeder_report.json",
        "outputs/reports/der_voltage_optimization_report.json",
        "outputs/operations/der_dispatch.csv",
    ),
    "rl_voltage_control_lightsim": (
        "outputs/reports/rl_feeder_report.json",
        "outputs/reports/rl_voltage_control_report.json",
        "outputs/operations/q_table.csv",
        "outputs/operations/learned_policy.csv",
    ),
}


__all__ = ["project_sense_check"]
