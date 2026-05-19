import os
import sys
import tempfile
from pathlib import Path

# Append the project root physically to resolve imports dynamically
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gridalyn.twin.db.manager import DigitalTwinManager


def test_data_manager_api(tmp_path):
    """Archived smoke demo for the legacy Falkor/DuckDB manager.

    The current dashboard path is `digital_twin/dashboard/catalog.json` plus
    `digital_twin/timeseries`. This demo opts into the old dashboard/public
    export path so accidental production calls do not recreate legacy artifacts.
    """
    print("========== BOOTING DIGITAL TWIN DATABASE MANAGER ==========\n")
    
    # Initialize the project abstract Scope boundaries
    # All semantic queries for 'tr_twin_001' map natively here
    manager = DigitalTwinManager(
        twin_id="tr_twin_001",
        allow_legacy_dashboard_public_export=True,
    )
    
    from examples.tutorials.demo_with_power_flow import PowerFlowAnalysis
    from gridalyn.foundation.data.datasets import get_dataset_path
    
    geojson_path = str(get_dataset_path('buildings_inside_polygon.geojson'))
    sim = PowerFlowAnalysis(input_file=geojson_path, output_dir=str(tmp_path))
    sim.extract_building_data()
    sim.create_grid_graphs()
    
    merged_nx = sim.pg_graph.merge_graphs()
    merged_nx.update(sim.pg_graph.graph_buildings)
    
    # ── 2. Load Topology entirely into FalkorDB GraphBLAS Engine ──
    print("\n--- 2. FalkorDB Adapter Operations ---")
    manager.falkor.clear()  # Ensure pristine DB
    try:
        stats = manager.falkor.import_networkx(merged_nx)
    except Exception as exc:
        if exc.__class__.__name__ in {
            "RedisLiteException",
            "RedisLiteServerStartError",
        }:
            try:
                import pytest
            except ImportError:
                print(f"SKIP: Embedded FalkorDB/redislite backend is unavailable: {exc}")
                return
            pytest.skip(f"Embedded FalkorDB/redislite backend is unavailable: {exc}")
        raise
    print(f"Topology successfully mounted inside Redis Falkor Instance!")
    print(f"Parsed Stats: {stats}")
    
    # Perform a semantic logic Cypher traversal natively ensuring connections function
    res = manager.falkor.execute_cypher("MATCH (s:Substation)-[r]->(t) RETURN s.id, labels(s)[0], type(r)")
    print(f"Cypher Result Sample (Substations -> Feeders):")
    for r in res:
        print(f"   -> {r}")
        
    # ── 3. Bond OLAP bulk traces through DuckDB ──
    print("\n--- 3. DuckDB Parquet Analytics Operations ---")
    # Because we actually generated the Parquet earlier via run_monte_carlo(),
    # the manager automatically knows the simulation filepath globally.
    df_snapshot = manager.fetch_duckdb_timeseries_view()
    
    if df_snapshot is not None:
        print("\nDuckDB Vector Query Sample (Showing realization traces 1-5):")
        print(df_snapshot.head())
        
    # Example duckpg mounting connection strings:
    # manager.mount_external_pg_asset_registry("postgresql://user:pass@localhost:5432/twin_aim")

    # ── 4. Web Push Interface ──
    print("\n--- 4. Dashboard Transfer Serialization ---")
    manager.export_web_snapshot()
    
    # Verify the created dashboard artifact structurally:
    dashboard_public_dir = os.path.join("dashboard", "public", "data", "tr_twin_001")
    if os.path.exists(dashboard_public_dir):
        files = os.listdir(dashboard_public_dir)
        print(f"SUCCESS: Synchronized {len(files)} Twin Files specifically into the internal Dashboard server volume!")
        print(files)
        
if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="gridalyn-twin-manager-") as tmp:
        test_data_manager_api(Path(tmp))
