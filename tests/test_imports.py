import unittest

from gridalyn import interfaces, simulation, twin
from gridalyn.interfaces.viz.interactive import GridPlotter
from gridalyn.twin.core.graph import PowerGridGraph


class TestImports(unittest.TestCase):
    def test_internal_power_grid_creation(self) -> None:
        """Low-level graph builder remains available from its owning module."""
        grid = PowerGridGraph()
        self.assertIsInstance(grid, PowerGridGraph)

    def test_grid_plotter_creation(self) -> None:
        """Test creation of GridPlotter instance"""
        grid = PowerGridGraph()
        plotter = GridPlotter(grid)
        self.assertIsInstance(plotter, GridPlotter)

    def test_gridalyn_namespace_imports_current_sdk_modules(self) -> None:
        """Gridalyn is the canonical public namespace."""
        self.assertTrue(hasattr(twin, "NetworkModelRepository"))
        self.assertTrue(hasattr(simulation, "build_synthetic_network_from_geojson"))
        self.assertTrue(hasattr(interfaces, "GridPlotter"))


if __name__ == "__main__":
    unittest.main()
