import argparse
import json
import random
from typing import Any, Dict, List, Optional

import numpy as np


class FakeGeoJSONGenerator:
    """
    Generates a fake GeoJSON FeatureCollection of buildings in a grid layout.
    """

    def __init__(
        self,
        grid_size: int = 32,
        seed: Optional[int] = None,
        irregularity: float = 0.3,
        min_size_variance: float = 0.8,
        max_size_variance: float = 1.5,
        rectangular: bool = False,
    ) -> None:
        """Initialize generator with configurable grid size
        Args:
            grid_size: Number of buildings per side (e.g. 32 creates 32x32=1024 buildings)
            seed: Seed for the random number generator for reproducibility.
            irregularity: Control the irregularity of the building shapes (0 for rectangular,
                          higher values for more irregular).
            min_size_variance: Minimum multiplier for building size.
            max_size_variance: Maximum multiplier for building size.
            rectangular: If True, generates rectangular buildings with no irregularity.
        """
        if seed is not None:
            random.seed(seed)
        # Base coordinates (Quebec City area)
        self.base_lon: float = -72.6
        self.irregularity: float = irregularity
        self.base_lat: float = 46.34
        self.min_size_variance: float = min_size_variance
        self.max_size_variance: float = max_size_variance
        self.rectangular: bool = rectangular
        if self.rectangular:
            self.irregularity = 0
        # Convert desired meters to degrees using proper scaling
        meters_per_deg_lat: float = 111000  # 1° latitude = 111 km
        meters_per_deg_lon: float = 111000 * np.cos(
            np.radians(self.base_lat)
        )  # Adjust for latitude
        # Convert meters to degrees
        self.block_size_lat: float = (
            33 / meters_per_deg_lat
        )  # 33 meters between buildings
        self.block_size_lon: float = 33 / meters_per_deg_lon
        self.street_width_lat: float = 11 / meters_per_deg_lat  # 11 meters for streets
        self.street_width_lon: float = 11 / meters_per_deg_lon
        self.building_size_lat: float = 11 / meters_per_deg_lat  # 11 meters per side
        self.building_size_lon: float = 11 / meters_per_deg_lon
        self.position_variance_lat: float = (
            2 / meters_per_deg_lat
        )  # 2 meters random variance
        self.position_variance_lon: float = 2 / meters_per_deg_lon
        self.grid_size: int = grid_size

    def generate_building(self, x: int, y: int, building_id: int) -> Dict[str, Any]:
        """Generate a building polygon in a grid layout"""
        # Calculate building position with streets using proper scaling
        x_offset: float = random.uniform(
            -self.position_variance_lon, self.position_variance_lon
        )
        y_offset: float = random.uniform(
            -self.position_variance_lat, self.position_variance_lat
        )
        lon: float = (
            self.base_lon + x * (self.block_size_lon + self.street_width_lon) + x_offset
        )
        lat: float = (
            self.base_lat + y * (self.block_size_lat + self.street_width_lat) + y_offset
        )

        # Add random variation to building size
        size_variance: float = random.uniform(
            self.min_size_variance, self.max_size_variance
        )
        building_size_lat: float = self.building_size_lat * size_variance
        building_size_lon: float = self.building_size_lon * size_variance

        # Create a building polygon
        coordinates: List[List[float]] = []
        if self.rectangular:
            # Generate rectangular building
            coordinates = [
                [lon, lat],
                [lon + building_size_lon, lat],
                [lon + building_size_lon, lat + building_size_lat],
                [lon, lat + building_size_lat],
                [lon, lat],
            ]
        else:
            # Generate building with random vertices
            num_vertices: int = random.randint(4, 8)
            center_lon: float = lon + building_size_lon / 2
            center_lat: float = lat + building_size_lat / 2

            coordinates = [
                [
                    center_lon
                    + random.uniform(0.8, 1.2)
                    * (building_size_lon / 2)
                    * np.cos(2 * np.pi * i / num_vertices)
                    * (1 + random.uniform(-self.irregularity, self.irregularity)),
                    center_lat
                    + random.uniform(0.8, 1.2)
                    * (building_size_lat / 2)
                    * np.sin(2 * np.pi * i / num_vertices)
                    * (1 + random.uniform(-self.irregularity, self.irregularity)),
                ]
                for i in range(num_vertices)
            ]
            coordinates.append(coordinates[0])  # Close the polygon

        return {
            "type": "Feature",
            "properties": {"id": building_id, "type": "building"},
            "geometry": {"type": "Polygon", "coordinates": [coordinates]},
        }

    def generate_geojson(self) -> Dict[str, Any]:
        """Generate a GeoJSON FeatureCollection with neighborhood features"""
        features: List[Dict[str, Any]] = []

        # Generate buildings in a grid with random offsets
        building_id: int = 0
        for x in range(self.grid_size):
            for y in range(self.grid_size):
                features.append(self.generate_building(x, y, building_id))
                building_id += 1

        return {
            "type": "FeatureCollection",
            "name": "buildings_inside_polygon",
            "crs": {
                "type": "name",
                "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
            },
            "features": features,
        }

    def save_to_file(self, file_path: str) -> None:
        """Save generated GeoJSON to file"""
        geojson: Dict[str, Any] = self.generate_geojson()
        with open(file_path, "w") as f:
            f.write(
                json.dumps(
                    {
                        "type": "FeatureCollection",
                        "name": "buildings_inside_polygon",
                        "crs": geojson["crs"],
                    }
                )
                + "\n"
            )
            f.write('{"features": [\n')
            for i, feature in enumerate(geojson["features"]):
                f.write(json.dumps(feature))
                if i < len(geojson["features"]) - 1:
                    f.write(",\n")
                else:
                    f.write("\n")
            f.write("]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a fake GeoJSON file.")
    parser.add_argument(
        "--grid_size",
        type=int,
        default=32,
        help="Number of buildings per side (e.g., 32 creates 32x32=1024 buildings)",
    )
    args = parser.parse_args()

    # Example usage
    generator = FakeGeoJSONGenerator(grid_size=args.grid_size)
    generator.save_to_file("fake_buildings.geojson")
