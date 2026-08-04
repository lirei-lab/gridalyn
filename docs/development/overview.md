# Development

Development documentation is for contributors, maintainers, and AI coding
agents working inside the repository. It explains where code belongs, how to
avoid committing generated noise, and how to verify changes before publication.

## Contributor Paths

<div class="landing-grid">
<a class="landing-card" href="../developer-workflow/">
<h3>Human Developer Workflow</h3>
<p>Common commands, generated-file rules, documentation rules, and commit hygiene.</p>
</a>
<a class="landing-card" href="../core-package-architecture/">
<h3>Repository Layout</h3>
<p>Where platform modules live and how canonical SDK boundaries are organized.</p>
</a>
<a class="landing-card" href="../module-boundaries/">
<h3>Module Boundaries</h3>
<p>Stable ownership rules for foundation, twin, assets, simulation, operations, projects, and interfaces.</p>
</a>
<a class="landing-card" href="../testing-and-validation/">
<h3>Testing And Validation</h3>
<p>The verification ladder for unit tests, project sense checks, artifacts, docs, and release readiness.</p>
</a>
<a class="landing-card" href="../project-hygiene/">
<h3>Project Hygiene</h3>
<p>Artifact placement, generated-output policy, and repository cleanliness rules.</p>
</a>
</div>

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
