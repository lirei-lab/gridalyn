"""Declared extension discovery command line interface."""

from __future__ import annotations

import argparse
import importlib
import json
import sys

from gridalyn.interfaces.cli.environment import configure_cli_environment

configure_cli_environment()

from gridalyn.foundation.platform.extensions import (  # noqa: E402
    DEFAULT_EXTENSIONS_GROUP,
    list_entry_point_metadata,
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
    """Raise when an extension declares capabilities its environment lacks.

    The engine is stdlib-only and cannot import ``capabilities``; the CLI is
    the layer that turns "registered but not ready" into the platform's
    :class:`MissingCapabilityError` — an extension is never silently accepted.

    Args:
        extension_id: The resolved extension ID.
        group: The entry-point group it came from.

    Raises:
        MissingCapabilityError: If the extension declares a ``REQUIRED_CAPABILITIES``
            capability whose optional modules are not importable.
    """
    from gridalyn.foundation.platform.capabilities import require_capabilities

    for record in list_entry_point_metadata(group):
        if record.name != extension_id:
            continue
        module = importlib.import_module(record.module)
        required = getattr(module, "REQUIRED_CAPABILITIES", ())
        if required:
            require_capabilities(*required, context=f"extension {extension_id!r}")
        return


def _validate_extensions(args: argparse.Namespace) -> int:
    """Resolve declared extension IDs and report their provenance facts."""
    declared = args.extension_ids
    if not declared:
        print("validate requires at least one extension ID", file=sys.stderr)
        return 2
    exit_code = 0
    for extension_id in declared:
        try:
            loaded = load_entry_point_extensions(args.group, [extension_id])
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
    the caller names, reports provenance facts, non-zero on any failure).

    Args:
        argv: Argument list to parse; defaults to ``sys.argv[1:]``.

    Returns:
        Exit code from the selected subcommand.
    """
    args, _extra_args = parse_args(argv)
    return args.handler(args)
