"""Unit tests for the generic extension engine (foundation/platform/extensions.py)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

from gridalyn.foundation.platform.extensions import (
    DEFAULT_EXTENSIONS_GROUP,
    EntryPointMetadata,
    ExtensionDescriptor,
    ExtensionRegistry,
    UnknownExtensionError,
    UnsupportedContractVersionError,
    extension_provenance,
    list_entry_point_metadata,
    list_installed_extensions,
    load_entry_point_extensions,
)


def _descriptor(
    extension_id: str = "acme-backend",
    *,
    role: str = "powerflow_backend",
    **kwargs: object,
) -> ExtensionDescriptor:
    defaults: dict[str, object] = dict(
        name="ACME Backend",
        version="1.2.0",
        contract_version="1",
        source="core",
        entry_point_group=None,
        module_hash=None,
    )
    defaults.update(kwargs)
    return ExtensionDescriptor(extension_id=extension_id, role=role, **defaults)  # type: ignore[arg-type]


def _factory() -> str:
    return "acme-instance"


def _write_module(tmp_path: Path, name: str, body: str) -> None:
    """Write a real importable module into the test's temp directory."""
    (tmp_path / f"{name}.py").write_text(body, encoding="utf-8")


def _entry_point_record(
    name: str,
    module: str,
    *,
    distribution: str | None = "fixture-dist",
    version: str = "1.0.0",
) -> EntryPointMetadata:
    """Build the metadata the discovery walk would return for a fixture module."""
    return EntryPointMetadata(
        name=name,
        value=module,
        module=module,
        attr=None,
        distribution=distribution,
        version=version,
    )


class TestRegistryIsGeneric:
    def test_registry_stores_any_role_without_interpreting_it(self) -> None:
        """The engine is role-agnostic: it never inspects factory output."""
        registry = ExtensionRegistry()
        registry.register(
            _factory, descriptor=_descriptor("a", role="powerflow_backend")
        )
        registry.register(_factory, descriptor=_descriptor("b", role="data_source"))
        registry.register(_factory, descriptor=_descriptor("c", role="stage_template"))
        assert [d.extension_id for d in registry.list_descriptors()] == ["a", "b", "c"]

    def test_unknown_role_is_data_not_validation(self) -> None:
        """The engine accepts any role string; role semantics belong to the caller."""
        registry = ExtensionRegistry()
        registry.register(_factory, descriptor=_descriptor("x", role="anything"))
        assert registry.get_descriptor("x").role == "anything"


class TestRegisterAndResolve:
    def test_register_then_get_descriptor(self) -> None:
        registry = ExtensionRegistry()
        registry.register(_factory, descriptor=_descriptor("acme"))
        descriptor = registry.get_descriptor("acme")
        assert descriptor.extension_id == "acme"
        assert descriptor.name == "ACME Backend"

    def test_resolve_calls_the_factory(self) -> None:
        registry = ExtensionRegistry()
        registry.register(_factory, descriptor=_descriptor("acme"))
        assert registry.resolve("acme") == "acme-instance"

    def test_resolve_forwards_kwargs(self) -> None:
        def factory(**kwargs: object) -> dict[str, object]:
            return kwargs

        registry = ExtensionRegistry()
        registry.register(factory, descriptor=_descriptor("kw"))
        assert registry.resolve("kw", a=1, b="two") == {"a": 1, "b": "two"}

    def test_duplicate_registration_raises_located_value_error(self) -> None:
        registry = ExtensionRegistry()
        registry.register(_factory, descriptor=_descriptor("acme"))
        with pytest.raises(ValueError, match="acme.*replace=True"):
            registry.register(_factory, descriptor=_descriptor("acme"))

    def test_duplicate_registration_allowed_with_replace(self) -> None:
        registry = ExtensionRegistry()
        registry.register(_factory, descriptor=_descriptor("acme"))
        registry.register(_factory, descriptor=_descriptor("acme"), replace=True)
        assert registry.get_descriptor("acme").version == "1.2.0"


class TestUnknownExtension:
    def test_resolve_unknown_lists_available_ids(self) -> None:
        registry = ExtensionRegistry()
        registry.register(_factory, descriptor=_descriptor("acme"))
        with pytest.raises(UnknownExtensionError, match="acme") as exc:
            registry.resolve("nope")
        assert "acme" in str(exc.value)

    def test_get_descriptor_unknown_raises(self) -> None:
        registry = ExtensionRegistry()
        with pytest.raises(UnknownExtensionError, match="none registered"):
            registry.get_descriptor("nope")


class TestDescriptorProvenance:
    def test_descriptor_as_dict_is_json_native(self) -> None:
        descriptor = _descriptor("acme")
        payload = descriptor.as_dict()
        json.dumps(payload)  # must not raise
        assert payload["extension_id"] == "acme"
        assert payload["role"] == "powerflow_backend"
        assert payload["source"] == "core"
        assert payload["contract_version"] == "1"

    def test_descriptor_is_frozen(self) -> None:
        descriptor = _descriptor("acme")
        with pytest.raises(AttributeError):
            descriptor.extension_id = "other"  # type: ignore[misc]


class TestSourceValidation:
    def test_unknown_source_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown source.*expected one of"):
            _descriptor("bad", source="ambient")  # type: ignore[arg-type]

    def test_all_three_sources_are_accepted(self) -> None:
        for source in ("core", "host", "entry_point"):
            descriptor = _descriptor(f"src-{source}", source=source)  # type: ignore[arg-type]
            assert descriptor.source == source


class TestContractVersion:
    def test_unsupported_contract_version_is_rejected(self) -> None:
        registry = ExtensionRegistry()
        with pytest.raises(UnsupportedContractVersionError, match="contract version"):
            registry.register(
                _factory, descriptor=_descriptor("v2", contract_version="2")
            )

    def test_supported_contract_version_is_accepted(self) -> None:
        registry = ExtensionRegistry()
        registry.register(_factory, descriptor=_descriptor("v1", contract_version="1"))
        assert registry.get_descriptor("v1").contract_version == "1"


class TestExtensionProvenance:
    def test_provenance_snapshot_is_json_native_and_sorted(self) -> None:
        registry = ExtensionRegistry()
        registry.register(_factory, descriptor=_descriptor("b"))
        registry.register(_factory, descriptor=_descriptor("a"))
        snapshot = extension_provenance(registry)
        json.dumps(snapshot)
        assert [row["extension_id"] for row in snapshot] == ["a", "b"]
        assert snapshot[0]["source"] == "core"
        assert snapshot[0]["contract_version"] == "1"

    def test_provenance_defaults_to_default_registry(self) -> None:
        # The shared DEFAULT_REGISTRY is empty unless something registers into it;
        # the snapshot is always a JSON-native list.
        snapshot = extension_provenance()
        assert isinstance(snapshot, list)
        json.dumps(snapshot)

    def test_register_extension_writes_into_default_registry(self) -> None:
        from gridalyn.foundation.platform.extensions import (
            DEFAULT_REGISTRY,
            register_extension,
        )

        extension_id = "host-example-13-02"
        register_extension(
            _factory, descriptor=_descriptor(extension_id, source="host")
        )
        assert DEFAULT_REGISTRY.get_descriptor(extension_id).source == "host"
        assert extension_id in [row["extension_id"] for row in extension_provenance()]

    def test_provenance_aggregates_multiple_registries(self) -> None:
        r1, r2 = ExtensionRegistry(), ExtensionRegistry()
        r1.register(_factory, descriptor=_descriptor("r1-x"))
        r2.register(_factory, descriptor=_descriptor("r2-y"))
        snapshot = extension_provenance(r1, r2)
        assert [row["extension_id"] for row in snapshot] == ["r1-x", "r2-y"]


class TestStdlibOnly:
    def test_extensions_module_imports_nothing_from_gridalyn(self) -> None:
        """The engine must stay stdlib-only so foundation stays the bottom layer."""
        import ast
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[1]
        source = (repo_root / "gridalyn/foundation/platform/extensions.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(
                    alias.name.startswith("gridalyn") or alias.name.startswith(".")
                    for alias in node.names
                ), f"extensions.py must not import gridalyn modules: {node.names}"
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, (
                    "extensions.py must not use relative imports (they would "
                    f"pull gridalyn siblings into the stdlib-only module): {node.level}"
                )
                assert not (node.module or "").startswith(
                    "gridalyn"
                ), f"extensions.py must not import gridalyn modules: {node.module}"


# A minimal extension module body following the loader's convention (exposes
# callable ``factory`` + ``descriptor``), written into a temp dir per test.
_EXTENSION_MODULE_BODY = """\
from gridalyn.foundation.platform.extensions import ExtensionDescriptor

descriptor = ExtensionDescriptor(
    extension_id={extension_id!r},
    role="powerflow_backend",
    name="Fixture extension",
    version="1.0.0",
    contract_version="1",
)

def factory():
    return "fixture-instance"
"""


class TestEntryPointDiscovery:
    """Awareness (list) must report without importing any module."""

    def test_list_installed_extensions_reports_without_importing(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        module_name = "acme_awareness_probe"
        _write_module(tmp_path, module_name, "print('IMPORTED')\n")
        record = _entry_point_record("acme-backend", module_name)
        monkeypatch.setattr(
            "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
            lambda group: [record],
        )
        monkeypatch.syspath_prepend(str(tmp_path))

        descriptors = list_installed_extensions()

        assert descriptors[0].extension_id == "acme-backend"
        assert descriptors[0].source == "entry_point"
        assert descriptors[0].entry_point_group == DEFAULT_EXTENSIONS_GROUP
        assert descriptors[0].version == "1.0.0"
        # The roster never imports the module it reports.
        assert module_name not in sys.modules

    def test_list_entry_point_metadata_missing_group_is_empty(self) -> None:
        assert list_entry_point_metadata("gridalyn.definitely_not_a_group") == []

    def test_awareness_and_resolution_are_separate(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """Listing is not resolution: role is unknown until a module loads."""
        module_name = "acme_separation_probe"
        _write_module(
            tmp_path,
            module_name,
            _EXTENSION_MODULE_BODY.format(extension_id="sep-ext"),
        )
        record = _entry_point_record("sep-ext", module_name)
        monkeypatch.setattr(
            "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
            lambda group: [record],
        )
        monkeypatch.syspath_prepend(str(tmp_path))

        descriptors = list_installed_extensions()

        # The roster reports the component without knowing its role — role is
        # only established when a module is loaded (resolution), never listed.
        assert descriptors[0].role == ""
        assert descriptors[0].source == "entry_point"
        assert module_name not in sys.modules


class TestDeclaredOnlyLoading:
    """Resolution imports ONLY the declared IDs, never ambient entries."""

    def _patch_registry(self, monkeypatch: MonkeyPatch) -> ExtensionRegistry:
        fresh = ExtensionRegistry()
        monkeypatch.setattr(
            "gridalyn.foundation.platform.extensions.DEFAULT_REGISTRY", fresh
        )
        return fresh

    def test_load_entry_point_extensions_loads_only_declared(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        module_name = "acme_declared_probe"
        _write_module(
            tmp_path,
            module_name,
            _EXTENSION_MODULE_BODY.format(extension_id="acme-backend"),
        )
        ambient = "acme_ambient_probe"
        _write_module(tmp_path, ambient, "print('AMBIENT')\n")
        records = [
            _entry_point_record("acme-backend", module_name),
            _entry_point_record("ambient-ext", ambient),
        ]
        monkeypatch.setattr(
            "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
            lambda group: records,
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        registry = self._patch_registry(monkeypatch)

        loaded = load_entry_point_extensions(DEFAULT_EXTENSIONS_GROUP, ["acme-backend"])

        assert [d.extension_id for d in loaded] == ["acme-backend"]
        assert loaded[0].source == "entry_point"
        assert loaded[0].entry_point_group == DEFAULT_EXTENSIONS_GROUP
        assert loaded[0].module_hash and len(loaded[0].module_hash) == 64
        # Only the declared module was imported; the ambient one was not.
        assert module_name in sys.modules
        assert ambient not in sys.modules
        assert registry.get_descriptor("acme-backend").source == "entry_point"

    def test_load_unknown_declared_id_is_located(
        self, monkeypatch: MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
            lambda group: [],
        )
        with pytest.raises(UnknownExtensionError) as excinfo:
            load_entry_point_extensions(DEFAULT_EXTENSIONS_GROUP, ["ghost-ext"])
        message = str(excinfo.value)
        assert "ghost-ext" in message
        assert "none registered" in message

    def test_load_module_without_convention_raises(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        module_name = "acme_bad_probe"
        _write_module(tmp_path, module_name, "VALUE = 1\n")
        monkeypatch.setattr(
            "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
            lambda group: [_entry_point_record("bad-ext", module_name)],
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        self._patch_registry(monkeypatch)

        with pytest.raises(ImportError, match="factory"):
            load_entry_point_extensions(DEFAULT_EXTENSIONS_GROUP, ["bad-ext"])

    def test_module_hash_is_content_sensitive(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        module_name = "acme_hash_probe"
        _write_module(
            tmp_path,
            module_name,
            _EXTENSION_MODULE_BODY.format(extension_id="hash-ext"),
        )
        monkeypatch.setattr(
            "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
            lambda group: [_entry_point_record("hash-ext", module_name)],
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        self._patch_registry(monkeypatch)

        first = load_entry_point_extensions(DEFAULT_EXTENSIONS_GROUP, ["hash-ext"])

        # The hash pins "exactly what was loaded": rewriting the module file
        # must change it (the hash re-reads __file__ contents fresh).
        _write_module(
            tmp_path,
            module_name,
            _EXTENSION_MODULE_BODY.format(extension_id="hash-ext") + "\n# v2\n",
        )
        second = load_entry_point_extensions(DEFAULT_EXTENSIONS_GROUP, ["hash-ext"])

        assert first[0].module_hash and len(first[0].module_hash) == 64
        assert first[0].module_hash != second[0].module_hash
