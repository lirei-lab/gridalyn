# Contributing

Thanks for your interest in Gridalyn. This document covers what you need to
know before opening a pull request.

## Setup

```bash
git clone https://github.com/lirei-lab/gridalyn
cd gridalyn
pip install -e ".[dev]"
pre-commit install
```

Python 3.12 is required. `uv.lock` is committed if you prefer `uv sync`.

## Running the tests

```bash
pytest -q
```

Some tests invoke workflow stages as subprocesses that call `python`, so run
them with your environment activated — a bare `pytest` from outside the venv
fails those with exit code 127 and the failure looks unrelated to your change.

CI runs the suite on Python 3.12 plus a `projects` job that executes the six
fast governed studies end to end and verifies their baselines. Heavier
validations skip when their gitignored inputs or outputs are absent; those are
operator-verified, so re-run them locally after touching a generator or kernel.

## Code style

`black` and `isort` at line length 88, `flake8` (complexity 10, Google
docstrings), and `mypy --disallow-untyped-defs`. `pre-commit` runs all of them.

Be aware that the tree does **not** currently pass flake8 in full — CI lints
only the files a pull request changes. Match the conventions of the code around
you; do not take an existing warning as licence to add another.

## Architectural rules

These are enforced by tests, not by convention:

- **Imports flow downward** through `foundation → twin → assets → simulation →
  operations → projects → interfaces`. A lower layer never imports a higher one.
- **No eager heavy imports in `__init__.py`.** Use the `_LAZY_EXPORTS`
  name → (module, attribute) map so that importing `gridalyn` stays cheap and
  optional dependencies stay optional.
- **pandapower and lightsim are optional capabilities**, gated through
  `gridalyn/foundation/platform/capabilities.py`. Never assume they import.
- **The SDK does not know about individual projects.** Anything under
  `projects/<name>/` is a study, not a dependency; hardcoding such a path inside
  `gridalyn/` fails a hygiene test.
- **Reports go through `script.write_report(...)`**, never hand-written JSON.

## Changing a study's results

Studies pin their headline metrics in `baselines/results_baseline.json`. A
re-run that moves a pinned value fails, and that failure is the feature: it
forces a change in results to be deliberate rather than incidental.

If your change moves a baseline, say so in the pull request and explain why the
new value is the correct one. Deliberate re-bases are recorded with their
rationale — `projects/ev_hosting_flex/CALIBRATION.md` documents several,
including what evidence justified each. Please follow that pattern.

If you are changing a generator that existing studies depend on, prefer an
**opt-in** parameter that leaves the default path byte-identical, and verify
that it is byte-identical rather than assuming so. Note that adding a draw from
an existing `numpy` generator shifts every later draw and will silently change
results downstream; key a separate stream instead.

## Pull requests

Keep them focused. Explain what changed and why, and include the evidence for
any claim about behaviour — a table, a test, a measurement. Assertions about
physical realism should be backed by a comparison against data, not by
plausibility.
