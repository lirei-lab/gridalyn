"""Reproducible end-to-end external-pilot run (Phase 18, plan 18-02).

Proves the framework's flagship claim with extensions OUTSIDE gridalyn: an
embedding application registers an external extension (and the 18-01 external
power-flow backend) through the declared mechanisms, runs a study, and the run
manifest records them — ``provenance.extensions`` populated and
``provenance.powerflow_backend`` naming the external backend.

Run (from the repo root):

    .venv/bin/python examples/extensions/pilot/run_pilot.py             # host source
    .venv/bin/python examples/extensions/pilot/run_pilot.py --entry-point

The output is a deterministic JSON summary of the manifest's provenance;
``tests/test_extension_pilot.py::EndToEndPilotTest`` pins it (exit 0 and the
populated provenance). See ``examples/extensions/pilot/PILOT.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import yaml

from gridalyn.foundation.platform import extensions as _extensions_module
from gridalyn.foundation.platform.extensions import (
    DEFAULT_EXTENSIONS_GROUP,
    EntryPointMetadata,
    ExtensionDescriptor,
    load_entry_point_extensions,
    register_extension,
)
from gridalyn.projects import init_project, run_workflow

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "examples" / "extensions" / "pilot_backend"))
sys.path.insert(0, str(REPO_ROOT / "examples" / "extensions" / "hello_world"))

import pilot_backend  # noqa: E402  - the example dir is added to sys.path above


def _scaffold_study() -> Path:
    """Scaffold a grid-study into a temp dir, declaring the pilot backend.

    Returns:
        The study directory, with ``project.yaml`` declaring
        ``pilot_native_backend`` as its power-flow backend.
    """
    tmp = tempfile.mkdtemp(prefix="pilot_run_")
    target = Path(tmp) / "pilot_case"
    init_project(target, name="pilot_case", template="grid-study")
    project_file = target / "project.yaml"
    data = yaml.safe_load(project_file.read_text(encoding="utf-8"))
    data["spec"]["simulation"]["powerflowBackend"] = pilot_backend.PILOT_BACKEND_ID
    project_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return target


def _register_generic_extension() -> None:
    """Register an external generic extension via the host API (source=host)."""
    register_extension(
        lambda: "pilot data source",
        descriptor=ExtensionDescriptor(
            extension_id="pilot_data_source",
            role="data_source",
            name="Pilot data source",
            version="0.1.0",
            contract_version="1",
            source="host",
        ),
    )


def _load_entry_point_extension() -> None:
    """Load the committed hello_world extension through the entry_point path.

    The committed example is not pip-installed, so its entry-point metadata is
    wired here the way a real installation would expose it; the loader then
    behaves exactly as it would against a real distribution
    (``source="entry_point"`` in ``provenance.extensions``).
    """
    from unittest import mock

    record = EntryPointMetadata(
        name="hello_world",
        value="hello_world",
        module="hello_world",
        attr=None,
        distribution="gridalyn-example-hello-world",
        version="0.1.0",
    )
    with mock.patch.object(
        _extensions_module,
        "list_entry_point_metadata",
        return_value=[record],
    ):
        load_entry_point_extensions(DEFAULT_EXTENSIONS_GROUP, ["hello_world"])


def main(argv: list[str] | None = None) -> int:
    """Run the pilot and print the manifest's extension provenance as JSON.

    Args:
        argv: Argument list to parse; defaults to ``sys.argv[1:]``.

    Returns:
        ``0`` on success; the manifest's ``provenance.extensions`` and the
        backend's ``extension_id``/``extension_source`` are printed as a
        deterministic JSON summary.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--entry-point",
        action="store_true",
        help="Load the committed hello_world extension via the entry_point "
        "path instead of registering a host extension.",
    )
    args = parser.parse_args(argv)

    target = _scaffold_study()
    if args.entry_point:
        _load_entry_point_extension()
    else:
        _register_generic_extension()
    # The 18-01 external backend, registered through the declared host API.
    pilot_backend.register(version="0.1.0")

    run_workflow(target, dry_run=True)
    manifest_path = target / "outputs" / "manifests" / "project_run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    backend = manifest["provenance"]["powerflow_backend"]
    summary = {
        "extensions": manifest["provenance"]["extensions"],
        "powerflow_backend": {
            "extension_id": backend.get("extension_id"),
            "extension_source": backend.get("extension_source"),
        },
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
