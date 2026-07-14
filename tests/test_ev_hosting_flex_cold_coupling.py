"""Tests for the cold-coupling comparison — the study's lead finding.

Tier 1 — hand-computed kernel check that the naive toggle actually removes the
cold escalation (no cache, no SDK base). Tier 2 — governed reproduce-and-pin
over the emitted comparison JSON (skipif absent).
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts._annual import N_DAYS, ev_fleet_annual
from projects.ev_hosting_flex.scripts.config import (
    PROJECT_OUTPUTS_DIR,
    SEED,
)

_CMP = PROJECT_OUTPUTS_DIR / "json" / "cold_coupling_comparison.json"
_SKIP = (
    "cold_coupling_comparison.json not present; run analyze_cold_coupling.py "
    "first (outputs are gitignored)"
)


def test_naive_toggle_removes_cold_escalation() -> None:
    """A naive fleet draws the SAME energy on cold and mild years; cold-coupled draws more."""
    cold_year = np.full(N_DAYS, -15.0)
    mild_year = np.full(N_DAYS, 20.0)
    # Cold-coupled: cold year draws more than mild.
    cc_cold = ev_fleet_annual(np.random.default_rng(SEED), 3, cold_year, hod0=0)
    cc_mild = ev_fleet_annual(np.random.default_rng(SEED), 3, mild_year, hod0=0)
    assert cc_cold.sum() > cc_mild.sum() * 1.2
    # Naive (kcold=0): cold and mild years draw the SAME (no cold escalation);
    # the only difference would be the rng stream, which is seed-identical here.
    nv_cold = ev_fleet_annual(
        np.random.default_rng(SEED), 3, cold_year, hod0=0,
        plugin_kcold=0.0, ev_kwh_kcold=0.0,
    )
    nv_mild = ev_fleet_annual(
        np.random.default_rng(SEED), 3, mild_year, hod0=0,
        plugin_kcold=0.0, ev_kwh_kcold=0.0,
    )
    assert nv_cold.sum() == pytest.approx(nv_mild.sum())
    # On a cold year the naive fleet draws LESS than the cold-coupled one.
    assert nv_cold.sum() < cc_cold.sum()


@pytest.mark.skipif(not _CMP.is_file(), reason=_SKIP)
def test_governed_cold_coupling_headline() -> None:
    """Governed reproduce-and-pin: naive overestimates firm hosting, underestimates curtailment.

    firm cold-coupled 4 -> naive 5 (+25 %); the naive model underestimates the
    curtailment the flexibility contract must deliver ~3.4x, because it misses
    the ~54 % more EV energy the cold-coupled model puts on cold days.
    (Re-based 2026-07-14 onto the realistic DHW-tank base: firm 2 -> 4.)
    """
    payload = json.loads(_CMP.read_text())
    cold = payload["models"]["cold_coupled"]
    naive = payload["models"]["naive"]
    # The naive model overestimates the firm limit.
    assert naive["firm_ev_count"] > cold["firm_ev_count"]
    assert cold["firm_ev_count"] == 4
    assert naive["firm_ev_count"] == 5
    assert payload["firm_overestimate_percent"] == pytest.approx(25.0)
    # More EV energy on cold days drives it; the P95 curves diverge above n=0.
    assert payload["cold_day_ev_energy_uplift_percent"] > 40.0
    assert cold["cold_day_ev_kwh_per_ev"] > naive["cold_day_ev_kwh_per_ev"]
    cc, nv = cold["p95_cold_evening_curve"], naive["p95_cold_evening_curve"]
    assert cc[0] == pytest.approx(nv[0])  # same base at 0 EV
    assert cc[cold["firm_ev_count"] + 1] > nv[cold["firm_ev_count"] + 1]
    # The naive model underestimates the flexibility work (curtailment energy).
    assert payload["curtailment_underestimate_ratio"] > 1.5
    assert cold["curtailed_energy_percent"] > naive["curtailed_energy_percent"]
