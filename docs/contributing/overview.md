# Development

Development documentation is for contributors, maintainers, and AI coding
agents working inside the repository. It explains where code belongs, how to
avoid committing generated noise, and how to verify changes before publication.

## Contributor Paths

- [Human Developer Workflow](developer-workflow.md) — Common commands, generated-file rules, documentation rules, and commit hygiene.
- [Repository Layout](module-boundaries.md) — Where platform modules live and how canonical SDK boundaries are organized.
- [Module Boundaries](module-boundaries.md) — Stable ownership rules for foundation, twin, assets, simulation, operations, projects, and interfaces.
- [Testing And Validation](testing-and-validation.md) — The verification ladder for unit tests, project sense checks, artifacts, docs, and release readiness.
- [Project Hygiene](project-hygiene.md) — Artifact placement, generated-output policy, and repository cleanliness rules.
## Development Rule

Reusable behavior belongs in `gridalyn/`. Project scripts should orchestrate
that behavior and write declared outputs. Documentation should explain the
public contract, not incidental implementation details.

Before sending a change for review, run the smallest relevant verification
first, then the broader checks:

```bash
uv run --with pytest python -m pytest -q
env UV_CACHE_DIR=/tmp/uv-cache uv run --extra docs mkdocs build --strict -f docs/mkdocs.yml
git diff --check
```

For project-facing changes, also run:

```bash
uv run gridalyn project verify projects/<name>
```
