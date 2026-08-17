"""The declared project-development binding surface.

A project is *bound*, not hand-wired: :func:`bind_project_components` resolves
the project's declared specs ONCE through the ``ProjectScript`` typed loaders,
resolves the declared power-flow backend through the backend registry, and
returns a frozen :class:`ProjectComponents` bundle a stage script drives::

    from gridalyn.projects.developer import bind_project_components
    from gridalyn.projects.scripting import project_script

    script = project_script()
    components = bind_project_components(script)
    net = components.build_feeder()

Project-defined components register through the per-role extension registries
before the bind and are consumed by explicit ID via
:meth:`ProjectComponents.consume` — never by ambient discovery. The currently
wired role is the power-flow **backend** (``register_powerflow_backend_extension``
→ ``consume("backend", id)``); the observation-producer / surrogate / policy
roles are declared surface for a follow-up (their registries do not yet expose
a ``registration_source`` discriminator the way the backend registry does).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gridalyn.projects.scripting import ProjectScript

__all__ = ["ProjectComponents", "bind_project_components"]


@dataclass(frozen=True)
class ProjectComponents:
    """Named components a stage script binds once from a project's contracts.

    Attributes:
        script: The ``ProjectScript`` the components were bound from.
        feeder_spec: The declared ``RadialFeederSpec`` (``sourceNetwork``
            input), or ``None`` if the project declares none.
        load_profiles: The generated load-profile frame (``loadGeneration``
            input), or ``None`` if the project declares none.
        backend: The resolved power-flow backend, or ``None`` if the project
            declares none.
        registered: Explicit-ID components the project registered through the
            per-role registries, keyed by their role name (``backend`` today;
            the platform's ``observation_producer`` / ``surrogate`` / ``policy``
            roles are declared follow-up surface).
    """

    script: ProjectScript
    feeder_spec: Any | None = None
    load_profiles: Any | None = None
    backend: Any | None = None
    registered: dict[str, dict[str, Any]] = field(default_factory=dict)

    def build_feeder(self) -> Any:
        """Construct the network through the SDK builder with the bound backend.

        Returns:
            A pandapower-style net built from the bound ``feeder_spec``. The
            backend is left untouched here (``solve`` is the caller's choice via
            the bound backend) so a stage that only builds + reports never
            solves implicitly.

        Raises:
            ValueError: If no feeder spec is bound.
        """
        if self.feeder_spec is None:
            raise ValueError(
                "ProjectComponents.build_feeder requires a bound feeder spec; "
                "the project declares no sourceNetwork input. Remediation: add "
                "spec.inputs.sourceNetwork or bind a spec explicitly."
            )
        from gridalyn.simulation.simulators.powerflow.feeders import (
            build_radial_pandapower_feeder,
        )

        return build_radial_pandapower_feeder(self.feeder_spec)

    def consume(self, role: str, component_id: str) -> Any:
        """Return a project-registered component by role and explicit ID.

        Args:
            role: The per-role registry name. Currently wired: ``backend``.
                The ``observation_producer`` / ``surrogate`` / ``policy``
                roles are declared follow-up surface (their registries do not
                yet expose a ``registration_source`` discriminator).
            component_id: The explicit component ID the project registered.

        Returns:
            The registered component object (a resolved ``PowerFlowBackend``
            for the ``backend`` role).

        Raises:
            ValueError: If the role or ID is not registered.
        """
        by_role = self.registered.get(role, {})
        if component_id not in by_role:
            known = ", ".join(sorted(by_role)) or "none"
            raise ValueError(
                f"no project-registered {role} component {component_id!r} "
                f"(registered: {known}). Remediation: register it through the "
                f"{role} per-role registry before bind_project_components."
            )
        if role == "backend":
            from gridalyn.simulation.backends.registry import resolve_powerflow_backend

            return resolve_powerflow_backend(component_id)
        # Unwired roles are unreachable today: only backend ever populates
        # ``registered``. Returning the stored object here keeps the future
        # surface honest when the other roles are wired.
        return by_role[component_id]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-native summary of the bound components."""
        return {
            "feeder_spec": (
                self.feeder_spec.name if self.feeder_spec is not None else None
            ),
            "has_load_profiles": self.load_profiles is not None,
            "backend_id": (
                getattr(self.backend, "descriptor", None).backend_id
                if self.backend is not None
                and getattr(self.backend, "descriptor", None) is not None
                else None
            ),
            "registered": {
                role: sorted(by_id) for role, by_id in self.registered.items()
            },
        }


def _collect_backend_registrations() -> dict[str, dict[str, Any]]:
    """Collect non-core backend registrations from the default registry.

    Records every registered backend whose ``registration_source != "core"``
    by ID -> descriptor. Core defaults are never project components.
    """
    from gridalyn.simulation.backends.registry import default_powerflow_backend_registry

    registry = default_powerflow_backend_registry()
    project_backends: dict[str, dict[str, Any]] = {}
    for descriptor in registry.list_descriptors():
        backend_id = descriptor.backend_id
        if registry.registration_source(backend_id) != "core":
            project_backends[backend_id] = descriptor
    return {"backend": project_backends} if project_backends else {}


def _declared_input_keys(script: ProjectScript) -> set[str]:
    """Return the input keys a project declares in ``spec.inputs``.

    Absence (a key not declared) is the *optional* case a bind may treat as
    ``None``; presence is the *contract* case, where the loader's located
    ``ValueError`` must propagate rather than being swallowed. A ``spec.inputs``
    that is present but NOT a mapping is itself declared-but-malformed and
    raises a located error — it is not silently treated as "nothing declared".

    Args:
        script: The prepared ``ProjectScript`` for the running project.

    Returns:
        The set of declared ``spec.inputs`` keys (``set()`` when none).

    Raises:
        ValueError: If ``spec.inputs`` is present but not a mapping (a located
            error naming the key and the found type, per the loader contract).
    """
    inputs = script.project.raw.get("spec", {}).get("inputs")
    if inputs is None:
        return set()
    if not isinstance(inputs, dict):
        raise ValueError(
            f"{script.project.path}: spec.inputs must be a mapping, "
            f"found {type(inputs).__name__}. Remediation: fix spec.inputs in "
            "project.yaml to a mapping of input-key -> declaration."
        )
    return set(inputs)


def bind_project_components(script: ProjectScript) -> ProjectComponents:
    """Resolve a project's declared components once and return them bound.

    Resolves the declared ``sourceNetwork`` feeder spec, the ``loadGeneration``
    profiles and the declared power-flow backend through the ``ProjectScript``
    typed loaders — never by re-deriving ``project.yaml`` literals or paths. A
    project with none of those declared returns a minimal-but-valid bundle
    (a stage that only writes reports needs nothing bound).

    Absent inputs are optional (bound to ``None``); a declared-but-malformed
    input is a contract violation and the loader's located ``ValueError``
    propagates — a silent swallow would mask a typo'd ``sourceNetwork`` as
    "no sourceNetwork declared".

    Args:
        script: The prepared ``ProjectScript`` for the running project.

    Returns:
        A frozen :class:`ProjectComponents` with the declared components bound.

    Raises:
        ValueError: If a declared component is present but cannot be resolved
            (a located error naming the YAML key and available inputs, per the
            loader contract).
    """
    declared = _declared_input_keys(script)

    feeder_spec = (
        script.load_radial_feeder_spec() if "sourceNetwork" in declared else None
    )
    load_profiles = (
        script.load_generated_load_profiles() if "loadGeneration" in declared else None
    )
    # The backend is never optional: a study that declares nothing still gets
    # the registry default, so this always resolves (or raises a located error
    # / MissingCapabilityError for a genuinely bad declaration).
    backend = script.powerflow_backend()

    registered = _collect_backend_registrations()

    return ProjectComponents(
        script=script,
        feeder_spec=feeder_spec,
        load_profiles=load_profiles,
        backend=backend,
        registered=registered,
    )
