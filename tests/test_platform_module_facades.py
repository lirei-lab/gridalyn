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
        # NetworkSnapshot was merged into NetworkModel (plan 11-01). The facade
        # entry for it is stale until plan 11-06 consolidates the export maps;
        # the name must not resolve either way.
        self.assertFalse(hasattr(twin, "NetworkSnapshot"))
        self.assertTrue(hasattr(twin, "SemanticGraphRepository"))
        self.assertTrue(hasattr(twin, "build_semantic_graph"))
        self.assertTrue(hasattr(twin, "validate_semantic_graph"))
        self.assertFalse(hasattr(twin, "FederatedGraphAdapter"))

    def test_assets_facade_exposes_model_generation_contracts(self):
        from gridalyn import assets

        self.assertTrue(hasattr(assets, "build_asset_registry"))
        self.assertTrue(hasattr(assets, "synthesize_building_model_tables"))
        self.assertTrue(hasattr(assets, "build_thermal_forecast"))
        self.assertTrue(hasattr(assets, "TransformerThermalModel"))

    def test_simulation_facade_exposes_powerflow_and_network_impact_contracts(self):
        from gridalyn import simulation

        self.assertTrue(hasattr(simulation, "PandapowerGridBuilder"))
        self.assertTrue(hasattr(simulation, "build_synthetic_network_from_geojson"))
        self.assertTrue(hasattr(simulation, "build_synthetic_network_from_config"))
        self.assertTrue(hasattr(simulation, "build_radial_pandapower_feeder"))
        self.assertTrue(hasattr(simulation, "build_voltage_control_feeder"))
        self.assertTrue(hasattr(simulation, "apply_pv_generation_to_pandapower"))
        self.assertTrue(hasattr(simulation, "SyntheticNetworkBuildResult"))
        self.assertTrue(hasattr(simulation, "build_network_impact_catalog"))
        self.assertTrue(hasattr(simulation, "build_provider_impact_predictions"))
        self.assertTrue(hasattr(simulation, "predict_physics_impact"))
        self.assertFalse(hasattr(simulation, "MonteCarloSimulationManager"))
        self.assertFalse(hasattr(simulation, "PowerflowMonteCarloRunner"))
        self.assertFalse(hasattr(simulation, "export_timeseries_to_kepler_parquet"))

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
        self.assertTrue(hasattr(interfaces, "GridPlotter"))
        self.assertFalse(hasattr(interfaces, "FederatedGraphAdapter"))

    def test_root_facade_keeps_low_level_builders_internal(self):
        import gridalyn

        self.assertTrue(hasattr(gridalyn, "assets"))
        self.assertTrue(hasattr(gridalyn, "simulation"))
        self.assertTrue(hasattr(gridalyn, "twin"))
        self.assertFalse(hasattr(gridalyn, "PowerGridGraph"))


if __name__ == "__main__":
    unittest.main()
