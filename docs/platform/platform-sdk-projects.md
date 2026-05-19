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
from gridalyn.foundation import GridalynWorkspace

workspace = GridalynWorkspace(".")
workspace.layout.base          # digital_twin/base
workspace.layout.flexibility   # digital_twin/flexibility
workspace.layout.operations    # digital_twin/operations
workspace.project_path("demo") # projects/demo
```

Project workflows may override paths, but default platform commands should use
the canonical `digital_twin/*` roots.

## Compatibility Boundary

Historical import paths such as `gridalyn.network` and `gridalyn.modeling`
remain available for compatibility. New code should use the canonical package
areas and the `gridalyn` CLI vocabulary.
