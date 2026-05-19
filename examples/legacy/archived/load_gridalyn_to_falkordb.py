import os
import networkx as nx
from redislite import FalkorDB

import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from create_grid_with_datagen import PowerFlowAnalysisDatagen

from gridalyn.data import datasets

def export_networkx_to_falkordb():
    print("====== Step 1: Generating Grid Topologies ======")
    input_file = str(datasets.get_dataset_path("buildings_inside_polygon.geojson"))

    sim = PowerFlowAnalysisDatagen(input_file=input_file)
    sim.extract_building_data()
    sim.create_grid_graphs()
    
    # Get the unified NetworkX graph representation of the entire topology
    nx_graph = sim.pg_graph.merge_graphs()
    # Also inject building loads into the master export graph!
    nx_graph.update(sim.pg_graph.graph_buildings)
    print(f"\nGrid topology generated successfully (NetworkX):")
    print(f"Total Nodes: {nx_graph.number_of_nodes()}")
    print(f"Total Edges: {nx_graph.number_of_edges()}")

    print("\n====== Step 2: Booting Embedded FalkorDB ======")
    db_path = "examples/generated/outputs/production_twin.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    # Boot the sub-process Redis GraphBLAS engine
    db = FalkorDB(dbfilename=db_path)
    graph = db.select_graph("GridalynTwin")
    print("FalkorDB engine booted and 'GridalynTwin' semantic graph instantiated.")

    print("\n====== Step 3: Pushing Topology to GraphBLAS ======")
    
    # Pre-parse nodes
    from collections import defaultdict
    nodes_by_label = defaultdict(list)
    
    for node_id, data in nx_graph.nodes(data=True):
        cimclass = data.get("cimclass", "cim.ConnectivityNode")
        label = cimclass.split(".")[-1]

        nodes_by_label[label].append({
            "id": str(node_id),
            "cimclass": cimclass,
            "cluster": data.get("cluster", -1),
            "type": data.get("type", "Unknown"),
            "p_mw": float(data.get("p_mw", 0.0)),
            "q_mvar": float(data.get("q_mvar", 0.0)),
        })

    print("Inserting Nodes grouped by label...")
    for label, props in nodes_by_label.items():
        graph.query(f"""
            UNWIND $props AS p
            CREATE (n:{label} {{
                id: p.id, 
                cimclass: p.cimclass, 
                cluster: p.cluster,
                type: p.type,
                p_mw: p.p_mw,
                q_mvar: p.q_mvar
            }})
        """, {"props": props})

    # Pre-parse edges
    edges_by_type = defaultdict(list)
    for src, dst, data in nx_graph.edges(data=True):
        cimclass = data.get("cimclass", "c.ACLineSegment")
        rel_type = "LINE"
        if "Transformer" in cimclass:
            rel_type = "TRANSFORMER_LINK"

        edges_by_type[rel_type].append({
            "src": str(src),
            "dst": str(dst),
            "cimclass": cimclass,
            "length": float(data.get("length", 0.0)),
            "weight": float(data.get("weight", 0.0))
        })

    print("Inserting Edges grouped by type...")
    for rel_type, props in edges_by_type.items():
        graph.query(f"""
            UNWIND $props AS e
            MATCH (source {{id: e.src}})
            MATCH (target {{id: e.dst}})
            CREATE (source)-[r:{rel_type} {{
                cimclass: e.cimclass,
                length: e.length,
                weight: e.weight
            }}]->(target)
        """, {"props": props})

    print("\n====== Summary: GraphBLAS Import Complete ======")
    res_nodes = graph.query("MATCH (n) RETURN count(n)").result_set[0][0]
    res_edges = graph.query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0]
    
    print(f"Nodes successfully loaded into C-Matrix: {res_nodes}")
    print(f"Edges successfully loaded into C-Matrix: {res_edges}")
    
    print("\nExample Query: Count nodes by Label:")
    result = graph.query("""
        MATCH (n)
        RETURN labels(n)[0] AS Node_Type, count(n) AS Total
        ORDER BY Total DESC
    """)
    for record in result.result_set:
        print(f"Label: {record[0]:<15} | Count: {record[1]}")

if __name__ == "__main__":
    export_networkx_to_falkordb()
