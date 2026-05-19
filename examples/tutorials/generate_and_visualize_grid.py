import json
import os
import tempfile

from gridalyn.adapters.geojson import FakeGeoJSONGenerator
from gridalyn.twin.core.graph import PowerGridGraph
from gridalyn.interfaces.viz.interactive import GridPlotter

# Create sample building data using FakeGeoJSONGenerator
generator = FakeGeoJSONGenerator(grid_size=32)
geojson = generator.generate_geojson()

# Save the generated GeoJSON data to a temporary file
with tempfile.NamedTemporaryFile(mode="w", suffix=".geojson", delete=False) as f:
    json.dump(geojson, f)
    temp_geojson_path = f.name

# Initialize the PowerGridGraph class, which is used to create and manage the power grid
power_grid = PowerGridGraph()

# Extract building data (centroids and areas) from the GeoJSON file
# This data is used to create the power grid
building_data = power_grid.extract_building_centers_and_areas(temp_geojson_path)

# Create the Low Voltage (LV) network
# This method creates the LV part of the power grid, connecting buildings to transformers
power_grid.create_lv_graph(
    max_load_per_building=10,  # 10 kW per building
    mv_lv_transformer_capacity=400,  # 400 kVA per transformer
)

# Initialize the GridPlotter class for visualization
# This class is used to create a map of the power grid
plotter = GridPlotter(power_grid)

# Create a map with all layers (LV, MV, HV) and save it to an HTML file
# This method creates a map with all the layers of the power grid and saves it to an HTML file
map_all = plotter.plot_building_and_centroid_graph(
    plot_lv_edges=True, plot_mv_edges=True, plot_hv_edges=True
)
# Create output directory if it doesn't exist
output_dir = "examples/generated/outputs"
os.makedirs(output_dir, exist_ok=True)

map_all.save(os.path.join(output_dir, "grid_all_layers.html"))
