# Development

Development documentation is for contributors, maintainers, and AI coding
agents working inside the repository. It explains where code belongs, how to
avoid committing generated noise, and how to verify changes before publication.

## Contributor Paths

<div class="landing-grid" markdown>

<a class="landing-card" href="developer-workflow/">
<h3>Human Developer Workflow</h3>

Common commands, generated-file rules, documentation rules, and commit hygiene.
</a>

<a class="landing-card" href="ai-agent-guide/">
<h3>AI Agent Guide</h3>

Task boundaries, verification expectations, project commands, and safe editing
rules for coding agents.
</a>

<a class="landing-card" href="core-package-architecture/">
<h3>Repository Layout</h3>

Where platform modules live and how canonical SDK boundaries are organized.
</a>

<a class="landing-card" href="code-structure-audit/">
<h3>Code Structure Audit</h3>

Current module boundaries, structural risks, cleanup priorities, and rules for
new code.
</a>

<a class="landing-card" href="testing-and-validation/">
<h3>Testing And Validation</h3>

The verification ladder for unit tests, project sense checks, artifacts, docs,
and release readiness.
</a>

</div>

## Development Rule

Reusable behavior belongs in `gridalyn/`. Project scripts should orchestrate
that behavior and write declared outputs. Documentation should explain the
public contract, not private implementation accidents.

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
