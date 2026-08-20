# 02-03 — Report Contract Audit (R3)

Audited at HEAD `21be62ba`, 2026-08-05. Revised 2026-08-05 (review cycle 1) after
three findings against the first revision: the classification rule was applied
inconsistently, the threshold's sensitivity was undisclosed, and helper-routed
writes were invisible. Scope: every JSON write site under `gridalyn/` and
`projects/`. **No production code was modified by this audit.**

---

## 1. Operational definition

Quoted verbatim from `gridalyn/foundation/platform/reports.py:14-23`:

```python
SCHEMA_VERSION = "1.0"
REQUIRED_REPORT_FIELDS = (
    "report_id",
    "schema_version",
    "created_at",
    "source_domain",
    "inputs",
    "artifacts",
    "summary",
    "validation",
)
```

`validate_report` (`reports.py:90-108`) additionally requires `report_id` be a `str`,
`schema_version == "1.0"`, `inputs` and `artifacts` be **lists**, and `summary` and
`validation` be **dicts**. `build_report` (`reports.py:63-87`) is the only sanctioned
constructor; `write_report` (`reports.py:127-148`) builds, validates, and serializes via
`write_json_report` (`reports.py:116-124`).

**A governed platform report** is the JSON document an artifact-producing run emits *about
itself*. **A dict merely named `report` is not a governed report.** A catalog, scorecard,
manifest, run-lineage record, cache metadata document, GeoJSON, model card, or study data
payload has its own shape and its own (different) contract; the envelope's absent fields
were never intended and their absence is not a defect.

The phase context's figure of "25 direct-JSON sites whose payload is named `report`" is a
**grep artifact**. It is neither a violation count nor an enumeration; it is not inherited
here as either.

### 1.1 The withdrawn rule, and why

The first revision of this audit classified by field count: `GOVERNED-VIOLATION` iff the
payload carried **≥ 6 of the 8** `REQUIRED_REPORT_FIELDS` by name and the writing module
never called `build_report` / `write_report`. That rule is withdrawn. Two defects, both
fatal to it:

**(a) The count is not a property of a site.** `write_locational_clearing_outputs`
(`operations/clearing/selection.py:617-645`) writes `locational_clearing_summary.json` from
a `report` dict its *caller* supplies. It has two callers, and they supply different dicts.
Both outputs are on disk right now:

| File | Envelope fields present | N/8 |
|---|---|---|
| `instances/default/digital_twin/flexibility/locational_clearing_summary.json` | `artifacts, created_at, inputs, report_id, schema_version, summary` | **6/8** |
| `projects/ev_hosting_flex/outputs/flexibility/locational_clearing_summary.json` | `artifacts, created_at, report_id, schema_version, summary` | **5/8** |

The first caller is `projects/workflows/scripts/generate_locational_flexibility_clearing.py:147-158`,
which injects `inputs` before the write. The second is
`projects/ev_hosting_flex/scripts/pipeline/analyze_locational_contracts.py:310`, which does
not. **One site, one line of code, two field counts.** A rule keyed on the count cannot
give that site a verdict.

The first revision made this worse by resolving the ambiguity in opposite directions at two
structurally identical sites: it counted `operations/verification.py:419` *after* caller
injection ("At runtime the written payload is therefore 6/8") and pinned it as a violation,
while counting `selection.py:639` *before* injection (5/8) and filing it `NOT-A-REPORT` on
the stated ground that it had "no `inputs`" — which is false of the artifact on disk. That
inconsistency is what produced the headline 6.

**(b) The headline was a fact about the bar, not the codebase.** Re-deriving the count as a
function of where the bar sits, and of where the payload is scored:

| Bar | Violations |
|---|---|
| ≥ 5/8, scored statically at the builder | **11** |
| ≥ 6/8, scored statically at the builder | **5** |
| ≥ 6/8, as §4 of the first revision actually reported it (runtime for `verification.py`, static for `selection.py`) | **6** |
| ≥ 6/8, runtime augmentation applied consistently everywhere | **7** |
| ≥ 7/8, scored statically | **1** |
| `validate_report(payload) == []` | **1** |
| **role ∧ destination ∧ not-routed (adopted, §1.2)** | **6** |

Every row above was re-derived for this revision from the payload-building source, not
carried over. A result that reads 11, 5, 6, 7 or 1 depending on a threshold nobody
independently motivated — and that reads three different values *at the same nominal
≥ 6/8 bar* depending only on where you evaluate the payload — is not a finding about the
codebase. It was presented as settled. It was not.

**(c) The rule's stated justification was contradicted by its own table.** The first
revision defended 6/8 like this: *"Reaching 6/8 requires also hand-building `inputs` /
`artifacts` / `summary` / `validation` — the envelope's content sections — which no domain
document does incidentally."* That is false of every row it had itself tabulated at 5/8.
All five hand-build **two** content sections:

| 5/8 site | Content sections hand-built |
|---|---|
| `assets/modeling/artifacts.py:88-92` | `inputs` + `artifacts` |
| `assets/modeling/scenarios.py:336-341` | `inputs` + `artifacts` |
| `twin/network/metadata.py:101-102` | `artifacts` + `validation` |
| `simulation/analytics/network_impact/surrogate.py:493-505` | `validation` + `summary` |
| `operations/clearing/selection.py:587,613,633` | `summary` + `artifacts` |

The defence was aimed at the 3/8 `{created_at, report_id, schema_version}` triad, which was
never the contested band. Against the band that actually borders the bar it says nothing.

### 1.2 The adopted rule: role and destination

The discriminator the first revision used throughout its *prose* — and nowhere in its rule
— is what a document is *for*. That is promoted to the rule.

| Verdict | Test |
|---|---|
| `ALREADY-GOVERNED` | The site *is* the contract's own serializer, or serializes a payload produced by `build_report`. |
| `GOVERNED-VIOLATION` | **Role** ∧ **Destination** ∧ **Not-routed**, all three below. |
| `NOT-A-REPORT` | Anything failing any of the three. |

- **Role** — the payload is the run's own account of itself: it carries an `inputs` and/or
  `artifacts` section naming *that run's* I/O. A sidecar describing a model, a case
  comparison, a cache or a network build does not qualify, however many envelope keys it
  happens to carry.
- **Destination** — it is written to a governed report location: a filename ending
  `_report.json`, or a path under a project's `outputs/reports/` (`ArtifactLayout.reports`,
  `workspace.py:95`).
- **Not-routed** — the writing module never calls `build_report` / `write_report`, **and**
  nothing downstream re-wraps the document into a governed report.

Why this rule and not a tuned field count:

1. **It is caller-independent.** It asks about the write's role and path, not the payload's
   contents, so `write_locational_clearing_outputs` gets one verdict rather than two. The
   instability that broke rule (a) does not arise: `locational_clearing_summary.json` is a
   sidecar for *both* callers, and is `NOT-A-REPORT` for both.
2. **It does not move when a payload gains one key.** Adding `source_domain` to a cache
   manifest does not make it a report; dropping `summary` from a stage's terminal report
   does not make it stop being one.
3. **All three conditions do real work** — none is decorative. Role alone would admit
   `assets/modeling/artifacts.py:97` and `scenarios.py:346`, which carry `inputs` *and*
   `artifacts`; destination rejects them (`models/*_manifest.json`). Destination alone would
   admit `projects/regression.py:120` (`outputs/reports/regression_report.json`),
   `simulation/analytics/network_impact/surrogate.py:538` and four sibling
   `network_impact_*_report.json` sidecars, plus `report_mv_lv_transformer_overloads.py:143`;
   role rejects all of them — none records its own I/O. Not-routed additionally rejects
   `report_mv_lv_transformer_overloads.py:143` and `twin/semantic/validation.py:151`, both
   of which `interfaces/reporting/digital_twin.py:50-112` re-wraps through
   `canonical_report` → `build_report`.
4. **The headline is stable across the withdrawn rule's whole contested band.** It selects
   6, the same number the first revision reported — but now for a reason that survives the
   5/8–6/8 boundary, because it never consults that boundary.

Field counts are retained below as **evidence**, scored **statically at the builder** (the
fields the writing module itself constructs, ignoring anything a caller injects). Scored
that way they are a well-defined property of a site. They no longer decide anything.

---

## 2. Enumeration

Two enumerations, kept separate because they have different denominators and mixing them
would double-count the same bytes.

### 2.1 Direct-JSON writes — **76 sites**

Method: AST scan of all `*.py` under `gridalyn/` and `projects/`, matching
`json.dump(...)`, `X.write_text(json.dumps(...))` and `X.write(json.dumps(...))`
(including `json.dumps(...) + "\n"` forms). Scanner records file, enclosing qualname,
payload identity, and line. Payload construction was then traced per site — through helper
functions and into other modules — before classification.

### 2.2 Helper-routed writes — **22 sites across 15 helpers**

A direct scan attributes a write to the line that calls `json.dump`. When that line sits
inside a helper that serializes a payload it was *handed*, every document routed through
the helper collapses onto one site and becomes invisible. The first revision missed this
entirely; it is a real gap, not a hypothetical one:

- `gridalyn/interfaces/reporting/schemas.py:52 write_json` is a generic `json.dump` wrapper
  **exported publicly** as `gridalyn.interfaces.write_json` (`interfaces/__init__.py:28`).
  In-repo it has one caller; out of repo its surface is unbounded.
- `projects/ev_hosting_flex/scripts/pipeline/prepare_topology_cache.py:96 _write_json` has
  **five** call sites (`:190, :191, :201, :202, :205`) writing five different cache
  documents. The direct scan sees one.
- `gridalyn/projects/workflows/digital_twin/build.py:write_build_manifest` has two
  (`:173, :180`).

So a second pass enumerates, for every function in the tree that serializes a parameter,
each of its call sites. That pass finds 15 such helpers and 22 call sites. The helper set
itself is machine-derived and pinned, so a *new* helper also fails the gate — the allowlist
cannot rot the way a hand-maintained one would.

### Enumeration discrepancy — reported, not silently adopted

The phase context recorded **~25** direct sites. This audit finds **76**. The discrepancy is
fully explained and is not a disagreement about the code:

- The 25 counted only sites whose **payload variable is named `report`**. Re-running that
  name filter over this enumeration yields **16** such sites (payload named `report` or
  `report_with_artifacts`); the remaining ~9 of the original 25 were almost certainly
  line-level grep matches on the *target* expression (`report_path.write_text`,
  `report_out.write_text`) rather than distinct payload-bearing sites.
- This audit deliberately drops the name filter, because the plan's whole point is that the
  variable name carries no information. Dropping it adds 60 sites whose payloads are named
  `manifest`, `catalog`, `scorecard`, `summary`, `payload`, `metadata`, `kpis`, `results`,
  `params` — several of which are *more* report-shaped than some named `report`.

The larger number is the correct denominator for R3. No site was excluded to reach it.

---

## 3. Per-site classification (direct writes)

"Fields" is the static count: the `REQUIRED_REPORT_FIELDS` the **writing module itself**
constructs. Verdicts come from §1.2, not from this column.

### 3.1 `gridalyn/` — foundation, interfaces

| File | Line | Payload | Fields | Class | Rationale |
|---|---|---|---|---|---|
| `foundation/platform/reports.py` | 120 | `payload` | 8/8 | ALREADY-GOVERNED | This *is* `write_json_report`, the contract's own serializer, called by `write_report` (`:147`) after `validate_report`. |
| `interfaces/reporting/schemas.py` | 55 | `payload` | n/a | NOT-A-REPORT | `write_json` generic serializer; see §2.2. Its own payload is a parameter, so it has no intrinsic shape. Its in-repo caller writes a report *manifest*, indexing three governed reports — an index, not a report. |
| `gridalyn/projects/dashboard_catalog.py` (relocated — §9) | 149 | `catalog` | 3/8 | NOT-A-REPORT | `:128-135`. A dashboard catalog: per-scenario `paths`/`metrics`/`topology_counts`. Role: no own-I/O sections. |

### 3.2 `gridalyn/assets/`

| File | Line | Payload | Fields | Class | Rationale |
|---|---|---|---|---|---|
| `assets/modeling/artifacts.py` | 97 | `manifest` | 5/8 | NOT-A-REPORT | `:76-94`. Carries `inputs` + `artifacts` (dicts, not contract lists), so it passes **role** — but destination is `models/building_model_manifest.json` and `report_id` self-describes as `building_model_manifest`. A build manifest. |
| `assets/modeling/scenarios.py` | 346 | `manifest` | 5/8 | NOT-A-REPORT | `:326-343`. Same shape, same reasoning, `models/scenario_model_manifest.json`. |

### 3.3 `gridalyn/twin/`

| File | Line | Payload | Fields | Class | Rationale |
|---|---|---|---|---|---|
| `twin/adapters/validation.py` | 98 | `report` | 6/8 | **GOVERNED-VIOLATION** | `build_network_adapter_validation_report` (`:16-68`): `{report_id: "network_adapter_validation", schema_version, created_at, source_adapter, source_standard, adapter, summary, validation, lineage, artifacts}`. **Role** ✔ — `artifacts` names the export's own outputs, with `bytes`/`exists` per file. **Destination** ✔ — `ArtifactLayout.reports / network_adapter_validation_report.json` (`twin/adapters/network.py:246`). **Not-routed** ✔ — imports neither `build_report` nor `write_report`. `validation` is already the contract's `{valid, errors, warnings, summary}`. See §5.4. |
| `twin/network/metadata.py` | 141 | `metadata` | 5/8 | NOT-A-REPORT | `build_base_metadata` (`:84-105`). Destination `base/metadata.json`. A model-version lineage document, consumed by `operations/artifacts.py:218` via `model_version_id_from_artifacts`. Destination test rejects it. |
| `twin/semantic/validation.py` | 151 | `report` | 1/8 | NOT-A-REPORT | `{created_at, valid, node_count, edge_count, errors, warnings}`. Re-wrapped downstream by `interfaces/reporting/digital_twin.py:97-112` into a governed `semantic_graph` report. Fails role *and* not-routed. |
| `twin/semantic/profile.py` | 111 | `profile` | 1/8 | NOT-A-REPORT | An ontology profile document. |
| `twin/core/graph.py` | 1027 | `buildings_list` | 0/8 | NOT-A-REPORT | A JSON **list** of building records. A data export. |
| `twin/geoprocess/generator.py` | 152 | inline dict | 0/8 | NOT-A-REPORT | GeoJSON `FeatureCollection` header. |
| `twin/geoprocess/generator.py` | 164 | `feature` | 0/8 | NOT-A-REPORT | Individual GeoJSON `Feature` objects. |

### 3.4 `gridalyn/simulation/`

| File | Line | Payload | Fields | Class | Rationale |
|---|---|---|---|---|---|
| `.../network_impact/catalog.py` | 80 | `catalog` | 3/8 | NOT-A-REPORT | A dashboard catalog. |
| `.../network_impact/perturbation_sampler.py` | 296 | `report` | 4/8 | NOT-A-REPORT | Destination `network_impact_physics_labels_report.json` (`:293`) — but written by `write_sampler_artifacts` alongside the labels parquet, and carries no `inputs`/`artifacts`. A sidecar. Fails role. |
| `.../network_impact/physics_model.py` | 256 | `report` | 4/8 | NOT-A-REPORT | Same pattern, `network_impact_physics_surrogate_report.json` (`:253`). Fails role. |
| `.../network_impact/surrogate.py` | 538 | `report` | 5/8 | NOT-A-REPORT | `:482-507`. One of **seven** paths written by `write_surrogate_artifacts` (`:510-539`); the other six are parquets. Describes the *model* (`{model, validation: {authority, policy}, summary}`), not the run. No `inputs`/`artifacts`. Fails role. A model card. |
| `.../network_impact/verification_report.py` | 475 | `report` | 4/8 | NOT-A-REPORT | `{validation: {authority, policy}, cases, dispatch, comparisons}`. No `inputs`/`artifacts`. A verification side-artifact — the category the plan names as legitimately non-governed. Fails role. |
| `simulators/powerflow/runner.py` | 255 | inline dict | 0/8 | NOT-A-REPORT | Power-flow cache key. |
| `simulators/powerflow/synthetic_network.py` | 161 | `report` | 1/8 | NOT-A-REPORT | Written by the network *builder* alongside the network it built. No `inputs`/`artifacts`, no `schema_version`, no `created_at`. Fails role. |
| `simulators/powerflow/topology_cache.py` | 78 | `manifest` | 2/8 | NOT-A-REPORT | A cache manifest (`artifact_type` is its own discriminator). |
| `simulators/powerflow/topology_cache.py` | 143 | `report` | 2/8 | NOT-A-REPORT | Cache validation side-artifact. Fails role. |

### 3.5 `gridalyn/operations/`

| File | Line | Payload | Fields | Class | Rationale |
|---|---|---|---|---|---|
| `operations/artifacts.py` | 150 | `report` | 6/8 | **GOVERNED-VIOLATION** | Built by `build_operational_kpi_report` (`settlement.py:126-178`), augmented in-module at `:104-107` with `operation_context` and at `:124-148` with hand-built `inputs` + `artifacts`. **Role** ✔ — `inputs` names four upstream parquets, `artifacts` names the four this run wrote. **Destination** ✔ — `projects/<id>/outputs/reports/operational_kpi_report.json` (`:54`). **Not-routed** ✔. Missing `source_domain` and `validation`; `inputs`/`artifacts` are dicts, not contract lists. The module builds a correct `{"valid": True, "errors": [], "warnings": []}` for its sibling `operation_run` at `:179` but never for the report itself. See §5.1. |
| `operations/artifacts.py` | 185 | `catalog` | 3/8 | NOT-A-REPORT | `build_operations_catalog` (`:277-329`). A dashboard catalog. This is the adjacency the plan flagged as suggestive: the catalog at `:185` is legitimate; the report at `:150` beside it is not. |
| `operations/clearing/selection.py` | 639 | `report_with_artifacts` | 5/8 | NOT-A-REPORT | **Reclassified rationale — the verdict is unchanged but the first revision's stated reason ("no `inputs`") was false of the artifact on disk; see §1.1(a).** Under §1.2: **Destination** ✘ — `out_dir/locational_clearing_summary.json`, a sidecar beside the two parquets `write_locational_clearing_outputs` writes in the same call and names in its own `artifacts`. **Role** ✘ — the payload is supplied by the caller, and the run's actual report is written *separately by that caller* to a different path (`generate_locational_flexibility_clearing.py:176`, §5.5). The summary is what the report points at, not the report. This verdict is now the same for both callers; the field count was not. |
| `operations/runs.py` | 155 | `payload` | 4/8 | NOT-A-REPORT | `OperationRun.to_dict` (`:56-77`). A run-lineage record with its **own** contract, enforced by `validate_operation_run` (`:116-145`) before write. Not the platform envelope, and correctly gated by its own validator. |
| `operations/settlement.py` | 500 | `scorecard` | 4/8 | NOT-A-REPORT | `:483-494`. Note `validation_authority` (a string) is not `validation`. A policy scorecard. |
| `operations/verification.py` | 419 | `report_with_artifacts` | 5/8 | **GOVERNED-VIOLATION** | `build_locational_clearing_verification_report` (`:365-398`) + `artifacts` added at `:412-418`. **Role** ✔ — `artifacts` names the dispatch parquet and the report this call writes. **Destination** ✔ — writes `report_path`, which its only caller sets to `.../locational_clearing_verification_report.json`. **Not-routed** ✔. Note the static count is 5/8, not the 6/8 the first revision reported; the sixth field came from the caller. The verdict does not depend on it. See §5.2. |
| `operations/verification.py` | 550 | `report` | 4/8 | NOT-A-REPORT | `write_shadow_report`; built by `build_shadow_report` (`:451-543`). The module docstring (`:14-16`) calls it a non-invasive shadow comparison. No `inputs`/`artifacts`. Fails role. |

### 3.6 `gridalyn/projects/`

| File | Line | Payload | Fields | Class | Rationale |
|---|---|---|---|---|---|
| `projects/sense_checks.py` | 94 | `payload` | **8/8** | **GOVERNED-VIOLATION** | `:59-92`. **8/8 with contract-correct types** — `validate_report()` on this payload returns **zero** errors. **Role** ✔ — `inputs: []` / `artifacts: []` are present and contract-typed; the check run consumes and produces nothing but itself. **Destination** ✔ — `outputs/reports/project_sense_check_report.json` (`:92`). **Not-routed** ✔. It *is* a governed platform report, hand-serialized instead of routed through `build_report`/`write_report`. Decisive under any rule in §1.1's table. See §5.3. |
| `projects/regression.py` | 120 | `report` | 3/8 | NOT-A-REPORT | `build_regression_report` (`:104-115`). **Destination** ✔ — `outputs/reports/regression_report.json` (`:12`). **Role** ✘ — no `inputs`, no `artifacts`; `valid`/`errors` are top-level scalars, not the contract's `validation` object. A baseline-comparison record. Worth flagging: this is the site nearest the boundary of the adopted rule, admitted by destination and rejected only by role. If R3 is later read as governing *any* document in `outputs/reports/`, this becomes a seventh violation. |
| `projects/runner.py` | 193 | `payload` | 0/8 | NOT-A-REPORT | The workflow run manifest. |
| `.../digital_twin/build.py` | 136 | `manifest` | 4/8 | NOT-A-REPORT | A build-step manifest. |
| `.../digital_twin/ev_scenarios.py` | 149 | `scenario_doc` | 1/8 | NOT-A-REPORT | A scenario definition document. |
| `.../digital_twin/ev_scenarios.py` | 161 | `index_doc` | 1/8 | NOT-A-REPORT | A scenario index. |
| `.../digital_twin/ev_timeseries.py` | 172 | inline dict | 1/8 | NOT-A-REPORT | A timeseries generation manifest. |
| `.../flexibility/locational_verification.py` | 131 | `report` | 6/8 | **GOVERNED-VIOLATION** | The same document as `verification.py:419`, after this module adds `inputs` (`:116-122`) and `artifacts` (`:127-130`) — both **in-module**, so 6/8 is a static count here. **Role** ✔, **Destination** ✔ (`DEFAULT_REPORT_OUT`, `:31`), **Not-routed** ✔. **Additional defect:** this line rewrites the *same path* `write_locational_verification_outputs` already wrote at `verification.py:419` — a duplicate write, last-write-wins. See §5.2. |
| `.../flexibility/spatial_powerflow_validation.py` | 206 | `summary` | 1/8 | NOT-A-REPORT | No `report_id`, no `schema_version`. A validation summary. |
| `.../scripts/generate_digital_twin_asset_registry.py` | 63 | `summary` | 1/8 | NOT-A-REPORT | `summarize_asset_registry` (`assets/modeling/assets.py:176-215`). |
| `.../scripts/generate_digital_twin_flexibility_providers.py` | 94 | `summary` | 1/8 | NOT-A-REPORT | `summarize_provider_registry` (`operations/clearing/selection.py:977-1005`). |
| `.../scripts/generate_digital_twin_semantic_graph.py` | 102 | `manifest` | 2/8 | NOT-A-REPORT | A graph manifest. |
| `.../scripts/generate_locational_flexibility_clearing.py` | 176 | `report` | 6/8 | **GOVERNED-VIOLATION** | `_build_report` output (`selection.py:557-614`) augmented in-module at `:147-158` with `constraint_ids` + hand-built `inputs`, and at `:166-174` with `artifacts`. **Role** ✔ — five named stage inputs, four named outputs. **Destination** ✔ — `DEFAULT_REPORT_PATH` (`:29`), the stage's terminal report. **Not-routed** ✔. Missing `source_domain`, `validation`. See §5.5. |
| `.../scripts/report_mv_lv_transformer_overloads.py` | 143 | `report` | 1/8 | NOT-A-REPORT | Destination ✔ (`ArtifactLayout.reports`), but **role** ✘ (no `inputs`/`artifacts`) and **not-routed** ✘ — `interfaces/reporting/digital_twin.py:50-67` wraps it into a governed `network_capacity` report via `canonical_report` → `build_report`. Despite the variable name, the module name, and a local function literally called `build_report` (`:108`, unrelated to `reports.build_report`), this is a domain findings document and the governed path already exists downstream. |
| `.../scripts/run_digital_twin_ev_powerflow.py` | 291 | `summary` | 1/8 | NOT-A-REPORT | Per-scenario power-flow summary. |
| `.../scripts/run_digital_twin_ev_powerflow.py` | 367 | inline dict | 1/8 | NOT-A-REPORT | Merged scenario index. |
| `.../scripts/validate_digital_twin_semantics.py` | 74 | `manifest` | 3/8 | NOT-A-REPORT | Re-writes the existing `graph_manifest.json` with a `validation` sub-block. An in-place manifest annotation, not a new report. |

### 3.7 `projects/admm_thermal_consensus/` — 11 sites, all NOT-A-REPORT

All are study data payloads, **0/8** on `REQUIRED_REPORT_FIELDS`, written to
`outputs/json/` or `outputs/`, keyed entirely by domain quantities. Every
`scripts/pipeline/*.py` module in this study **does** call `script.write_report(...)` — its
governed report is emitted separately, and these JSONs are the data it references.

`scripts/pipeline/build_network.py` (2 sites: bus-weight map, network spec),
`build_study_report.py::results`, `comfort_validation.py::results`,
`generate_agents.py::params`, `imputer_comparison.py::results`, `run_admm.py` (2 sites:
`kpis`, `convergence`), `train_forecaster.py::cv`, `uncertainty_sweep.py` (inline),
`scripts/validate_convergence.py::out`.

`validate_convergence.py` is a standalone operator script, **not** a workflow stage (absent
from `projects/admm_thermal_consensus/workflow.yaml`), so R3's "artifact-producing run"
obligation does not attach. Noted as advisory in §6.

### 3.8 `projects/ev_hosting_flex/` and `projects/synthetic_geojson_feeder/` — 2 sites, all NOT-A-REPORT

All are study data payloads written to `outputs/json/`, keyed entirely by domain
quantities, **0/8** on `REQUIRED_REPORT_FIELDS`, failing both role and destination.
**Every one of these modules also calls `script.write_report(...)`** — verified by scan —
so each stage does emit its governed report; these JSON files are the data artifacts that
report references. Sixteen of them are the `source` files the `ev_hosting_flex` regression
baseline pins (§5, sequencing).

The flagship's pipeline stage writes were migrated (2026-08-17) from direct
`json.dumps` onto `script.write_json(...)` — see §3.9
and §13 — so the only remaining direct sites here are
`prepare_topology_cache::_write_json` (the helper; its 5 call sites are enumerated in §3.9;
the topology-cache seam is owned by that helper), and
`synthetic_geojson_feeder/scripts/generate_building_footprints.py::payload` (a GeoJSON
FeatureCollection; the module emits its governed report at `:25`).

### 3.9 Helper-routed writes — 46 sites

| Helper | Call sites | Class | Rationale |
|---|---|---|---|
| `foundation/platform/reports.py::write_json_report` | `reports.py::write_report:147` | ALREADY-GOVERNED | The sanctioned path: `build_report` → `validate_report` → serialize. |
| | `interfaces/reporting/schemas.py::write_report:112` | ALREADY-GOVERNED | Payload comes from `build_report`, so contract-shaped by construction — but this local helper skips `validate_report`. See §6. |
| | `reports.py::write_manifest:181` | NOT-A-REPORT | A report *index*: `manifest_id`, not `report_id`. |
| `interfaces/reporting/schemas.py::write_json` | `interfaces/reporting/digital_twin.py:127` | NOT-A-REPORT | `digital_twin_report_manifest.json` — indexes three governed reports; it is not one. |
| `projects/regression.py::write_regression_report` | `regression.py:138` | NOT-A-REPORT | See §3.6. |
| `projects/runner.py::_write_manifest` | `runner.py` (`run_project`, `_attach_provenance`) | NOT-A-REPORT | Workflow run manifest, written from two sites: the normal close, and the provenance-assembly failure path added 2026-08-14 so a malformed `spec.simulation` declaration still leaves a manifest to read. |
| `.../digital_twin/build.py::write_build_manifest` | `build.py:173`, `:180` | NOT-A-REPORT | Build manifest, written twice (dry-run and real). |
| `gridalyn/projects/dashboard_catalog.py::write_dashboard_catalog` (relocated — §9) | `generate_digital_twin_dashboard_catalog.py:83` | NOT-A-REPORT | Catalog. |
| `operations/settlement.py::write_flexibility_clearing_scorecard` | `generate_flexibility_clearing_scorecard.py:71` | NOT-A-REPORT | Scorecard. |
| `.../network_impact/catalog.py::write_network_impact_catalog` | `generate_network_impact_dashboard_catalog.py:58` | NOT-A-REPORT | Catalog. |
| `.../network_impact/perturbation_sampler.py::write_sampler_artifacts` | `generate_network_impact_perturbation_samples.py:166` | NOT-A-REPORT | Sidecar. |
| `.../network_impact/physics_model.py::write_physics_surrogate_artifacts` | `train_network_impact_physics_surrogate.py:61` | NOT-A-REPORT | Sidecar. |
| `.../network_impact/surrogate.py::write_surrogate_artifacts` | `generate_network_impact_surrogate.py:67` | NOT-A-REPORT | Model card sidecar. |
| `.../network_impact/verification_report.py::write_network_impact_verification_report` | `generate_network_impact_verification_report.py:349` | NOT-A-REPORT | Side-artifact; no own-I/O sections. |
| `operations/verification.py::write_shadow_report` | `generate_provider_selection_shadow_report.py:129` | NOT-A-REPORT | Shadow comparison. |
| `twin/semantic/validation.py::write_validation_report` | `validate_digital_twin_semantics.py:62` | NOT-A-REPORT | Re-wrapped downstream. |
| `.../prepare_topology_cache.py::_write_json` | `:190, :191, :201, :202, :205` | NOT-A-REPORT | Five cache documents (ratings, downstream topology, feeder selection, nameplate, building counts) behind one direct-scan site. |
| `.../pipeline/*.py::script.write_json` (20 sites) | 18 stage derives + `validate_powerflow::run_stage` | NOT-A-REPORT | The flagship's study-data payloads, migrated 2026-08-17 from direct `json.dumps` to `ProjectScript.write_json`. Same class as the admm siblings above (§13). |

---

## 4. Reconciling counts

### Direct-JSON writes

| Classification | Count |
|---|---|
| `GOVERNED-VIOLATION` | **0** |
| `NOT-A-REPORT` | **40** |
| `ALREADY-GOVERNED` | **1** |
| **Sites examined** | **41** |

`0 + 40 + 1 = 41` ✔

By subtree: `gridalyn/` 40 sites (0 violations, 39 not-a-report, 1 already-governed);
`projects/` 1 site (0 violations, 1 not-a-report — `prepare_topology_cache::_write_json`;
the flagship's 20 stage writes moved to the helper-routed set in §13).

### Helper-routed writes

| Classification | Count |
|---|---|
| `GOVERNED-VIOLATION` | **0** |
| `NOT-A-REPORT` | **44** |
| `ALREADY-GOVERNED` | **2** |
| **Sites examined** | **46** (across 16 helpers) |

`0 + 44 + 2 = 46` ✔

The six violations are unchanged from the first revision, but four of the six now rest on a
different and caller-independent argument, and `operations/clearing/selection.py:639`'s
`NOT-A-REPORT` verdict rests on a *true* premise rather than a false one (§3.5).

---

## 5. Remedies (for a follow-up plan — NOT applied here)

Each remedy is a `write_report` substitution plus the `ReportMetadata` it needs. In every
case `inputs` and `artifacts` must also change from **dicts** to the contract's **lists**
(`file_reference(path, root)` entries) — an output-shape change.

### 5.0 Why these are deferred — corrected

The first revision deferred everything on the ground that *"every fix moves a regression
baseline"*. **That is false, and the claim is withdrawn.** `compare_regression_metric`
(`projects/regression.py:83-89`) pins a `json_path` inside a named `source` file.
Enumerating every `source` across all eight `projects/*/baselines/results_baseline.json`
(122 metric rows, 29 distinct source files) yields:

- 16 × `outputs/json/*.json` — `ev_hosting_flex` study data payloads (§3.8)
- 13 × `outputs/reports/*_report.json` — `admm_report`, `der_voltage_optimization_report`,
  `forecast_report`, `ieee33_daily_timeseries_report`, `ieee33_scenario_comparison_report`,
  `imputer_comparison_report`, `minimal_grid_report`, `powerflow_report`,
  `prosumer_realtime_market_report`, `rl_feeder_report`, `rl_voltage_control_report`,
  `study_report`, `synthetic_geojson_feeder_report`

**None of the six violation artifacts appears in any baseline.** Not
`project_sense_check_report.json`, not `operational_kpi_report.json`, not
`locational_clearing_verification_report.json`, not `network_adapter_validation_report.json`,
not `locational_flexibility_clearing_report.json`. The thirteen governed reports that *are*
pinned all already go through `script.write_report(...)`.

The real risk is **consumer breakage**, not baseline drift, and it is specific per remedy.
The audit still applies no code — this remains an audit — but the reason is now stated
correctly and per-site.

### 5.1 `gridalyn/operations/artifacts.py:150`

Replace `report_path.write_text(json.dumps(report, ...))` with:

```python
write_report(
    report_path,
    metadata=ReportMetadata(
        report_id="operational_kpi_report",
        source_domain="operations",
        model_version_id=model_version_id,
        study_run_id=study_run_id,
        project={"name": project_id, "scenario_id": scenario_id},
    ),
    inputs=[file_reference(p, root) for p in (...) if p.exists()],
    artifacts=[file_reference(paths[name], root) for name in (
        "network_constraints", "flexibility_offers",
        "dispatch_instructions", "settlement_records",
    )],
    summary={**report["summary"], "operation_context": context.to_dict(),
             "constraint_summary": report["constraint_summary"]},
    validation={"valid": True, "errors": [], "warnings": []},
)
```

**What breaks:** `build_operations_catalog` (`artifacts.py:151`) and `build_operation_run`
(`:158`) both read the pre-write in-memory dict — the catalog takes `report=report`, and
`build_operation_run` reads `report["inputs"]` (`:167`) and `report.get("summary", {})`
(`:180`). Reshaping `inputs` into a list of `file_reference` entries changes
`operation_run.json`'s `input_artifacts`, which `validate_operation_run`
(`runs.py:116-145`) then checks. Keep the in-memory `report` dict as-is for those two
consumers and change only what is serialized, or update all three together.
`operations/artifacts.py:185` (the catalog) must **not** change.

### 5.2 `gridalyn/operations/verification.py:419` + `gridalyn/projects/workflows/flexibility/locational_verification.py:131`

One document written twice to the same path. **The first revision's remedy was backwards
and is reversed here.** It said to delete the *caller's* write. But the two payloads are not
the same document:

```python
# verification.py:413-418 — first write, SDK side
"artifacts": {"dispatch": str(dispatch_path), "report": str(report_path)}
#              ^^^^^^^^^^^^^^^^^^ ABSOLUTE machine paths

# locational_verification.py:127-130 — second write, caller side, currently wins
"artifacts": {"dispatch": _relpath(outputs["dispatch"]),
              "report": _relpath(outputs["report"])}
#              ^^^^^^^^^^^^^^^^^^ relative to ROOT
```

Deleting the caller's write would ship **absolute paths** in a governed artifact —
machine-specific, non-reproducible, and a direct regression against the reproducibility
constraint. It is only invisible today because the caller overwrites it.

Corrected remedy:

- **Remove the report write from `write_locational_verification_outputs`**
  (`verification.py:419`), leaving it to write the dispatch parquet and return its path.
  The caller already owns the report.
- Alternatively, if the SDK is to own the write, it must first relativize:
  `file_reference(path, root)` (`reports.py`) already returns
  `{path (relative), bytes, sha256}` and is exactly the target shape — use it rather than
  `str(path)`.
- Then convert the caller's write to `write_report(report_out,
  metadata=ReportMetadata(report_id="locational_clearing_verification",
  source_domain="operations"), inputs=[file_reference(p, ROOT) for p in the five input
  paths], artifacts=[file_reference(p, ROOT) for p in outputs.values()], summary=...,
  validation=...)`.
- The existing `validation` block `{authority, policy}` is **not** the contract's
  `validation`; move it into `summary` and supply a real
  `{"valid": ..., "errors": [], "warnings": []}` derived from the comparison outcome.
- Fold `cases`, `dispatch`, `comparisons`, `constraint_ids` into `summary`.

**What breaks:** nothing in-repo reads
`locational_clearing_verification_report.json`; no baseline pins it. The risk here is the
lowest of the five, and fixing it removes a duplicate write and a reproducibility defect at
the same time.

### 5.3 `gridalyn/projects/sense_checks.py:94`

Highest-confidence, lowest-risk fix — the payload is already 8/8 with correct types, so
`build_report` produces an identical envelope:

```python
write_report(
    out,
    metadata=ReportMetadata(
        report_id="project_sense_check_report",
        source_domain="project_verification",
        project={"name": project.name},
    ),
    inputs=[],
    artifacts=[],
    summary={"checked_count": ..., "passed_count": ..., "failed_count": ...,
             "error_count": ..., "score": ...},
    validation={"valid": not error_failures, "errors": [...], "warnings": [...]},
)
```

**What breaks:** `project_sense_check` *returns* the same dict it writes, and consumers read
the flattened duplicates that sit outside the envelope — `gridalyn/projects/api.py:123-124`
reads `sense["valid"]` to compute `verify_project`'s verdict, and
`gridalyn/interfaces/cli/project.py:124` prints the returned dict. Keep returning the
flattened dict; write the governed one. Two further details: the current write appends a
trailing newline and `write_json_report` also appends one, so byte output is stable; and
`project` changes from a bare string to `{"name": ...}`, so grep
`project_sense_check_report` consumers first. `api.py:143` only references the path.

### 5.4 `gridalyn/twin/adapters/validation.py:98`

`write_network_adapter_validation_report` should call `write_report` with
`ReportMetadata(report_id="network_adapter_validation", source_domain="twin")`. `summary`
already exists (`{counts, artifact_count}`) and `validation` is already the correct
`{valid, errors, warnings, summary}` shape. Needs: `source_domain`, `inputs` (the source
tables under `base_dir`, as `file_reference` entries) and `artifacts` converted from the
current dict-of-dicts to a list.

**What breaks:** both callers — `twin/adapters/network.py:189` and
`twin/adapters/cim.py:87` — already pass `artifact_paths`, so the conversion is local.
`twin/network/metadata.py:105` records the report's *path* as `adapter_validation_report`
inside `base/metadata.json`; the path is unchanged, so lineage holds. Note the layer rule
holds: `twin` may import `foundation`.

### 5.5 `gridalyn/projects/workflows/scripts/generate_locational_flexibility_clearing.py:176`

Replace the terminal `report_path.write_text(...)` with `write_report(report_path,
metadata=ReportMetadata(report_id="locational_flexibility_clearing",
source_domain="operations"), inputs=[file_reference(p, ROOT) for p in the five input
paths], artifacts=[file_reference(p, ROOT) for p in artifact_paths.values()],
summary={... clearing_method, clearing_policy, dt_h, constraint_ids, constraint_summary},
validation={"valid": True, "errors": [], "warnings": []})`.

**What breaks:** `projects/workflows/flexibility/locational_verification.py:103-107` reads
`clearing_report.get("constraint_ids")` from this file and falls back to deriving them from
the selections parquet. Moving `constraint_ids` into `summary` silently switches that stage
to the fallback path, so update the reader in the same change.

**On the sidecar** (`selection.py:639`, `locational_clearing_summary.json`): the first
revision said it *"stays as it is — it is `NOT-A-REPORT`"*. The verdict stands under §1.2,
but the instruction was resting on a false premise (that it lacks `inputs`; it has them for
this caller — §1.1(a)). The correct statement: **the sidecar stays because it is a sidecar,
not because of what it contains.** Two consequences the follow-up plan must respect:

- `write_locational_clearing_outputs` has a **second caller**,
  `projects/ev_hosting_flex/scripts/pipeline/analyze_locational_contracts.py:310`, which
  writes into `projects/ev_hosting_flex/outputs/flexibility/` rather than the shared twin
  directory. Any change to the writer hits both studies.
- Because this stage's `report` dict is threaded *through* the writer before being
  augmented and written again at `:176`, the sidecar and the report share a prefix. If §5.5
  restructures the report into a contract envelope, decide explicitly whether the sidecar
  keeps the flat legacy shape (recommended — it has its own consumers) or follows.

### Sequencing note for the follow-up plan

Re-derived from actual consumers. **The first revision's sequencing cited a study
directory that does not exist** — it had been consolidated away, and the reference is
dropped.

1. **§5.2 first** — lowest risk. No in-repo consumer, no baseline, and it fixes a
   reproducibility defect (absolute paths) plus a duplicate write. Verify: re-run the
   locational verification stage, confirm one write and ROOT-relative `artifacts`.
2. **§5.3** — one behavioural coupling (`projects/api.py:123-124` reads the returned dict),
   handled by keeping the return value flat. Verify: `gridalyn-project verify` on the six
   fixture projects, and the `projects` CI job.
3. **§5.4** — two callers, both in `twin/adapters/`, both already passing `artifact_paths`.
   Lineage in `base/metadata.json` references the path only. Verify: rebuild the twin from
   both the network and CIM adapters.
4. **§5.5** — must land together with the `constraint_ids` reader in
   `locational_verification.py:103`, and must decide the sidecar question above.
5. **§5.1 last** — the widest blast radius: three consumers of one in-memory dict
   (`build_operations_catalog`, `build_operation_run`, and `validate_operation_run`
   downstream of it), and it is the only remedy that changes a document under
   `projects/ev_hosting_flex/outputs/reports/`.

---

## 6. Not examined, and why

Nothing in scope was excluded. For completeness, the following were deliberately **outside**
the enumeration:

- **`tests/`** — test fixtures and helpers. R3 governs artifact-producing *runs*, not test
  scaffolding. Per the plan's edge-case rule these are out-of-scope, not violations.
- **`dashboard/`** — the React SPA. JavaScript, consumes artifacts, produces none.
- **`docs/`, `configs/`, `datasets/`** — no Python write sites.
- **Non-JSON writers** — `to_parquet`, `to_csv`, `to_hdf`, matplotlib `savefig`,
  `rdflib.serialize`. The report contract governs the JSON report envelope; these are the
  artifacts a report *references*.
- **`json.dumps` used without writing** — hashing, logging, embedding in a string, or
  round-tripping through a dataframe cell. The scanner matched only calls whose result is
  passed to `json.dump`, `.write_text(...)` or `.write(...)`, so these never entered the
  count.

### Known limits of the enumeration

1. **Indirection beyond one hop.** §2.2 resolves calls to functions that serialize a
   parameter, one level deep. A helper called *through another helper*, or dispatched
   dynamically (`getattr`, a writer stored in a dict), would still be counted only at the
   innermost write. No such case exists in the tree today — the 15 helpers found are all
   called directly — but the limit is real and the gate cannot detect it.
2. **Name-based call matching.** The helper pass matches call sites by bare callee name, so
   an unrelated function sharing a helper's name would surface as an extra site. That fails
   loudly (an unclassified site) rather than silently, which is the correct direction.
3. **Non-Python writers.** Nothing outside `*.py` under `gridalyn/` and `projects/` is
   scanned.

### Advisory observations, neither a violation of R3 as written

1. `projects/admm_thermal_consensus/scripts/validate_convergence.py` writes an artifact but
   is not a workflow stage (absent from `workflow.yaml`), so no governed report is required.
   If it is ever promoted to a stage, it acquires the obligation.
2. `gridalyn/interfaces/reporting/schemas.py:111` (`write_report`, a *local* helper distinct
   from the platform one) calls `write_json_report` directly, skipping `validate_report`.
   Its payload comes from `build_report` so it is contract-shaped by construction, but a
   malformed `metrics` dict would be written unvalidated. Cheap hardening, not a violation.
3. `projects/regression.py:120` is the closest call under the adopted rule — a governed
   destination rejected only on role (§3.6). Recorded so a future reading of R3 that widens
   to "any document in `outputs/reports/`" finds it already identified rather than
   discovered late.

---

## 7. Locked in by

`tests/test_report_contract.py` — re-derives both enumerations by AST scan and asserts they
match the pinned classification. Twelve tests. A **new** direct-JSON write, a **new**
helper-routed write, or a **new** JSON helper each fail until classified here. The 6
`GOVERNED-VIOLATION` sites are pinned in `_KNOWN_VIOLATIONS` with the remedy section cited,
so they are visible rather than silently tolerated, and the gate fails if a violation is
fixed without updating this audit.

Sites are keyed `"<path>::<enclosing qualname>::<payload identity>#<ordinal>"`. The qualname
and the ordinal are both load-bearing: the first revision keyed on `(file,
payload-variable-name)` with `dict.setdefault`, which meant **a second governed report added
to an already-classified file under an already-classified payload name was absorbed
silently** — seven tests passed and the examined count did not move. Verified fixed by three
mutation probes against `gridalyn/twin/network/metadata.py` (all reverted):

| Probe | Injected | Result |
|---|---|---|
| A | New function, already-pinned file, already-pinned payload name `metadata` | **fails** — `...::write_sneaky_report::metadata#0` unclassified |
| B | Second write of `metadata` **inside** the already-pinned `write_base_metadata` | **fails** — `...::write_base_metadata::metadata#1` unclassified; `examined` 76 → 77; message names the sibling line |
| C | New call to the pinned helper `write_json` | **fails** — helper-routed site unclassified; helper-routed `examined` 22 → 23 |

Two tests read this document, which is why it is tracked here in `docs/development/` rather
than alongside the workflow notes that produced it: those are excluded from the published
repository, and a test may not depend on a path a fresh checkout does not carry. If the file
is missing the tests **fail with a message naming the missing path** rather than erroring or
skipping — the pins are only meaningful alongside the rationale recorded here.

---

## 8. Amendment — 2026-08-06 (§5.2 duplicate write removed)

The sections above are the audit as taken; their counts are historical and are not
rewritten. This amendment records the first remedy applied since.

**Finding #8 closed, in this audit's own recommended direction.** The duplicate-write half
of the corrected §5.2 remedy is applied: the SDK-side report write inside
`write_locational_verification_outputs` (`gridalyn/operations/verification.py`, formerly
`:419`) is **removed**. The function still writes the dispatch parquet, still creates the
report destination's parent directory, and still returns both paths; it no longer
serializes the report. The **surviving single writer** is the caller,
`gridalyn/projects/workflows/flexibility/locational_verification.py` (`generate_report`),
whose ROOT-relative-paths write always won the race — so the bytes that land on disk are
**identical** before and after (verified: the caller's write sequence produces
byte-identical final artifacts; only the transient absolute-paths first write is gone).
No baseline pins the artifact (§5.0), so nothing moved.

**What this changes in the enumerations:**

- Direct-JSON sites examined: **76 → 75**. Removed site:
  `gridalyn/operations/verification.py::write_locational_verification_outputs::report_with_artifacts#0`.
- `GOVERNED-VIOLATION`: **6 → 5**. Reconciliation: `5 + 69 + 1 = 75` ✔
- Helper-routed enumeration: unchanged (`22` across 15 helpers) —
  `write_locational_verification_outputs` never serialized a caller-supplied payload, so it
  was never a pinned helper.
- The caller's site
  (`.../locational_verification.py::generate_report::report#0`) **remains a
  `GOVERNED-VIOLATION`**: it is still hand-serialized. The second half of §5.2 — converting
  that write to `write_report(...)` with contract-shaped `inputs`/`artifacts`/`validation` —
  is still open and still sequenced first in §5's follow-up ordering.

**Related hardening, same phase:** advisory observation §6.2 is also closed — the local
`write_report` in `gridalyn/interfaces/reporting/schemas.py` now runs `validate_report`
before writing and raises a located, remediating `ValueError` on a non-conforming payload
(plan 05-03 tasks 1–2), and `tests/test_canonical_report_conformance.py` gates the tracked
canonical reports.

Pins updated together with this amendment in `tests/test_report_contract.py`
(`_KNOWN_VIOLATIONS`, the examined-count guard, and the module docstring), per §7's rule
that a fixed violation must update the audit and the gate in the same change.

## 9. Amendment — 2026-08-06 (dashboard catalog builder relocated)

The sections above are the audit as taken; their counts and classifications are
historical and are not rewritten. This amendment records a path move only — no
write site was added, removed, or reclassified.

**Layer-exception #13 retired by relocation.** The dashboard catalog builder,
formerly the module `gridalyn.interfaces.reporting.dashboard_catalog`, moved via
`git mv` (content byte-identical) to `gridalyn/projects/dashboard_catalog.py`. Its
only in-package dependency is `gridalyn.twin.network`, so the projects layer hosts it
legally, and the stage script `generate_digital_twin_dashboard_catalog.py` now imports
it downward — retiring the second documented entry in
`tests/test_layer_direction.py::_DOCUMENTED_EXCEPTIONS`, which is now empty. (The
first entry, `validate_workspace`'s upward import in
`gridalyn/foundation/platform/validation.py`, was retired in the same change by
re-homing the composed implementation into `gridalyn/projects/validation.py` behind a
foundation-registered socket.)

**What this changes in the enumerations:**

- The §3.1 direct-write row and the §3.9 helper row for the catalog builder now name
  `gridalyn/projects/dashboard_catalog.py`; their path cells were re-pointed in place
  (marked "relocated — §9") so the documentation path gate stays truthful. Line
  references inside those rows (`149`, `:128-135`) are unchanged and still accurate —
  the file content did not change. The §3.9 call-site reference
  `generate_digital_twin_dashboard_catalog.py:83` predates this move: deleting that
  script's 18-line layer-exception comment shifted the call to line 65.
- Counts are unchanged: 75 direct-JSON sites examined, 5 `GOVERNED-VIOLATION`, 22
  helper-routed writes across 15 helpers. Classification of the site
  (`NOT-A-REPORT`, a catalog) is unaffected by where the module lives.
- Public names are unchanged: `build_dashboard_catalog` and `write_dashboard_catalog`
  remain importable from `gridalyn.interfaces` and `gridalyn.interfaces.reporting`.

Pins updated together with this amendment in `tests/test_report_contract.py`
(`_NOT_A_REPORT_BY_FILE` and `_PARAM_SERIALIZING_HELPERS` path keys).

## 10. Amendment — 2026-08-06: sections 5.1–5.5 applied; zero known violations

The sections above are the audit as taken; their counts are historical. This
amendment records the completion of ALL remaining §5 remedies in one wave. The
gate's `_KNOWN_VIOLATIONS` is now empty, the way the layer gate's exception
allowlist emptied — by fixing causes. Reconciliation: **0 + 69 + 1 = 70**
direct-JSON sites examined (76 at audit time → 75 after §8 → 70 now);
helper-routed enumeration unchanged at 22.

**§5.1** `gridalyn/operations/artifacts.py` — the serialized
`operational_kpi_report.json` is now the contract envelope: KPI metrics,
`operation_context` and `constraint_summary` under `summary`;
`inputs`/`artifacts` as `file_reference` lists; governance ids on
`ReportMetadata`. The consumer constraint was honoured by the first recorded
option: the in-memory `report` dict keeps its pre-conversion shape, so
`build_operations_catalog`, `build_operation_run` and `validate_operation_run`
see byte-identical inputs and the operations catalog is untouched. One
serialized-shape consumer §5.1's analysis missed:
`tests/test_ev_project_operational_artifacts.py` read the file's top-level
`operation_context`; it now reads `summary.operation_context`.

**§5.2** the surviving caller write in
`gridalyn/projects/workflows/flexibility/locational_verification.py` routes
through `write_report(...)`: the five stage inputs as `file_reference`
entries, the dispatch parquet as the artifact, `{authority, policy}` folded
into `summary`, and the contract `validation` derived from the replay
comparison (errors when the cleared case adds overloads; warnings on loading
or voltage regressions). The report no longer lists itself in `artifacts` — a
self-referencing `file_reference` computed pre-write carries a stale hash on
re-runs. S14 closed with it: the dead `report` parameter of
`write_locational_verification_outputs` is removed end-to-end.

**§5.3** `gridalyn/projects/sense_checks.py` routes its on-disk report
through `write_report` (`report_id="project_sense_check_report"`,
`source_domain="project_verification"`). Envelope identity proven literally:
under a frozen clock, all eight `REQUIRED_REPORT_FIELDS` serialize
byte-identically old-vs-new; file-side differences are `project` (bare string
→ `{"name": ...}`, anticipated in §5.3), the standard `governance` block, and
the flattened duplicates plus `checks` which leave the file but remain on the
returned dict that `projects/api.py` and the CLI consume — the return
contract is unchanged. The §6 advisory-3 ruling on `regression.py` (#15) is
now a comment at the write site; this audit's `regression.py` line references
(`:120`, `:138`) have shifted by +10 lines.

**§5.4** `gridalyn/twin/adapters/validation.py` — the writer routes through
`write_report` (`source_domain="twin"`); `source_adapter`, `source_standard`,
`adapter` and `lineage` fold into `summary`; the exported base tables are
recorded as both `inputs` and `artifacts` (`file_reference` lists).
`build_network_adapter_validation_report` keeps its flat shape for in-memory
consumers; both callers consume only the returned path and needed no change.
The lineage pointer in `base/metadata.json` records the path only, unchanged.

**§5.5** the terminal write in
`generate_locational_flexibility_clearing.py` routes through `write_report`
(`report_id="locational_flexibility_clearing"`); `constraint_ids` lives under
`summary.constraint_ids`, and the reader in `locational_verification.py` was
updated in the same change (new envelope → legacy flat → parquet fallback).
The sidecar `locational_clearing_summary.json` keeps its flat legacy shape
per §5.5 — it is a sidecar with its own consumers, not the run's report.

**Installed-layout hardening in the same wave (#30):** both locational-chain
modules dropped module-scope `parents[4]`/`DEFAULT_LAYOUT` for an explicit
`--root` with the located no-tree guard, mirroring
`gridalyn/interfaces/reporting/digital_twin.py`. The same hazard remains in
`spatial_powerflow_validation.py` (recorded as ledger finding #39, not fixed
here).

## 11. Amendment — 2026-08-06: the orphaned-input command chain retired

**Counts move: direct-JSON sites 70 → 69, helper-routed sites 22 → 18.**
`tests/test_report_contract.py` pins both numbers and both classified sets; it
caught every one of these removals before this section was written, which is
what the vanished-site assertions exist for.

**Why.** Five commands — `verify-clearing`, `perturbation-samples`,
`verify-network-impact`, `shadow-report` and `scorecard` — read
`instances/default/digital_twin/flexibility/market_dispatch_timeseries.parquet`
as a default input. A repo-wide scan finds that path read at four sites and
**written at none**. It came from a study that was consolidated away, and the
capability was never re-homed; the provenance recorded in
`instances/default/digital_twin/flexibility/network_impact_physics_labels_report.json`
still points at that former study's output directory.

The five matching steps in `gridalyn/projects/workflows/digital_twin/build.py`
were all `optional=True`, so every `twin build --include-network-impact` run
failed them and still exited 0 — a green exit on an incomplete build, measured
during the Phase 7 docs sweep (5 of 22 steps failed, `rc=0`).

**Removed from the direct-JSON classification (1 site, NOT-A-REPORT):**

| Site | Prior ruling |
|---|---|
| `gridalyn/projects/workflows/flexibility/spatial_powerflow_validation.py::generate_spatial_cls_powerflow_validation::summary#0` | NOT-A-REPORT |

**Removed from the helper-routed classification (4 sites):**

| Site |
|---|
| `generate_flexibility_clearing_scorecard.py::main::write_flexibility_clearing_scorecard#0` |
| `generate_network_impact_perturbation_samples.py::main::write_sampler_artifacts#0` |
| `generate_network_impact_verification_report.py::generate_report::write_network_impact_verification_report#0` |
| `generate_provider_selection_shadow_report.py::generate_shadow_report::write_shadow_report#0` |

**Zero known violations is unaffected.** Every removed site was already
classified NOT-A-REPORT or helper-routed; none was a GOVERNED-VIOLATION, so
the §10 result stands with a smaller denominator.

**What §5.2 now refers to.** That section paired
`gridalyn/operations/verification.py:419` with
`gridalyn/projects/workflows/flexibility/locational_verification.py:131`. The
workflow module is deleted; the operations-layer helpers it called
(`write_locational_verification_outputs`, `build_shadow_report`,
`write_shadow_report`) are **retained** — they are published SDK surface
exported through `gridalyn/operations/__init__.py` and still covered by
`tests/test_locational_clearing_verification.py`. §5.2's ruling therefore
still describes live code; only its workflow-side caller is gone.

**Ledger finding #39 closes as moot.** The `parents[4]` installed-layout
hazard recorded at the end of §10 lived in `spatial_powerflow_validation.py`,
which no longer exists. It is closed by deletion, not by a fix — if that
module is ever reinstated, the hazard returns with it.

## 12. Amendment — 2026-08-17: admm migration onto the Project Developer API

**Counts move: direct-JSON sites 69 → 59, helper-routed sites 18 → 28.**
`tests/test_report_contract.py` pins both numbers and both classified sets; it
caught every one of these reclassifications before this section was written,
which is what the vanished-site assertions exist for.

**Why.** The Project Developer API migrated the
`admm_thermal_consensus` pipeline's study-data JSON writes off raw
`json.dumps` onto the new `script.write_json(...)` surface
(`gridalyn/projects/scripting.py::ProjectScript.write_json`). A direct write
site becomes invisible to the direct scan once the payload is serialized
inside a helper — the direct scan attributes it to the helper instead — so
those 10 documents moved from the §3.7 direct enumeration to the §3.9
helper-routed enumeration. Every migrated module still emits its governed
report via `script.write_report(...)`; the reclassified JSONs are the same
domain-data payloads, unchanged in role (NOT-A-REPORT).

**Removed from the direct-JSON classification (10 sites, NOT-A-REPORT):**

| Site |
|---|
| `build_network.py::main::<inline:DictComp>#0` |
| `build_network.py::main::<inline:feeder,homes_per_bus,...>#0` |
| `build_study_report.py::main::results#0` |
| `comfort_validation.py::main::results#0` |
| `generate_agents.py::main::params#0` |
| `imputer_comparison.py::main::results#0` |
| `run_admm.py::main::convergence#0` |
| `run_admm.py::main::kpis#0` |
| `train_forecaster.py::main::cv#0` |
| `uncertainty_sweep.py::main::<inline:band,...>#0` |

All under `projects/admm_thermal_consensus/scripts/pipeline/`.

**Added to the helper-routed classification (10 sites, NOT-A-REPORT):**

| Site |
|---|
| `build_network.py::main::write_json#0` |
| `build_network.py::main::write_json#1` |
| `build_study_report.py::main::write_json#0` |
| `comfort_validation.py::main::write_json#0` |
| `generate_agents.py::main::write_json#0` |
| `imputer_comparison.py::main::write_json#0` |
| `run_admm.py::main::write_json#0` |
| `run_admm.py::main::write_json#1` |
| `train_forecaster.py::main::write_json#0` |
| `uncertainty_sweep.py::main::write_json#0` |

All under `projects/admm_thermal_consensus/scripts/pipeline/`, routed through
`ProjectScript.write_json`.

**Zero known violations is unaffected.** Every moved site was already
classified NOT-A-REPORT as a direct write; the migration changes only *which*
enumeration names it, not its class. `scripts/validate_convergence.py::out`
remains the study's single direct-JSON write — it is a standalone operator
script, not a workflow stage, and was deliberately left off the migration.

**Reconciliation.** Direct: `0 + 58 + 1 = 59` ✔ (was `0 + 68 + 1 = 69`).
Helper-routed: `0 + 26 + 2 = 28` ✔ (was `0 + 16 + 2 = 18`).

Pins updated together with this amendment in `tests/test_report_contract.py`
(`_NOT_A_REPORT_BY_FILE`, `_HELPER_ROUTED_NOT_A_REPORT`, and both count
guards), per §7's rule that a reclassification must update the audit and the
gate in the same change.

## 13. Amendment — 2026-08-17: ev_hosting_flex migration onto the Project Developer API

**Counts move: direct-JSON sites 59 → 41, helper-routed sites 28 → 46.**
`tests/test_report_contract.py` pins both numbers and both classified sets; it
caught every one of these reclassifications before this section was written,
which is what the vanished-site assertions exist for.

**Why.** The `ev_hosting_flex` pipeline's 20 study-data JSON writes were
migrated (2026-08-17) off raw `json.dumps`
onto the `script.write_json(...)` surface — the same Project Developer API
pattern the admm study adopted in §12. A direct write site becomes invisible
to the direct scan once the payload is serialized inside a helper — the direct
scan attributes it to the helper instead — so those 20 documents moved from
the §3.8 direct enumeration to the §3.9 helper-routed enumeration. Every
migrated module still emits its governed report via
`script.write_report(...)`; the reclassified JSONs are the same domain-data
payloads, unchanged in role (NOT-A-REPORT). The reads moved to
`script.read_json(...)` too; only `prepare_topology_cache.py` (the topology
cache seam, owned by Plan 20-03) still serializes directly through its local
`_write_json` helper, and `synthetic_geojson_feeder` is untouched.

**Removed from the direct-JSON classification (20 sites, NOT-A-REPORT):**

| Site |
|---|
| `analyze_clustered_adoption.py::derive_clustered::payload#0` |
| `analyze_cold_coupling.py::derive_cold_coupling::payload#0` |
| `analyze_cold_insurance.py::derive_cold_insurance::payload#0` |
| `analyze_congestion_risk.py::derive_congestion::payload#0` |
| `analyze_credibility.py::derive_credibility::payload#0` |
| `analyze_fleet_triage.py::derive_fleet_triage::payload#0` |
| `analyze_flexibility_incentive.py::derive_incentive::payload#0` |
| `analyze_locational_contracts.py::derive_locational_contracts::payload#0` |
| `analyze_network_characterization.py::derive_characterization::payload#0` |
| `analyze_network_performance.py::derive_performance::payload#0` |
| `analyze_nonwires_value.py::derive_nonwires_value::payload#0` |
| `analyze_phase_imbalance.py::derive_phase::payload#0` |
| `analyze_voltage_risk.py::derive_voltage::payload#0` |
| `analyze_voltage_risk_network.py::derive_voltage_network::payload#0` |
| `apply_curtailment_contracts.py::derive_curtailment::payload#0` |
| `compute_congestion_annual.py::derive_annual_congestion::payload#0` |
| `compute_curtailment_economics.py::derive_curtailment_economics::payload#0` |
| `validate_powerflow.py::run_stage::violations_payload#0` |

All under `projects/ev_hosting_flex/scripts/pipeline/`.

**Added to the helper-routed classification (20 sites, NOT-A-REPORT):**

| Site |
|---|
| `analyze_clustered_adoption.py::derive_clustered::write_json#0` |
| `analyze_cold_coupling.py::derive_cold_coupling::write_json#0` |
| `analyze_cold_insurance.py::derive_cold_insurance::write_json#0` |
| `analyze_congestion_risk.py::derive_congestion::write_json#0` |
| `analyze_credibility.py::derive_credibility::write_json#0` |
| `analyze_fleet_triage.py::derive_fleet_triage::write_json#0` |
| `analyze_flexibility_incentive.py::derive_incentive::write_json#0` |
| `analyze_locational_contracts.py::derive_locational_contracts::write_json#0` |
| `analyze_network_characterization.py::derive_characterization::write_json#0` |
| `analyze_network_performance.py::derive_performance::write_json#0` |
| `analyze_nonwires_value.py::derive_nonwires_value::write_json#0` |
| `analyze_phase_imbalance.py::derive_phase::write_json#0` |
| `analyze_voltage_risk.py::derive_voltage::write_json#0` |
| `analyze_voltage_risk_network.py::derive_voltage_network::write_json#0` |
| `apply_curtailment_contracts.py::derive_curtailment::write_json#0` |
| `compute_congestion_annual.py::derive_annual_congestion::write_json#0` |
| `compute_curtailment_economics.py::derive_curtailment_economics::write_json#0` |
| `validate_powerflow.py::run_stage::write_json#0` |

All under `projects/ev_hosting_flex/scripts/pipeline/`, routed through
`ProjectScript.write_json`.

**Zero known violations is unaffected.** Every moved site was already
classified NOT-A-REPORT as a direct write; the migration changes only *which*
enumeration names it, not its class. `prepare_topology_cache.py::_write_json`
remains the study's single direct-JSON write (its five call sites were already
helper-routed in §3.9), awaiting the Plan 20-03 topology-cache migration.

**Reconciliation.** Direct: `0 + 40 + 1 = 41` ✔ (was `0 + 58 + 1 = 59`).
Helper-routed: `0 + 44 + 2 = 46` ✔ (was `0 + 26 + 2 = 28`).

Pins updated together with this amendment in `tests/test_report_contract.py`
(`_NOT_A_REPORT_BY_FILE`, `_HELPER_ROUTED_NOT_A_REPORT`, and both count
guards), per §7's rule that a reclassification must update the audit and the
gate in the same change.

## 14. Amendment — 2026-08-20: twin-network-model export stages (Phase 31, Milestone 14)

**Counts move: helper-routed sites 46 → 50. Direct-JSON sites unchanged (41).**

**Why.** Five new additive, terminal pipeline stages (`export_twin_network_model`)
were added to `ev_hosting_flex`, `synthetic_geojson_feeder`,
`der_voltage_optimization`, `prosumer_battery_market`,
`rl_voltage_control_lightsim` and `admm_thermal_consensus`, so each project's
network can be loaded through `gridalyn.twin`'s canonical `NetworkModel`. Four
of the five (all but `synthetic_geojson_feeder`, which needs no extra config
file) write a small provenance JSON — the feeder/config parameters the
exported `NetworkModel` was built from — via `script.write_json(...)` before
calling the export adapter. This is domain-data provenance the governed
`twin_network_model_report` references as an artifact, not a report itself —
the same class as the admm (§12) and ev_hosting_flex (§13) study-data
payloads.

**Added to the helper-routed classification (4 sites, NOT-A-REPORT):**

| Site |
|---|
| `projects/admm_thermal_consensus/scripts/pipeline/export_twin_network_model.py::run_stage::write_json#0` |
| `projects/der_voltage_optimization/scripts/export_twin_network_model.py::run_stage::write_json#0` |
| `projects/prosumer_battery_market/scripts/export_twin_network_model.py::run_stage::write_json#0` |
| `projects/rl_voltage_control_lightsim/scripts/export_twin_network_model.py::run_stage::write_json#0` |

**Reconciliation.** Helper-routed: `46 + 4 = 50`.

Pins updated together with this amendment in `tests/test_report_contract.py`
(`_HELPER_ROUTED_NOT_A_REPORT` and both count guards), per §7's rule that a
reclassification must update the audit and the gate in the same change.
