import json
import pickle

def main():
    print("Loading network topology cache...")
    with open("outputs/pp_net_cache.pkl", "rb") as f:
        net = pickle.load(f)

    nodes_path = "../dashboard/public/grid_nodes_results.geojson"
    print(f"Patching {nodes_path}...")
    with open(nodes_path) as f:
        nodes = json.load(f)

    for feature in nodes['features']:
        name = feature['properties'].get('name', '')
        feature['properties']['category'] = "LV" if isinstance(name, str) and "lv_" in name else "MV"

    with open(nodes_path, 'w') as f:
        json.dump(nodes, f)

    lines_path = "../dashboard/public/grid_lines_results.geojson"
    print(f"Patching {lines_path}...")
    with open(lines_path) as f:
        lines = json.load(f)

    for feature in lines['features']:
        line_idx = feature['properties']['line_idx']
        from_bus_idx = net.line.at[line_idx, 'from_bus']
        from_name = net.bus.at[from_bus_idx, 'name']
        feature['properties']['category'] = "LV" if isinstance(from_name, str) and "lv_" in from_name else "MV"

    with open(lines_path, 'w') as f:
        json.dump(lines, f)

    print("GeoJSON files updated successfully with MV/LV categories for React.")

if __name__ == "__main__":
    main()
