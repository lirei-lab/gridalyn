"""Gate: a regression baseline's tolerances must be able to fail.

Why this exists
---------------
``projects/ieee_33_bus_demo`` pinned ``summary.max_line_loading_percent`` at
0.00025788 with a tolerance of 0.01 -- a **relative tolerance of 3877%**. The
value could move by a factor of 38 and the metric still passed, on every push,
in a CI fixture.

The cause was not a typo. ``pandapower.networks.case33bw()`` declares
``max_i_ka = 99999`` because the canonical IEEE-33 dataset (Baran & Wu, 1989)
specifies no ampacities, so ``loading_percent`` on that feeder is current
divided by an effectively infinite rating and is near zero by construction.
The metric was meaningless for that study, and a tolerance wide enough to
never fail is what let it look like a check for as long as it did. It was
replaced by ``max_voltage_violation_count`` and ``best_voltage_scenario``,
which the scenario-comparison stage actually defines.

What this gate asserts
----------------------
For every metric in every study's ``baselines/results_baseline.json`` whose
expectation is a non-zero number, ``tolerance / |expected|`` must not exceed
:data:`_MAX_RELATIVE_TOLERANCE`. Measured against the real corpus rather than
chosen to fit it: the widest surviving metric sits at 0.4%, and the 122
metrics have a median relative tolerance of 0.000%, so a 10% ceiling leaves
two orders of magnitude of headroom for a study that genuinely needs a loose
pin, while still catching anything in the class this was written for.

Zero and boolean expectations are exempt and separately checked: a relative
tolerance is undefined against zero, so those are held to an ABSOLUTE ceiling
instead, which is the stricter statement of the same idea.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PROJECTS = _REPO_ROOT / "projects"

#: A metric may absorb at most 10% of its own expected value before it stops
#: being a check. See the module docstring for how this was calibrated.
_MAX_RELATIVE_TOLERANCE = 0.10

#: For an expectation of exactly zero, relative tolerance is undefined. These
#: are pinned absolutely instead; 1e-3 is two orders of magnitude above the
#: 1e-6 the corpus actually uses.
_MAX_ABSOLUTE_TOLERANCE_AT_ZERO = 1e-3


def _baselines() -> list[tuple[str, Path]]:
    """Return ``(study name, baseline path)`` for every study that pins one."""
    return [
        (path.parent.parent.name, path)
        for path in sorted(_PROJECTS.glob("*/baselines/results_baseline.json"))
    ]


def _metrics(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    metrics = payload.get("metrics", [])
    return [metric for metric in metrics if isinstance(metric, dict)]


class BaselineToleranceTests(unittest.TestCase):
    def test_at_least_the_known_studies_are_covered(self) -> None:
        """A gate that finds no files passes vacuously; this stops that."""
        found = _baselines()
        self.assertGreaterEqual(
            len(found),
            6,
            f"expected the governed studies to pin baselines, found {len(found)}",
        )

    def test_no_metric_can_absorb_a_large_fraction_of_its_own_value(self) -> None:
        offenders: list[str] = []
        for study, path in _baselines():
            for metric in _metrics(path):
                expected = metric.get("expected")
                tolerance = metric.get("tolerance")
                if isinstance(expected, bool) or not isinstance(expected, (int, float)):
                    continue
                if not isinstance(tolerance, (int, float)) or expected == 0:
                    continue
                relative = abs(tolerance / expected)
                if relative > _MAX_RELATIVE_TOLERANCE:
                    offenders.append(
                        f"{study}:{metric.get('id')} expected={expected} "
                        f"tolerance={tolerance} ({relative * 100:.1f}% of the "
                        "expected value)"
                    )
        self.assertEqual(
            [],
            offenders,
            "these metrics tolerate more than "
            f"{_MAX_RELATIVE_TOLERANCE * 100:.0f}% of their own value, so they "
            "cannot fail on a real regression. Tighten the tolerance, or remove "
            "the metric if the quantity is not meaningful for that study "
            "(the way max_line_loading_percent was not, against case33bw's "
            f"unspecified thermal rating):\n  " + "\n  ".join(offenders),
        )

    def test_a_zero_expectation_is_pinned_absolutely_and_tightly(self) -> None:
        offenders: list[str] = []
        for study, path in _baselines():
            for metric in _metrics(path):
                expected = metric.get("expected")
                tolerance = metric.get("tolerance")
                if isinstance(expected, bool) or expected != 0:
                    continue
                if not isinstance(tolerance, (int, float)):
                    continue
                if abs(tolerance) > _MAX_ABSOLUTE_TOLERANCE_AT_ZERO:
                    offenders.append(
                        f"{study}:{metric.get('id')} tolerance={tolerance}"
                    )
        self.assertEqual(
            [],
            offenders,
            "a metric expected to be zero must be pinned within "
            f"{_MAX_ABSOLUTE_TOLERANCE_AT_ZERO}, since relative tolerance says "
            f"nothing there:\n  " + "\n  ".join(offenders),
        )

    def test_every_metric_declares_a_tolerance(self) -> None:
        """An absent tolerance is not a strict check; it is an unstated one."""
        offenders = [
            f"{study}:{metric.get('id')}"
            for study, path in _baselines()
            for metric in _metrics(path)
            if metric.get("tolerance") is None
        ]
        self.assertEqual([], offenders, f"metrics with no tolerance: {offenders}")


if __name__ == "__main__":
    unittest.main()
