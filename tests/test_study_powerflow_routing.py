"""Study stages must solve through the backend contract, and declare which one.

Two holes this closes, both found by an adversarial review of the branch that
introduced the routing (2026-08-14):

* ``tests/test_powerflow_backend_contract.py`` scans only ``gridalyn/``. Ten
  direct ``pandapower.runpp`` sites lived in ``projects/`` -- including one in a
  CI fixture -- and nothing would have caught a regression back to them.
* ``provenance.powerflow_backend`` recorded one backend ID per run, while
  ``ev_hosting_flex`` solves its full-network voltage path on lightsim2grid and
  everything else on pandapower native. The manifest named an engine one of its
  stages did not use.

The declaration is checked against the real call graph rather than against an
injection point. Threading a backend object down three call levels would have
verified only that one path was wired; resolving which accessor each stage
transitively reaches verifies every path, including ones added later.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from gridalyn.projects.loader import load_project
from gridalyn.projects.model_inputs import (
    load_powerflow_backend_by_stage,
    load_powerflow_backend_id,
)
from gridalyn.simulation.backends.contract import (
    LIGHTSIM2GRID_BACKEND_ID,
    PANDAPOWER_NATIVE_BACKEND_ID,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECTS_DIR = REPO_ROOT / "projects"

#: Solver entry points a study must not call directly. ``runpp_3ph`` is absent
#: on purpose: the backend contract models ``runpp`` only, so there is nothing
#: to route a three-phase solve to. That exemption is declared here rather than
#: left implicit, and its single site is pinned below.
FORBIDDEN_SOLVER_CALLS = ("runpp",)

#: The one accepted direct three-phase solve, with the reason it is accepted.
THREE_PHASE_EXEMPTIONS = {
    "projects/ev_hosting_flex/scripts/pipeline/analyze_phase_imbalance.py": (
        "runpp_3ph has no backend in the contract, which covers runpp only"
    ),
}

#: Study-local accessors that resolve a backend, mapped to the ID they resolve.
BACKEND_ACCESSORS = {
    "native_backend": PANDAPOWER_NATIVE_BACKEND_ID,
    "lightsim_backend": LIGHTSIM2GRID_BACKEND_ID,
}


def _study_python_files() -> list[Path]:
    return sorted(
        path
        for path in PROJECTS_DIR.rglob("*.py")
        if "__pycache__" not in path.parts and "outputs" not in path.parts
    )


def _direct_solver_calls(path: Path) -> list[tuple[int, str]]:
    """Return ``(lineno, attribute)`` for each direct solver call in ``path``."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - a broken study script fails elsewhere
        return []
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in FORBIDDEN_SOLVER_CALLS:
                found.append((node.lineno, node.func.attr))
    return found


class StudyStagesUseTheBackendContract(unittest.TestCase):
    def test_no_study_script_calls_runpp_directly(self) -> None:
        offenders = []
        for path in _study_python_files():
            for lineno, attribute in _direct_solver_calls(path):
                relative = path.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"{relative}:{lineno} calls {attribute}")
        self.assertEqual(
            offenders,
            [],
            "study stages must solve through resolve_powerflow_backend so the "
            "engine reaches provenance.powerflow_backend; a bare runpp is "
            "invisible in every governed artifact: " + "; ".join(offenders),
        )

    def test_three_phase_exemption_is_declared_and_still_real(self) -> None:
        # The exemption is real, but it must not quietly outlive its reason.
        for relative, reason in THREE_PHASE_EXEMPTIONS.items():
            with self.subTest(path=relative):
                path = REPO_ROOT / relative
                self.assertTrue(path.is_file(), f"{relative} no longer exists")
                self.assertIn(
                    "runpp_3ph",
                    path.read_text(encoding="utf-8"),
                    f"{relative} is exempted because {reason}, but no longer "
                    "calls runpp_3ph; drop the exemption",
                )


class DeclaredBackendsMatchTheCallGraph(unittest.TestCase):
    """A stage's declared backend must be the one its code actually reaches."""

    def _module_for(self, relative: str) -> Path:
        return PROJECTS_DIR / relative

    @staticmethod
    def _module_graph(path: Path) -> tuple[dict[str, set[str]], dict[str, Path]]:
        """Return this module's per-function call names and its study imports.

        Args:
            path: Module to parse.

        Returns:
            ``(calls, imports)`` where ``calls`` maps each function name -- plus
            the pseudo-entry ``"<module>"`` for top-level code -- to the bare
            names it calls, and ``imports`` maps each name imported from a
            ``projects.*`` module to that module's path.
        """
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls: dict[str, set[str]] = {"<module>": set()}
        imports: dict[str, Path] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("projects."):
                    target = REPO_ROOT / (node.module.replace(".", "/") + ".py")
                    for alias in node.names:
                        imports[alias.asname or alias.name] = target
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names: set[str] = set()
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
                        names.add(inner.func.id)
                calls[node.name] = names
        return calls, imports

    def _accessors_reached(self, entry: Path) -> set[str]:
        """Return the backend accessors ``entry`` reaches through real calls.

        Walks the call graph at FUNCTION granularity across study modules. A
        module-level walk is not good enough here: every stage script imports
        ``_powerflow``, which defines both accessors, so module reachability
        marks all of them as reaching lightsim2grid. What matters is whether the
        specific functions a stage calls lead to one.

        Args:
            entry: Stage script to start from.

        Returns:
            Names from :data:`BACKEND_ACCESSORS` reachable from this script.
        """
        reached: set[str] = set()
        seen: set[tuple[Path, str]] = set()
        work: list[tuple[Path, str]] = [(entry, "<module>")]
        graphs: dict[Path, tuple[dict[str, set[str]], dict[str, Path]]] = {}
        # Top-level code plus every function the entry module defines: a stage
        # script's work happens in helpers its own main() calls.
        if entry.is_file():
            graphs[entry] = self._module_graph(entry)
            work.extend((entry, name) for name in graphs[entry][0])
        while work:
            module, function = work.pop()
            if (module, function) in seen or not module.is_file():
                continue
            seen.add((module, function))
            if module not in graphs:
                graphs[module] = self._module_graph(module)
            calls, imports = graphs[module]
            for name in calls.get(function, set()):
                if name in BACKEND_ACCESSORS:
                    reached.add(name)
                elif name in calls:
                    work.append((module, name))
                elif name in imports:
                    work.append((imports[name], name))
        return reached

    def test_ev_hosting_flex_declares_both_engines_it_reaches(self) -> None:
        project_file = PROJECTS_DIR / "ev_hosting_flex" / "project.yaml"
        project = load_project(project_file)
        overrides = load_powerflow_backend_by_stage(project)

        # The lightsim stage: declared as an override, and its call graph must
        # actually reach the lightsim accessor.
        lightsim_stage = "analyze_voltage_risk_network"
        self.assertEqual(overrides.get(lightsim_stage), LIGHTSIM2GRID_BACKEND_ID)
        reached = self._accessors_reached(
            PROJECTS_DIR
            / "ev_hosting_flex"
            / "scripts"
            / "pipeline"
            / f"{lightsim_stage}.py"
        )
        self.assertIn(
            "lightsim_backend",
            reached,
            f"{lightsim_stage} declares lightsim2grid but its call graph never "
            "reaches lightsim_backend(); the declaration is not backed by code",
        )
        self.assertEqual(
            load_powerflow_backend_id(project, stage_id=lightsim_stage),
            LIGHTSIM2GRID_BACKEND_ID,
        )

        # The study default must be the engine every other solving stage uses.
        self.assertEqual(
            load_powerflow_backend_id(project), PANDAPOWER_NATIVE_BACKEND_ID
        )

    def test_a_stage_reaching_lightsim_must_declare_it(self) -> None:
        # The direction that catches drift: any ev_hosting_flex stage script
        # whose call graph reaches lightsim_backend() must carry an override.
        # Without this, moving the lightsim call into another stage would leave
        # that stage recorded as pandapower_native.
        project = load_project(PROJECTS_DIR / "ev_hosting_flex" / "project.yaml")
        overrides = load_powerflow_backend_by_stage(project)
        pipeline = PROJECTS_DIR / "ev_hosting_flex" / "scripts" / "pipeline"
        undeclared = []
        for script in sorted(pipeline.glob("*.py")):
            if script.name == "__init__.py":
                continue
            if "lightsim_backend" not in self._accessors_reached(script):
                continue
            if overrides.get(script.stem) != LIGHTSIM2GRID_BACKEND_ID:
                undeclared.append(script.stem)
        self.assertEqual(
            undeclared,
            [],
            "these stages reach lightsim_backend() but do not declare it in "
            "spec.simulation.powerflowBackendByStage, so their manifest would "
            f"name the wrong engine: {undeclared}",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
