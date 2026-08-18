# Build A Minimal Digital Twin

Use the minimal tutorial data when you want a fast sanity check without running
a larger workflow.

## Inputs

The tracked demo dataset lives under:

```text
examples/tutorials/data/minimal/
```

It is intentionally small and suitable for smoke tests, tutorials, and examples.
It is not a replacement for governed project workflows.

## Validate The Workspace

```bash
uv run gridalyn platform check-artifacts --summary-only
```

## Inspect Digital Twin Commands

```bash
uv run gridalyn twin --help
```

For the generated digital twin build entrypoint, use:

```bash
uv run gridalyn twin build --dry-run --skip-heavy
```

Remove `--dry-run` only when you intend to regenerate the heavy shared digital
twin artifacts. Note that `--dry-run` is not read-only: it still rewrites
`instances/default/digital_twin/reports/digital_twin_build_manifest.json` with
the planned steps, and that file is tracked, so a dry run leaves the working
tree dirty.

## Next Step

Run a larger project when you need flexibility operations, reports, figures,
and dashboard-facing outputs:

```bash
uv run gridalyn project run projects/ev_hosting_flex
```
