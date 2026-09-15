"""Run the feeder-criticality example study end to end (bd 4ky.8).

Proves the extension claim with a real run, not a dry one: a study declares an
extension gridalyn does not ship, its stage builds a semantic graph asking for
the capability that extension contributes, and the graph carries it.

The committed extension is not pip-installed, so this script exposes its entry
point the way an installed distribution does -- a ``*.dist-info`` directory with
an ``entry_points.txt`` -- from a temporary site directory placed on the import
path of this process AND of every stage subprocess the runner starts. No loader
is patched: discovery goes through ``importlib.metadata`` exactly as it would
against a real installation.

Run (from the repo root):
    .venv/bin/python examples/extensions/feeder_criticality/run_example.py
    .venv/bin/python examples/extensions/feeder_criticality/run_example.py \\
        --without-declaration

The first prints a deterministic JSON summary and exits 0. The second copies the
study without its ``spec.inputs.extensions`` declaration but leaves the extension
installed: the build must fail loudly, because an extension that is not declared
is never loaded. ``tests/test_extension_semantic_capability.py`` pins both.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

EXAMPLE_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXAMPLE_DIR.parents[2]
STUDY_DIR = EXAMPLE_DIR / "study"

_DIST_INFO = "feeder_criticality-0.1.0.dist-info"
_METADATA = "Metadata-Version: 2.1\nName: feeder_criticality\nVersion: 0.1.0\n"
_ENTRY_POINTS = "[gridalyn.extensions]\nfeeder_criticality = feeder_criticality\n"


def install_entry_point(site_dir: Path) -> None:
    """Expose the example's entry point from ``site_dir``, as an install would.

    Args:
        site_dir: A directory that will be put on the import path.
    """
    dist_info = site_dir / _DIST_INFO
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(_METADATA, encoding="utf-8")
    (dist_info / "entry_points.txt").write_text(_ENTRY_POINTS, encoding="utf-8")


def put_on_path(*directories: Path) -> None:
    """Make ``directories`` importable here and in every stage subprocess.

    The repository root goes first so the gridalyn being demonstrated is this
    checkout's, not whichever one an editable install points at.

    Args:
        directories: Directories to prepend, in order.
    """
    entries = [str(directory) for directory in directories]
    for entry in reversed(entries):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    existing = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = os.pathsep.join(
        entries + ([existing] if existing else [])
    )


def copy_study(target_root: Path, *, declare: bool) -> Path:
    """Copy the committed study, optionally without its extension declaration.

    Args:
        target_root: Directory to copy the study into.
        declare: Keep ``spec.inputs.extensions`` when true; remove it otherwise.

    Returns:
        The copied study directory.
    """
    target = target_root / "study"
    shutil.copytree(STUDY_DIR, target, ignore=shutil.ignore_patterns("outputs"))
    if not declare:
        project_file = target / "project.yaml"
        data = yaml.safe_load(project_file.read_text(encoding="utf-8"))
        data["spec"]["inputs"].pop("extensions")
        project_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    """Run the example study and print what its semantic graph carries.

    Args:
        argv: Argument list to parse; defaults to ``sys.argv[1:]``.

    Returns:
        ``0`` when the run completes, ``1`` when it fails; the failure is
        printed to stderr with its type.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--without-declaration",
        action="store_true",
        help="Run the study with its spec.inputs.extensions declaration removed.",
    )
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="feeder_criticality_") as tmp:
        root = Path(tmp)
        install_entry_point(root / "site")
        put_on_path(REPO_ROOT, EXAMPLE_DIR, root / "site")
        study = copy_study(root, declare=not args.without_declaration)

        from gridalyn.projects import run_workflow

        # Stage subprocesses write to the stdout they inherit (prepare-workspace
        # prints JSON). Point stdout at stderr for the run, so this script's
        # stdout carries nothing but its own summary.
        sys.stdout.flush()
        saved_stdout = os.dup(sys.stdout.fileno())
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        try:
            run_workflow(study)
        except Exception as exc:  # noqa: BLE001 - reported, then a non-zero exit
            print(f"run failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        finally:
            sys.stdout.flush()
            os.dup2(saved_stdout, sys.stdout.fileno())
            os.close(saved_stdout)
        report = json.loads(
            (study / "outputs/reports/semantic_graph_report.json").read_text(
                encoding="utf-8"
            )
        )
        manifest = json.loads(
            (study / "outputs/manifests/project_run_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        summary = {
            "status": manifest["status"],
            "extensions": [
                {
                    key: entry[key]
                    for key in ("extension_id", "role", "source", "version")
                }
                for entry in manifest["provenance"]["extensions"]
            ],
            "graph": report["summary"],
            "valid": report["validation"]["valid"],
        }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
