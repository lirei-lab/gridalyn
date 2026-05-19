import sys
import unittest
from unittest.mock import mock_open, patch

from examples.tutorials import create_grid_with_datagen_parallel
from gridalyn.workflows.scripts import sync_dashboard_public_from_digital_twin


class LegacyDashboardPublicGuardsTest(unittest.TestCase):
    def test_datagen_parallel_runs_without_legacy_dashboard_export(self):
        with (
            patch.object(create_grid_with_datagen_parallel, "datasets") as datasets,
            patch.object(create_grid_with_datagen_parallel, "MonteCarloSimulationManager") as manager_cls,
            patch("builtins.open", mock_open(read_data='{"simulation": {"n_realizations": 2, "resolution_minutes": 15}}')),
        ):
            datasets.get_dataset_path.return_value = "demo_buildings.geojson"
            manager = manager_cls.return_value

            create_grid_with_datagen_parallel.main([])

        manager.run_monte_carlo.assert_called_once_with(
            n_realizations=2,
            resolution_minutes=15,
        )
        manager_cls.assert_called_once()

    def test_sync_requires_legacy_opt_in(self):
        with patch.object(sys, "argv", ["sync_dashboard_public_from_digital_twin.py"]):
            with self.assertRaises(SystemExit) as ctx:
                sync_dashboard_public_from_digital_twin.main()

        self.assertIn("Refusing to write dashboard/public", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
