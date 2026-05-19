import os
from redislite import FalkorDB

def build_and_query_grid():
    db_path = "examples/generated/outputs/local_falkor.db"
    
    # Clean up previous runs if exists
    if os.path.exists(db_path):
        os.remove(db_path)

    print("Initializing embedded FalkorDBLite process...")
    # 1. Spawn the isolated FalkorDB embedded process
    # This boots a tiny Redis socket under the hood and compiles the GraphBLAS sparse matrices
    db = FalkorDB(dbfilename=db_path)

    # 2. Select or create the 'PowerGrid' graph
    graph = db.select_graph("PowerGrid")

    print("\n--- Generating Topology Operations ---")
    
    # 3. Create topological nodes and edges using openCypher
    # Substation -> MV Feeder -> LV Transformer -> Building Array
    print("Executing Cypher: Building Spatial Topology...")
    graph.query("""
        CREATE (:Substation {name: 'Sub_Alpha', capacity_mva: 25, voltage_kv: 110})
    """)
    
    graph.query("""
        MATCH (s:Substation {name: 'Sub_Alpha'})
        CREATE (s)-[:FEEDER_LINE {impedance: 0.05, max_current_amps: 400}]->
               (t_mv:Transformer {name: 'Trafo_MV1', type: 'MV_LV', capacity_kva: 630})
    """)
    
    # Add a couple of buildings connected to the LV transformer
    graph.query("""
        MATCH (t:Transformer {name: 'Trafo_MV1'})
        CREATE (t)-[:SERVICE_DROP {length_m: 15}]->(:Building {name: 'Bld_101', load_kw: 12.5})
        CREATE (t)-[:SERVICE_DROP {length_m: 22}]->(:Building {name: 'Bld_102', load_kw: 8.2})
        CREATE (t)-[:SERVICE_DROP {length_m: 10}]->(:Building {name: 'Bld_103', load_kw: 15.0})
    """)

    print("Grid topology committed successfully via GraphBLAS sparse matrix mapping.")

    # 4. Perform an analytical lookup: Find downstream load hierarchy
    print("\n--- Analytical Grid Operations ---")
    
    # Query: Match down from Substation all the way to Buildings dynamically
    # *1..5 means "traverse 1 to 5 hops down any edges"
    query = """
    MATCH p=(sub:Substation)-[*1..5]->(b:Building)
    RETURN sub.name AS Substation, 
           b.name AS Building, 
           b.load_kw AS Load_kW,
           length(p) AS HopsDistance
    ORDER BY b.load_kw DESC
    """
    
    print("Executing Deep Traversal Query (Cypher):")
    print(query.strip())
    
    result = graph.query(query)
    
    print("\nResults:")
    print(f"{'Substation':<15} | {'Building':<15} | {'Load (kW)':<10} | {'Hops Distance'}")
    print("-" * 65)
    
    total_load = 0
    for record in result.result_set:
        sub_name = record[0]
        bld_name = record[1]
        load = record[2]
        hops = record[3]
        total_load += load
        print(f"{sub_name:<15} | {bld_name:<15} | {load:<10} | {hops}")
        
    print("-" * 65)
    print(f"Aggregated Downstream Traced Load: {total_load} kW")
    
if __name__ == "__main__":
    build_and_query_grid()
