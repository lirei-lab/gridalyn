"""
Main GeoProcessor class for handling GeoJSON data in powergeo.

This module provides the GeoProcessor class which:
- Loads and validates GeoJSON data
- Processes building geometries
- Calculates areas and centroids
- Converts data to pandas DataFrame
"""

import json
import os
from typing import Any, Dict, List, Optional, Tuple, Union

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Polygon

from .utils import extract_building_data, validate_geojson


class GeoProcessor:
    """Class for processing GeoJSON building data."""

    def __init__(
        self,
        buildings_file: Optional[str] = None,
        polygon_coords: Optional[List[Tuple[float, float]]] = None,
        output_file: Optional[str] = None,
    ) -> None:
        """Initialize GeoProcessor."""
        self.geojson_data: Optional[Union[Dict[str, Any], str]] = None
        self.buildings_file = buildings_file
        self.polygon_coords = polygon_coords
        self.output_file = output_file
        self.buildings: Optional[gpd.GeoDataFrame] = None
        self.selection_polygon: Optional[gpd.GeoDataFrame] = None
        self.buildings_within_polygon: Optional[gpd.GeoDataFrame] = None
        self.dataframe: Optional[pd.DataFrame] = None

    def load_geojson(self, source: Union[str, Dict[str, Any]]) -> Tuple[bool, str]:
        """
        Load and validate GeoJSON data from file path or dictionary.

        Args:
            source: File path (str) or dictionary containing GeoJSON data

        Returns:
            tuple: (success, message)
                - success: Boolean indicating if loading was successful
                - message: Description of any loading issues
        """
        try:
            # Load from file if string path provided
            if isinstance(source, str):
                try:
                    with open(source, "r") as f:
                        self.geojson_data = json.load(f)
                except Exception as e:
                    return False, f"Error loading GeoJSON file: {str(e)}"
            else:
                self.geojson_data = source

            # Validate the data
            if self.geojson_data is not None:
                is_valid, message = validate_geojson(self.geojson_data)
                if not is_valid:
                    self.geojson_data = None
                    return False, message
            else:
                return False, "No GeoJSON data to validate"

            return True, "GeoJSON loaded successfully"

        except Exception as e:
            self.geojson_data = None
            return False, f"Error in load_geojson: {str(e)}"

    def load_geojson_from_url(self, url: str) -> Tuple[bool, str]:
        """
        Load and validate GeoJSON data from a URL.

        Args:
            url: URL to the GeoJSON data

        Returns:
            tuple: (success, message)
                - success: Boolean indicating if loading was successful
                - message: Description of any loading issues
        """
        try:
            response = requests.get(url)
            response.raise_for_status()  # Raise an exception for bad status codes
            geojson_data = response.json()
            return self.load_geojson(geojson_data)
        except requests.exceptions.RequestException as e:
            return False, f"Error downloading GeoJSON data from URL: {str(e)}"
        except json.JSONDecodeError as e:
            return False, f"Error decoding JSON from URL: {str(e)}"

    def process_buildings(self) -> Tuple[bool, str]:
        """
        Process building features from loaded GeoJSON.

        Returns:
            tuple: (success, message)
                - success: Boolean indicating if processing was successful
                - message: Description of any processing issues
        """
        if self.geojson_data is None:
            return False, "No GeoJSON data loaded"

        try:
            # Ensure geojson_data is a dictionary before passing to extract_building_data
            if isinstance(self.geojson_data, str):
                return False, "GeoJSON data is a file path, not loaded as dictionary"

            # Extract building data
            self.buildings = extract_building_data(self.geojson_data)

            if not self.buildings:
                return False, "No valid buildings found in GeoJSON"

            # Convert to DataFrame
            self.dataframe = pd.DataFrame(self.buildings)

            # Rename columns to match expected format
            self.dataframe = self.dataframe.rename(
                columns={"area": "Area (sq. meters)", "centroid": "Centroid"}
            )

            # Split centroid into x, y columns
            self.dataframe[["x", "y"]] = pd.DataFrame(
                self.dataframe["Centroid"].tolist(), index=self.dataframe.index
            )
            self.dataframe = self.dataframe.drop("Centroid", axis=1)

            return True, f"Successfully processed {len(self.buildings)} buildings"

        except Exception as e:
            self.buildings = []
            self.dataframe = None
            return False, f"Error processing buildings: {str(e)}"

    def process_buildings_in_polygon(self) -> None:
        """
        Loads building footprints from a GeoJSON file, selects buildings within a given polygon,
        and saves the result to a new GeoJSON file.
        """
        if not self.buildings_file:
            raise ValueError("buildings_file is required to filter buildings by polygon")
        if not self.polygon_coords:
            raise ValueError("polygon_coords is required to filter buildings by polygon")
        if not self.output_file:
            raise ValueError("output_file is required to save filtered buildings")

        # Load the buildings dataset
        self.buildings = gpd.read_file(self.buildings_file)
        if self.buildings.empty:
            raise ValueError(f"No features found in {self.buildings_file}")

        if self.buildings.crs is None:
            self.buildings = self.buildings.set_crs("EPSG:4326")

        # OSMnx and imported footprint layers may include non-building nodes,
        # ways, or lines. The grid generator only consumes footprint polygons.
        polygon_mask = self.buildings.geom_type.isin(["Polygon", "MultiPolygon"])
        self.buildings = self.buildings.loc[polygon_mask].copy()
        if self.buildings.empty:
            raise ValueError(
                f"No Polygon or MultiPolygon building footprints found in {self.buildings_file}"
            )

        self.buildings["geometry"] = self.buildings.geometry.make_valid()

        # Create a Polygon geometry from the coordinates
        self.selection_polygon = gpd.GeoDataFrame(
            {"geometry": [Polygon(self.polygon_coords)]},
            crs="EPSG:4326",  # CRS for WGS84
        ).to_crs(self.buildings.crs)

        # Perform spatial intersection to select buildings inside the polygon
        self.buildings_within_polygon = gpd.overlay(
            self.buildings,
            self.selection_polygon,
            how="intersection",
            keep_geom_type=True,
        )
        self.buildings_within_polygon = self.buildings_within_polygon.loc[
            self.buildings_within_polygon.geom_type.isin(["Polygon", "MultiPolygon"])
        ].copy()
        if self.buildings_within_polygon.empty:
            raise ValueError("No building footprints intersect the selection polygon")

        # Save the result to a new GeoJSON file
        output_dir = os.path.dirname(self.output_file)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        self.buildings_within_polygon.to_file(self.output_file, driver="GeoJSON")

        print(f"Buildings inside the polygon saved to {self.output_file}")

    def get_building_data(self) -> Optional[pd.DataFrame]:
        """
        Get processed building data as DataFrame.

        Returns:
            Optional[pd.DataFrame]: DataFrame with building data or None if no data processed
        """
        return self.dataframe

    def get_statistics(self) -> Dict:
        """
        Get statistics about the processed buildings.

        Returns:
            dict: Dictionary containing statistics:
                - num_buildings: Total number of buildings
                - total_area: Total building area in square meters
                - avg_area: Average building area in square meters
                - min_area: Minimum building area in square meters
                - max_area: Maximum building area in square meters
        """
        if self.dataframe is None:
            return {}

        try:
            areas = self.dataframe["Area (sq. meters)"]
            return {
                "num_buildings": len(self.dataframe),
                "total_area": areas.sum(),
                "avg_area": areas.mean(),
                "min_area": areas.min(),
                "max_area": areas.max(),
            }
        except Exception as e:
            print(f"Error calculating statistics: {str(e)}")
            return {}

    def get_building_by_id(self, building_id: Union[int, str]) -> Optional[Dict]:
        """
        Get data for a specific building by ID.

        Args:
            building_id: Building identifier

        Returns:
            Optional[Dict]: Building data dictionary or None if not found
        """
        if self.dataframe is None:
            return None

        try:
            building = self.dataframe[self.dataframe["id"] == building_id]
            if len(building) == 0:
                return None
            return building.iloc[0].to_dict()
        except Exception as e:
            print(f"Error getting building {building_id}: {str(e)}")
            return None
