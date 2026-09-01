# Release Readiness

This page defines the initial public release boundary for Gridalyn. The goal is
not to claim operational parity with mature utility platforms; the goal is to
publish a coherent, reproducible platform core that can grow toward that target.

## V0.1 Positioning

Gridalyn v0.1 is a **utility network-model platform seed**:

- synthetic data first;
- model-centric rather than script-centric;
- North America semantic profile;
- project-governed workflows;
- canonical Parquet/JSON artifacts;
- reproducible demo workflows;
- dashboard-ready catalog and reports;
- import/export adapter contracts ready for richer utility data sources.

**What v0.1 does not claim.** `gridalyn.twin` is a **canonical, identified,
schema-declared digital model**, and the SDK ships the measured-state ingest
path — automated one-way physical → digital flow — so under the Kritzinger
taxonomy a deployment becomes a digital *shadow* when a user feeds that path
their own measured data. v0.1 does not claim the layer *is* a shadow out of
the box: the SDK cannot ship measured data, both producers it exercises in CI
remain simulated-or-fixture, and the measured path at scale is
operator-receipted (protocol `measured-state-ingest`). It is not a digital
twin (which needs both directions — a recorded non-goal). Treat
"digital twin" in the package and directory names as a target, and see
[Network Model](../components/twin.md#what-problem-this-layer-solves) for
the measurement behind that statement.

The public demos are included because they exercise different platform
capabilities. None of them is the platform boundary.

## In Scope

| Area | Public v0.1 commitment |
| --- | --- |
| Core SDK | `gridalyn` Python package with network, adapter, modeling, analytics, market, semantic, reporting, project, workflow, and CLI modules. |
| Network model | Repository API over generated `instances/default/digital_twin/base` Parquet artifacts, with endpoint and connectivity validation. |
| Adapters | Synthetic pandapower adapter and CIM-like Parquet adapter with descriptor metadata. |
| Project workflows | `project.yaml` and `workflow.yaml` contracts using `apiVersion`, `kind`, `metadata`, and `spec`. |
| Demo workflows | `projects/*` cover minimal grids, benchmark feeders, GeoJSON synthesis, prosumer markets, DER optimization, RL voltage control, and flexibility operations., plus the ev_hosting_flex and admm_thermal_consensus research studies. |
| Semantic layer | North America profile using CIM, ASHRAE 223/Brick, OpenADR, IEEE 2030.5, EFOnt, and local CLS extensions. |
| Reports | Canonical JSON manifests and validation reports with lineage and artifact checks. |
| Dashboard integration | Dashboard catalog metadata can consume project, digital twin, semantic, and network-impact outputs. |
| Governance | Artifact policy, regression baseline, docs build, and release checks are documented and testable. |

## Out Of Scope For V0.1

| Area | Reason |
| --- | --- |
| Certified utility operations | v0.1 is not certified for operational switching, planning approval, protection studies, or regulatory reporting. |
| Full CIM service | The current CIM path is a Parquet adapter contract, not a complete CIM RDF or service implementation. |
| Live utility integrations | GIS, AMI, SCADA, OMS, DERMS, and market integrations are adapter targets, not shipped integrations. |
| Managed model server | The model repository is local/library-first. A hosted service can be built on top later. |
| Full dashboard product | The dashboard is an artifact viewer and digital-twin explorer, not yet a complete operator console. |
| Publication workspace | Papers, presentations, and compiled document artifacts are outside the public platform architecture. |

## Required Release Checks

Run these commands from the repository root before tagging or publishing:

```bash
uv run --with pytest python -m pytest -q
uv run --extra docs mkdocs build --strict -f docs/mkdocs.yml
uv run gridalyn platform check-artifacts --summary-only
uv run gridalyn project verify-all
uv run gridalyn project regression projects/ev_hosting_flex
node --test dashboard/src/*.test.js
(cd dashboard && npm run build)
```

Expected outcome:

- unit tests pass;
- documentation builds with strict MkDocs checks;
- no generated data, dashboard build outputs, large binaries, or compiled
  document artifacts are accidentally tracked;
- all governed demo projects verify successfully;
- larger workflow regression baselines remain healthy;
- dashboard tests and production build succeed.

## Public Documentation Rules

The public documentation should prioritize the platform in this order:

1. documentation map, installation, quickstart, and reproducibility;
2. architecture, capability architecture, digital twin data, building models,
   and project workflow contracts;
3. demo project execution and workflow YAML reference;
4. operations, flexibility, network-impact analysis, reports, and dashboard
   integration;
5. semantic graph and graph database migration path;
6. developer guide, public API, hygiene, and artifact governance;
7. release readiness and roadmap.

Do not make publication drafts, presentation workspaces, archives, or local
runtime folders part of the main navigation. The product story should stay
centered on the platform core and its executable workflows.

## Publication Checklist

- README explains Gridalyn as a platform, not a single-library prototype.
- MkDocs navigation starts with user onboarding, architecture, release scope,
  workflows, platform contracts, and development governance.
- Demo workflows can be validated from their project contracts and public docs.
- Generated outputs are ignored unless they are intentionally tiny tutorial
  fixtures.
- Package metadata does not promise unavailable hosted services.
- All examples are clearly either tutorials or workflow entrypoints.
- Regression baselines identify meaningful behavioral drift.

## Citation And DOI

The platform exists so a published result can be re-derived and cited. The
citation apparatus is complete except for the one step that cannot be automated
from inside the repository: minting the DOI.

**What is already in place.**

- `CITATION.cff` — the citable record. Its `version` is asserted against
  `pyproject.toml` by `tests/test_citation_metadata.py`, because a citation
  naming a version this tree is not at is worse than no citation.
- `.zenodo.json` — the deposition metadata Zenodo reads when a GitHub release
  is archived. Title, version and licence are asserted to agree with
  `CITATION.cff` by the same test.

**Minting the DOI — a human step, once.**

1. Sign in at <https://zenodo.org> with the GitHub account that owns the
   repository at <https://github.com/lirei-lab/gridalyn>, and enable it
   under *GitHub → Repositories*.
   Zenodo only archives releases created **after** the switch is on.
2. Cut a GitHub release whose tag matches `pyproject.toml`'s `version`
   (`v0.1.0` for `0.1.0`). Zenodo archives the tarball and mints two DOIs: a
   **concept DOI** that always resolves to the newest version, and a
   **version DOI** for that release alone.
3. Put the **concept DOI** in `CITATION.cff` as a bare `doi:` field — the
   identifier, not a URL:

   ```yaml
   doi: 10.5281/zenodo.XXXXXXX
   ```

   `test_doi_when_present_is_well_formed` skips while the field is absent and
   starts asserting its shape the moment it is added.
4. Re-run `uv run pytest -q tests/test_citation_metadata.py` and confirm four
   passes with no skip.

**On every subsequent release**, bump `version` in `pyproject.toml`,
`CITATION.cff` and `.zenodo.json` together — the test fails if they drift — and
leave the concept DOI unchanged, since it is what a reference manager resolves.

## Next Milestones

The next public milestones should remain compatible with the v0.1 contracts:

- model snapshot versioning and diff reports;
- capability contracts for foundation, digital twin, modeling, simulation,
  market operations, experiments, and applications;
- richer network-query APIs by feeder, transformer, downstream zone, and
  operational state;
- expanded CIM import/export coverage;
- hosted model service prototype;
- dashboard network explorer driven by the repository API;
- flexibility clearing that treats topology and provider aggregation as first
  class constraints.
