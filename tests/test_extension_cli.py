"""CLI tests for the declared-extension discovery surface (Phase 15, 15-02).

The CLI is the awareness/resolution face: ``gridalyn extension list`` reports
installed extensions without importing them (the no-import property itself is
pinned at the engine layer in ``tests/test_extensions.py``), and ``gridalyn
extension validate`` loads only the declared IDs — side-effect free — reporting
provenance facts and exiting non-zero on any undeclared, unimportable, or
unready (missing-capability) ID.
"""

from __future__ import annotations

import importlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from gridalyn.foundation.platform.extensions import (
    DEFAULT_REGISTRY,
    SUPPORTED_CONTRACT_VERSIONS,
    EntryPointMetadata,
    ExtensionDescriptor,
    ExtensionRegistry,
    UnknownExtensionError,
    load_entry_point_extensions,
)
from gridalyn.interfaces.cli import extension


def _descriptor(extension_id: str = "acme-backend") -> ExtensionDescriptor:
    """A resolved-looking entry-point descriptor for CLI output tests."""
    return ExtensionDescriptor(
        extension_id=extension_id,
        role="powerflow_backend",
        name="ACME Backend",
        version="1.2.0",
        contract_version="1",
        source="entry_point",
        entry_point_group="gridalyn.extensions",
    )


class ExtensionListCliTest(unittest.TestCase):
    """``gridalyn extension list`` is the awareness path — no imports."""

    def test_list_prints_descriptor_roster(self) -> None:
        # The no-import property is pinned at the engine layer
        # (test_extensions.py::TestEntryPointDiscovery); this test pins the
        # CLI's output wiring for the roster.
        with mock.patch(
            "gridalyn.interfaces.cli.extension.list_installed_extensions",
            return_value=[_descriptor()],
        ):
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = extension.main(["list"])
        self.assertEqual(0, code)
        self.assertIn("acme-backend", stdout.getvalue())
        self.assertIn("entry_point", stdout.getvalue())
        self.assertIn("v1.2.0", stdout.getvalue())

    def test_list_json_is_machine_readable(self) -> None:
        with mock.patch(
            "gridalyn.interfaces.cli.extension.list_installed_extensions",
            return_value=[_descriptor()],
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = extension.main(["list", "--json"])
        self.assertEqual(0, code)
        payload = json.loads(stdout.getvalue())
        self.assertEqual("acme-backend", payload[0]["extension_id"])
        self.assertEqual("entry_point", payload[0]["source"])


class ExtensionValidateCliTest(unittest.TestCase):
    """``gridalyn extension validate`` is declared-only resolution."""

    def test_validate_resolves_a_declared_id(self) -> None:
        with (
            mock.patch(
                "gridalyn.interfaces.cli.extension.load_entry_point_extensions",
                return_value=[_descriptor()],
            ),
            mock.patch("gridalyn.interfaces.cli.extension._check_capability_readiness"),
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = extension.main(["validate", "acme-backend"])
        self.assertEqual(0, code)
        self.assertIn("acme-backend: OK", stdout.getvalue())
        self.assertIn("contract_version=1", stdout.getvalue())

    def test_validate_undeclared_id_exits_nonzero_with_located_error(self) -> None:
        def _raise(group: str, declared_ids: list[str], **kwargs: object) -> None:
            raise UnknownExtensionError(
                "declared extension 'ghost' is not installed in entry-point "
                "group 'gridalyn.extensions'"
            )

        with mock.patch(
            "gridalyn.interfaces.cli.extension.load_entry_point_extensions",
            side_effect=_raise,
        ):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = extension.main(["validate", "ghost"])
        self.assertEqual(1, code)
        self.assertIn("ghost", stderr.getvalue())
        self.assertIn("not installed", stderr.getvalue())

    def test_validate_requires_at_least_one_id(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = extension.main(["validate"])
        self.assertEqual(2, code)
        self.assertIn("at least one extension ID", stderr.getvalue())


class ExtensionValidateReadinessTest(unittest.TestCase):
    """The capability-readiness gate runs on validate (never silently accepted).

    Uses real fixture modules so the whole chain executes: the CLI loads the
    module through the loader, then ``require_extension_capabilities`` reads its
    ``REQUIRED_CAPABILITIES`` and raises ``MissingCapabilityError`` when they
    cannot be met — the only thing faked is module availability.
    """

    _READY_BODY = """\
from gridalyn.foundation.platform.extensions import ExtensionDescriptor

descriptor = ExtensionDescriptor(
    extension_id="cli-ready-ext",
    role="powerflow_backend",
    name="Ready",
    version="1.0.0",
    contract_version="1",
)

def factory():
    return "ready"
"""

    _UNREADY_BODY = """\
from gridalyn.foundation.platform.extensions import ExtensionDescriptor

REQUIRED_CAPABILITIES = ("sim",)

descriptor = ExtensionDescriptor(
    extension_id="cli-unready-ext",
    role="powerflow_backend",
    name="Unready",
    version="1.0.0",
    contract_version="1",
)

def factory():
    return "unready"
"""

    def _install(self, name: str, body: str) -> list[EntryPointMetadata]:
        """Write a real importable fixture module and return its metadata."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / f"{name}.py").write_text(body, encoding="utf-8")
        sys.path.insert(0, tmp.name)
        self.addCleanup(sys.path.remove, tmp.name)
        return [
            EntryPointMetadata(
                name=f"{name}-ext",
                value=name,
                module=name,
                attr=None,
                distribution="fixture",
                version="1.0.0",
            )
        ]

    def test_validate_accepts_ready_extension(self) -> None:
        records = self._install("cli_ready_a_probe", self._READY_BODY)
        with mock.patch(
            "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
            return_value=records,
        ):
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = extension.main(["validate", "cli_ready_a_probe-ext"])
        self.assertEqual(0, code)
        self.assertIn("cli_ready_a_probe-ext: OK", stdout.getvalue())

    def test_validate_surfaces_unready_extension(self) -> None:
        records = self._install("cli_unready_b_probe", self._UNREADY_BODY)
        with (
            mock.patch(
                "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
                return_value=records,
            ),
            mock.patch(
                "gridalyn.foundation.platform.capabilities.missing_capability_modules",
                return_value=["lightsim2grid"],
            ),
        ):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = extension.main(["validate", "cli_unready_b_probe-ext"])
        self.assertEqual(1, code)
        self.assertIn("cli_unready_b_probe-ext", stderr.getvalue())
        self.assertIn("sim", stderr.getvalue())

    def test_validate_does_not_mutate_default_registry(self) -> None:
        before = [d.extension_id for d in DEFAULT_REGISTRY.list_descriptors()]
        records = self._install("cli_ready_c_probe", self._READY_BODY)
        with mock.patch(
            "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
            return_value=records,
        ):
            code = extension.main(["validate", "cli_ready_c_probe-ext"])
        self.assertEqual(0, code)
        after = [d.extension_id for d in DEFAULT_REGISTRY.list_descriptors()]
        self.assertEqual(before, after)


class ScaffoldCliTest(unittest.TestCase):
    """``gridalyn extension new`` writes a conformant extension package (17-01)."""

    def test_new_scaffolds_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = extension.main(["new", "hello_world", "--target", tmp])
            self.assertEqual(0, code, stderr.getvalue())
            pkg = Path(tmp) / "hello_world"
            self.assertTrue((pkg / "pyproject.toml").is_file())
            self.assertTrue((pkg / "hello_world.py").is_file())
            self.assertTrue((pkg / "test_hello_world.py").is_file())
            self.assertIn("scaffolded extension", stdout.getvalue())

    def test_new_scaffolded_module_is_conformant(self) -> None:
        # A module name distinct from the committed example (hello_world), so
        # a previously imported example cannot shadow this scaffolded module
        # in sys.modules (17-03 isolation fix).
        name = "scaff_conform_ext"
        with tempfile.TemporaryDirectory() as tmp:
            code = extension.main(["new", name, "--target", tmp])
            self.assertEqual(0, code)
            module_dir = Path(tmp) / name
            sys.path.insert(0, str(module_dir))
            self.addCleanup(sys.path.remove, str(module_dir))
            module = importlib.import_module(name)
            self.addCleanup(sys.modules.pop, name, None)
        descriptor = module.descriptor
        self.assertIsInstance(descriptor, ExtensionDescriptor)
        self.assertEqual(name, descriptor.extension_id)
        self.assertEqual("powerflow_backend", descriptor.role)
        self.assertIn(descriptor.contract_version, SUPPORTED_CONTRACT_VERSIONS)
        self.assertTrue(callable(module.factory))

    def test_new_rejects_bad_name_with_located_error(self) -> None:
        # Review cycle 2: names outside the PEP 508/bare-key charset (spaces,
        # '=', non-ASCII, '#' — or path traversal) must be a located CLI error,
        # never a silently-uninstallable package.
        with tempfile.TemporaryDirectory() as tmp:
            for bad_name in ["../evil", "hello world", "a=b", "héllo", "x#y"]:
                with self.subTest(name=bad_name):
                    stderr = io.StringIO()
                    with redirect_stderr(stderr):
                        code = extension.main(["new", bad_name, "--target", tmp])
                    self.assertEqual(1, code, bad_name)
                    self.assertIn("extension new", stderr.getvalue())

    def test_scaffolded_pyproject_wires_the_entry_point(self) -> None:
        # Review cycle 2 (TRA W2): the load-bearing pyproject wiring — the
        # piece that makes `pip install` -> `extension validate <id>` work —
        # is pinned by parsing the generated TOML.
        import tomllib

        with tempfile.TemporaryDirectory() as tmp:
            code = extension.main(["new", "scaff_toml_ext", "--target", tmp])
            self.assertEqual(0, code)
            pyproject = tomllib.loads(
                (Path(tmp) / "scaff_toml_ext" / "pyproject.toml").read_text(
                    encoding="utf-8"
                )
            )
        entry_points = pyproject["project"]["entry-points"]
        self.assertEqual(
            "scaff_toml_ext",
            entry_points["gridalyn.extensions"]["scaff_toml_ext"],
        )
        self.assertIn("scaff_toml_ext", pyproject["tool"]["setuptools"]["py-modules"])

    def test_scaffold_output_matches_committed_example_verbatim(self) -> None:
        # Review cycle 2 (W1): the committed example must be exactly what the
        # scaffolder produces, so scaffold.yaml's "generated verbatim" note is
        # true and reproducible (and the output is black/isort-clean by
        # construction, since the committed example passes pre-commit).
        from gridalyn.interfaces.cli.scaffold import scaffold_extension

        committed = (
            Path(__file__).resolve().parents[1]
            / "examples"
            / "extensions"
            / "hello_world"
        )
        with tempfile.TemporaryDirectory() as tmp:
            scaffold_extension("hello_world", role="data_source", target=tmp)
            generated = Path(tmp) / "hello_world"
            for relative in (
                "hello_world.py",
                "test_hello_world.py",
                "pyproject.toml",
            ):
                with self.subTest(file=relative):
                    self.assertEqual(
                        (committed / relative).read_text(encoding="utf-8"),
                        (generated / relative).read_text(encoding="utf-8"),
                    )

    def test_name_edge_cases_are_validated_or_sanitized(self) -> None:
        # Review cycle 2 (TRA S4): the defensive branches of _validate_name /
        # _module_name are pinned, not left implicit.
        from gridalyn.interfaces.cli.scaffold import _module_name, _validate_name

        for bad in ["", "   ", ".", "..", "hello world", "a=b", "héllo"]:
            with self.subTest(name=bad):
                with self.assertRaises(ValueError):
                    _validate_name(bad)
        self.assertEqual("module_123", _module_name("123"))
        self.assertEqual("hello_world", _module_name("hello-world"))

    def test_new_refuses_existing_directory_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "hello_world").mkdir()
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = extension.main(["new", "hello_world", "--target", tmp])
            self.assertEqual(1, code)
            self.assertIn("already exists", stderr.getvalue())
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = extension.main(
                    ["new", "hello_world", "--target", tmp, "--force"]
                )
            self.assertEqual(0, code)


class ScaffoldResolvesTest(unittest.TestCase):
    """A scaffolded extension resolves through the validate path (17-02).

    The ROADMAP success criterion — "scaffolded extension passes validate" —
    pinned end-to-end: scaffold -> module on path -> declared-only resolution
    via load_entry_point_extensions (the exact path the validate CLI runs)
    -> descriptor provenance facts. A fresh registry and a monkeypatched
    entry-point metadata keep the process-global DEFAULT_REGISTRY untouched.
    """

    def _records(self, name: str) -> list[EntryPointMetadata]:
        return [
            EntryPointMetadata(
                name=name,
                value=name,
                module=name,
                attr=None,
                distribution="scaff-fixture",
                version="0.1.0",
            )
        ]

    def test_scaffolded_extension_resolves_through_loader(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code = extension.main(["new", "scaff_resolve_ext", "--target", tmp])
            self.assertEqual(0, code)
            module_dir = Path(tmp) / "scaff_resolve_ext"
            sys.path.insert(0, str(module_dir))
            self.addCleanup(sys.path.remove, str(module_dir))
            self.addCleanup(sys.modules.pop, "scaff_resolve_ext", None)
            with mock.patch(
                "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
                return_value=self._records("scaff_resolve_ext"),
            ):
                resolved = load_entry_point_extensions(
                    "gridalyn.extensions",
                    ["scaff_resolve_ext"],
                    registry=ExtensionRegistry(),
                )
        descriptor = resolved[0]
        self.assertEqual("scaff_resolve_ext", descriptor.extension_id)
        self.assertEqual("entry_point", descriptor.source)
        self.assertEqual("1", descriptor.contract_version)
        self.assertEqual("powerflow_backend", descriptor.role)

    def test_scaffolded_extension_passes_cli_validate(self) -> None:
        # The CLI validate path end-to-end: the scaffolded module on the path
        # is resolved (declared-only) and reported OK, with a fresh registry
        # so the process-global default is never mutated.
        with tempfile.TemporaryDirectory() as tmp:
            code = extension.main(["new", "scaff_cli_ext", "--target", tmp])
            self.assertEqual(0, code)
            module_dir = Path(tmp) / "scaff_cli_ext"
            sys.path.insert(0, str(module_dir))
            self.addCleanup(sys.path.remove, str(module_dir))
            self.addCleanup(sys.modules.pop, "scaff_cli_ext", None)
            with mock.patch(
                "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
                return_value=self._records("scaff_cli_ext"),
            ):
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = extension.main(["validate", "scaff_cli_ext"])
        self.assertEqual(0, code, stderr.getvalue())
        self.assertIn("scaff_cli_ext: OK", stdout.getvalue())


class CommittedExampleTest(unittest.TestCase):
    """The committed example under ``examples/extensions/`` validates (17-03).

    The authoring path is proven on a shipped, tracked artifact: the module a
    reader opens at ``examples/extensions/hello_world/`` resolves through the
    declared-only loader and passes the capability-readiness gate — the same
    two steps ``gridalyn extension validate`` performs. A fresh registry and
    monkeypatched metadata keep the process-global ``DEFAULT_REGISTRY``
    untouched.
    """

    REPO_ROOT = Path(__file__).resolve().parents[1]

    def _records(self, name: str) -> list[EntryPointMetadata]:
        return [
            EntryPointMetadata(
                name=name,
                value=name,
                module=name,
                attr=None,
                distribution="gridalyn-example-hello-world",
                version="0.1.0",
            )
        ]

    def test_committed_example_resolves_and_passes_readiness(self) -> None:
        from gridalyn.foundation.platform.capabilities import (
            require_extension_capabilities,
        )

        example_dir = self.REPO_ROOT / "examples" / "extensions" / "hello_world"
        self.assertTrue((example_dir / "hello_world.py").is_file())
        sys.path.insert(0, str(example_dir))
        self.addCleanup(sys.path.remove, str(example_dir))
        self.addCleanup(sys.modules.pop, "hello_world", None)
        with mock.patch(
            "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
            return_value=self._records("hello_world"),
        ):
            resolved = load_entry_point_extensions(
                "gridalyn.extensions",
                ["hello_world"],
                registry=ExtensionRegistry(),
            )
            require_extension_capabilities("hello_world", "gridalyn.extensions")
        descriptor = resolved[0]
        self.assertEqual("hello_world", descriptor.extension_id)
        self.assertEqual("data_source", descriptor.role)
        self.assertEqual("entry_point", descriptor.source)
        self.assertEqual("1", descriptor.contract_version)
