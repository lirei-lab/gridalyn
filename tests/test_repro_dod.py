"""Executable Definition-of-Done harness for REPRO-05.

This module is the auditable proof that ``gridalyn project run
projects/flexibility_cls`` reproduces the committed baselines end-to-end through
the canonical API. It covers the three machine-checkable legs of the Phase-5 DoD
(the fourth — the *fresh-venv* build itself — is the human-verify checkpoint in
Plan 05-02, because it touches the shell/interpreter outside autonomous CLI):

* :func:`test_regression_gate_green` runs the project's ``verify_regression.py``
  in a fresh subprocess and asserts the 74/74 gate exits ``0`` (``"valid":
  true``). This is the headline reproduction claim.
* :func:`test_baseline_identical_across_hashseeds` reuses the existing
  ``tests/test_operations_determinism.py`` seed-0-vs-seed-1 normalized comparison
  (``_run_regression``, which normalizes ``created_at`` internally) and asserts
  the only diff between
  the two runs is the normalized wall-clock ``created_at`` provenance field — the
  committed clearing numbers are byte-identical across independent hash
  randomization.
* :func:`test_run_is_network_free` asserts the ``flexibility_cls`` weather path
  resolves to the committed CSV via ``load_project_tmy`` and the study weather
  module never calls ``download_tmy`` — the run is network-free by construction.

Reuse, do NOT rebuild: the seed matrix and report normalization live in
``test_operations_determinism.py`` and are imported here verbatim (RESEARCH
§Don't Hand-Roll). No new external dependencies are introduced and the sacred
``results_baseline.json`` is never touched. If any leg diverges, that is a
PINNING defect (D-07) surfaced for the Plan 05-02 human checkpoint — tighten the
pin, never re-baseline.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Reuse the existing determinism primitives — the seed matrix and the
# created_at normalization are NOT rebuilt here (RESEARCH §Don't Hand-Roll).
from tests.test_operations_determinism import (
    _VERIFY_SCRIPT,
    _run_regression,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WEATHER_INPUT = (
    _REPO_ROOT / "projects" / "flexibility_cls" / "scripts" / "weather_input.py"
)


def _verify_regression_subprocess(hashseed: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run ``verify_regression.py`` in a fresh subprocess and return the result.

    Args:
        hashseed: Optional ``PYTHONHASHSEED`` value for the child process. When
            ``None`` the parent environment is inherited unchanged.

    Returns:
        The completed process (capturing stdout/stderr) so callers can assert on
        both the return code and the report payload.
    """
    env = dict(os.environ)
    if hashseed is not None:
        env["PYTHONHASHSEED"] = hashseed
    return subprocess.run(
        [sys.executable, str(_VERIFY_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
    )


def test_regression_gate_green() -> None:
    """The flexibility_cls regression gate reproduces the baseline (74/74).

    Invokes the project's ``verify_regression.py`` exactly as the canonical
    ``gridalyn project regression`` path does and asserts exit ``0`` — i.e. the
    committed ``results_baseline.json`` is reproduced with ``"valid": true`` and
    no failed metric. A non-zero exit here is a PINNING defect (D-07), not a
    re-baseline trigger.
    """
    result = _verify_regression_subprocess()
    assert result.returncode == 0, (
        "flexibility_cls regression gate is NOT green — REPRO-05 DoD failure. "
        "This is a PINNING defect (D-07): tighten the pin until the committed "
        f"baseline reproduces; do NOT edit results_baseline.json.\n{result.stdout}"
        f"\n{result.stderr}"
    )
    assert '"valid": true' in result.stdout, (
        "regression report did not report valid=true:\n" + result.stdout
    )


def test_baseline_identical_across_hashseeds() -> None:
    """The committed numbers are byte-identical across two PYTHONHASHSEED values.

    Reuses the seed-0-vs-seed-1 normalized comparison from
    ``test_operations_determinism`` (``_run_regression``, which normalizes the
    ``created_at`` provenance line internally). Each run executes
    ``verify_regression.py`` in a fully isolated subprocess with
    independent hash randomization; after the wall-clock ``created_at`` provenance
    line is normalized out, the two reports must be byte-identical. A divergence
    on a clearing number is a D-07 pinning defect surfaced to the human
    checkpoint — never an autonomous re-baseline.
    """
    seed0 = _run_regression("0")
    seed1 = _run_regression("1")
    assert seed0 == seed1, (
        "flexibility_cls baseline is NON-reproducible across PYTHONHASHSEED — "
        "REPRO-05 DoD failure. The only permitted diff is the normalized "
        "created_at provenance field. This is a PINNING defect (D-07): tighten "
        "the pin; do NOT pick a new canonical order or re-baseline."
    )
    # The harness must actually be exercising the normalization, not comparing
    # two empty strings: a real regression report carries the "valid" field.
    assert '"valid"' in seed0, "regression report was empty — harness not wired"


def test_run_is_network_free() -> None:
    """The flexibility_cls weather path is the committed CSV, never download_tmy.

    The run is network-free by construction: the study weather module pins the
    committed ``tmy_trois_rivieres.csv`` via ``load_project_tmy`` and explicitly
    forbids ``download_tmy`` (whose synthetic fallback would change the study
    day). This asserts the source never reaches ``download_tmy`` and that the
    pinned ``TMY_SOURCE`` label is intact.
    """
    weather_src = _WEATHER_INPUT.read_text(encoding="utf-8")

    # Parse the module so a *mention* of download_tmy in the docstring warning
    # (the module deliberately documents why NOT to use it) is not mistaken for a
    # live-fetch call. Only an actual call node fails the network-free leg.
    tree = ast.parse(weather_src)
    download_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "download_tmy")
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "download_tmy"
            )
        )
    ]
    assert not download_calls, (
        "flexibility_cls weather path CALLS download_tmy — the run is NOT "
        "network-free; the committed TMY CSV must be the only weather source."
    )
    # The module must also not import download_tmy as a callable into scope.
    imported_download = any(
        isinstance(node, ast.ImportFrom)
        and any(alias.name == "download_tmy" for alias in node.names)
        for node in ast.walk(tree)
    )
    assert not imported_download, (
        "flexibility_cls weather module imports download_tmy — the live-fetch "
        "path must not be reachable on the reproducible route."
    )
    # The pinned CSV loader and its source label are the only weather route.
    assert "load_project_tmy" in weather_src
    assert "TMY_SOURCE" in weather_src

    # Behavioral confirmation: importing and reading the pinned loader resolves
    # the committed CSV (no network), and the source label is the pinned value.
    sys.path.insert(0, str(_WEATHER_INPUT.parent))
    try:
        import importlib

        weather_input = importlib.import_module("weather_input")
        importlib.reload(weather_input)
    finally:
        sys.path.pop(0)

    if not weather_input.TMY_INPUT_PATH.exists():
        pytest.skip("committed TMY CSV not present in this checkout")

    tmy = weather_input.load_project_tmy()
    assert not tmy.empty, "pinned TMY CSV resolved to an empty frame"
    assert tmy.attrs["gridalyn_weather_source"] == weather_input.TMY_SOURCE
    # Guard the forbidden "auto" source is still rejected (D-08, network-free).
    with pytest.raises(ValueError):
        weather_input.guard_pinned_weather_source("auto")
