# Installation

Gridalyn is a Python workspace managed with `uv`. Everything on the Start path
runs in that environment, and installing it takes one command.

## Prerequisites

- Python 3.12 or newer;
- [`uv`](https://github.com/astral-sh/uv) for dependency management;
- Git.

Install `uv` if needed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Install the environment

From the repository root:

```bash
uv sync
```

That is the whole SDK and CLI: pandapower, pvlib, geopandas, LightGBM and the
plotting stack are all in the base install, and every page on the Start path
runs on it.

## Check the installation

```bash
uv run gridalyn doctor
```

`doctor` prints a short summary and ends with a verdict. On a fresh clone it
looks like this; the three extras read `missing` because the Start path does
not need them:

```text
Gridalyn 0.1.0 on Python 3.12.11 (.../gridalyn/.venv/bin/python)
Workspace: .../gridalyn (valid)
Projects: 11 found
Optional extras (not needed for the Start path):
  missing  geo  osmnx          only if you need it: pip install "gridalyn[geo]"
  missing  ops  cvxpy          only if you need it: pip install "gridalyn[ops]"
  missing  sim  lightsim2grid  only if you need it: pip install "gridalyn[sim]"
Ready: run 'gridalyn quickstart my-first-study' for a first result.
```

`gridalyn doctor --json` prints the same facts as one JSON payload, for
scripts.

## When you need more

??? note "Optional extras: OpenStreetMap, LightSim2Grid, cvxpy"

    Three optional capabilities each add one module that is kept out of the
    base install:

    | Extra | Adds | Needed for |
    | --- | --- | --- |
    | `geo` | `osmnx` | downloading OpenStreetMap streets and building footprints |
    | `sim` | `lightsim2grid` | the LightSim2Grid power-flow backend |
    | `ops` | `cvxpy` | `gridalyn market` commands and voltage-constrained DER dispatch |

    `all` installs all three. You do not have to predict which you need: when
    a study stage stops on a missing capability, the error names the extra and
    prints a `pip install "gridalyn[<extra>]"` command; in this `uv` workspace
    the equivalent is `uv sync --extra <extra>`.

    `uv sync` synchronises the environment exactly: each command *replaces* the
    installed set rather than adding to it, so `uv sync --extra geo` after
    `uv sync --extra dev` uninstalls the dev toolchain. Pass every group you
    want in one command:

    ```bash
    uv sync --extra dev --extra geo
    ```

??? note "Contributing: tests, linters and the documentation build"

    `uv sync --extra dev` installs the full runtime plus the test, lint and
    documentation tooling. The rest is in [Contributing](../contributing/overview.md).

??? note "The browser dashboard"

    Node.js 20 and Docker are needed only for the browser dashboard; see
    [Open The Dashboard](../guides/open-the-dashboard.md).

??? note "Byte-stable results across machines"

    For a pinned Python and a frozen lock, follow
    [Reproduce A Published Result](../guides/reproducibility.md).

Next: [Quickstart](quickstart.md)
