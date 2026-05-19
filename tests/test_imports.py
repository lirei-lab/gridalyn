import unittest

from gridalyn import PowerGridGraph
from gridalyn.viz.interactive import GridPlotter
from gridalyn import PowerGridGraph as GridalynPowerGridGraph
from gridalyn.viz.interactive import GridPlotter as GridalynGridPlotter


class TestImports(unittest.TestCase):
    def test_power_grid_creation(self) -> None:
        """Test creation of PowerGridGraph instance"""
        grid = PowerGridGraph()
        self.assertIsInstance(grid, PowerGridGraph)

    def test_grid_plotter_creation(self) -> None:
        """Test creation of GridPlotter instance"""
        grid = PowerGridGraph()
        plotter = GridPlotter(grid)
        self.assertIsInstance(plotter, GridPlotter)

    def test_gridalyn_namespace_imports_current_sdk(self) -> None:
        """Gridalyn is the canonical public namespace."""
        grid = GridalynPowerGridGraph()
        plotter = GridalynGridPlotter(grid)

        self.assertIsInstance(grid, GridalynPowerGridGraph)
        self.assertIsInstance(plotter, GridalynGridPlotter)


if __name__ == "__main__":
    unittest.main()
