"""The documented verb table must keep describing the API it governs.

``docs/contributing/conventions.md`` instructs contributors to pick a
documented prefix rather than invent one. That instruction is only followable
while the table covers the verbs the SDK actually uses, so these tests measure
the gap rather than trusting it.
"""

from __future__ import annotations

import unittest

from tools.verb_prefixes import (
    ENTRY_POINT_NAMES,
    ESTABLISHED,
    public_functions,
    read_documented_prefixes,
    report,
)


class TestVerbPrefixTable(unittest.TestCase):
    def test_no_undocumented_prefix_has_become_established(self) -> None:
        """A verb used by >= ESTABLISHED public functions must be in the table."""
        documented, acknowledged, unwanted = read_documented_prefixes()
        known = documented | acknowledged | unwanted
        counts: dict[str, list[str]] = {}
        for name, _ in public_functions():
            if name in ENTRY_POINT_NAMES:
                continue
            counts.setdefault(name.split("_")[0], []).append(name)

        drift = {
            verb: names
            for verb, names in counts.items()
            if verb not in known and len(names) >= ESTABLISHED
        }
        self.assertEqual(
            drift,
            {},
            "these verbs are used by the SDK but absent from "
            "docs/contributing/conventions.md; either rename to a documented "
            "prefix or document the verb with the behaviour it signals",
        )

    def test_report_runs_and_passes_its_own_check(self) -> None:
        """The reporting tool is exercised, not just importable."""
        self.assertEqual(report(check=True), 0)

    def test_documented_verbs_are_actually_used(self) -> None:
        """The table describes the API; it does not aspire ahead of it.

        A prefix documented as an SDK verb but used by nothing is the same
        drift in the other direction -- the guide would be teaching a
        convention the code does not follow.
        """
        documented, _, _ = read_documented_prefixes()
        used = {name.split("_")[0] for name, _ in public_functions()}
        self.assertEqual(
            sorted(documented - used),
            [],
            "documented verbs that no public function uses",
        )

    def test_entry_points_are_excluded_by_name(self) -> None:
        """``main`` is an entry point, not a helper, and is named as such."""
        self.assertIn("main", ENTRY_POINT_NAMES)
        names = [name for name, _ in public_functions()]
        self.assertGreater(names.count("main"), 1, "expected per-module CLI mains")


if __name__ == "__main__":
    unittest.main()
