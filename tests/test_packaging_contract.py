"""Assert the built distribution actually ships the data files the code opens.

Wheel contents must be **observed**, not inferred. This project's own review loop
once concluded from `find_packages()` returning 36 packages (vs 39 for
`find_namespace_packages()`) that `gridalyn/assets/datagen/{data,grid}` were
omitted from the wheel for lack of `__init__.py`. Building the wheel disproved
it: `weather.py` and `network.py` ship and import fine as namespace packages.
The real defect was elsewhere — `[tool.setuptools.package-data]` declared only
the `.pkl` model weights, so `gridalyn/projects/schemas/*.json` never shipped and
`validate_project` raised `FileNotFoundError` on a pip-installed gridalyn.

So these tests build a real wheel and read its namelist. They are deliberately
NOT skippable: a packaging gate that skips silently is the exact failure mode it
exists to prevent. The build costs a few seconds; a broken install costs a user
the SDK's core value.

Prerequisites (hard requirements, not best-effort)
--------------------------------------------------
Because nothing here skips, both prerequisites below fail the suite loudly, by
design. Each failure names the missing prerequisite rather than surfacing a raw
subprocess error.

1. **A git checkout.** The required set of data files is derived from the git
   index (`git ls-files`), not a hand-maintained list. Running from an unpacked
   sdist — which has no `.git` — cannot satisfy these tests.

2. **A reachable package index.** `pip wheel` runs with build isolation
   *enabled*, so it downloads the `[build-system] requires` backend into a
   throwaway environment. Under `PIP_NO_INDEX=1`, or on an offline runner, the
   build fails and so do these tests.

   `--no-build-isolation` was measured and rejected. `pyproject.toml` declares
   `requires = ["setuptools>=61.0"]` but expresses its license in the PEP 639
   SPDX form (`license = "MIT"`), which setuptools only accepts from 77.0
   onward. Isolation resolves that to setuptools 83.0.0 and the build succeeds;
   without isolation the build reuses the environment's pinned setuptools
   75.8.0 and aborts during metadata generation with "`project.license` must be
   valid exactly by one definition (2 matches found)". Isolation is what makes
   this build *correct* here, not merely convenient, so it stays.

   Measured on this repo (warm pip cache): isolated build ~3.3 s; the
   non-isolated attempt fails in ~0.7 s.

Why the wheel is built from a pristine copy
-------------------------------------------
`pip wheel <repo>` builds a local directory **in place**, and setuptools'
`build_py` copies data files into `build/lib/` without ever pruning it. A file
that shipped once therefore keeps being copied into every later wheel even after
`[tool.setuptools.package-data]` stops declaring it — so a gate that builds
straight from the checkout reads stale output and passes on a package that would
ship broken from a clean CI runner.

That is not hypothetical: it was measured here by mutation. With this repo's
existing `build/` present, deleting the `projects/schemas/*.json` glob still
produced a wheel containing both schemas and all five tests stayed green; after
wiping `build/` the same mutation produced a wheel with only the `.pkl` weights,
which is the red this gate exists to give. So the build runs against a fresh copy
of the git-tracked working tree (619 files, ~19 MB, well under a second), which
also stops these tests from writing `build/` and `gridalyn.egg-info/` into the
developer's checkout on every run.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE_DIR = _REPO_ROOT / "gridalyn"

# Files `gridalyn` resolves relative to its own package directory at runtime.
# `gridalyn/projects/validation.py` reads both of these via
# `SCHEMA_DIR = Path(__file__).parent / "schemas"`.
_RUNTIME_RESOLVED_SCHEMAS = (
    "gridalyn/projects/schemas/study_project.schema.json",
    "gridalyn/projects/schemas/workflow.schema.json",
)


# Data files deliberately kept out of the distribution. Empty today, and
# `test_the_deliberately_unpackaged_escape_hatch_stays_empty` keeps it that way:
# anything listed here is a file the source tree carries but an installed
# gridalyn cannot open, silently removed from the required set with nothing
# asserting it is genuinely unread. Adding an entry must be a deliberate act, so
# it costs a failing test until the entry is justified in that test's exemption
# list too.
_DELIBERATELY_UNPACKAGED: frozenset[str] = frozenset()


def _git(*args: str) -> str:
    """Run a read-only git command in the repo root and return its stdout.

    Args:
        *args: Arguments appended to `git`, e.g. `("ls-files", "gridalyn")`.

    Returns:
        The command's standard output.

    Raises:
        RuntimeError: If git is unavailable or the command fails — most often
            because the suite is running outside a git checkout, which these
            tests cannot support. The message names the prerequisite.
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=_REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment defect
        raise RuntimeError(
            "missing prerequisite: git is not on PATH. The packaging contract "
            "derives its required data-file set from the git index, so these "
            "tests must run from a git checkout with git installed."
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"missing prerequisite: `git {' '.join(args)}` failed in "
            f"{_REPO_ROOT} (exit {result.returncode}). The packaging contract "
            "derives its required data-file set from the git index, so these "
            "tests must run from a git checkout — an unpacked sdist has no git "
            "index to derive it from.\n"
            f"git stderr:\n{result.stderr}"
        )
    return result.stdout


def _data_paths(git_output: str) -> list[str]:
    """Return the non-`.py` paths listed in a `git ls-files` output block."""
    return sorted(
        path for path in git_output.splitlines() if path and not path.endswith(".py")
    )


def _tracked_data_files() -> list[str]:
    """Return every git-tracked non-`.py` file under `gridalyn/`.

    Derived from the git index rather than a hand-maintained list, so a newly
    added data file joins the required set automatically and this test fails
    until `[tool.setuptools.package-data]` declares it.

    Returns:
        Sorted repo-relative paths, minus `_DELIBERATELY_UNPACKAGED`.
    """
    return [
        path
        for path in _data_paths(_git("ls-files", "gridalyn"))
        if path not in _DELIBERATELY_UNPACKAGED
    ]


def _untracked_data_files() -> list[str]:
    """Return every untracked, non-ignored non-`.py` file under `gridalyn/`.

    Such a file is a blind spot: the code may open it, but it is absent from the
    git index and therefore from the required set, so the wheel could omit it
    and still pass. `.py` files are excluded because they cannot widen the
    *data*-file set this contract derives.

    Returns:
        Sorted repo-relative paths.
    """
    return _data_paths(_git("ls-files", "--others", "--exclude-standard", "gridalyn"))


def _package_data_globs() -> list[str]:
    """Return the `[tool.setuptools.package-data]` globs declared for `gridalyn`.

    Returns:
        The declared glob patterns, relative to the `gridalyn/` package dir.
    """
    with (_REPO_ROOT / "pyproject.toml").open("rb") as handle:
        config = tomllib.load(handle)
    package_data = config["tool"]["setuptools"]["package-data"]
    return list(package_data.get("gridalyn", []))


def _tracked_files_matching(pattern: str) -> set[str]:
    """Return the repo-relative paths a package-data glob resolves to on disk.

    Uses `Path.glob` rather than `fnmatch` so `*` does not cross directory
    separators, matching setuptools' own interpretation of these patterns.

    Args:
        pattern: A glob relative to the `gridalyn/` package directory.

    Returns:
        Repo-relative POSIX paths of the matching files.
    """
    return {
        f"gridalyn/{match.relative_to(_PACKAGE_DIR).as_posix()}"
        for match in _PACKAGE_DIR.glob(pattern)
        if match.is_file()
    }


# Build output is never a build *input*, and `build/lib/` is precisely the
# stale-copy source this export exists to escape. Both are untracked here, but
# excluding them structurally means the guarantee does not rest on a checkout's
# .gitignore hygiene.
_BUILD_OUTPUT_PREFIXES = ("build/", "dist/")


def _is_build_output(relative: str) -> bool:
    """Return whether a repo-relative path is build output rather than source."""
    return relative.startswith(_BUILD_OUTPUT_PREFIXES) or ".egg-info/" in relative


def _export_tracked_tree(destination: Path) -> None:
    """Copy the git-tracked working tree into a pristine directory.

    Working-tree contents are copied, not `HEAD`, so an uncommitted
    `pyproject.toml` change is what gets built and this gate reacts to the edit
    under review. See this module's docstring for why building in the checkout
    itself yields a false green.

    Args:
        destination: Existing empty directory to populate.

    Raises:
        RuntimeError: If no tracked file was copied, which would leave an empty
            tree that cannot be built.
    """
    copied = 0
    for relative in _git("ls-files", "-z").split("\0"):
        if not relative or _is_build_output(relative):
            continue
        source = _REPO_ROOT / relative
        # Skip gitlink (submodule) entries and anything deleted from the working
        # tree; neither can be copied as a file.
        if not source.is_file():
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    if copied == 0:
        raise RuntimeError(
            f"copied no git-tracked file from {_REPO_ROOT}; the packaging "
            "contract would otherwise build an empty source tree and certify a "
            "wheel that means nothing."
        )


def _build_wheel(source_tree: Path, destination: str) -> Path:
    """Build a wheel from a pristine source tree and return its path.

    Build isolation stays enabled on purpose; see this module's docstring for
    the measurement behind that choice and the package-index requirement it
    implies.

    Args:
        source_tree: Directory holding the exported working tree to build.
        destination: Directory the wheel is written to.

    Returns:
        Path to the single built gridalyn wheel.

    Raises:
        RuntimeError: If the build fails or does not yield exactly one wheel.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "-w",
            destination,
            str(source_tree),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "pip wheel failed; the packaging contract cannot be verified from "
            "the source tree alone. This build needs a reachable package index "
            "— it runs with build isolation enabled, which downloads the "
            "[build-system] requires backend, so PIP_NO_INDEX=1 or an offline "
            "runner fails here by design (see this module's docstring).\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    wheels = sorted(Path(destination).glob("gridalyn-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected exactly one gridalyn wheel, found: {wheels}")
    return wheels[0]


class PackagingContractTest(unittest.TestCase):
    """The built wheel must contain every data file the package reads at runtime."""

    _tmp: tempfile.TemporaryDirectory
    _wheel_names: list[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        source_tree = Path(cls._tmp.name) / "source"
        wheel_dir = Path(cls._tmp.name) / "wheel"
        source_tree.mkdir()
        wheel_dir.mkdir()
        _export_tracked_tree(source_tree)
        wheel_path = _build_wheel(source_tree, str(wheel_dir))
        with zipfile.ZipFile(wheel_path) as archive:
            cls._wheel_names = archive.namelist()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_wheel_ships_the_json_schemas_validation_resolves_at_runtime(self) -> None:
        # Assert on file paths, never on a `gridalyn/projects/schemas/` directory
        # entry: zip archives may or may not record directory entries.
        shipped = set(self._wheel_names)
        missing = [name for name in _RUNTIME_RESOLVED_SCHEMAS if name not in shipped]

        self.assertEqual(
            [],
            missing,
            "the built wheel is missing data files that "
            "gridalyn/projects/validation.py opens at runtime: "
            f"{missing}. `validate_project` — a top-level public export and the "
            "`gridalyn validate` CLI — raises FileNotFoundError on a "
            "pip-installed gridalyn until [tool.setuptools.package-data] "
            "declares them.",
        )

    def test_wheel_ships_every_tracked_data_file_under_the_package(self) -> None:
        expected = _tracked_data_files()

        # Guard against a vacuous pass: if `git ls-files` returned nothing the
        # loop below would assert on an empty set and this test would certify a
        # wheel it never inspected.
        self.assertNotEqual(
            [],
            expected,
            "derived no tracked data files under gridalyn/ — the git index "
            "lookup failed, so this test would otherwise pass vacuously.",
        )
        self.assertIn(
            "gridalyn/projects/schemas/study_project.schema.json",
            expected,
            "the derivation stopped seeing a file known to be tracked; "
            "_tracked_data_files() is no longer sound.",
        )

        shipped = set(self._wheel_names)
        missing = [name for name in expected if name not in shipped]

        self.assertEqual(
            [],
            missing,
            "these data files are tracked under gridalyn/ but absent from the "
            f"built wheel: {missing}. Any file the package opens relative to "
            "its own __file__ must be declared in "
            "[tool.setuptools.package-data]; otherwise it works from a repo "
            "checkout and raises FileNotFoundError once pip-installed. Declare "
            "it there, or add it to _DELIBERATELY_UNPACKAGED with a reason.",
        )

    def test_no_untracked_data_file_hides_from_the_derived_required_set(self) -> None:
        # Blind spot in the direction the test above cannot see: it certifies
        # the wheel against the git index, so a data file that exists on disk
        # but was never `git add`ed is required by nothing and may be silently
        # absent from the wheel.
        untracked = _untracked_data_files()

        self.assertEqual(
            [],
            untracked,
            "these non-.py files exist under gridalyn/ but are neither tracked "
            f"nor ignored: {untracked}. The required data-file set is derived "
            "from the git index, so an untracked file is invisible to it — the "
            "wheel could omit it and this suite would still pass. Commit it "
            "(so it joins the required set and must be declared in "
            "[tool.setuptools.package-data]), gitignore it if it is build "
            "output, or delete it.",
        )

    def test_every_package_data_glob_matches_a_tracked_file(self) -> None:
        # Blind spot in the third direction: a glob for a file that was never
        # committed is checked by nothing. It looks like coverage in
        # pyproject.toml while guaranteeing the shipment of no file at all.
        globs = _package_data_globs()

        self.assertNotEqual(
            [],
            globs,
            "read no package-data globs for `gridalyn` from pyproject.toml — "
            "either the declaration was removed (in which case no data file "
            "ships at all) or this parse is no longer sound.",
        )

        tracked = set(_tracked_data_files())
        unmatched = [
            pattern
            for pattern in globs
            if not (_tracked_files_matching(pattern) & tracked)
        ]

        self.assertEqual(
            [],
            unmatched,
            "these [tool.setuptools.package-data] globs match no git-tracked "
            f"file under gridalyn/: {unmatched}. A glob with no tracked match "
            "ships nothing and asserts nothing — it is dead packaging config. "
            "Point it at a committed file or remove it.",
        )

    def test_the_deliberately_unpackaged_escape_hatch_stays_empty(self) -> None:
        # _DELIBERATELY_UNPACKAGED subtracts files from the required set with no
        # assertion that they are genuinely unread at runtime, so an entry can
        # hide a real packaging defect. Keep it empty; adding an entry must
        # require editing this test and stating the justification here.
        self.assertEqual(
            frozenset(),
            _DELIBERATELY_UNPACKAGED,
            "_DELIBERATELY_UNPACKAGED is no longer empty: "
            f"{sorted(_DELIBERATELY_UNPACKAGED)}. Every entry silently removes "
            "a file from the wheel's required set, and nothing verifies the "
            "package never opens it. If an exemption is genuinely warranted, "
            "record here why each file is unread at runtime and update this "
            "assertion deliberately.",
        )
