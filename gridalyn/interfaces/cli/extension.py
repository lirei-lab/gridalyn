"""Declared extension discovery command line interface."""

from __future__ import annotations

import argparse
import json
import sys

from gridalyn.interfaces.cli.environment import configure_cli_environment

configure_cli_environment()

from gridalyn.foundation.platform.extensions import (  # noqa: E402
    DEFAULT_EXTENSIONS_GROUP,
    list_installed_extensions,
    load_entry_point_extensions,
)


def _list_extensions(args: argparse.Namespace) -> int:
    """Print the installed-extension roster without importing any module."""
    descriptors = list_installed_extensions(group=args.group)
    if args.json:
        print(json.dumps([d.as_dict() for d in descriptors], indent=2, sort_keys=True))
        return 0
    if not descriptors:
        print(
            f"no extensions installed in entry-point group {args.group!r}",
            file=sys.stderr,
        )
        return 0
    for descriptor in descriptors:
        print(
            f"{descriptor.extension_id}\tv{descriptor.version}\t"
            f"contract={descriptor.contract_version}\tsource={descriptor.source}"
        )
    return 0


def _check_capability_readiness(extension_id: str, group: str) -> None:
    """Surface an unready extension as the platform's capability error.

    The engine is stdlib-only and cannot import ``capabilities``; the shared
    readiness gate lives there. The CLI is one caller of it — an extension
    whose ``REQUIRED_CAPABILITIES`` cannot be met is reported, never silently
    accepted.

    Args:
        extension_id: The resolved extension ID.
        group: The entry-point group it came from.

    Raises:
        MissingCapabilityError: If the extension declares a capability whose
            optional modules are not importable.
    """
    from gridalyn.foundation.platform.capabilities import require_extension_capabilities

    require_extension_capabilities(extension_id, group)


def _validate_extensions(args: argparse.Namespace) -> int:
    """Resolve declared extension IDs and report their provenance facts.

    Validation is deliberately side-effect free: each ID is resolved into a
    throwaway registry, so a failed ``validate`` never leaves a registration
    behind in the process-global ``DEFAULT_REGISTRY``.
    """
    from gridalyn.foundation.platform.extensions import ExtensionRegistry

    declared = args.extension_ids
    if not declared:
        print("validate requires at least one extension ID", file=sys.stderr)
        return 2
    exit_code = 0
    for extension_id in declared:
        try:
            loaded = load_entry_point_extensions(
                args.group, [extension_id], registry=ExtensionRegistry()
            )
            _check_capability_readiness(extension_id, args.group)
        except Exception as exc:
            print(f"extension {extension_id}: {exc}", file=sys.stderr)
            exit_code = 1
            continue
        descriptor = loaded[0]
        print(
            f"extension {descriptor.extension_id}: OK "
            f"(version={descriptor.version}, contract_version="
            f"{descriptor.contract_version}, source={descriptor.source})"
        )
    return exit_code


def _new_extension(args: argparse.Namespace) -> int:
    """Scaffold a conformant extension package under ``--target/<name>``.

    Authoring first-class (Phase 17, plan 17-01): one command produces a
    package that already satisfies the module convention the engine resolves,
    so ``gridalyn extension validate`` can load it after install. Errors are
    located and remediating; the engine is never modified.

    Args:
        args: Parsed ``new`` arguments (``name``, ``role``, ``target``,
            ``force``).

    Returns:
        ``0`` on success; ``1`` with a located stderr message otherwise.
    """
    from gridalyn.interfaces.cli.scaffold import scaffold_extension

    try:
        package_dir = scaffold_extension(
            args.name,
            role=args.role,
            target=args.target,
            force=args.force,
        )
    except (ValueError, FileExistsError) as exc:
        print(f"extension new: {exc}", file=sys.stderr)
        return 1
    print(f"scaffolded extension {args.name!r} at {package_dir}")
    print(
        f"next: install the package, then run `gridalyn extension validate "
        f"{args.name}`"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the ``gridalyn extension`` argument parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser(
        "list",
        help="List installed extensions without importing them (awareness).",
    )
    list_parser.add_argument("--group", default=DEFAULT_EXTENSIONS_GROUP)
    list_parser.add_argument("--json", action="store_true", help="Emit JSON.")
    list_parser.set_defaults(handler=_list_extensions)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Load declared extension IDs and report resolution (declared-only).",
    )
    validate_parser.add_argument("--group", default=DEFAULT_EXTENSIONS_GROUP)
    validate_parser.add_argument(
        "extension_ids",
        nargs="*",
        help="Declared extension IDs to resolve (at least one required).",
    )
    validate_parser.set_defaults(handler=_validate_extensions)

    new_parser = subparsers.add_parser(
        "new",
        help="Scaffold a conformant extension package.",
    )
    new_parser.add_argument("name", help="Extension ID / package name.")
    new_parser.add_argument(
        "--role",
        default="powerflow_backend",
        help="Role the extension serves (default: powerflow_backend).",
    )
    new_parser.add_argument(
        "--target",
        default=None,
        help="Directory to write the package into (default: current directory).",
    )
    new_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an already-existing package directory.",
    )
    new_parser.set_defaults(handler=_new_extension)
    return parser


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    """Parse ``gridalyn extension`` arguments, tolerating trailing extras."""
    parser = build_parser()
    args, extra_args = parser.parse_known_args(argv)
    return args, extra_args


def main(argv: list[str] | None = None) -> int:
    """Run the ``gridalyn extension`` command group.

    ``list`` is the awareness path (installed extensions, no module imported);
    ``validate`` is the declared-only resolution path (loads exactly the IDs
    the caller names, reports provenance facts, non-zero on any failure);
    ``new`` scaffolds a conformant extension package (authoring first-class).

    Args:
        argv: Argument list to parse; defaults to ``sys.argv[1:]``.

    Returns:
        Exit code from the selected subcommand.
    """
    args, _extra_args = parse_args(argv)
    return args.handler(args)
