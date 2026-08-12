# Gridalyn

**Reproducible, citable studies of electric distribution grids and their
distributed energy resources — declarative YAML in, baseline-pinned numbers
out.**

[![Documentation](https://img.shields.io/badge/docs-lirei.ca%2Fgridalyn-2f6f4e)](https://lirei.ca/gridalyn/)
[![CI](https://github.com/lirei-lab/gridalyn/actions/workflows/ci.yml/badge.svg)](https://github.com/lirei-lab/gridalyn/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.12+-blue)](https://www.python.org/)

📖 **[Documentation](https://lirei.ca/gridalyn/)** ·
[Quickstart](https://lirei.ca/gridalyn/getting-started/quickstart/) ·
[Projects](https://lirei.ca/gridalyn/projects/overview/) ·
[Python SDK](https://lirei.ca/gridalyn/sdk/overview/) ·
[Contributing](CONTRIBUTING.md)

Gridalyn is an open-source Python SDK and utility digital-twin platform for
modeling, simulating, and optimizing multi-scale distribution systems — the
flexible building loads, EV chargers, and storage at the edge, and the feeders
and transformers they stress. It serves two audiences at once:

- **researchers** who need studies that survive re-running: validated synthetic
  data, recorded seeds, and headline numbers that carry their uncertainty;
- **utility-platform developers** who need a clean, layered core that can later
  ingest real GIS, CIM, AMI, SCADA, DER, and flexibility-market data.

Most grid studies are hard to reproduce: the load generator was never validated
against anything real, the seed was never written down, and the scripts drifted
after the paper shipped. Gridalyn's answer is to make a study **data, not
code** — and to enforce that posture with tests rather than convention.

## A study is data, not code

A study is two YAML files: a `StudyProject` that declares inputs, scenarios,
and metrics, and a `Workflow` that names the stages which compute them.

```yaml
# project.yaml — the study's contract (abridged)
kind: StudyProject
metadata:
  name: minimal_grid_project
  version: 0.1.0
spec:
  problem:
    type: powerflow_validation
    environment: pandapower_powerflow
  experiments:
    - id: baseline_powerflow
      scenario: baseline
      metrics: [powerflow_converged, min_voltage_pu, bus_count]
```

The runner executes the stage DAG, and every artifact-producing stage writes a
governed report. The run closes with a manifest that records the git commit,
the per-stage seed map, the numeric-stack versions, SHA-256 hashes of the
pinned inputs, and which load-generation model actually ran:

```bash
uv run gridalyn project validate projects/minimal_grid_project
uv run gridalyn project run projects/minimal_grid_project
uv run gridalyn project verify projects/minimal_grid_project
```

`verify` compares every declared metric against the study's committed baseline,
with explicit tolerances. A metric whose source file is missing is a failure,
not a skip.

## What "reproducible" means here

Each of these is held by a dedicated gate in `tests/`, so regressing one is a
red build rather than a silent drift:

- **Provenance over trust.** Seeds are declared in YAML and resolved per stage;
  the run manifest hashes the pinned inputs and records which macro model
  generated the loads, because a silent model substitution was once measured at
  −14% to +32% on the generated base.
- **One report contract.** Every artifact-producing run emits the same governed
  JSON envelope; a test classifies every JSON write site in the repository, so
  a hand-rolled report cannot slip in.
- **Baselines with teeth.** Studies are pinned metric-by-metric against
  committed baselines. Six fast fixture studies run end-to-end and
  baseline-verified on every push, in about 77 seconds.
- **Architecture as a test, not a diagram.** Seven layers, imports strictly
  downward; import hygiene is checked per sub-package in isolated subprocesses;
  the packaging gate builds a real wheel and imports from it.

## The studies

| Study | Role |
|---|---|
| `projects/ev_hosting_flex/` | Flagship research study — EV hosting capacity and flexibility on a Québec all-electric feeder |
| `projects/admm_thermal_consensus/` | Distributed ADMM coordination of cold-climate electric heating, on the same Québec calibration |
| Six small projects | CI contract fixtures — fast, governed, baseline-verified on every push |

The flagship study carries 81 pinned metrics. Its current baseline puts firm
hosting at **11 EVs** (P05–P95: 10–13) and flexible hosting at **16** — a 45%
expansion without network reinforcement — from 50 realizations across seeds and
winter severities, because the point estimates are weather-sensitive. The
stochastic building base is validated on diurnal shape against the all-electric
subset of a real Hydro-Québec 1000-home dataset, and its hot-water tank physics
against the CREST model lineage (`projects/ev_hosting_flex/CALIBRATION.md`).

The findings are reported honestly even where they weaken the flexibility
case: the network is genuinely robust at the median, and the value concentrates
in the tail, the substation, and reinforcement deferral.

## Architecture at a glance

```text
interfaces/   CLI, reporting catalogs, visualization
projects/     study contract, workflow runner, regression, sense checks
operations/   flexibility clearing, dispatch, settlement, KPIs
simulation/   pandapower / LightSim2Grid power flow, environments, analytics
assets/       building, DER, EV, thermal modeling + synthetic data generation
twin/         network topology, CIM/GeoJSON adapters, semantic graph
foundation/   governance, report contract, capabilities, workspace   [stdlib only]
```

Imports flow strictly downward. Studies live outside the package: their YAML
contracts drive the SDK, their artifacts land under each project's `outputs/`
directory, and the default materialized twin lives in
`instances/default/digital_twin/`. A browser dashboard under `dashboard/`
consumes the generated catalogs and reports.

**On the name `twin`.** It is aspirational, and the docs say so rather than
letting readers assume otherwise. Under the Kritzinger taxonomy — which
separates the classes by *automated data flow*, not fidelity — `gridalyn.twin`
is a **digital model with provenance, a declared schema, and a place for a
clock**: not a digital shadow, and not a digital twin. Nothing automatically
carries measurements from a physical feeder into it; every observation is read
off a *solved* network. What would move it up a class is written down in
[Network Model](https://lirei.ca/gridalyn/concepts/network-model/#what-class-of-thing-this-is).

## Install

Requires Python 3.12+ and [`uv`](https://github.com/astral-sh/uv) (plain `pip
install -e ".[dev]"` also works). Node.js 20+ only if you build the dashboard.

```bash
uv sync --extra dev
uv run gridalyn --help
```

For a lighter install, `uv sync` alone gives the core library. Optional
capability groups keep the heavy integrations out of it:

```bash
uv sync --extra geo        # GeoJSON, OSM, geospatial preprocessing
uv sync --extra sim        # pandapower and LightSim2Grid simulation helpers
uv sync --extra ops        # optimization and operational analytics
uv sync --extra dashboard  # map and visualization helpers
uv sync --extra all        # full platform runtime
```

Each `uv sync` synchronises the environment exactly, replacing the installed
set rather than adding to it — combine groups in one command
(`uv sync --extra dev --extra geo`) instead of running them in sequence.

The complete set of extras is `all`, `cim`, `dashboard`, `dev`, `docs`, `geo`,
`ops`, `sim`, `test` and `typing`. **There is no `semantic` extra**; it was
removed on 2026-08-07 when the dead RDF/XML exporter and `rdflib` went with it.
The semantic graph needs no extra — it is Parquet and pandas, both base
dependencies — so `uv sync` alone is enough to build and validate it.

Synthetic load and weather generation is documented in
`docs/sdk/data-generation.md`; treat its output as a synthetic baseline unless
a project explicitly documents calibration.

## Quickstart

```bash
# Check the workspace, then the governed artifacts
uv run gridalyn doctor
uv run gridalyn validate

# Run the smallest governed project end to end
uv run gridalyn project list
uv run gridalyn project run projects/minimal_grid_project
uv run gridalyn project verify-all
```

`verify-all` applies the verification ladder to *every* project under
`projects/`, and a project only passes once its (git-ignored) outputs exist. On
a fresh checkout it therefore reports the un-run projects as failures and exits
non-zero; that is the expected result, not a broken install. Run the projects
you care about first, and note that a fully green `verify-all` also requires
the two long-running studies (`ev_hosting_flex`, `admm_thermal_consensus`).

When you need the full research arc — calibrated inputs, pinned headline
metrics, and reproduce-and-pin verification — run the flagship study. It also
exercises the flexibility-market API end to end (locational clearing, provider
registry, settlement) inside its contract stage. A full source regeneration is
long-running — roughly six hours across 22 stages — and operator-verified via a
pinned verification receipt rather than gated in CI; warm runs against an
existing cache take minutes. To run it:

```bash
uv run gridalyn project run projects/ev_hosting_flex
uv run gridalyn project verify projects/ev_hosting_flex
```

## Command line

`gridalyn` is the root entry point; domains hang off it as subcommands
(`twin`, `project`, `market`, `semantic`, `dashboard`, `platform`), and each is
also installed as a standalone `gridalyn-*` script for automation:

```bash
uv run gridalyn --help
uv run gridalyn project --help
uv run gridalyn-flex --help
```

## Documentation

The full documentation lives at **[lirei.ca/gridalyn](https://lirei.ca/gridalyn/)**
— start with the
[documentation map](https://lirei.ca/gridalyn/getting-started/documentation-map/).
To build it locally:

```bash
uv run --extra docs mkdocs serve -f docs/mkdocs.yml
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, the architectural rules the
tests enforce, and what to do when a change moves a study's pinned baseline;
the operator verification protocol is in `docs/development/verification.md`.
Participation is governed by our [Code of Conduct](CODE_OF_CONDUCT.md), and
[SECURITY.md](SECURITY.md) covers how to report a vulnerability.

## Citing

If you use Gridalyn or its studies in your research, please cite it. GitHub
renders [CITATION.cff](CITATION.cff) as a "Cite this repository" button, which
gives you BibTeX and APA directly.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).

## Disclaimer

Gridalyn can generate and analyze realistic synthetic power-grid scenarios, but
it is not certified operational utility software. Treat v0.1 as a research and
platform-development release. Validate any operational decision support with
utility-grade data, engineering review, and the applicable grid codes.
