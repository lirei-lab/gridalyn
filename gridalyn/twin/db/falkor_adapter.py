import os
import networkx as nx
from collections import defaultdict

class FalkorAdapter:
    """
    Manages the Semantic Topology Engine using an embedded FalkorDB process.
    GraphBLAS sparse-matrix technology allows lightning-fast topological path querying.
    """
    
    def __init__(self, db_filepath: str, graph_name: str = "GridalynTwin"):
        self.db_filepath = db_filepath
        self.graph_name = graph_name
        self._db = None
        self._graph = None

    def connect(self):
        """Spawns or connects to the isolated FalkorDB embedded process."""
        from redislite import FalkorDB

        self._db = FalkorDB(dbfilename=self.db_filepath)
        self._graph = self._db.select_graph(self.graph_name)
        return self._graph

    def clear(self):
        """Purges the underlying database strictly for this graph."""
        if os.path.exists(self.db_filepath):
            os.remove(self.db_filepath)

    def import_networkx(self, nx_graph: nx.Graph):
        """
        Parses an arbitrarily complex NetworkX power grid graph and performs 
        batched Cypher injection to translate it into a queryable semantic ontology.
        """
        if self._graph is None:
            self.connect()

        # Ensure an O(1) index exists on GridNode(id) prior to batch injection to prevent quadratic matrix scans!
        try:
            self._graph.query("CREATE INDEX ON :GridNode(id)")
        except Exception:
            pass

        # 1. Parsing Nodes -> Mapping to Semantic Labels
        nodes_by_label = defaultdict(list)
        for node_id, data in nx_graph.nodes(data=True):
            # Resolve exact namespace CIM class if exists, fallback to General
            cimclass = data.get("cimclass", "cim.ConnectivityNode")
            label = cimclass.split(".")[-1]
            
            nodes_by_label[label].append({
                "id": str(node_id),
                "cimclass": cimclass,
                "cluster": data.get("cluster", -1),
                "type": str(data.get("type", "Unknown")),
                "p_mw": float(data.get("p_mw", 0.0) if data.get("p_mw") is not None else 0.0),
                "q_mvar": float(data.get("q_mvar", 0.0) if data.get("q_mvar") is not None else 0.0),
            })

        for label, props in nodes_by_label.items():
            self._graph.query(f"""
                UNWIND $props AS p
                CREATE (n:{label}:GridNode {{
                    id: p.id, 
                    cimclass: p.cimclass, 
                    cluster: p.cluster,
                    type: p.type,
                    p_mw: p.p_mw,
                    q_mvar: p.q_mvar
                }})
            """, {"props": props})

        # 2. Parsing Edges -> Mapping to Relationships
        edges_by_type = defaultdict(list)
        for src, dst, data in nx_graph.edges(data=True):
            cimclass = data.get("cimclass", "c.ACLineSegment")
            # Classify Physical Infrastructure
            rel_type = "LINE"
            if "Transformer" in cimclass:
                rel_type = "TRANSFORMER_LINK"

            edges_by_type[rel_type].append({
                "src": str(src),
                "dst": str(dst),
                "cimclass": cimclass,
                "length": float(data.get("length", 0.0) if data.get("length") is not None else 0.0),
                "weight": float(data.get("weight", 0.0) if data.get("weight") is not None else 0.0)
            })

        for rel_type, props in edges_by_type.items():
            self._graph.query(f"""
                UNWIND $props AS e
                MERGE (source:GridNode {{id: e.src}})
                MERGE (target:GridNode {{id: e.dst}})
                CREATE (source)-[:{rel_type} {{
                    cimclass: e.cimclass,
                    length: e.length,
                    weight: e.weight
                }}]->(target)
            """, {"props": props})

        return self.get_stats()

    def get_stats(self) -> dict:
        """Runs a validation count against the resulting graph matrix."""
        if self._graph is None:
            self.connect()
            
        nodes = self._graph.query("MATCH (n:GridNode) RETURN count(n)").result_set[0][0]
        edges = self._graph.query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0]
        return {"nodes": nodes, "edges": edges}

    def execute_cypher(self, query: str, params: dict = None) -> list:
        if self._graph is None:
            self.connect()
        res = self._graph.query(query, params)
        return res.result_set
