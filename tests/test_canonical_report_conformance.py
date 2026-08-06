"""Conformance gate for the tracked canonical digital-twin reports (R9, #14).

Every canonical report committed under
``instances/default/digital_twin/reports/canonical/`` must satisfy the platform
report contract: :func:`validate_report` returns zero errors. The three tracked
reports predated the compliant builder — they carried ``metrics`` instead of
``summary``, no ``validation`` block, and a dict-shaped ``artifacts`` — and
nothing failed when they were committed. This gate makes that class of rot
impossible to commit silently again.

Scope note: the sibling ``reports/mv_lv_transformer_overload_report.json`` is
deliberately NOT covered. Despite its ``*_report.json`` name it is a domain
document, not a platform report — the report-contract audit
(``docs/development/report-contract-audit.md``) classifies it NOT-A-REPORT
because ``gridalyn/interfaces/reporting/digital_twin.py`` re-wraps it
downstream into the governed ``network_capacity`` canonical report. Wrapping
it in a report envelope would break its own consumers.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from gridalyn.foundation.platform.reports import validate_report

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CANONICAL_DIR = (
    _REPO_ROOT / "instances" / "default" / "digital_twin" / "reports" / "canonical"
)
_REGENERATE_HINT = (
    "regenerate with `python -m gridalyn.interfaces.reporting.digital_twin` "
    "from the workspace root"
)

# The canonical reports the digital-twin build is contracted to produce. Pinned
# so an emptied or renamed directory fails loudly instead of passing vacuously.
_EXPECTED_REPORTS = (
    "network_capacity_report.json",
    "scenario_registry_report.json",
    "semantic_graph_report.json",
)

# JSON siblings under canonical/ that are deliberately NOT platform reports.
# The report *index* is a manifest routed through ``write_manifest``; the
# report-contract audit classifies it NOT-A-REPORT, and wrapping a manifest in
# a report envelope would break its own consumers. Every other ``*.json`` in
# the directory must pass ``validate_report`` -- a report cannot escape the
# gate by choosing a non-``_report`` filename (S10).
_NON_REPORT_SIBLINGS = frozenset({"digital_twin_report_manifest.json"})


class CanonicalReportConformanceTest(unittest.TestCase):
    """Every tracked canonical report passes the platform report contract."""

    def test_expected_canonical_reports_are_present(self) -> None:
        """The gate must not pass vacuously on a missing or emptied directory."""
        missing = [
            name for name in _EXPECTED_REPORTS if not (_CANONICAL_DIR / name).is_file()
        ]
        self.assertEqual(
            missing,
            [],
            f"{_CANONICAL_DIR}: missing canonical report(s) {missing}; "
            f"{_REGENERATE_HINT}.",
        )

    def test_every_canonical_report_passes_validate_report(self) -> None:
        """Every ``*.json`` under canonical/ yields zero contract errors.

        The glob is deliberately ``*.json``, not ``*_report.json`` (S10): the
        directory's contract is that everything in it is a platform report, so
        a report committed under a non-``_report`` name must not escape the
        gate by its filename. The named manifest sibling is the one documented
        exception. Note the gate pins the committed artifacts, not the
        generator -- regenerating requires a built digital-twin workspace,
        which a unit gate cannot assume; the regenerate hint names the command.
        """
        failures: dict[str, list[str]] = {}
        for path in sorted(_CANONICAL_DIR.glob("*.json")):
            if path.name in _NON_REPORT_SIBLINGS:
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            errors = validate_report(payload)
            if errors:
                failures[path.relative_to(_REPO_ROOT).as_posix()] = errors
        self.assertEqual(
            failures,
            {},
            "Canonical report(s) violate the platform report contract:\n"
            + "\n".join(
                f"  {name}: {'; '.join(errors)}"
                for name, errors in sorted(failures.items())
            )
            + f"\n{_REGENERATE_HINT}.",
        )

    def test_non_report_sibling_exclusions_are_not_stale(self) -> None:
        """Every excluded sibling must still exist, or the exclusion must go.

        A stale exclusion is a standing permission: if the manifest is renamed
        or retired, a future report could adopt the excluded name and skip the
        contract check silently.
        """
        stale = sorted(
            name
            for name in _NON_REPORT_SIBLINGS
            if not (_CANONICAL_DIR / name).is_file()
        )
        self.assertEqual(
            stale,
            [],
            f"_NON_REPORT_SIBLINGS entries no longer present in {_CANONICAL_DIR}: "
            f"{stale}; delete the entry rather than leave a standing permission.",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
