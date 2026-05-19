import os
import json
import logging
import pandas as pd
import warnings
from typing import Dict, Any

class DashboardExporter:
    """
    Serializes high-density Graph queries and Bulk Data frames into 
    static endpoints so the Frontend UI (e.g. Vite) can mount them seamlessly.

    Deprecated:
        The dashboard now reads `instances/default/digital_twin/dashboard/catalog.json`
        and scenario Parquet files mounted from the default digital-twin
        instance. This exporter is retained only for legacy demos that still
        target `dashboard/public`.
    """
    def __init__(self, public_dir: str = "dashboard/public/data"):
        warnings.warn(
            "DashboardExporter is legacy. Publish dashboard data through "
            "instances/default/digital_twin/dashboard/catalog.json and "
            "instances/default/digital_twin/timeseries instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.public_dir = public_dir

    def export_graph_topology(self, twin_id: str, nodes_res: list, edges_res: list):
        """Dumps topological Graph definitions."""
        out_dir = os.path.join(self.public_dir, twin_id)
        os.makedirs(out_dir, exist_ok=True)
        
        filepath = os.path.join(out_dir, "graph_topology.json")
        payload = {
            "twin_id": twin_id,
            "nodes": [n for n in nodes_res],
            "edges": [e for e in edges_res]
        }
        with open(filepath, "w") as f:
            json.dump(payload, f, indent=2)
        logging.info(f"Dashboard Exporter: Pushed topology -> {filepath}")

    def export_olap_metrics(self, twin_id: str, df: pd.DataFrame, metric_name: str = "baseline"):
        """Dumps aggregate metadata or Time-Series arrays into native .parquet or .json."""
        out_dir = os.path.join(self.public_dir, twin_id)
        os.makedirs(out_dir, exist_ok=True)
        
        filepath = os.path.join(out_dir, f"{metric_name}_metrics.json")
        df.to_json(filepath, orient="records")
        logging.info(f"Dashboard Exporter: Pushed OLAP view -> {filepath}")
