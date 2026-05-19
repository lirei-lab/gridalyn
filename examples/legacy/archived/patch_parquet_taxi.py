import duckdb
import pickle
import pandas as pd
import os

def main():
    print("Loading network topology cache...")
    with open("outputs/pp_net_cache.pkl", "rb") as f:
        net = pickle.load(f)

    # DataFrame mapping: bus_idx -> category
    categories = []
    for idx in net.bus.index:
        name = net.bus.at[idx, 'name']
        category = "LV" if isinstance(name, str) and "lv_" in name else "MV"
        categories.append({'bus_idx': int(idx), 'category': category})

    df_cat_nodes = pd.DataFrame(categories)

    # DataFrame mapping: line_idx -> category based on string substring origin
    line_categories = []
    for idx in net.line.index:
        from_bus_idx = net.line.at[idx, 'from_bus']
        from_name = net.bus.at[from_bus_idx, 'name']
        category = "LV" if isinstance(from_name, str) and "lv_" in from_name else "MV"
        line_categories.append({'line_idx': int(idx), 'category': category})
        
    df_cat_lines = pd.DataFrame(line_categories)

    con = duckdb.connect()

    # 1. Patch Nodes Parquet
    nodes_parquet = "outputs/kepler_timeseries_nodes.parquet"
    new_nodes_parquet = "../dashboard/public/kepler_timeseries_nodes.parquet"
    
    # Ensure public folder exists
    os.makedirs("../dashboard/public", exist_ok=True)

    print("Patching Nodes Parquet to Dashboard Public...")
    con.execute(f"""
        COPY (
            SELECT t.*, c.category 
            FROM '{nodes_parquet}' as t
            LEFT JOIN df_cat_nodes as c ON t.bus_idx = c.bus_idx
        ) TO '{new_nodes_parquet}' (FORMAT 'parquet', COMPRESSION 'snappy');
    """)

    # 2. Patch Lines Parquet
    lines_parquet = "outputs/kepler_timeseries_lines.parquet"
    new_lines_parquet = "../dashboard/public/kepler_timeseries_lines.parquet"

    print("Patching Lines Parquet to Dashboard Public...")
    con.execute(f"""
        COPY (
            SELECT t.*, c.category 
            FROM '{lines_parquet}' as t
            LEFT JOIN df_cat_lines as c ON t.line_idx = c.line_idx
        ) TO '{new_lines_parquet}' (FORMAT 'parquet', COMPRESSION 'snappy');
    """)

    print("Successfully injected MV/LV taxonomy into into public DuckDB compressed files!")

if __name__ == "__main__":
    main()
