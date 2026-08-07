"""Gate: the semantic CLI needs no falkordb (Phase 9, finding G13)."""

from __future__ import annotations

import importlib
import sys
import unittest


class _BlockFalkordbFinder:
    """A meta-path finder that makes ``falkordb`` unimportable."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "falkordb" or fullname.startswith("falkordb."):
            raise ImportError("falkordb blocked for test")
        return None


class SemanticCliNoFalkordbTest(unittest.TestCase):
    """The semantic build/validate pipeline is parquet-only; no falkordb gate."""

    def test_semantic_capability_removed_from_map(self) -> None:
        from gridalyn.foundation.platform.capabilities import (
            OPTIONAL_CAPABILITY_MODULES,
        )

        self.assertNotIn("semantic", OPTIONAL_CAPABILITY_MODULES)

    def test_semantic_cli_imports_with_falkordb_blocked(self) -> None:
        sys.meta_path.insert(0, _BlockFalkordbFinder())
        try:
            # The hider is live: importing falkordb must fail. If the semantic
            # CLI needed falkordb, the import below would raise.
            with self.assertRaises(ImportError):
                importlib.import_module("falkordb")

            import gridalyn.interfaces.cli.semantic as semantic

            for command in ("build", "validate"):
                args = semantic.parse_args([command])[0]
                self.assertEqual(args.command, command)
                self.assertTrue(callable(args.handler))
        finally:
            sys.meta_path.pop(0)

    def test_require_semantic_is_an_unknown_capability(self) -> None:
        from gridalyn.foundation.platform.capabilities import require_capabilities

        with self.assertRaises(KeyError):
            require_capabilities("semantic")


if __name__ == "__main__":
    unittest.main()
