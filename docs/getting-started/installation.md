# Installation

This repository is a Python workspace with a JavaScript dashboard for Gridalyn: the core
digital-twin SDK, governed project workflows, semantic graph exports, canonical
reports, and the dashboard. Use the `gridalyn` CLI for all local workflows.

## Prerequisites

Recommended local tools:

- Python 3.12 or newer;
- `uv` for Python dependency management;
- Node.js 20 or newer for the dashboard;
- Docker and Docker Compose for local dashboard deployment;
- Git.

Install `uv` if needed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Python Environment

From the repository root:

```bash
uv sync --extra dev
```

Use plain `uv sync` when you only need the installable SDK and CLI. Optional
extras install heavier capability groups:

```bash
uv sync --extra geo        # geospatial preprocessing and OSM tooling
uv sync --extra sim        # pandapower and LightSim2Grid helpers
uv sync --extra ops        # optimization and operational analytics
uv sync --extra semantic   # semantic graph and database tooling
uv sync --extra dashboard  # dashboard and visualization helpers
uv sync --extra all        # full runtime capability set
```

The `dev` extra installs the full runtime plus test and documentation tooling
for the repository workflow.

Run the test suite:

```bash
uv run --with pytest python -m pytest -q
```

Run a focused test module:

```bash
uv run --with pytest python -m pytest tests/test_project_hygiene.py -q
```

## Dashboard Environment

Install frontend dependencies:

```bash
npm install --prefix dashboard
```

Run checks:

```bash
npm --prefix dashboard run lint
npm --prefix dashboard run build
```

Deploy locally with compose:

```bash
docker compose -f dashboard/docker-compose.yml up -d --build dashboard
```

The dashboard is typically available at:

```text
http://localhost:8081/
```

## Documentation Environment

Build the documentation:

```bash
uv run --extra docs mkdocs build --strict -f docs/mkdocs.yml
```

MkDocs writes generated HTML to the root `site/` directory, which is ignored by
Git. The source documentation lives under the domain folders in `docs/`.

## Repository Layout

The main source directories are:

```text
configs/                 reusable grid and geography configuration
gridalyn/                canonical Python SDK package and namespace
projects/                governed reproducible workflows
instances/default/       default local digital-twin instance
dashboard/               browser application source
docs/                    MkDocs source
examples/                tutorials and data-acquisition examples
```

Generated simulations can update many figures, Parquet files, and JSON reports.
Review `git status --short` before committing so generated project outputs do
not get mixed with source-only changes.

## Next Step

Continue with the [Reproducibility Guide](reproducibility.md) after the
environment is installed.
