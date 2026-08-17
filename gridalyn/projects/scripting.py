"""Boilerplate-free helpers for governed project workflow scripts.

A workflow stage script typically needs the same setup: resolve the project
workspace, create the standard ``outputs/*`` directories, configure headless
matplotlib, and write reports stamped with the project name. ``project_script``
bundles that setup into one call::

    from gridalyn.projects.scripting import project_script

    script = project_script()
    figure = script.figures_dir / "voltage_profile.png"
    ...
    script.write_report("powerflow_report", summary={"min_voltage_pu": 0.95})
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

import numpy as np

from gridalyn.projects import model_inputs
from gridalyn.projects.loader import load_project
from gridalyn.projects.models import StudyProject
from gridalyn.projects.outputs import (
    ProjectWorkspacePreparation,
    prepare_project_workspace,
)


def find_project_root(start: Path | str | None = None) -> Path:
    """Return the nearest ancestor directory containing ``project.yaml``."""
    candidates: list[Path] = []
    if start is not None:
        candidates.append(Path(start).resolve())
    else:
        candidates.append(Path.cwd().resolve())
        script_path = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else None
        if script_path is not None and script_path.exists():
            candidates.append(script_path.parent)
    for candidate in candidates:
        for directory in (candidate, *candidate.parents):
            if (directory / "project.yaml").is_file():
                return directory
    searched = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(
        f"no project.yaml found in {searched} or any parent directory; "
        "run the script from a project workspace or pass root=<project-dir>"
    )


def _configure_headless_matplotlib() -> None:
    """Force the non-interactive Agg backend when matplotlib is installed."""
    try:
        import matplotlib
    except ImportError:
        return
    matplotlib.use("Agg")


@dataclass(frozen=True)
class ProjectScript:
    """Loaded project plus the prepared workspace a stage script writes into."""

    project: StudyProject
    workspace: ProjectWorkspacePreparation

    @property
    def name(self) -> str:
        return self.project.name

    @property
    def version(self) -> str:
        return self.project.version

    @property
    def root(self) -> Path:
        return self.project.root

    @property
    def base_dir(self) -> Path:
        return self.project.base_dir

    @property
    def data_dir(self) -> Path:
        return self.project.root / "outputs" / "data"

    @property
    def figures_dir(self) -> Path:
        return self.project.root / "outputs" / "figures"

    @property
    def reports_dir(self) -> Path:
        return self.project.root / "outputs" / "reports"

    @property
    def manifests_dir(self) -> Path:
        return self.project.root / "outputs" / "manifests"

    @property
    def operations_dir(self) -> Path:
        return self.project.root / "outputs" / "operations"

    @property
    def cache_dir(self) -> Path:
        return self.project.root / "outputs" / "cache"

    def path(self, relative: Path | str) -> Path:
        """Resolve a project-relative output path, creating parent directories."""
        target = self.project.root / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def read_json(self, relative: Path | str) -> Any:
        """Read a project-relative JSON file and return the parsed payload.

        Args:
            relative: Project-relative path to the JSON file.

        Returns:
            The parsed JSON value.

        Raises:
            FileNotFoundError: If the resolved file does not exist, naming the
                resolved absolute path.
            ValueError: If the file is not valid JSON, naming the path.
        """
        target = self.path(relative)
        if not target.is_file():
            raise FileNotFoundError(f"no such JSON file: {target}")
        try:
            with target.open(encoding="utf-8") as handle:
                return json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{target}: malformed JSON: {exc}") from exc

    def write_json(
        self, relative: Path | str, payload: Mapping[str, Any] | list[Any]
    ) -> dict[str, Any]:
        """Write deterministic JSON to a project-relative path.

        Writes ``json.dumps(payload, indent=2, sort_keys=True)`` plus a trailing
        newline so the bytes are reproducible across runs, then returns the
        ``file_reference`` provenance record for the written file.

        Args:
            relative: Project-relative output path.
            payload: JSON-serialisable payload to write.

        Returns:
            The provenance record (``path``/``bytes``/``sha256``) for the file.
        """
        target = self.path(relative)
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        target.write_text(text, encoding="utf-8")
        return self.file_reference(target)

    def load_project_module(self, relative: str) -> ModuleType:
        """Import a project-relative module by dotted path.

        Imports e.g. ``"scripts.config"`` resolved under the project root,
        without ``sys.path`` mutation or ``Path(__file__).parents[N]``
        boilerplate. Repeated calls return the cached module.

        Args:
            relative: Dotted project-relative module path (e.g.
                ``"scripts.config"``).

        Returns:
            The imported module.

        Raises:
            ValueError: If ``relative`` is not a dotted module path.
            FileNotFoundError: If the resolved module file does not exist,
                naming the dotted path and the file looked up.
        """
        if "." not in relative:
            raise ValueError(
                f"expected a dotted project-relative module path "
                f"(e.g. 'scripts.config'); got {relative!r}"
            )
        if relative in sys.modules:
            return sys.modules[relative]
        resolved = self.project.root / (relative.replace(".", "/") + ".py")
        if not resolved.is_file():
            raise FileNotFoundError(
                f"no project module {relative!r} (looked for {resolved})"
            )
        spec = importlib.util.spec_from_file_location(relative, resolved)
        if spec is None or spec.loader is None:
            raise ImportError(
                f"could not build an import spec for {relative!r} at {resolved}"
            )
        module = importlib.util.module_from_spec(spec)
        sys.modules[relative] = module
        spec.loader.exec_module(module)
        return module

    def report_metadata(self, report_id: str) -> Any:
        """Return ``ReportMetadata`` stamped with this project's identity."""
        from gridalyn.foundation.platform.reports import ReportMetadata

        return ReportMetadata(
            report_id=report_id,
            source_domain=self.name,
            project={"name": self.name},
        )

    def write_report(
        self,
        report_id: str,
        *,
        path: Path | str | None = None,
        inputs: list[dict[str, Any]] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        summary: dict[str, Any] | None = None,
        validation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Write a platform report with project metadata pre-filled.

        Defaults to ``outputs/reports/<report_id>.json`` inside the project.
        """
        from gridalyn.foundation.platform.reports import write_report

        report_path = (
            Path(path) if path is not None else self.reports_dir / f"{report_id}.json"
        )
        return write_report(
            report_path,
            metadata=self.report_metadata(report_id),
            inputs=inputs,
            artifacts=artifacts,
            summary=summary,
            validation=validation,
        )

    def file_reference(self, path: Path | str) -> dict[str, Any]:
        """Return a provenance record for a file, relative to the project root."""
        from gridalyn.foundation.platform.reports import file_reference

        return file_reference(path, root=self.project.root)

    def input(self, key: str) -> Mapping[str, Any]:
        """Return one named mapping from ``spec.inputs``."""
        return model_inputs.project_input(self.project, key)

    def load_radial_feeder_spec(self, input_key: str = "sourceNetwork") -> Any:
        return model_inputs.load_radial_feeder_spec(self.project, input_key)

    def load_der_dispatch_assets(self, input_key: str = "derAssets") -> tuple[Any, ...]:
        return model_inputs.load_der_dispatch_assets(self.project, input_key)

    def load_prosumer_assets(
        self, input_key: str = "prosumerAssets"
    ) -> tuple[Any, ...]:
        return model_inputs.load_prosumer_assets(self.project, input_key)

    def load_voltage_control_der_spec(
        self,
        input_key: str = "voltageControlDer",
        feeder: Any | None = None,
    ) -> Any:
        return model_inputs.load_voltage_control_der_spec(
            self.project, input_key, feeder=feeder
        )

    def load_numeric_profile_array(self, input_key: str) -> np.ndarray:
        return model_inputs.load_numeric_profile_array(self.project, input_key)

    def load_generated_load_profiles(self, input_key: str = "loadGeneration") -> Any:
        return model_inputs.load_generated_load_profiles(self.project, input_key)

    def load_generated_load_multipliers(
        self, input_key: str = "loadGeneration"
    ) -> np.ndarray:
        return model_inputs.load_generated_load_multipliers(self.project, input_key)

    def simulation_seed(self, stream: str) -> int:
        """Return one named RNG seed this study declares in ``spec.simulation``.

        Args:
            stream: Name of the declared stream, e.g. ``"policy"``.

        Returns:
            The declared integer seed, so the value the manifest records is the
            value this stage actually draws from.
        """
        return model_inputs.load_simulation_seed(self.project, stream)

    def powerflow_backend_id(self) -> str:
        """Return the backend ID this study declares in ``spec.simulation``."""
        return model_inputs.load_powerflow_backend_id(self.project)

    def powerflow_backend(self, **settings: Any) -> Any:
        """Resolve the power-flow backend this study declares.

        A solving stage calls this instead of ``pandapower.runpp`` so that the
        engine it uses is the one ``provenance.powerflow_backend.backend_id``
        records. Resolution is strict by design: naming an unavailable backend
        raises ``MissingCapabilityError`` at this call rather than degrading to
        a different solver, because a silent downgrade changes solved values
        while leaving every governed artifact unchanged.

        Args:
            **settings: Solver keywords overriding the backend's declared
                settings for this instance.

        Returns:
            A ``PowerFlowBackend`` whose ``solve(net, **kwargs)`` is the single
            place this stage may solve.
        """
        from gridalyn.simulation.backends.registry import resolve_powerflow_backend

        return resolve_powerflow_backend(self.powerflow_backend_id(), **settings)


def project_script(
    root: Path | str | None = None,
    headless_matplotlib: bool = True,
) -> ProjectScript:
    """Load the surrounding project and prepare its output workspace.

    Resolves the project workspace by searching for ``project.yaml`` upward
    from the current directory (and the running script's directory), creates
    the standard ``outputs/*`` tree, points the matplotlib cache inside it,
    and switches matplotlib to the headless Agg backend.
    """
    project_root = find_project_root(root)
    project = load_project(project_root / "project.yaml")
    workspace = prepare_project_workspace(project.root)
    os.environ.setdefault("MPLCONFIGDIR", str(workspace.matplotlib_cache.resolve()))
    if headless_matplotlib:
        _configure_headless_matplotlib()
    return ProjectScript(project=project, workspace=workspace)


__all__ = [
    "ProjectScript",
    "find_project_root",
    "project_script",
]
