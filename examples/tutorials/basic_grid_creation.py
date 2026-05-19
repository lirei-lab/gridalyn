"""
Basic example demonstrating how to create and visualize a power grid using gpower.

This example shows how to:
1. Generate sample building data using FakeGeoJSONGenerator
2. Create a hierarchical power grid with LV, MV, and HV networks
3. Visualize the grid using GridPlotter
"""

import json
import os
import tempfile

from gridalyn.adapters.geojson import FakeGeoJSONGenerator
from gridalyn.twin.core.graph import PowerGridGraph
from gridalyn.interfaces.viz.interactive import GridPlotter


def main() -> None:
    # Create sample building data (32x32 grid = 1024 buildings)
    print("Generating sample building data...")
    generator = FakeGeoJSONGenerator(grid_size=32)
    geojson = generator.generate_geojson()

    # Save to temporary file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".geojson", delete=False) as f:
        json.dump(geojson, f)
        temp_geojson_path = f.name
        print(f"Saved sample GeoJSON to: {temp_geojson_path}")

    # Initialize PowerGridGraph
    power_grid = PowerGridGraph()

    # Extract building data
    print("\nExtracting building data...")
    building_data = power_grid.extract_building_centers_and_areas(temp_geojson_path)

    print(f"Successfully extracted data for {len(building_data)} buildings")
    print(
        f"Total building area: {building_data['Area (sq. meters)'].sum():.2f} sq. meters"
    )
    print(
        f"Average building area: {building_data['Area (sq. meters)'].mean():.2f} sq. meters"
    )

    # Create grid hierarchy
    # Total load: 1024 buildings * 10 kW = 10.24 MW
    print("\nCreating grid hierarchy...")

    # Create LV network
    # Each LV transformer serves ~40 buildings (400 kW load)
    print("Creating LV network...")
    power_grid.create_lv_graph(
        max_load_per_building=10,  # 10 kW per building
        mv_lv_transformer_capacity=400,  # 400 kVA per transformer
    )
    print(
        f"Created LV network with "
        f"{len(power_grid.graph_lv_buses) if power_grid.graph_lv_buses is not None else 0} "
        f"buses"
    )

    # Create MV network
    # Each MV transformer serves ~10 LV transformers (4 MW load)
    print("\nCreating MV network...")
    power_grid.create_mv_graph(
        mv_lv_transformer_capacity=400,  # 400 kVA per LV transformer
        hv_mv_transformer_capacity=5000,  # 5 MVA per MV transformer
    )
    print(
        f"Created MV network with "
        f"{len(power_grid.graph_mv_buses) if power_grid.graph_mv_buses is not None else 0} "
        f"buses"
    )

    # Create HV network
    # HV network serves all MV transformers
    print("\nCreating HV network...")
    power_grid.create_hv_substation_graph(
        hv_mv_transformer_capacity=5000,  # 5 MVA per MV transformer
        hv_substation_capacity=15000,  # 15 MVA total HV capacity
    )
    print(
        f"Created HV network with "
        f"{len(power_grid.graph_hv_buses) if power_grid.graph_hv_buses is not None else 0} "
        f"buses"
    )

    # Create building graph
    print("\nCreating building graph...")
    power_grid.create_building_graph()
    print(
        f"Created building graph with "
        f"{len(power_grid.graph_buildings) if power_grid.graph_buildings is not None else 0} "
        f"nodes"
    )

    # Create plotter
    print("\nCreating visualization...")
    plotter = GridPlotter(power_grid)

    # Create map with all layers
    print("Creating map with all layers...")
    map_all = plotter.plot_building_and_centroid_graph(
        plot_lv_edges=True, plot_mv_edges=True, plot_hv_edges=True
    )
    output_dir = "examples/generated/outputs"
    os.makedirs(output_dir, exist_ok=True)

    map_all_path = os.path.join(output_dir, "grid_all_layers.html")
    map_all.save(map_all_path)
    print(f"Saved map with all layers to: {map_all_path}")

    # Create map with only HV and MV layers
    print("\nCreating map with only HV and MV layers...")
    map_hv_mv = plotter.plot_building_and_centroid_graph(
        plot_lv_edges=False, plot_mv_edges=True, plot_hv_edges=True
    )
    map_hv_mv_path = os.path.join(output_dir, "grid_hv_mv_layers.html")
    map_hv_mv.save(map_hv_mv_path)
    print(f"Saved map with HV/MV layers to: {map_hv_mv_path}")

    print("\nDone! Open the HTML files in a web browser to view the visualizations:")
    print(f"- {map_all_path}")
    print(f"- {map_hv_mv_path}")


if __name__ == "__main__":
    main()
