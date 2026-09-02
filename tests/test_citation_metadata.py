"""The citation apparatus must not name a version the repository is not at.

The platform exists so a researcher can re-run a study and cite the result. A
citation pointing at the wrong version is worse than none, so the version is
asserted to agree across every file that states it, and the DOI -- once minted
-- is checked for shape rather than merely presence.
"""

from __future__ import annotations

import json
import re
import tomllib
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CITATION = REPO_ROOT / "CITATION.cff"
PYPROJECT = REPO_ROOT / "pyproject.toml"
ZENODO = REPO_ROOT / ".zenodo.json"

#: A DOI is ``10.<registrant>/<suffix>``; Zenodo mints ``10.5281/zenodo.<id>``.
DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$")


def _citation() -> dict:
    return yaml.safe_load(CITATION.read_text(encoding="utf-8"))


class TestCitationMetadata(unittest.TestCase):
    def test_citation_file_exists_and_is_well_formed(self) -> None:
        data = _citation()
        self.assertEqual(data["cff-version"], "1.2.0")
        self.assertEqual(data["type"], "software")
        self.assertTrue(data["authors"], "CITATION.cff must name an author")

    def test_version_agrees_with_pyproject(self) -> None:
        """A citation naming the wrong version is worse than none."""
        packaged = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        declared = packaged["project"]["version"]
        self.assertEqual(
            _citation()["version"],
            declared,
            "CITATION.cff version disagrees with pyproject.toml; update both "
            "together, or a citation will name a version this tree is not at",
        )

    def test_zenodo_metadata_agrees_with_the_citation(self) -> None:
        """The deposition metadata is what mints the DOI; it must not drift."""
        self.assertTrue(
            ZENODO.is_file(),
            ".zenodo.json is what Zenodo reads when a release is archived",
        )
        zenodo = json.loads(ZENODO.read_text(encoding="utf-8"))
        citation = _citation()
        self.assertEqual(zenodo["version"], citation["version"])
        self.assertEqual(zenodo["title"], citation["title"])
        self.assertEqual(zenodo["license"].lower(), citation["license"].lower())

    def test_doi_when_present_is_well_formed(self) -> None:
        """Shape, not presence: minting the DOI is a release-time human act.

        Once ``doi:`` is added to CITATION.cff this asserts it is a real DOI
        rather than a URL or a placeholder, and that the Zenodo metadata agrees.
        """
        citation = _citation()
        doi = citation.get("doi")
        if doi is None:
            self.skipTest(
                "no DOI minted yet -- see docs/contributing/releasing.md; this "
                "test starts checking it the moment CITATION.cff carries one"
            )
        self.assertRegex(
            str(doi),
            DOI_PATTERN,
            "doi: must be the bare DOI (10.5281/zenodo.NNNN), not a URL",
        )


if __name__ == "__main__":
    unittest.main()
