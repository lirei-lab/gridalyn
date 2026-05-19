import os
import warnings
import networkx as nx

from gridalyn.twin.db.falkor_adapter import FalkorAdapter
from gridalyn.twin.db.duck_adapter import DuckAdapter
from gridalyn.twin.db.dashboard_sync import DashboardExporter

class DigitalTwinManager:
    """
    Project Scope Manager for massive Power Grid Digital Twins.
    Links abstract mathematical Graph representations (FalkorDB) directly 
    to vectorized time-series Simulation Matrices (DuckDB/Parquet).

    Deprecated:
        The canonical digital-twin contract now lives under `digital_twin/`.
        This manager is kept only for legacy Falkor/DuckDB experiments and
        should not be used to publish dashboard data or canonical twin state.
    """

    def __init__(
        self,
        twin_id: str,
        gridalyn_root: str = ".",
        allow_legacy_dashboard_public_export: bool = False,
    ):
        warnings.warn(
            "DigitalTwinManager is legacy. Use digital_twin/{base,scenarios,timeseries,"
            "semantic,reports} artifacts and gridalyn.twin.db.federated_graph_adapter "
            "for current workflows.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.twin_id = twin_id
        self.allow_legacy_dashboard_public_export = allow_legacy_dashboard_public_export
        
        # Dedicated persistent local database directory for legacy experiments.
        # Keep it out of tracked `data/`; canonical twin artifacts live in `digital_twin/`.
        self.scope_dir = os.path.join(gridalyn_root, ".cache", "twins", self.twin_id)
        os.makedirs(self.scope_dir, exist_ok=True)
        
        # FalkorDB Engine configuration using the robust embedded mode
        self.db_filepath = os.path.join(self.scope_dir, f"{self.twin_id}_falkor.db")
        self.falkor = FalkorAdapter(db_filepath=self.db_filepath, graph_name=self.twin_id)

        # Legacy DuckDB pipeline. Current dashboard flows read `digital_twin/timeseries`
        # directly through the scenario catalog instead.
        self.simulation_dir = os.path.join(gridalyn_root, "paper", "data")
        self.duck = DuckAdapter(data_dir=self.simulation_dir)

        # Unified Frontend Sync API
        self.exporter = DashboardExporter(
            public_dir=os.path.join(gridalyn_root, "dashboard", "public", "data")
        )

    def synchronize_topology(self, raw_networkx_graph: nx.Graph) -> dict:
        """
        Extracts structural asset information directly from native Generation 
        routines, dropping them deeply into the compiled Falkor Cypher matrix.
        """
        print(f"[{self.twin_id}] Syncing Topology into FalkorDB GraphBLAS instance...")
        stats = self.falkor.import_networkx(raw_networkx_graph)
        print(f"[{self.twin_id}] Successful Import! Elements: {stats}")
        return stats

    def fetch_duckdb_timeseries_view(self) -> type:
        """
        Executes OLAP logic to pull physical baseline metadata out of massive Parquet stores.
        Dynamically filters purely against elements mapped inside Falkor if necessary.
        """
        print(f"[{self.twin_id}] Spawning DuckDB Context across massive Parquet slices...")
        
        try:
            # Execute standard baseline fetching across the entire MC matrix
            sql = f"SELECT * FROM read_parquet('{os.path.join(self.simulation_dir, 'substation_baseline_mc.parquet')}') LIMIT 10"
            df = self.duck.query(sql)
            print(f"[{self.twin_id}] DuckDB successfully scanned and parsed simulation arrays (Preview: {df.shape})")
            return df
        except Exception as e:
            print(f"[{self.twin_id}] Missing Parquet matrices. Have you successfully executed run_monte_carlo() ? -> Exception: {e}")
            return None

    def mount_external_pg_asset_registry(self, postgres_connection: str):
        """
        Uses duckpg explicitly to query active PG production asset databases alongside 
        our analytical OLAP `.parquet` timeseries engine inside identical SQL frames.
        """
        print(f"[{self.twin_id}] Activating `duckpg` Integration over Postgres Streams!")
        try:
            res = self.duck.mount_duckpg(postgres_connection)
            print(f"[{self.twin_id}] Successfully bonded DuckDB memory space exactly against external PostgreSQL Database.")
            return res
        except Exception as e:
            print(f"[{self.twin_id}] DuckPG Extension explicitly failed mapping: {e}")
            return None

    def export_web_snapshot(self):
        """
        Dumps the latest structural matrices and timeseries evaluations directly to 
        static dashboard/.json structures, satisfying the Front-End Vite logic 
        without needing a FastAPI backend running persistently!
        """
        if not self.allow_legacy_dashboard_public_export:
            raise RuntimeError(
                "DigitalTwinManager.export_web_snapshot is legacy and would write "
                "dashboard/public/data. Current dashboards should consume "
                "digital_twin/dashboard/catalog.json plus digital_twin/timeseries. "
                "Pass allow_legacy_dashboard_public_export=True only for archived demos."
            )
        print(f"[{self.twin_id}] Serializing entire project scope out toward the external Dashboard...")
        
        # Pull minimal semantic topology logic out of FalkorDB
        node_res = self.falkor.execute_cypher("MATCH (n:GridNode) RETURN n.id, n.cimclass, labels(n)[0] LIMIT 100")
        edge_res = self.falkor.execute_cypher("MATCH (s)-[r]->(d) RETURN s.id, d.id, type(r) LIMIT 100")
        
        nodes = [{"id": row[0], "cimclass": row[1], "type": row[2]} for row in node_res]
        edges = [{"src": row[0], "dst": row[1], "type": row[2]} for row in edge_res]
        
        self.exporter.export_graph_topology(self.twin_id, nodes, edges)
        
        # Serialize OLAP views
        duck_df = self.fetch_duckdb_timeseries_view()
        if duck_df is not None:
            self.exporter.export_olap_metrics(self.twin_id, duck_df)
            
        print(f"[{self.twin_id}] Legacy snapshot exported into 'dashboard/public/data/{self.twin_id}'.")
