# Contributing

Thanks for your interest in Gridalyn. This page is the entry point; the
detail lives in the [Contributing section](https://lirei.ca/gridalyn/contributing/overview/)
of the documentation, whose source is under `docs/contributing/`.

## Setup

The source repository, `github.com/lirei-lab/gridalyn-dev`, is private until
publication; pull requests are opened there, by collaborators with access.

```bash
git clone https://github.com/lirei-lab/gridalyn-dev.git gridalyn
cd gridalyn
pip install -e ".[dev]"
pre-commit install
```

Python 3.12 is required. `uv.lock` is committed, and CI measures in an
environment synced `--locked` from it.

## Before you open a pull request

- **Put code where it belongs.** Imports flow downward through `foundation →
  twin → assets → simulation → operations → projects → interfaces`; reusable
  behaviour lives in `gridalyn/`, never in a study's scripts; importing a
  sub-package must not load an optional dependency. Tests enforce all of this:
  [Architecture Rules](docs/contributing/module-boundaries.md).
- **Follow the conventions.** Verb prefixes, code style, lazy exports and
  error messages: [Conventions](docs/contributing/conventions.md).
- **Run the gates CI will run.** Every CI gate and the command that runs it
  locally — tests, three mypy ratchets, the documentation instruction ledger
  and path checks, the mermaid check, verification receipts, lint on changed
  files — is listed in
  [What CI checks on your pull request](docs/contributing/developer-workflow.md#what-ci-checks-on-your-pull-request).
- **Pick the right check.** [Testing And Validation](docs/contributing/testing-and-validation.md)
  says which check proves which change, and how to read a skip.
- **After touching a generator or kernel**, run what CI cannot:
  [Operator Verification](docs/contributing/verification.md).

## Changing a study's results

Studies pin their headline metrics in `baselines/results_baseline.json`. A
re-run that moves a pinned value fails, and that failure is the feature: it
makes a change in results deliberate rather than incidental. If your change
moves a baseline, say so in the pull request, explain why the new value is the
correct one, and record the re-base as
[Recording a re-base](docs/contributing/verification.md#recording-a-re-base)
describes.

If you change a generator that existing studies depend on, prefer an
**opt-in** parameter that leaves the default path byte-identical, and verify
that it is byte-identical rather than assuming so. Adding a draw from an
existing `numpy` generator shifts every later draw and silently changes results
downstream; key a separate stream instead.

## Pull requests

Keep them focused. Explain what changed and why, and include the evidence for
any claim about behaviour — a table, a test, a measurement. A claim about
physical realism needs a comparison against data, not plausibility.
