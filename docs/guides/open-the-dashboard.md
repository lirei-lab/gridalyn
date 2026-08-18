# Open The Dashboard

The dashboard is a general grid and operations viewer. It should load scenarios,
reports, and network-impact metadata from generated catalog files rather than
from hard-coded study assumptions.

## Generate Or Refresh The Catalog

```bash
uv run gridalyn dashboard catalog
```

## Run The Dashboard

For local development, inspect the dashboard package instructions:

```bash
cd dashboard
npm install
npm run dev
```

For container deployment, use the compose file that applies to your environment.
The documentation site itself is served separately from `docs/docker-compose.yml`.

## What To Check

After opening the dashboard:

- scenario selection should be programmatic;
- grid metrics should update with the selected scenario;
- EV-specific text should not dominate the general platform view;
- network-impact and semantic summary cards should come from catalog/report
  metadata;
- missing optional reports should degrade gracefully.

See [Dashboard](../components/interfaces.md) for the data contracts.
