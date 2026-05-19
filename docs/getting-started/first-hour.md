# First Hour With Gridalyn

This path is for a new user who wants to understand the platform without
reading every page first. Follow it in order.

## 1. Position Yourself

Read:

- [What Is Gridalyn?](what-is-gridalyn.md)
- [Architecture Map](../platform/capability-architecture.md)
- [Project Model](../projects/project-model.md)

You should come away with one mental model:

```text
network model -> digital twin artifacts -> project workflow -> reports and apps
```

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

## 3. Inspect Demo Projects

Start with the compact IEEE 33-bus demo:

```bash
uv run gridalyn project run projects/ieee_33_bus_demo
uv run gridalyn project status projects/ieee_33_bus_demo --check-artifacts
uv run gridalyn project verify projects/ieee_33_bus_demo
```

This verifies the project workflow, pandapower execution, JSON report contract,
figure generation, and objective-level sense checks on a known distribution
feeder.

Then inspect the larger flexibility workflow if you need the full operations
stack:

```bash
uv run gridalyn project plan projects/flexibility_cls
uv run gridalyn project status projects/flexibility_cls --check-artifacts
uv run gridalyn project verify projects/flexibility_cls
```

The first command shows what will run. The second command checks whether the
declared reports and figures exist and follow the expected contracts.

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
| Run the smallest real project | [IEEE 33-Bus Demo](../projects/ieee-33-demo.md) |
| Reproduce demo projects | [Run Demo Projects](run-ev-project.md) |
| Build a new study | [Project Template Guide](../projects/template-guide.md) |
| Use the Python SDK | [SDK Public Contract](../sdk/public-contract.md) |
| Understand operational workflows | [Utility Operations](../platform/operations.md) |
| Publish or review generated outputs | [Reports](../applications/reports.md) |

## What Not To Do First

Do not start by editing generated outputs, dashboard public assets, or
project-local scripts that should be reusable library code. Start with the
project contract, then move reusable behavior into `gridalyn/`.
