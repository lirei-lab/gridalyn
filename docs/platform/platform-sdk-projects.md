# Platform, SDK, And Projects

Gridalyn separates three concerns that are easy to mix up in research code:

| Layer | What It Is | What Belongs There | What Does Not Belong There |
| --- | --- | --- | --- |
| Platform | The governed architecture and artifact contract. | Digital twin roots, IDs, reports, manifests, validation rules, compatibility policy. | One-off study assumptions. |
| SDK | Reusable Python capabilities under `gridalyn/`. | Network models, GeoJSON preprocessing, simulation helpers, operation contracts, semantic graph builders. | Hard-coded project paths or manuscript outputs. |
| Projects | Executable case studies under `projects/<name>/`. | `project.yaml`, `workflow.yaml`, local scripts, declared inputs, generated outputs. | Reusable platform logic that another project would need. |

The dependency direction is intentionally one-way:

```text
projects/<name>  ->  gridalyn SDK  ->  platform artifact contract
```

Code under `gridalyn/` must not import from `projects/`. A hygiene test enforces
that boundary.

## Workspace Contract

Applications should use `GridalynWorkspace` and `ArtifactLayout` instead of
hard-coding directories:

```python
from gridalyn.foundation import workspace_from_path

workspace = workspace_from_path("projects/demo/scripts")
workspace.root                         # repository or source-archive root
workspace.layout.configs               # configs
workspace.layout.default_instance      # instances/default
workspace.layout.base                  # digital_twin/base
workspace.layout.flexibility           # digital_twin/flexibility
workspace.layout.operations            # digital_twin/operations
workspace.project_path("demo")         # projects/demo
```

`workspace_from_path()` discovers the workspace from a nested file or directory.
It uses Git metadata when available and falls back to Gridalyn source markers
(`pyproject.toml`, `gridalyn/`, and `projects/`) so downloaded source archives
and clean public checkouts work the same way.

Project workflows may override paths, but default platform commands should use
the canonical `configs/`, `instances/`, `projects/`, and `digital_twin/*`
roots. Use `GridalynWorkspace(root)` only when the caller already knows the
exact workspace root.

## Compatibility Boundary

Historical import paths such as `gridalyn.network` and `gridalyn.modeling`
remain available for compatibility. New code should use the canonical package
areas and the `gridalyn` CLI vocabulary.
