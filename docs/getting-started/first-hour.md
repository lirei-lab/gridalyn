# First Hour With Gridalyn

This path is for a new user who wants to understand Gridalyn as a platform
without reading every page first. Follow it in order. Use demo projects as
executable evidence for platform contracts, not as the definition of the
platform.

## 1. Position Yourself

Read:

- [What Is Gridalyn?](what-is-gridalyn.md)
- [Architecture Map](../platform/capability-architecture.md)
- [Python SDK Overview](../sdk/overview.md)
- [Project Model](../projects/project-model.md)

You should come away with one mental model:

```text
SDK capability -> digital twin artifact -> governed workflow -> report or app
```

The important distinction is:

| Surface | Role |
| --- | --- |
| `gridalyn/` | Reusable SDK and platform capability. |
| `projects/<name>/` | Governed executable study using SDK capabilities. |
| `instances/default/digital_twin/` | Canonical materialized twin artifacts. |
| `docs/` | Public explanation of platform contracts, not a narrative for one demo. |

## 2. Verify The Workspace

From the repository root:

```bash
uv run gridalyn validate
```

This is the lightweight platform check. It validates repository policy and the
project contracts without regenerating heavy outputs.

For stricter checks:

```bash
uv run gridalyn validate --check-project-artifacts
```

## 3. Run One Minimal Contract Check

Start with the minimal project:

```bash
uv run gridalyn project run projects/minimal_grid_project
uv run gridalyn project status projects/minimal_grid_project --check-artifacts
uv run gridalyn project verify projects/minimal_grid_project
```

This verifies the platform's smallest workflow loop: project manifest,
workflow stage, generated artifacts, JSON report, figure, run manifest, and
objective-level sense check.

If you want a benchmark feeder after that, run:

```bash
uv run gridalyn project verify projects/ieee_33_bus_demo
```

If you need the full operations stack, inspect the larger flexibility workflow:

```bash
uv run gridalyn project plan projects/flexibility_cls
uv run gridalyn project status projects/flexibility_cls --check-artifacts
uv run gridalyn project verify projects/flexibility_cls
```

The first command shows what will run. The second command checks whether the
declared reports and figures exist and follow the expected contracts. Treat it
as a comprehensive stress test, not as the only story Gridalyn tells.

## 4. Create A Small Project

```bash
uv run gridalyn project init projects/my_first_case --template grid-study
uv run gridalyn project run projects/my_first_case
uv run gridalyn project status projects/my_first_case --check-artifacts
```

This gives you a clean project workspace with a runnable workflow and a valid
JSON report. Use it to learn the project contract before adding domain logic.

## 5. Choose Your Next Track

| Goal | Next page |
| --- | --- |
| Understand platform boundaries | [Platform, SDK, And Projects](../platform/platform-sdk-projects.md) |
| Use reusable Python surfaces | [SDK Public Contract](../sdk/public-contract.md) |
| Build a new study | [Project Template Guide](../projects/template-guide.md) |
| Understand operational workflows | [Utility Operations](../platform/operations.md) |
| Compare executable examples | [Run Demo Projects](run-demo-projects.md) |
| Publish or review generated outputs | [Reports](../applications/reports.md) |

## What Not To Do First

Do not start by editing generated outputs, dashboard public assets, or
project-local scripts that should be reusable library code. Start with the
project contract, then move reusable behavior into `gridalyn/`.
