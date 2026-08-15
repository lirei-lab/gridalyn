"""Unit tests for the generic extension engine (foundation/platform/extensions.py)."""

from __future__ import annotations

import json

import pytest

from gridalyn.foundation.platform.extensions import (
    ExtensionDescriptor,
    ExtensionRegistry,
    UnknownExtensionError,
    UnsupportedContractVersionError,
    extension_provenance,
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
                assert not (node.module or "").startswith(
                    "gridalyn"
                ), f"extensions.py must not import gridalyn modules: {node.module}"
