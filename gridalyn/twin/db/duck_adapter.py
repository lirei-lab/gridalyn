import os
import duckdb
import pandas as pd
import numpy as np
from typing import Optional, List, Dict, Any

class DuckAdapter:
    """
    Manages Bulk Data integration over DuckDB/Parquet (OLAP).
    """
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.conn = duckdb.connect(database=':memory:')

    def query(self, sql: str) -> pd.DataFrame:
        """Executes a pure DuckDB SQL analytical statement and returns a DataFrame."""
        return self.conn.execute(sql).df()

    def get_time_series(self, metric: str = 'baseline') -> np.ndarray:
        """
        Dynamically mounts the massive Parquet file inside DuckDB as a virtual View.
        Performs vector-driven aggregation queries against thousands of spatial realizations.
        """
        if metric == 'baseline':
            file_path = os.path.join(self.data_dir, "substation_baseline_mc.parquet")
        else:
            file_path = os.path.join(self.data_dir, "substation_powerflow_mc.parquet")
            
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Missing Bulk Analytical Matrix: {file_path}")

        return self.conn.execute(f"SELECT * FROM read_parquet('{file_path}')").df().values.T

    def mount_duckpg(self, connection_string: str, mount_name: str = "pg_twin"):
        """
        Activates the `duckpg` strategy - mounting an external live PostgreSQL 
        Asset Information Model stream seamlessly alongside Parquet inside DuckDB engine.
        """
        self.conn.execute("INSTALL postgres;")
        self.conn.execute("LOAD postgres;")
        self.conn.execute(f"ATTACH '{connection_string}' AS {mount_name} (TYPE POSTGRES);")
        return self.conn.execute("SHOW TABLES;").df()
