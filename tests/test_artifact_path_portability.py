"""Gate: an artifact must not record where the machine that made it kept files.

Why this exists
---------------
Two flagship artifacts embedded absolute filesystem paths (bd r5j):
``outputs/json/locational_contracts.json`` stored ten of them under
``operational_artifacts``, and ``outputs/reports/twin_network_model_report.json``
stored one as ``summary.out_dir`` -- inside a governed report's ``summary``, the
surface baselines pin.

The cost is not tidiness. This repo's stated core value is that a researcher
re-runs a study and gets baseline-matching results; an artifact naming
``/home/<someone>/...`` cannot match anywhere but that machine. It was found as
a FALSE POSITIVE: verifying an unrelated refactor from a git worktree produced a
"differing artifact" that was only the worktree's own path, and reading it cost
real time.

The two halves of this gate, and why they are not the same test
--------------------------------------------------------------
1. ``ProjectScript.relative`` is unit-tested here, including the case where a
   path lies outside the project. That half runs everywhere, CI included.
2. The artifact scan can only run where the artifacts exist. Study ``outputs/``
   are gitignored, so in CI this half SKIPS -- like every other reproduce-and-pin
   test in this suite, and for the same reason. It is an operator gate, and
   ``conftest.py`` prints its skip reason so a green run cannot hide that the
   verification did not happen.

Stating that plainly matters more than pretending otherwise: a scan that skips
in CI is not enforcement, and writing it as though it were would be the vacuous
gate this repo has already shipped twice. The half that CI enforces is the
helper's behaviour; the half an operator enforces is that the artifacts on disk
actually used it.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PROJECTS = _REPO_ROOT / "projects"

#: A leading "/" or a Windows drive letter. Relative paths and URLs do not match.
_ABSOLUTE = re.compile(r"^(/|[A-Za-z]:[\\/])")

_SKIP_NO_OUTPUTS = (
    "no study has emitted outputs/{json,reports} yet; run "
    "'gridalyn project run projects/<study>' first (outputs are gitignored)"
)


def _absolute_strings(payload: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """Yield every ``(json path, value)`` in ``payload`` that is an absolute path.

    Args:
        payload: Parsed JSON of any shape.
        path: Dotted prefix accumulated during the walk.

    Yields:
        One pair per offending string, so the failure can name the exact key.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield from _absolute_strings(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            yield from _absolute_strings(value, f"{path}[{index}]")
    elif isinstance(payload, str) and _ABSOLUTE.match(payload):
        yield path, payload


def _emitted_artifacts() -> list[Path]:
    """Return every JSON artifact any study has actually written."""
    found: list[Path] = []
    for study in sorted(_PROJECTS.iterdir()):
        for sub in ("json", "reports"):
            directory = study / "outputs" / sub
            if directory.is_dir():
                found.extend(sorted(directory.glob("*.json")))
    return found


class RelativeRenderingTest(unittest.TestCase):
    """``ProjectScript.relative`` is the supported way to record a path."""

    def test_a_path_inside_the_project_is_rendered_relative(self) -> None:
        """This is the case every artifact should hit."""
        from gridalyn.projects.scripting import ProjectScript

        script = _stub_script(Path("/tmp/study"))
        self.assertEqual(
            "outputs/json/x.json",
            ProjectScript.relative(script, Path("/tmp/study/outputs/json/x.json")),
        )

    def test_a_path_outside_the_project_is_left_alone_not_dotted_out(self) -> None:
        """``../../elsewhere`` would hide the fact; the absolute path shows it."""
        from gridalyn.projects.scripting import ProjectScript

        script = _stub_script(Path("/tmp/study"))
        self.assertEqual(
            "/tmp/elsewhere/x.json",
            ProjectScript.relative(script, Path("/tmp/elsewhere/x.json")),
        )

    def test_it_is_the_inverse_of_path_for_a_project_relative_input(self) -> None:
        """``relative(path(x)) == x`` is the property callers rely on."""
        from gridalyn.projects.scripting import ProjectScript

        script = _stub_script(Path("/tmp/study"))
        absolute = Path("/tmp/study") / "outputs/data/y.parquet"
        self.assertEqual(
            "outputs/data/y.parquet", ProjectScript.relative(script, absolute)
        )


class EmittedArtifactPortabilityTest(unittest.TestCase):
    """No artifact on disk may name the machine that produced it."""

    def test_no_emitted_json_artifact_embeds_an_absolute_path(self) -> None:
        """Operator gate: skips in CI, where no study has run."""
        artifacts = _emitted_artifacts()
        if not artifacts:
            self.skipTest(_SKIP_NO_OUTPUTS)
        offenders: list[str] = []
        for artifact in artifacts:
            try:
                payload = json.loads(artifact.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            for key, value in _absolute_strings(payload):
                rel = artifact.relative_to(_REPO_ROOT)
                offenders.append(f"{rel}{key} = {value}")
        self.assertEqual(
            offenders,
            [],
            "these artifacts record where THIS machine kept its files, so they "
            "cannot reproduce byte-for-byte anywhere else:\n  "
            + "\n  ".join(offenders)
            + "\nRecord the path with script.relative(...) (bd r5j).",
        )

    def test_the_scan_would_catch_one(self) -> None:
        """Without this, a green result could mean the walker never looks."""
        payload = {"a": {"b": "/home/someone/x.json"}, "c": ["outputs/ok.json"]}
        self.assertEqual(
            [(".a.b", "/home/someone/x.json")], list(_absolute_strings(payload))
        )


def _stub_script(root: Path) -> Any:
    """Return the smallest object ``ProjectScript.relative`` needs.

    ``relative`` reads only ``self.project.root``, so the method is called
    unbound against this stand-in rather than loading a real project. That
    keeps the unit half of this gate free of fixtures, which is why it can run
    in CI while the artifact half cannot.

    Args:
        root: The project root to resolve against.

    Returns:
        An object exposing ``.project.root``.
    """
    return SimpleNamespace(project=SimpleNamespace(root=root))


if __name__ == "__main__":
    unittest.main()
