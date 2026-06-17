"""Determinism harness for the operations clearing path (D-04 gate #2).

This module proves CLEAR-03 reproducibility of the canonical flexibility
clearing/settlement path and doubles as the D-02 fallback detector:

* :func:`test_clearing_identical_across_hashseeds` runs the project's
  ``verify_regression.py`` twice in fully isolated subprocesses with
  ``PYTHONHASHSEED`` set to ``"0"`` and ``"1"``. Independent hash
  randomization across the two runs must not change a single clearing number;
  the only field permitted to differ is the wall-clock ``created_at``
  provenance timestamp, which is normalized out before the byte comparison.
* :func:`test_clearing_identical_under_varied_input_order` exercises the frozen
  ``run_flexibility_clearing_operation`` entry point with the provider rows
  constructed in two different orders and asserts the sorted selections output
  is identical, proving the existing ``provider_id`` tie-break is
  order-independent.

Both tests run on the CURRENT pre-merge state. If the two-``PYTHONHASHSEED``
runs ever diverge on a real clearing number, that is a D-02 re-baseline event:
STOP, do not pick a new canonical order, and escalate to the user (D-01). It is
NOT resolvable autonomously.

This file is reused as D-04 gate #2 by every later sub-merge in this phase.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_VERIFY_SCRIPT = (
    _REPO_ROOT / "projects" / "flexibility_cls" / "scripts" / "verify_regression.py"
)

# The sole non-deterministic provenance field injected by the regression report
# wrapper (gridalyn/projects/regression.py). It is a wall-clock timestamp, not a
# clearing number, so it is normalized out before the byte comparison.
_CREATED_AT_RE = re.compile(r'^\s*"created_at":\s*".*?",?\s*$')


def _normalize_report(stdout: str) -> str:
    """Strip the wall-clock ``created_at`` line from a regression report dump.

    Args:
        stdout: Raw ``json.dumps(..., sort_keys=True)`` regression report text.

    Returns:
        The report text with any ``created_at`` provenance line removed, so two
        runs are byte-comparable on their clearing numbers alone.
    """
    return "\n".join(
        line for line in stdout.splitlines() if not _CREATED_AT_RE.match(line)
    )


def _run_regression(hashseed: str) -> str:
    """Run ``verify_regression.py`` in a fresh subprocess under a hash seed.

    Args:
        hashseed: Value to assign to ``PYTHONHASHSEED`` for the child process,
            isolating hash randomization from the parent and the sibling run.

    Returns:
        The normalized stdout (sorted-keys JSON regression report) of the run.
    """
    env = {**os.environ, "PYTHONHASHSEED": hashseed}
    result = subprocess.run(
        [sys.executable, str(_VERIFY_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"verify_regression.py failed under PYTHONHASHSEED={hashseed}: "
        f"{result.stderr}"
    )
    return _normalize_report(result.stdout)


def test_clearing_identical_across_hashseeds() -> None:
    """The clearing path is byte-identical across two PYTHONHASHSEED values.

    Subprocess isolation gives each run independent hash randomization. A
    divergence here (on a clearing number, not the normalized ``created_at``)
    is a D-02 re-baseline event and must be escalated to the user, never
    resolved by inventing a new canonical order.
    """
    seed0 = _run_regression("0")
    seed1 = _run_regression("1")
    assert seed0 == seed1, (
        "Clearing path is NON-reproducible across PYTHONHASHSEED — D-02 "
        "re-baseline event. Do NOT pick a new canonical order; escalate to "
        "the user per D-01."
    )


def test_clearing_identical_under_varied_input_order() -> None:
    """Clearing output is identical when provider rows are built in any order.

    Constructs a small fixed clearing problem, runs the frozen
    ``run_flexibility_clearing_operation`` entry point once with providers in
    their natural order and once with the rows reversed, and asserts the sorted
    selections are identical. This proves the ``provider_id`` tie-break in the
    locational sort is order-independent (RESEARCH §3 varied-build-order check).
    """
    code = (
        "import json\n"
        "import pandas as pd\n"
        "from gridalyn.operations import run_flexibility_clearing_operation\n"
        "\n"
        "scenario_id = 'sc1'\n"
        "requirements = pd.DataFrame([\n"
        "    {'timestep': 0, 'constraint_id': 'c1', 'required_kw': 50.0},\n"
        "])\n"
        "provider_rows = [\n"
        "    {'provider_id': 'p_a', 'scenario_id': scenario_id,\n"
        "     'provider_type': 'soft_cls_building', 'available_capacity_kw': 30.0,\n"
        "     'base_cost_per_kw_h': 1.0, 'selection_priority': 0},\n"
        "    {'provider_id': 'p_b', 'scenario_id': scenario_id,\n"
        "     'provider_type': 'soft_cls_building', 'available_capacity_kw': 30.0,\n"
        "     'base_cost_per_kw_h': 1.0, 'selection_priority': 0},\n"
        "    {'provider_id': 'p_c', 'scenario_id': scenario_id,\n"
        "     'provider_type': 'soft_cls_building', 'available_capacity_kw': 30.0,\n"
        "     'base_cost_per_kw_h': 1.0, 'selection_priority': 0},\n"
        "]\n"
        "impact_rows = [\n"
        "    {'provider_id': r['provider_id'], 'scenario_id': scenario_id,\n"
        "     'constraint_id': 'c1', 'predicted_deliverability_factor': 1.0,\n"
        "     'predicted_relief_kw': 30.0, 'selection_score': 1.0}\n"
        "    for r in provider_rows\n"
        "]\n"
        "\n"
        "def clear(rows):\n"
        "    providers = pd.DataFrame(rows)\n"
        "    impact = pd.DataFrame(impact_rows)\n"
        "    _events, selections, _report = run_flexibility_clearing_operation(\n"
        "        requirements=requirements, providers=providers, impact=impact,\n"
        "        scenario_id=scenario_id, dt_h=1.0,\n"
        "    )\n"
        "    cols = sorted(selections.columns)\n"
        "    ordered = selections.sort_values(\n"
        "        ['event_id', 'provider_id']\n"
        "    ).reset_index(drop=True)[cols]\n"
        "    return ordered.to_json(orient='records')\n"
        "\n"
        "natural = clear(provider_rows)\n"
        "reversed_order = clear(list(reversed(provider_rows)))\n"
        "assert natural == reversed_order, 'varied-order clearing diverged'\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("OK"), result.stdout
