from typing import Tuple

import geopandas as gpd
import osmnx as ox


class BuildingDownloader:
    def __init__(self, config_path: str = "configs/geography/tr01.json") -> None:
        self.config_path = config_path

    def download_buildings(
        self, polygon_coordinates: Tuple[Tuple[float, float]], output_path: str
    ) -> None:
        """
        Downloads building shapes for a given polygon using osmnx and saves them to a file.


        Args:
            polygon_coordinates: The polygon coordinates to download building shapes for.
            output_path: The path to save the downloaded building shapes.
        """
        from shapely.geometry import Polygon

        polygon_list = [list(coord) for coord in polygon_coordinates]
        polygon = Polygon(polygon_list)
        gdf = ox.features_from_polygon(polygon, tags={"building": True})

        if gdf.empty:
            raise ValueError("OSMnx returned no building features for the polygon")

        buildings = gdf[gdf["building"].notnull()].copy()
        buildings = buildings.loc[
            buildings.geom_type.isin(["Polygon", "MultiPolygon"])
        ].copy()
        if buildings.empty:
            raise ValueError("OSMnx returned no Polygon/MultiPolygon building footprints")

        buildings = gpd.GeoDataFrame(buildings, geometry="geometry", crs=gdf.crs)
        if buildings.crs is None:
            buildings = buildings.set_crs("EPSG:4326")

        import os

        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        buildings.to_file(output_path, driver="GeoJSON")
