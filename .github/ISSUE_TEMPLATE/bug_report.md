---
name: Bug report
about: Something behaves differently from what the documentation says
title: ''
labels: bug
assignees: ''
---

## What happened

## What you expected

## Reproduction

The command or code you ran, and the project it ran against:

```bash

```

## Environment

- Gridalyn version or commit:
- Python version (`python -V`):
- Installed extras (`pip install -e ".[dev]"`, `.[sim]`, …):
- OS:

## If a result moved

If a study's pinned numbers changed, include the regression output — it names
each metric, what was expected, and what was produced:

```bash
uv run gridalyn project regression projects/<name>
```

Note that `outputs/` is not committed, so a study must be run before `verify` or
`regression` can read anything.
