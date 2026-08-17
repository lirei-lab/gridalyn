import json
import os

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point


def export_pp_to_geojson(net, output_dir: str):
    """
    Exports a pandapower network's spatial nodes and edges to GeoJSON files
    compatible with Kepler.gl and modern GIS tooling.

    Args:
        net: A fully constructed pandapower network.
        output_dir: String output path where the geojson files will be dumped.
    """
    os.makedirs(output_dir, exist_ok=True)

    print("\n====== Exporting Results for Kepler.gl ======")

    bus_details = net.bus
    res_bus = getattr(net, "res_bus", pd.DataFrame(index=bus_details.index))

    # 1. Coordinate Parsing
    if "geo" in bus_details.columns:

        def extract_coords(geo_str):
            try:
                if pd.notna(geo_str):
                    data = json.loads(geo_str.replace("'", '"'))
                    return data.get("coordinates", [0, 0])
            except Exception:
                pass
            return [0, 0]

        coords = bus_details["geo"].apply(extract_coords)
        bus_x = coords.apply(lambda c: c[0])
        bus_y = coords.apply(lambda c: c[1])
    else:
        bus_x = pd.Series(0, index=bus_details.index)
        bus_y = pd.Series(0, index=bus_details.index)

    # 2. Nodes Export
    nodes = []
    for bus_idx in bus_details.index:
        x, y = bus_x.at[bus_idx], bus_y.at[bus_idx]
        vm_pu = res_bus.at[bus_idx, "vm_pu"] if bus_idx in res_bus.index else None
        p_mw = res_bus.at[bus_idx, "p_mw"] if bus_idx in res_bus.index else None
        bus_name = (
            bus_details.at[bus_idx, "name"]
            if bus_idx in bus_details.index
            else str(bus_idx)
        )
        bus_category = "LV" if isinstance(bus_name, str) and "lv_" in bus_name else "MV"

        nodes.append(
            {
                "geometry": Point(y, x),
                "bus_idx": int(bus_idx),
                "name": str(bus_name),
                "category": bus_category,
                "vm_pu": float(vm_pu) if pd.notna(vm_pu) else None,
                "p_mw": float(p_mw) if pd.notna(p_mw) else None,
            }
        )

    nodes_gdf = gpd.GeoDataFrame(nodes, crs="EPSG:4326")
    nodes_out_path = os.path.join(output_dir, "grid_nodes_results.geojson")
    nodes_gdf.to_file(nodes_out_path, driver="GeoJSON")
    print(f"  Exported {len(nodes_gdf)} Nodes to {nodes_out_path}")

    # 3. Edges Export
    lines = []
    res_line = getattr(net, "res_line", pd.DataFrame(index=net.line.index))
    line_details = net.line

    for line_idx in line_details.index:
        from_bus = line_details.at[line_idx, "from_bus"]
        to_bus = line_details.at[line_idx, "to_bus"]
        loading = (
            res_line.at[line_idx, "loading_percent"]
            if line_idx in res_line.index
            else None
        )

        from_bus_name = (
            bus_details.at[from_bus, "name"] if from_bus in bus_details.index else ""
        )
        line_category = (
            "LV" if isinstance(from_bus_name, str) and "lv_" in from_bus_name else "MV"
        )

        p1 = (
            (bus_y.at[from_bus], bus_x.at[from_bus])
            if from_bus in bus_x.index
            else None
        )
        p2 = (bus_y.at[to_bus], bus_x.at[to_bus]) if to_bus in bus_x.index else None

        if p1 and p2:
            lines.append(
                {
                    "geometry": LineString([p1, p2]),
                    "line_idx": int(line_idx),
                    "category": line_category,
                    "loading_percent": float(loading) if pd.notna(loading) else None,
                }
            )

    if lines:
        lines_gdf = gpd.GeoDataFrame(lines, crs="EPSG:4326")
        lines_out_path = os.path.join(output_dir, "grid_lines_results.geojson")
        lines_gdf.to_file(lines_out_path, driver="GeoJSON")
        print(f"  Exported {len(lines_gdf)} Lines to {lines_out_path}")
