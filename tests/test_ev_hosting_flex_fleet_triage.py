"""Governance tests for the fleet triage -- the study's declared primary result.

``project.yaml`` says of ``fleet_triage``: "This is the study's primary result;
the per-feeder stages below are the worked example behind it." Until 2026-09-04
it was the only substantive artifact with no baseline pin: 75 of the 81 pins
governed the worked example, none governed the result. These tests, and the
``fleet.*`` pins in ``baselines/results_baseline.json``, close that gap.

Tiers: (1) the pin-to-cell mapping, provable from config alone; (3) governed
reproduce-and-pin against the emitted artifact (skipif absent).

The pins address ``triage[i]`` by integer index because the artifact's list is
built by three nested loops (convention, dispersion, adoption) and the JSON on
disk carries no keyed headline block. Tier 1 makes that index a checked fact
rather than a magic number: if any grid is reordered or resized, the index moves
and the test says so before a pin silently reads the wrong cell.
"""

from __future__ import annotations

import json

import pytest

from projects.ev_hosting_flex.scripts.config import (
    PROJECT_OUTPUTS_DIR,
    TRIAGE_ADOPTION_GRID,
    TRIAGE_BASE_DISPERSION,
    TRIAGE_DISPERSION_GRID,
    TRIAGE_HEADLINE_RATING_CONVENTION,
    TRIAGE_RATING_CONVENTIONS,
)

#: The ``triage[i]`` index each convention's headline cell (adoption = 1 EV/home,
#: dispersion = the base case) sits at. These are what ``fleet.*`` pins in the
#: baseline address; tier 1 derives them from config and asserts equality.
PINNED_HEADLINE_INDEX = {"static": 16, "hourly_kt": 40}

_HEADLINE_ADOPTION = 1.0


def _headline_index(convention: str) -> int:
    """Return where ``analyze_fleet_triage`` places a convention's headline cell.

    Mirrors the stage's construction order exactly -- convention-major, then
    dispersion, then adoption -- so this is the same arithmetic the stage does,
    not an independent guess.

    Args:
        convention: One of ``TRIAGE_RATING_CONVENTIONS``.

    Returns:
        The zero-based index into the emitted ``triage`` list.
    """
    c = list(TRIAGE_RATING_CONVENTIONS).index(convention)
    d = [float(x) for x in TRIAGE_DISPERSION_GRID].index(float(TRIAGE_BASE_DISPERSION))
    a = [float(x) for x in TRIAGE_ADOPTION_GRID].index(_HEADLINE_ADOPTION)
    return (c * len(TRIAGE_DISPERSION_GRID) + d) * len(TRIAGE_ADOPTION_GRID) + a


# ─── 1. The index the pins rely on, from config alone ───────────────────────


def test_pinned_indices_match_the_grids_in_config() -> None:
    """The baseline's ``triage[16]`` / ``triage[40]`` are the headline cells.

    Fails, naming the convention, if any triage grid is reordered or resized
    without the ``fleet.*`` pins being re-pointed.
    """
    for convention, pinned in PINNED_HEADLINE_INDEX.items():
        derived = _headline_index(convention)
        assert derived == pinned, (
            f"{convention}: config places the headline cell at triage[{derived}] "
            f"but the baseline pins triage[{pinned}]; a triage grid changed -- "
            f"re-point the fleet.* pins in results_baseline.json."
        )


def test_both_conventions_are_pinned_not_just_the_headline() -> None:
    """Every evaluated convention has a pinned cell.

    Pinning only the declared headline would re-hide the 6.7x gap between
    conventions one commit after it was made visible (syntgrid-eei.1).
    """
    assert set(PINNED_HEADLINE_INDEX) == set(TRIAGE_RATING_CONVENTIONS)
    assert TRIAGE_HEADLINE_RATING_CONVENTION in PINNED_HEADLINE_INDEX


# ─── 3. Governed reproduce-and-pin (skipif artifacts absent) ────────────────

_TRIAGE = PROJECT_OUTPUTS_DIR / "json" / "fleet_triage.json"
_REPORT = PROJECT_OUTPUTS_DIR / "reports" / "fleet_triage_report.json"
_SKIP = (
    "fleet_triage.json not present; run analyze_fleet_triage.py first "
    "(outputs are gitignored)"
)


@pytest.mark.skipif(not _TRIAGE.is_file(), reason=_SKIP)
def test_governed_pinned_cells_are_the_headline_cells() -> None:
    """The cells the pins address carry the (convention, dispersion, adoption)
    they claim to -- the artifact-side half of tier 1."""
    p = json.loads(_TRIAGE.read_text())
    triage = p["triage"]
    n_expected = (
        len(TRIAGE_RATING_CONVENTIONS)
        * len(TRIAGE_DISPERSION_GRID)
        * len(TRIAGE_ADOPTION_GRID)
    )
    assert len(triage) == n_expected
    for convention, i in PINNED_HEADLINE_INDEX.items():
        cell = triage[i]
        assert cell["rating_convention"] == convention
        assert cell["adoption_ev_per_home"] == pytest.approx(_HEADLINE_ADOPTION)
        assert cell["dispersion"] == pytest.approx(float(TRIAGE_BASE_DISPERSION))


@pytest.mark.skipif(not (_TRIAGE.is_file() and _REPORT.is_file()), reason=_SKIP)
def test_governed_report_summary_agrees_with_the_pinned_headline_cell() -> None:
    """The report's summary is the pinned cell under the declared convention.

    The summary is what a reader quotes; the pin is what the gate checks. They
    must be the same number, and the declared convention must be the one the
    summary was computed under.
    """
    p = json.loads(_TRIAGE.read_text())
    s = json.loads(_REPORT.read_text())["summary"]
    assert s["headline_rating_convention"] == p["headline_rating_convention"]
    cell = p["triage"][PINNED_HEADLINE_INDEX[s["headline_rating_convention"]]]
    assert s["n_at_risk_at_1ev"] == cell["n_at_risk"]
    assert s["flex_defers_at_1ev"] == cell["flex_defers"]
    assert s["needs_steel_at_1ev"] == cell["needs_steel"]
    assert s["base_constrained_at_1ev"] == cell["base_constrained"]
    assert s["deferred_fraction_at_1ev"] == pytest.approx(
        cell["deferred_fraction_of_at_risk"]
    )


@pytest.mark.skipif(not _TRIAGE.is_file(), reason=_SKIP)
def test_governed_categories_partition_the_fleet_up_to_rounding() -> None:
    """The four triage categories account for every transformer.

    ``triage_fleet`` averages each category over the allocation draws and
    rounds each INDEPENDENTLY, so the four rounded counts can sum to n+1 or n-1
    (measured: 541 of 540 under ``hourly_kt``). That is a presentation defect,
    tracked separately; this test pins the bound so it cannot widen, and should
    tighten to equality when the rounding is made to partition.
    """
    p = json.loads(_TRIAGE.read_text())
    n = int(p["n_transformers"])
    for i in PINNED_HEADLINE_INDEX.values():
        cell = p["triage"][i]
        total = (
            cell["never_binds"]
            + cell["flex_defers"]
            + cell["needs_steel"]
            + cell["base_constrained"]
        )
        assert abs(total - n) <= 1, f"triage[{i}]: categories sum to {total} of {n}"
        assert cell["n_at_risk"] == (
            cell["flex_defers"] + cell["needs_steel"] + cell["base_constrained"]
        )


@pytest.mark.skipif(not _REPORT.is_file(), reason=_SKIP)
def test_governed_no_uncertainty_block_and_the_reason_is_stated() -> None:
    """The primary result carries no ``uncertainty`` block, and says why.

    CLAUDE.md: an interval is carried where the study samples a distribution it
    can defend, and is ABSENT rather than faked where it does not. The fleet
    triage medians rest on k_base=3 base realizations shared across
    transformers of equal home count -- neither many nor independent -- so
    the honest outcome is a pin without an interval plus the stated reason.
    This test fails if a block appears without that decision being revisited,
    or if the reason disappears from the report.
    """
    r = json.loads(_REPORT.read_text())
    assert "uncertainty" not in r, (
        "an uncertainty block appeared on fleet_triage_report; if k_base was "
        "raised and the interval is now defensible, update this test and "
        "syntgrid-eei.2 together"
    )
    warnings = " ".join(r["validation"]["warnings"])
    assert "K_BASE" in warnings and "sampling error" in warnings
