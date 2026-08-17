"""Scaffolding for authoring conformant gridalyn extensions (Phase 17, 17-01).

The extension engine (:mod:`gridalyn.foundation.platform.extensions`) resolves
a module that exposes ``factory`` (a callable) and ``descriptor`` (an
:class:`ExtensionDescriptor`), optionally declares ``REQUIRED_CAPABILITIES``,
and is wired as an entry point in the ``gridalyn.extensions`` group. This
module makes authoring first-class: :func:`scaffold_extension` writes a
package that already satisfies that contract, so a developer runs
``gridalyn extension new`` and gets something ``gridalyn extension validate``
can load.

The scaffolder is deliberately side-effect free on the engine: it only writes
files. It imports nothing from the engine beyond the constants it needs to
validate the requested descriptor shape, and it never registers anything.
"""

from __future__ import annotations

from pathlib import Path

from gridalyn.foundation.platform.extensions import (
    DEFAULT_EXTENSIONS_GROUP,
    SUPPORTED_CONTRACT_VERSIONS,
)

#: Default role a scaffolded extension serves when the caller does not choose.
DEFAULT_EXTENSION_ROLE = "powerflow_backend"

#: Default semantic version stamped into the scaffolded descriptor.
DEFAULT_EXTENSION_VERSION = "0.1.0"

_MODULE_TEMPLATE = '''\
"""Extension {name!r} (role: {role!r}), scaffolded by gridalyn extension new.

A conformant extension module: the engine reads ``descriptor`` (an
:class:`gridalyn.foundation.platform.extensions.ExtensionDescriptor`) and
``factory`` (a callable returning the role's component) when this extension is
resolved through the ``{group}`` entry-point group.
"""

from __future__ import annotations

from gridalyn.foundation.platform.extensions import ExtensionDescriptor
{capabilities_block}
descriptor = ExtensionDescriptor(
    extension_id={name!r},
    role={role!r},
    name={name!r},
    version={version!r},
    contract_version={contract_version!r},
)


def factory():
    """Return the role component this extension provides.

    Returns:
        The component the role expects; the scaffold provides a placeholder
        the extension author replaces with a real implementation.
    """
    return None
'''

_TEST_TEMPLATE = '''\
"""Smoke test for the {name} extension (scaffolded by gridalyn extension new)."""

from __future__ import annotations

from gridalyn.foundation.platform.extensions import SUPPORTED_CONTRACT_VERSIONS

import {module_name}  # noqa: E402  - scaffolded fixture, ordering is deliberate


def test_descriptor_is_conformant() -> None:
    descriptor = {module_name}.descriptor
    assert descriptor.extension_id == {name!r}
    assert descriptor.role == {role!r}
    assert descriptor.contract_version in SUPPORTED_CONTRACT_VERSIONS


def test_factory_is_callable() -> None:
    assert callable({module_name}.factory)
'''

_PYPROJECT_TEMPLATE = """\
[project]
name = {name!r}
version = {version!r}
requires-python = ">=3.12"
dependencies = ["gridalyn"]

[project.entry-points.{group!r}]
{name} = "{module_name}"
"""


def _module_name(name: str) -> str:
    """Derive a valid Python module identifier from an extension name.

    Args:
        name: The extension ID/package name (e.g. ``"hello-world"``).

    Returns:
        A valid Python module identifier (non-alphanumeric runs become
        underscores; leading digits get a ``module_`` prefix).
    """
    slug = "".join(char if char.isalnum() else "_" for char in name)
    slug = slug.strip("_")
    if not slug:
        raise ValueError(f"extension name {name!r} yields no valid module name")
    if slug[0].isdigit():
        slug = f"module_{slug}"
    return slug


def _validate_name(name: str) -> None:
    """Reject an extension name that cannot be safely scaffolded.

    Args:
        name: The extension ID/package name.

    Raises:
        ValueError: If the name is empty, contains path separators or ``..``
            (path traversal), or yields no valid Python module identifier.
    """
    if not name or not name.strip():
        raise ValueError("extension name must be a non-empty string")
    if "/" in name or "\\" in name or ".." in name or name in {".", ".."}:
        raise ValueError(
            f"extension name {name!r} must not contain path separators or "
            "'..' (it is used as a directory and module name)"
        )
    _module_name(name)


def scaffold_extension(
    name: str,
    *,
    role: str = DEFAULT_EXTENSION_ROLE,
    target: str | Path | None = None,
    force: bool = False,
    version: str = DEFAULT_EXTENSION_VERSION,
    contract_version: str = "1",
    capabilities: tuple[str, ...] = (),
) -> Path:
    """Write a conformant extension package under ``<target>/<name>/``.

    The written package satisfies the engine's module convention so it can be
    loaded by :func:`gridalyn.foundation.platform.extensions.load_entry_point_extensions`:
    a module exposing ``descriptor`` + ``factory`` (plus
    ``REQUIRED_CAPABILITIES`` when declared), a ``pyproject.toml`` wiring the
    entry point in the ``gridalyn.extensions`` group, and a smoke test.

    Args:
        name: Extension ID / package name; becomes the directory and module
            name (invalid identifier characters are replaced with underscores).
        role: Role the extension serves (default ``powerflow_backend``).
        target: Directory to write the package into; defaults to the current
            directory. Created if it does not exist.
        force: Overwrite an already-existing package directory.
        version: Semantic version stamped into the descriptor and pyproject.
        contract_version: Role-contract version the descriptor declares; must
            be one the engine supports.
        capabilities: Optional capability names the extension requires, emitted
            as the module-level ``REQUIRED_CAPABILITIES`` tuple (checked by
            the capability-readiness gate at resolve time).

    Returns:
        The path of the written package directory.

    Raises:
        ValueError: If ``name``/``role`` are invalid or ``contract_version`` is
            unsupported.
        FileExistsError: If ``<target>/<name>`` exists and ``force`` is false.
    """
    _validate_name(name)
    if not role or not role.strip():
        raise ValueError("extension role must be a non-empty string")
    if contract_version not in SUPPORTED_CONTRACT_VERSIONS:
        supported = ", ".join(sorted(SUPPORTED_CONTRACT_VERSIONS))
        raise ValueError(
            f"extension {name!r} requests unsupported contract version "
            f"{contract_version!r} (supported: {supported})"
        )
    package_dir = Path(target or ".") / name
    if package_dir.exists() and not force:
        raise FileExistsError(
            f"target extension directory already exists: {package_dir} "
            "(pass force=True to overwrite it deliberately)"
        )
    package_dir.mkdir(parents=True, exist_ok=True)
    module_name = _module_name(name)
    capabilities_block = (
        f"REQUIRED_CAPABILITIES = {capabilities!r}\n\n" if capabilities else ""
    )
    module_body = _MODULE_TEMPLATE.format(
        name=name,
        role=role,
        version=version,
        contract_version=contract_version,
        group=DEFAULT_EXTENSIONS_GROUP,
        capabilities_block=capabilities_block,
    )
    test_body = _TEST_TEMPLATE.format(
        name=name,
        role=role,
        module_name=module_name,
    )
    pyproject_body = _PYPROJECT_TEMPLATE.format(
        name=name,
        version=version,
        group=DEFAULT_EXTENSIONS_GROUP,
        module_name=module_name,
    )
    (package_dir / f"{module_name}.py").write_text(module_body, encoding="utf-8")
    (package_dir / f"test_{module_name}.py").write_text(test_body, encoding="utf-8")
    (package_dir / "pyproject.toml").write_text(pyproject_body, encoding="utf-8")
    return package_dir
