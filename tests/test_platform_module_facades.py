import importlib
import unittest


class PlatformModuleFacadeTest(unittest.TestCase):
    def test_seven_platform_modules_are_importable(self):
        for module_name in [
            "gridalyn.foundation",
            "gridalyn.twin",
            "gridalyn.assets",
            "gridalyn.simulation",
            "gridalyn.operations",
            "gridalyn.projects",
            "gridalyn.interfaces",
        ]:
            with self.subTest(module_name=module_name):
                self.assertIsNotNone(importlib.import_module(module_name))

    def test_foundation_facade_exposes_governance_and_artifact_contracts(self):
        from gridalyn import foundation

        self.assertTrue(hasattr(foundation, "ModelVersion"))
        self.assertTrue(hasattr(foundation, "StudyRun"))
        self.assertTrue(hasattr(foundation, "ReportMetadata"))
        self.assertTrue(hasattr(foundation, "check_artifact_policy"))
        self.assertTrue(hasattr(foundation, "validate_workspace"))

    def test_twin_facade_exposes_network_adapter_and_semantic_contracts(self):
        from gridalyn import twin

        self.assertTrue(hasattr(twin, "NetworkModelRepository"))
        self.assertTrue(hasattr(twin, "NetworkModel"))
        self.assertTrue(hasattr(twin, "NetworkSnapshot"))
        self.assertTrue(hasattr(twin, "build_semantic_graph"))
        self.assertTrue(hasattr(twin, "validate_semantic_graph"))

    def test_assets_facade_exposes_model_generation_contracts(self):
        from gridalyn import assets

        self.assertTrue(hasattr(assets, "build_synthetic_network_from_geojson"))
        self.assertTrue(hasattr(assets, "SyntheticNetworkBuildResult"))
        self.assertTrue(hasattr(assets, "build_asset_registry"))
        self.assertTrue(hasattr(assets, "synthesize_building_model_tables"))
        self.assertTrue(hasattr(assets, "build_thermal_forecast"))

    def test_simulation_facade_exposes_powerflow_and_network_impact_contracts(self):
        from gridalyn import simulation

        self.assertTrue(hasattr(simulation, "PandapowerGridBuilder"))
        self.assertTrue(hasattr(simulation, "MonteCarloSimulationManager"))
        self.assertTrue(hasattr(simulation, "build_network_impact_catalog"))
        self.assertTrue(hasattr(simulation, "build_provider_impact_predictions"))
        self.assertTrue(hasattr(simulation, "predict_physics_impact"))

    def test_operations_facade_exposes_market_and_operation_contracts(self):
        from gridalyn import operations

        self.assertTrue(hasattr(operations, "OperationRun"))
        self.assertTrue(hasattr(operations, "build_operation_run"))
        self.assertTrue(hasattr(operations, "run_flexibility_clearing_operation"))
        self.assertTrue(hasattr(operations, "build_operational_kpi_report"))
        self.assertTrue(hasattr(operations, "build_locational_clearing"))
        self.assertTrue(hasattr(operations, "build_provider_registry"))
        self.assertTrue(hasattr(operations, "write_locational_clearing_outputs"))

    def test_projects_facade_exposes_project_and_workflow_contracts(self):
        from gridalyn import projects

        self.assertTrue(hasattr(projects, "StudyProject"))
        self.assertTrue(hasattr(projects, "WorkflowSpec"))
        self.assertTrue(hasattr(projects, "init_project"))
        self.assertTrue(hasattr(projects, "load_project"))
        self.assertTrue(hasattr(projects, "load_workflow"))
        self.assertTrue(hasattr(projects, "project_verify_all"))
        self.assertTrue(hasattr(projects, "validate_project_file"))

    def test_interfaces_facade_exposes_cli_report_dashboard_and_graph_contracts(self):
        from gridalyn import interfaces

        self.assertTrue(hasattr(interfaces, "gridalyn_main"))
        self.assertTrue(hasattr(interfaces, "build_dashboard_catalog"))
        self.assertTrue(hasattr(interfaces, "write_dashboard_catalog"))
        self.assertTrue(hasattr(interfaces, "FederatedGraphAdapter"))
        self.assertTrue(hasattr(interfaces, "GridPlotter"))


if __name__ == "__main__":
    unittest.main()
