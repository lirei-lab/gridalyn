"""Report-contract coverage gate (R3), locking in the 02-03 audit.

The SDK's cross-cutting rule is that every artifact-producing run emits a
governed platform report via ``write_report`` — never hand-written report JSON.
Enforcing that mechanically is not as simple as banning ``json.dump``: the repo
writes 69 JSON artifacts directly plus 18 through in-repo JSON helpers, and the
overwhelming majority are legitimately *not* platform reports (catalogs,
manifests, scorecards, run-lineage records, cache metadata, GeoJSON, study data
payloads). Each has its own shape and its own contract.

``docs/development/report-contract-audit.md`` (the tracked audit)
classified all of them by reading the code that builds each payload. This module
pins that classification so it cannot rot.

The classification rule
-----------------------

A site is a ``GOVERNED-VIOLATION`` when all three hold:

* **Role** — the payload is the run's own account of itself: it carries an
  ``inputs`` and/or ``artifacts`` section naming *that run's* I/O. A sidecar
  describing a model, a case comparison or a cache does not qualify, however
  many envelope keys it happens to carry.
* **Destination** — it is written to a governed report location: a filename
  ending ``_report.json``, or a path under a project's ``outputs/reports/``
  (``ArtifactLayout.reports``).
* **Not routed** — the writing module never calls ``build_report`` /
  ``write_report``, and nothing downstream re-wraps the document into a governed
  report.

This replaces the audit's original ``>= 6 of 8 REQUIRED_REPORT_FIELDS`` bar,
which was withdrawn for two reasons recorded in audit §1: the count is not a
property of a site (``write_locational_clearing_outputs`` writes 6/8 for one
caller and 5/8 for the other, both verified on disk), and the headline swung
11 → 5/6/7 → 1 across adjacent bars. Field counts survive in the audit as
*evidence*, scored statically at the builder; they are no longer the rule.

The tests
---------

* :func:`test_required_report_fields_are_unchanged` — the audit reasons about
  this envelope throughout. If the contract grows or loses a field, every
  classification must be revisited, so pin the tuple.
* :func:`test_every_direct_json_write_site_is_classified` — re-derives the site
  list by AST scan. A **new** direct-JSON write fails here until someone
  classifies it in the audit. This is the guard that stops a hand-written
  governed report from appearing silently.
* :func:`test_every_helper_routed_write_is_classified` — the same guard for
  documents written through an in-repo JSON helper, which the direct scan counts
  once at the helper and would otherwise miss entirely (audit §6).
* :func:`test_param_serializing_helpers_are_pinned` — keeps the helper list
  itself honest: a new helper that serializes a caller-supplied payload fails
  here, so the helper pass cannot silently under-cover.
* :func:`test_no_classified_site_vanished_silently` — the reverse direction. A
  pinned site that disappears (moved, renamed, deleted) must be reflected in the
  audit rather than quietly dropping out of the denominator.
* :func:`test_site_keys_identify_exactly_one_write` — no key may stand for two
  writes, in either enumeration. This is what stops a new governed report from
  hiding behind a pinned one; see "Site keys" below.
* :func:`test_known_violations_are_visible_not_tolerated` — the five
  ``GOVERNED-VIOLATION`` sites are named here with their remedy section, so they
  are impossible to forget. Fixing one without updating the audit fails. (Six
  at audit time; the §5.2 duplicate write in ``operations/verification.py`` was
  removed by the 2026-08-06 amendment.)
* :func:`test_audit_counts_reconcile` and
  :func:`test_helper_routed_counts_reconcile` — examined == violations +
  not-a-report + already-governed, in each enumeration, against the live scan.

Site keys
---------

Sites are keyed by ``"<path>::<enclosing qualname>::<payload identity>#<n>"``
rather than by line number: line numbers shift under any edit above them, which
would make this gate fail for reasons that have nothing to do with the report
contract. The qualname and the occurrence ordinal are both load-bearing — an
earlier version keyed on ``(file, payload-variable-name)`` alone and a second
governed report added to an already-pinned file under an already-pinned payload
name passed every test silently. Failure messages report the live line numbers,
including the sibling occurrences in the same group, so a finding can be located.

Coupling to ``.planning/``
--------------------------

Two tests read the audit document. ``.planning/`` is currently untracked, so on
a checkout that lacks it those tests fail — deliberately, with a message naming
the missing path, rather than skipping. The pins here are only meaningful
alongside the rationale recorded there; a silent skip would leave the gate
looking green while the classification it enforces was unreadable.
"""

from __future__ import annotations

import ast
import unittest
from collections import defaultdict
from pathlib import Path

from gridalyn.foundation.platform.reports import REQUIRED_REPORT_FIELDS

_REPO_ROOT = Path(__file__).resolve().parents[1]
_AUDIT_REL = "docs/development/report-contract-audit.md"
_AUDIT_PATH = _REPO_ROOT / _AUDIT_REL

# Only shipped code is in scope. `tests/` is scaffolding, not an
# artifact-producing run, so it carries no obligation under R3.
_SCAN_ROOTS = ("gridalyn", "projects")

# The eight fields as of the audit. Pinned so that a change to the contract
# forces the classification to be redone rather than silently invalidated.
_AUDITED_REQUIRED_FIELDS = (
    "report_id",
    "schema_version",
    "created_at",
    "source_domain",
    "inputs",
    "artifacts",
    "summary",
    "validation",
)

# --------------------------------------------------------------------------
# GOVERNED-VIOLATION — the run's own report, at a governed report destination,
# hand-serialized by a module that never routes through build_report /
# write_report. Recorded, NOT tolerated: each maps to a remedy section in the
# audit. This plan deliberately changed no production code.
# --------------------------------------------------------------------------
_KNOWN_VIOLATIONS: dict[str, str] = {
    # EMPTY since 2026-08-06 — all five audit §5 remedies are applied (§5.1
    # artifacts.py, §5.2 locational_verification.py, §5.3 sense_checks.py,
    # §5.4 twin/adapters/validation.py, §5.5 the clearing script); each site
    # now routes through build_report/write_report. See the audit's dated
    # amendment. A NEW hand-serialized report must be FIXED, not added here:
    # this dict emptied the same way the layer gate's exception allowlist did
    # — by fixing causes — and should stay empty.
}

# --------------------------------------------------------------------------
# ALREADY-GOVERNED — the contract's own serializer.
# --------------------------------------------------------------------------
_ALREADY_GOVERNED: frozenset[str] = frozenset(
    {
        # write_json_report, called by write_report after validate_report.
        "gridalyn/foundation/platform/reports.py::write_json_report::payload#0",
    }
)

# --------------------------------------------------------------------------
# NOT-A-REPORT — domain documents. Each was classified from the role its writer
# plays and the destination it writes to; see the per-site table in the audit.
# Keyed per file to keep the pin readable and diffable.
# --------------------------------------------------------------------------
_NOT_A_REPORT_BY_FILE: dict[str, tuple[str, ...]] = {
    "gridalyn/assets/modeling/artifacts.py": (
        "write_building_model_artifacts::manifest#0",
    ),
    "gridalyn/assets/modeling/scenarios.py": (
        "write_scenario_model_artifacts::manifest#0",
    ),
    "gridalyn/interfaces/reporting/schemas.py": ("write_json::payload#0",),
    "gridalyn/operations/artifacts.py": (
        "materialize_flexibility_operation_artifacts::catalog#0",
    ),
    # The sidecar beside the two parquets it names, NOT the run's report: the
    # run's report is written separately by the caller to a different path.
    # Caller-independent, which the old field-count rule was not.
    "gridalyn/operations/clearing/selection.py": (
        "write_locational_clearing_outputs::report_with_artifacts#0",
    ),
    "gridalyn/operations/runs.py": ("write_operation_run::payload#0",),
    "gridalyn/operations/settlement.py": (
        "write_flexibility_clearing_scorecard::scorecard#0",
    ),
    "gridalyn/operations/verification.py": ("write_shadow_report::report#0",),
    "gridalyn/projects/dashboard_catalog.py": ("write_dashboard_catalog::catalog#0",),
    # outputs/reports/regression_report.json — governed destination, but the
    # payload never records its own inputs/artifacts. Role test rejects it.
    "gridalyn/projects/regression.py": ("write_regression_report::report#0",),
    "gridalyn/projects/runner.py": ("_write_manifest::payload#0",),
    "gridalyn/projects/workflows/digital_twin/build.py": (
        "write_build_manifest::manifest#0",
    ),
    "gridalyn/projects/workflows/digital_twin/ev_scenarios.py": (
        "generate_ev_scenarios::index_doc#0",
        "generate_ev_scenarios::scenario_doc#0",
    ),
    "gridalyn/projects/workflows/digital_twin/ev_timeseries.py": (
        (
            "generate_ev_timeseries::<inline:area_m2_used_for_generation,assignment"
            "_seed,created_at,resolution_minutes,scenarios,start_timestamp>#0"
        ),
    ),
    "gridalyn/projects/workflows/scripts/generate_digital_twin_asset_registry.py": (
        "generate_asset_registry::summary#0",
    ),
    "gridalyn/projects/workflows/scripts/"
    "generate_digital_twin_flexibility_providers.py": (
        "generate_flexibility_provider_artifacts::summary#0",
    ),
    "gridalyn/projects/workflows/scripts/generate_digital_twin_semantic_graph.py": (
        "generate_semantic_graph::manifest#0",
    ),
    # Re-wrapped downstream into a governed `network_capacity` report by
    # interfaces/reporting/digital_twin.py via canonical_report -> build_report.
    "gridalyn/projects/workflows/scripts/report_mv_lv_transformer_overloads.py": (
        "build_report::report#0",
    ),
    "gridalyn/projects/workflows/scripts/run_digital_twin_ev_powerflow.py": (
        "_export_results::summary#0",
        (
            "run_scenarios::<inline:created_at,generator_type,load_realization_seed"
            ",p_total_policy,q_ev_policy,resolution_minutes,scenarios>#0"
        ),
    ),
    "gridalyn/projects/workflows/scripts/validate_digital_twin_semantics.py": (
        "validate_semantic_artifacts::manifest#0",
    ),
    "gridalyn/simulation/analytics/network_impact/catalog.py": (
        "write_network_impact_catalog::catalog#0",
    ),
    "gridalyn/simulation/analytics/network_impact/perturbation_sampler.py": (
        "write_sampler_artifacts::report#0",
    ),
    "gridalyn/simulation/analytics/network_impact/physics_model.py": (
        "write_physics_surrogate_artifacts::report#0",
    ),
    "gridalyn/simulation/analytics/network_impact/surrogate.py": (
        "write_surrogate_artifacts::report#0",
    ),
    "gridalyn/simulation/analytics/network_impact/verification_report.py": (
        "write_network_impact_verification_report::report#0",
    ),
    "gridalyn/simulation/simulators/powerflow/runner.py": (
        (
            "PowerflowMonteCarloRunner._prepare_grid::<inline:cache_schema,config,c"
            "onfig_hash>#0"
        ),
    ),
    "gridalyn/simulation/simulators/powerflow/synthetic_network.py": (
        "build_synthetic_network_from_config::report#0",
    ),
    "gridalyn/simulation/simulators/powerflow/topology_cache.py": (
        "prepare_synthetic_topology_cache::manifest#0",
        "validate_building_footprints::report#0",
    ),
    "gridalyn/twin/core/graph.py": (
        "PowerGridGraph.export_building_data_to_json::buildings_list#0",
    ),
    "gridalyn/twin/geoprocess/generator.py": (
        "FakeGeoJSONGenerator.save_to_file::<inline:crs,name,type>#0",
        "FakeGeoJSONGenerator.save_to_file::feature#0",
    ),
    "gridalyn/twin/network/metadata.py": ("write_base_metadata::metadata#0",),
    "gridalyn/twin/semantic/profile.py": ("write_profile::profile#0",),
    # Re-wrapped downstream by interfaces/reporting/digital_twin.py.
    "gridalyn/twin/semantic/validation.py": ("write_validation_report::report#0",),
    # The admm pipeline's study-data JSONs are now helper-routed: the
    # migration (Phase 19, 2026-08-17) replaced their direct json.dumps with
    # script.write_json(...), so they are enumerated in the helper-routed set
    # (§3.9) instead of here. Only validate_convergence.py (a standalone
    # operator script, not a workflow stage) still serializes directly.
    "projects/admm_thermal_consensus/scripts/validate_convergence.py": ("main::out#0",),
    # -- ev_hosting_flex study data payloads. Every module below also emits its
    # governed report via script.write_report(...); these JSONs are the data it
    # references. The pipeline stage writes were migrated (Phase 20, plan 20-02)
    # to script.write_json(...) and are now enumerated in the helper-routed set
    # (§3.9); only prepare_topology_cache.py (the topology-cache seam, Plan
    # 20-03) still serializes directly through its local _write_json helper.
    "projects/ev_hosting_flex/scripts/pipeline/prepare_topology_cache.py": (
        "_write_json::payload#0",
    ),
    "projects/synthetic_geojson_feeder/scripts/generate_building_footprints.py": (
        "main::payload#0",
    ),
}

_NOT_A_REPORT: frozenset[str] = frozenset(
    f"{path}::{local}"
    for path, locals_ in _NOT_A_REPORT_BY_FILE.items()
    for local in locals_
)

_CLASSIFIED: frozenset[str] = (
    frozenset(_KNOWN_VIOLATIONS) | _ALREADY_GOVERNED | _NOT_A_REPORT
)

# --------------------------------------------------------------------------
# In-repo JSON helpers — functions that serialize a payload they were *handed*.
# The direct scan records such a helper once, at its own `json.dump`, so every
# document routed through it is invisible there. `gridalyn.interfaces.write_json`
# is the sharpest case: a generic json.dump wrapper exported publicly. This pin
# is auto-verified by test_param_serializing_helpers_are_pinned.
# --------------------------------------------------------------------------
_PARAM_SERIALIZING_HELPERS: frozenset[str] = frozenset(
    {
        "gridalyn/foundation/platform/reports.py::write_json_report",
        "gridalyn/interfaces/reporting/schemas.py::write_json",
        "gridalyn/operations/settlement.py::write_flexibility_clearing_scorecard",
        "gridalyn/operations/verification.py::write_shadow_report",
        "gridalyn/projects/dashboard_catalog.py::write_dashboard_catalog",
        "gridalyn/projects/regression.py::write_regression_report",
        "gridalyn/projects/runner.py::_write_manifest",
        "gridalyn/projects/workflows/digital_twin/build.py::write_build_manifest",
        "gridalyn/simulation/analytics/network_impact/"
        "catalog.py::write_network_impact_catalog",
        "gridalyn/simulation/analytics/network_impact/"
        "perturbation_sampler.py::write_sampler_artifacts",
        "gridalyn/simulation/analytics/network_impact/"
        "physics_model.py::write_physics_surrogate_artifacts",
        "gridalyn/simulation/analytics/network_impact/"
        "surrogate.py::write_surrogate_artifacts",
        "gridalyn/simulation/analytics/network_impact/"
        "verification_report.py::write_network_impact_verification_report",
        "gridalyn/twin/semantic/validation.py::write_validation_report",
        "projects/ev_hosting_flex/scripts/pipeline/prepare_topology_cache.py::"
        "_write_json",
    }
)

# Helper-routed writes whose payload comes from build_report and is therefore
# contract-shaped by construction.
_HELPER_ROUTED_ALREADY_GOVERNED: frozenset[str] = frozenset(
    {
        "gridalyn/foundation/platform/reports.py::write_report::write_json_report#0",
        # Local write_report helper; validates the payload before writing (audit
        # §8 closed §6.2: validation now happens in write_report).
        "gridalyn/interfaces/reporting/schemas.py::write_report::write_json_report#0",
    }
)

# Helper-routed writes that are domain documents.
_HELPER_ROUTED_NOT_A_REPORT: frozenset[str] = frozenset(
    {
        # A report *index* (manifest_id, not report_id), not a report.
        "gridalyn/foundation/platform/reports.py::write_manifest::write_json_report#0",
        "gridalyn/interfaces/reporting/digital_twin.py::"
        "build_digital_twin_reports::write_json#0",
        "gridalyn/projects/regression.py::"
        "run_project_regression::write_regression_report#0",
        "gridalyn/projects/runner.py::run_project::_write_manifest#0",
        # The same run manifest, written on the provenance-assembly failure
        # path so a malformed declaration still leaves a trace on disk.
        "gridalyn/projects/runner.py::_attach_provenance::_write_manifest#0",
        "gridalyn/projects/workflows/digital_twin/build.py::"
        "run_digital_twin_build::write_build_manifest#0",
        "gridalyn/projects/workflows/digital_twin/build.py::"
        "run_digital_twin_build::write_build_manifest#1",
        "gridalyn/projects/workflows/scripts/"
        "generate_digital_twin_dashboard_catalog.py::main::write_dashboard_catalog#0",
        "gridalyn/projects/workflows/scripts/"
        "generate_network_impact_dashboard_catalog.py::"
        "main::write_network_impact_catalog#0",
        "gridalyn/projects/workflows/scripts/generate_network_impact_surrogate.py::"
        "main::write_surrogate_artifacts#0",
        "gridalyn/projects/workflows/scripts/validate_digital_twin_semantics.py::"
        "validate_semantic_artifacts::write_validation_report#0",
        # Five distinct cache documents behind one direct-scan site.
        "projects/ev_hosting_flex/scripts/pipeline/prepare_topology_cache.py::"
        "derive_topology_artifacts::_write_json#0",
        "projects/ev_hosting_flex/scripts/pipeline/prepare_topology_cache.py::"
        "derive_topology_artifacts::_write_json#1",
        "projects/ev_hosting_flex/scripts/pipeline/prepare_topology_cache.py::"
        "derive_topology_artifacts::_write_json#2",
        "projects/ev_hosting_flex/scripts/pipeline/prepare_topology_cache.py::"
        "derive_topology_artifacts::_write_json#3",
        "projects/ev_hosting_flex/scripts/pipeline/prepare_topology_cache.py::"
        "derive_topology_artifacts::_write_json#4",
        # admm_thermal_consensus study-data payloads, migrated (Phase 19,
        # 2026-08-17) from direct json.dumps to script.write_json(...). Same
        # class as their ev_hosting_flex siblings: domain data the governed
        # report references, not reports themselves (see §3.7 / §3.9).
        "projects/admm_thermal_consensus/scripts/pipeline/build_network.py::"
        "main::write_json#0",
        "projects/admm_thermal_consensus/scripts/pipeline/build_network.py::"
        "main::write_json#1",
        "projects/admm_thermal_consensus/scripts/pipeline/build_study_report.py::"
        "main::write_json#0",
        "projects/admm_thermal_consensus/scripts/pipeline/comfort_validation.py::"
        "main::write_json#0",
        "projects/admm_thermal_consensus/scripts/pipeline/generate_agents.py::"
        "main::write_json#0",
        "projects/admm_thermal_consensus/scripts/pipeline/imputer_comparison.py::"
        "main::write_json#0",
        "projects/admm_thermal_consensus/scripts/pipeline/run_admm.py::"
        "main::write_json#0",
        "projects/admm_thermal_consensus/scripts/pipeline/run_admm.py::"
        "main::write_json#1",
        "projects/admm_thermal_consensus/scripts/pipeline/train_forecaster.py::"
        "main::write_json#0",
        "projects/admm_thermal_consensus/scripts/pipeline/uncertainty_sweep.py::"
        "main::write_json#0",
        # ev_hosting_flex study-data payloads, migrated (Phase 20, plan 20-02,
        # 2026-08-17) from direct json.dumps to script.write_json(...). Same
        # class as their admm siblings: domain data the governed report
        # references, not reports themselves (see §3.7 / §3.9).
        "projects/ev_hosting_flex/scripts/pipeline/analyze_clustered_adoption.py::"
        "derive_clustered::write_json#0",
        "projects/ev_hosting_flex/scripts/pipeline/analyze_cold_coupling.py::"
        "derive_cold_coupling::write_json#0",
        "projects/ev_hosting_flex/scripts/pipeline/analyze_cold_insurance.py::"
        "derive_cold_insurance::write_json#0",
        "projects/ev_hosting_flex/scripts/pipeline/analyze_congestion_risk.py::"
        "derive_congestion::write_json#0",
        "projects/ev_hosting_flex/scripts/pipeline/analyze_credibility.py::"
        "derive_credibility::write_json#0",
        "projects/ev_hosting_flex/scripts/pipeline/analyze_fleet_triage.py::"
        "derive_fleet_triage::write_json#0",
        "projects/ev_hosting_flex/scripts/pipeline/analyze_flexibility_incentive.py::"
        "derive_incentive::write_json#0",
        "projects/ev_hosting_flex/scripts/pipeline/analyze_locational_contracts.py::"
        "derive_locational_contracts::write_json#0",
        "projects/ev_hosting_flex/scripts/pipeline/analyze_network_characterization.py::"
        "derive_characterization::write_json#0",
        "projects/ev_hosting_flex/scripts/pipeline/analyze_network_performance.py::"
        "derive_performance::write_json#0",
        "projects/ev_hosting_flex/scripts/pipeline/analyze_nonwires_value.py::"
        "derive_nonwires_value::write_json#0",
        "projects/ev_hosting_flex/scripts/pipeline/analyze_phase_imbalance.py::"
        "derive_phase::write_json#0",
        "projects/ev_hosting_flex/scripts/pipeline/analyze_voltage_risk.py::"
        "derive_voltage::write_json#0",
        "projects/ev_hosting_flex/scripts/pipeline/analyze_voltage_risk_network.py::"
        "derive_voltage_network::write_json#0",
        "projects/ev_hosting_flex/scripts/pipeline/apply_curtailment_contracts.py::"
        "derive_curtailment::write_json#0",
        "projects/ev_hosting_flex/scripts/pipeline/compute_congestion_annual.py::"
        "derive_annual_congestion::write_json#0",
        "projects/ev_hosting_flex/scripts/pipeline/compute_curtailment_economics.py::"
        "derive_curtailment_economics::write_json#0",
        "projects/ev_hosting_flex/scripts/pipeline/validate_powerflow.py::"
        "run_stage::write_json#0",
        # twin_network_model_config.json: provenance for the twin-network-model
        # export stages (Phase 31/Milestone 14) -- the config the exported
        # NetworkModel was built from, referenced as an artifact by the
        # governed twin_network_model_report, not a report itself.
        "projects/admm_thermal_consensus/scripts/pipeline/"
        "export_twin_network_model.py::run_stage::write_json#0",
        "projects/der_voltage_optimization/scripts/export_twin_network_model.py::"
        "run_stage::write_json#0",
        "projects/prosumer_battery_market/scripts/export_twin_network_model.py::"
        "run_stage::write_json#0",
        "projects/rl_voltage_control_lightsim/scripts/export_twin_network_model.py::"
        "run_stage::write_json#0",
    }
)

_HELPER_ROUTED_CLASSIFIED: frozenset[str] = (
    _HELPER_ROUTED_ALREADY_GOVERNED | _HELPER_ROUTED_NOT_A_REPORT
)


def _dotted_name(node: ast.expr) -> str | None:
    """Return the dotted name of an attribute/name expression.

    Args:
        node: Expression appearing in a call's ``func`` position.

    Returns:
        The dotted source name (e.g. ``"json.dump"``), or ``None`` when the
        expression is not a plain name/attribute chain.
    """
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _called_name(call: ast.Call) -> str | None:
    """Return the bare callee name of a call, ignoring any module prefix.

    Args:
        call: Any call node.

    Returns:
        ``"write_json"`` for both ``write_json(...)`` and ``mod.write_json(...)``,
        or ``None`` for calls with a computed callee.
    """
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _payload_identity(node: ast.expr) -> str:
    """Return a line-independent identity for a written JSON payload.

    Named payloads use the variable name. Inline dict literals use their sorted
    string keys, which survives reformatting and line movement. Anything else
    falls back to its AST node type. Uniqueness within a file comes from the
    enclosing qualname and the occurrence ordinal, not from this value alone.

    Args:
        node: The expression being serialized to JSON.

    Returns:
        A stable identity string.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Dict):
        keys = sorted(
            str(key.value)
            for key in node.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        )
        return "<inline:" + ",".join(keys) + ">"
    return "<inline:" + type(node).__name__ + ">"


def _qualname_by_node(tree: ast.Module) -> dict[int, str]:
    """Map every node in ``tree`` to its enclosing function/class qualname.

    Args:
        tree: A parsed module.

    Returns:
        Mapping of ``id(node)`` to a dotted qualname, empty string at module
        level.
    """
    qualnames: dict[int, str] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                nested = f"{prefix}.{child.name}" if prefix else child.name
                qualnames[id(child)] = nested
                visit(child, nested)
            else:
                qualnames[id(child)] = prefix
                visit(child, prefix)

    visit(tree, "")
    return qualnames


def _is_print_to_file(call: ast.Call) -> bool:
    """Return whether a call is ``print(..., file=<target>)`` writing to a file.

    ``print(json.dumps(payload), file=fh)`` serializes a document exactly like
    ``fh.write`` (S11). Printing to ``sys.stdout`` / ``sys.stderr`` is console
    output, not an artifact write, so those targets do not count.

    Args:
        call: Any call node encountered during the scan.

    Returns:
        True when the call prints to an explicit non-stream ``file=`` target.
    """
    if not (isinstance(call.func, ast.Name) and call.func.id == "print"):
        return False
    for keyword in call.keywords:
        if keyword.arg == "file":
            return _dotted_name(keyword.value) not in {"sys.stdout", "sys.stderr"}
    return False


def _json_payload_argument(call: ast.Call) -> ast.expr | None:
    """Return the payload written by a direct-JSON write call, if any.

    Matches ``json.dump(payload, fh)``, ``path.write_text(json.dumps(payload))``,
    ``fh.write(json.dumps(payload))``, ``path.write_bytes(json.dumps(payload)
    .encode(...))`` and ``print(json.dumps(payload), file=fh)`` (the last two
    added by S11), including forms concatenating a trailing newline.

    Args:
        call: Any call node encountered during the scan.

    Returns:
        The serialized payload expression, or ``None`` when the call does not
        write JSON to a file.
    """
    if _dotted_name(call.func) == "json.dump" and call.args:
        return call.args[0]

    attr = call.func.attr if isinstance(call.func, ast.Attribute) else None
    is_write_method = attr in {"write_text", "write", "write_bytes"}
    if not (is_write_method or _is_print_to_file(call)) or not call.args:
        return None

    candidate: ast.expr = call.args[0]
    while isinstance(candidate, ast.BinOp):
        candidate = candidate.left
    if (
        isinstance(candidate, ast.Call)
        and isinstance(candidate.func, ast.Attribute)
        and candidate.func.attr == "encode"
    ):
        candidate = candidate.func.value
    if (
        isinstance(candidate, ast.Call)
        and _dotted_name(candidate.func) == "json.dumps"
        and candidate.args
    ):
        return candidate.args[0]
    return None


def _parsed_modules() -> dict[str, ast.Module]:
    """Parse every Python module under the scanned roots.

    Returns:
        Mapping of repo-relative POSIX path to parsed module.

    Raises:
        AssertionError: When a scan root is missing (S11) -- a renamed or moved
            root must fail loudly, not silently empty the denominator.
    """
    modules: dict[str, ast.Module] = {}
    for root_name in _SCAN_ROOTS:
        root = _REPO_ROOT / root_name
        if not root.is_dir():
            raise AssertionError(
                f"report-contract scan root {root_name!r} not found at {root}; "
                "update _SCAN_ROOTS if the tree moved -- an absent root would "
                "silently drop every site under it from the scan."
            )
        for path in sorted(root.rglob("*.py")):
            relative = path.relative_to(_REPO_ROOT).as_posix()
            modules[relative] = ast.parse(
                path.read_text(encoding="utf-8"), filename=str(path)
            )
    return modules


def _numbered(groups: dict[str, list[int]]) -> dict[str, tuple[str, int, list[int]]]:
    """Assign occurrence ordinals to grouped write sites.

    Grouping accumulates rather than discarding: two writes that share a file,
    an enclosing function and a payload identity both survive, as ``#0`` and
    ``#1``. Under the previous ``setdefault`` keying the second was dropped
    silently, which let a new governed report hide inside an already-pinned file.

    Args:
        groups: Mapping of group key to the line numbers matched under it.

    Returns:
        Mapping of full site key to ``(repo-relative path, line, sibling lines)``.
    """
    sites: dict[str, tuple[str, int, list[int]]] = {}
    for group_key, lines in groups.items():
        ordered = sorted(lines)
        relative = group_key.split("::", 1)[0]
        for ordinal, line in enumerate(ordered):
            sites[f"{group_key}#{ordinal}"] = (relative, line, ordered)
    return sites


def _scan_direct_json_write_sites() -> dict[str, tuple[str, int, list[int]]]:
    """Enumerate every direct-JSON write site under the scanned roots.

    Returns:
        Mapping of site key to ``(repo-relative path, line, sibling lines)``.
    """
    groups: dict[str, list[int]] = defaultdict(list)
    for relative, tree in _parsed_modules().items():
        qualnames = _qualname_by_node(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            payload = _json_payload_argument(node)
            if payload is None:
                continue
            scope = qualnames.get(id(node)) or "<module>"
            groups[f"{relative}::{scope}::{_payload_identity(payload)}"].append(
                node.lineno
            )
    return _numbered(dict(groups))


def _scan_param_serializing_helpers() -> dict[str, str]:
    """Find functions that serialize a payload handed to them by a caller.

    These are the in-repo JSON helpers: the direct scan sees one write inside
    the helper, so every document routed through it is invisible there.

    Returns:
        Mapping of ``"<path>::<qualname>"`` to the helper's bare function name.
    """
    helpers: dict[str, str] = {}
    for relative, tree in _parsed_modules().items():
        qualnames = _qualname_by_node(tree)
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            parameters = {
                argument.arg
                for argument in (
                    function.args.posonlyargs
                    + function.args.args
                    + function.args.kwonlyargs
                )
            }
            for node in ast.walk(function):
                if not isinstance(node, ast.Call):
                    continue
                payload = _json_payload_argument(node)
                if isinstance(payload, ast.Name) and payload.id in parameters:
                    scope = qualnames.get(id(function)) or function.name
                    helpers[f"{relative}::{scope}"] = function.name
    return helpers


def _scan_helper_routed_write_sites() -> dict[str, tuple[str, int, list[int]]]:
    """Enumerate every call to an in-repo JSON helper.

    Each such call writes a distinct document that the direct scan attributes to
    the helper, not to the caller. Matching is by bare callee name, so an
    unrelated same-named function would surface here as an unclassified site
    rather than being missed.

    Returns:
        Mapping of site key to ``(repo-relative path, line, sibling lines)``.
    """
    helper_names = set(_scan_param_serializing_helpers().values())
    groups: dict[str, list[int]] = defaultdict(list)
    for relative, tree in _parsed_modules().items():
        qualnames = _qualname_by_node(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _called_name(node)
            if name not in helper_names:
                continue
            scope = qualnames.get(id(node)) or "<module>"
            groups[f"{relative}::{scope}::{name}"].append(node.lineno)
    return _numbered(dict(groups))


def _audit_text() -> str:
    """Read the audit document, failing loudly when it is absent.

    Returns:
        The audit's text.

    Raises:
        AssertionError: When the audit document is missing, naming the path.
    """
    if not _AUDIT_PATH.is_file():
        raise AssertionError(
            f"Missing {_AUDIT_REL} (looked in {_AUDIT_PATH}).\n"
            "This gate pins the classification recorded in that document; "
            "without it the pins have no rationale and cannot be reviewed. "
            "the audit is tracked under `docs/`, so a fresh checkout "
            "will not have it — restore the directory, or commit it, before "
            "relying on this gate."
        )
    return _AUDIT_PATH.read_text(encoding="utf-8")


def _describe(sites: dict[str, tuple[str, int, list[int]]], keys: list[str]) -> str:
    """Render site keys with their live line numbers for a failure message.

    Args:
        sites: The live scan result.
        keys: Keys to describe.

    Returns:
        An indented, newline-joined description.
    """
    lines: list[str] = []
    for key in keys:
        relative, line, siblings = sites[key]
        others = [str(item) for item in siblings if item != line]
        suffix = f"  (others in this group: {', '.join(others)})" if others else ""
        lines.append(f"  {relative}:{line}{suffix}\n      key: {key}")
    return "\n".join(lines)


class ReportContractAuditTest(unittest.TestCase):
    """Pin the 02-03 report-contract classification against the live tree."""

    def test_audit_document_is_present(self) -> None:
        """The classification this module pins must be readable alongside it."""
        self.assertTrue(_audit_text())

    def test_required_report_fields_are_unchanged(self) -> None:
        """A change to the contract invalidates every classification."""
        self.assertEqual(
            tuple(REQUIRED_REPORT_FIELDS),
            _AUDITED_REQUIRED_FIELDS,
            "REQUIRED_REPORT_FIELDS changed since the 02-03 audit. The audit "
            "reasons about this envelope throughout — including the field-count "
            f"evidence in §1 — so re-run the classification in {_AUDIT_REL} and "
            "update _AUDITED_REQUIRED_FIELDS here.",
        )

    def test_every_direct_json_write_site_is_classified(self) -> None:
        """A new direct-JSON write must be classified before it can land."""
        sites = _scan_direct_json_write_sites()
        unclassified = sorted(set(sites) - _CLASSIFIED)
        self.assertEqual(
            unclassified,
            [],
            "Unclassified direct-JSON write site(s):\n"
            f"{_describe(sites, unclassified)}\n\n"
            f"Classify each in {_AUDIT_REL} by reading the code that builds its "
            "payload, then add its key to _KNOWN_VIOLATIONS, _ALREADY_GOVERNED "
            "or _NOT_A_REPORT_BY_FILE here. A payload that is the run's own "
            "account of itself, at a governed report destination, must be "
            "emitted through write_report — not hand-serialized.",
        )

    def test_every_helper_routed_write_is_classified(self) -> None:
        """A document routed through an in-repo JSON helper is not invisible."""
        sites = _scan_helper_routed_write_sites()
        unclassified = sorted(set(sites) - _HELPER_ROUTED_CLASSIFIED)
        self.assertEqual(
            unclassified,
            [],
            "Unclassified helper-routed JSON write site(s):\n"
            f"{_describe(sites, unclassified)}\n\n"
            "These write through a helper that serializes a caller-supplied "
            "payload, so the direct scan records them at the helper rather than "
            f"here. Classify each in {_AUDIT_REL} §6 and pin it in "
            "_HELPER_ROUTED_NOT_A_REPORT or _HELPER_ROUTED_ALREADY_GOVERNED.",
        )

    def test_param_serializing_helpers_are_pinned(self) -> None:
        """A new JSON helper must be pinned, or its callers go uncounted."""
        self.assertEqual(
            sorted(_scan_param_serializing_helpers()),
            sorted(_PARAM_SERIALIZING_HELPERS),
            "The set of in-repo functions that serialize a caller-supplied JSON "
            "payload changed. Every such helper hides its callers from the "
            f"direct scan, so record the change in {_AUDIT_REL} §6 and update "
            "_PARAM_SERIALIZING_HELPERS together with the helper-routed pins.",
        )

    def test_no_classified_site_vanished_silently(self) -> None:
        """A pinned site that disappears must be reflected in the audit."""
        sites = _scan_direct_json_write_sites()
        missing = sorted(_CLASSIFIED - set(sites))
        self.assertEqual(
            missing,
            [],
            "Pinned direct-JSON write site(s) no longer found:\n  "
            + "\n  ".join(missing)
            + "\n\nIf a site was fixed, moved or renamed, update its row and the "
            f"reconciling counts in {_AUDIT_REL}, then update this module.",
        )

    def test_no_helper_routed_site_vanished_silently(self) -> None:
        """A pinned helper-routed site that disappears must be reflected too."""
        sites = _scan_helper_routed_write_sites()
        missing = sorted(_HELPER_ROUTED_CLASSIFIED - set(sites))
        self.assertEqual(
            missing,
            [],
            "Pinned helper-routed write site(s) no longer found:\n  "
            + "\n  ".join(missing)
            + f"\n\nUpdate {_AUDIT_REL} §6 and this module together.",
        )

    def test_site_keys_identify_exactly_one_write(self) -> None:
        """Each key must name one write, so none can be silently absorbed."""
        for label, scan in (
            ("direct", _scan_direct_json_write_sites),
            ("helper-routed", _scan_helper_routed_write_sites),
        ):
            sites = scan()
            groups: dict[str, list[int]] = defaultdict(list)
            for key, (_, line, _) in sites.items():
                groups[key.rsplit("#", 1)[0]].append(line)
            collisions = {
                group: sorted(lines)
                for group, lines in groups.items()
                if len(set(lines)) != len(lines)
            }
            with self.subTest(scan=label):
                self.assertEqual(
                    collisions,
                    {},
                    f"{label} site keys collapse distinct writes onto one key:\n"
                    + "\n".join(
                        f"  {group}  lines {lines}"
                        for group, lines in sorted(collisions.items())
                    )
                    + "\n\nThe key scheme (path, qualname, payload identity, "
                    "ordinal) must distinguish every write, or a new governed "
                    "report can hide behind a pinned one.",
                )

    def test_known_violations_are_visible_not_tolerated(self) -> None:
        """Any re-added known violation must stay visible with its remedy.

        Empty since 2026-08-06 (all five remedies applied); the loop is the
        contract for any future entry, and emptiness itself is asserted by
        ``test_audit_counts_reconcile`` via the violation count.
        """
        sites = _scan_direct_json_write_sites()
        for key, remedy in sorted(_KNOWN_VIOLATIONS.items()):
            with self.subTest(site=key):
                self.assertIn(
                    key,
                    sites,
                    f"Known GOVERNED-VIOLATION {key} is gone. If it was fixed, "
                    f"remove it here and update {_AUDIT_REL} ({remedy}) so the "
                    "counts still reconcile.",
                )
                self.assertTrue(
                    remedy.startswith("audit section "),
                    "Every known violation must cite its remedy section.",
                )

    def test_audit_records_every_known_violation(self) -> None:
        """The audit must name each violating file, not just this module."""
        audit_text = _audit_text()
        self.assertIn("GOVERNED-VIOLATION", audit_text)
        for key in sorted(_KNOWN_VIOLATIONS):
            file_path = key.split("::", 1)[0]
            with self.subTest(site=file_path):
                self.assertIn(
                    file_path,
                    audit_text,
                    f"{file_path} is pinned as a GOVERNED-VIOLATION but is not "
                    f"named in {_AUDIT_REL}.",
                )

    def test_audit_counts_reconcile(self) -> None:
        """Examined == violations + not-a-report + already-governed."""
        examined = len(_scan_direct_json_write_sites())
        violations = len(_KNOWN_VIOLATIONS)
        not_a_report = len(_NOT_A_REPORT)
        already_governed = len(_ALREADY_GOVERNED)
        self.assertEqual(
            examined,
            violations + not_a_report + already_governed,
            f"Counts do not reconcile: examined={examined}, "
            f"violations={violations}, not_a_report={not_a_report}, "
            f"already_governed={already_governed}. Update {_AUDIT_REL} and the "
            "pinned sets together.",
        )
        # Guard against a vacuous pass if the scanner silently stops matching.
        self.assertEqual(
            examined,
            41,
            "The 02-03 audit examined 76 direct-JSON write sites; the "
            "duplicate-write removal brought it to 75, the 2026-08-06 wave "
            "applying audit sections 5.1-5.5 brought it to 70 with zero known "
            "violations, and retiring the orphaned-input commands "
            "the same day removed one more (spatial_powerflow_validation.py), "
            "leaving 69. The 2026-08-17 admm migration (Phase 19) routed the "
            "study's 10 pipeline JSON writes through script.write_json, "
            "moving them from this direct set to the helper-routed set, "
            "leaving 59. The 2026-08-17 ev_hosting_flex migration (Phase 20, "
            "plan 20-02) routed the flagship's 20 pipeline JSON writes "
            "through script.write_json too, leaving 41 (only "
            "prepare_topology_cache.py, the Plan 20-03 seam, still "
            "serializes directly through its local _write_json helper). A "
            "different number means the tree moved or the "
            "scanner no longer matches; reconcile before adjusting.",
        )

    def test_helper_routed_counts_reconcile(self) -> None:
        """The helper-routed enumeration reconciles against the audit too."""
        examined = len(_scan_helper_routed_write_sites())
        self.assertEqual(
            examined,
            len(_HELPER_ROUTED_CLASSIFIED),
            f"Helper-routed counts do not reconcile: examined={examined}, "
            f"pinned={len(_HELPER_ROUTED_CLASSIFIED)}. Update {_AUDIT_REL} §6 "
            "and the pinned sets together.",
        )
        self.assertEqual(
            examined,
            50,
            "The 02-03 audit examined 22 helper-routed write sites across 15 "
            "helpers; retiring the orphaned-input commands on "
            "2026-08-06 removed five of them (the clearing scorecard, "
            "perturbation sampler, network-impact verification report, "
            "provider-selection shadow report and physics-surrogate trainer), "
            "leaving 17. 2026-08-14 added one back: the run manifest is now "
            "also written from runner._attach_provenance, so a malformed "
            "spec.simulation declaration leaves a manifest rather than only a "
            "traceback. That makes 18. The 2026-08-17 admm migration (Phase "
            "19) routed 10 pipeline study-data JSONs through "
            "script.write_json, bringing the helper-routed total to 28. The "
            "2026-08-17 ev_hosting_flex migration (Phase 20, plan 20-02) "
            "routed the flagship's 20 pipeline JSON writes through "
            "script.write_json, bringing the helper-routed total to 46 (the "
            "five prepare_topology_cache _write_json cache documents were "
            "already counted there). The Phase 31 (Milestone 14) "
            "twin-network-model export stages added 4 more "
            "script.write_json(twin_network_model_config.json) sites (admm, "
            "der_voltage_optimization, prosumer_battery_market, "
            "rl_voltage_control_lightsim), bringing the total to 50. A "
            "different number means the tree moved; reconcile before "
            "adjusting this number.",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
