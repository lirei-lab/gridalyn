"""
Manages the topology and transformation of power grid graphs.

This module provides the `PowerGridGraph` class, a comprehensive tool for
creating, manipulating, and exporting power grid graph topologies. It is
designed to handle the entire workflow of power grid modeling, from
processing raw building data to generating a unified, multi-level grid
representation suitable for simulation and analysis.

The class supports the creation of low-voltage (LV), medium-voltage (MV),
and high-voltage (HV) networks, and provides methods for merging these into
a single, cohesive graph. It also includes functionalities for integrating
with the Common Information Model (CIM) and exporting the grid to various
formats.
"""

import json
import logging
from typing import Dict, List, Optional, Tuple

import geopandas as gpd
import networkx as nx
import numpy as np
from geopy.distance import geodesic
from pyproj import Transformer
from scipy.sparse.csgraph import minimum_spanning_tree
from scipy.spatial.distance import cdist
from sklearn.cluster import KMeans

from gridalyn.twin.core.ontology import create_node_payload


class PowerGridError(Exception):
    """Base exception class for power grid errors."""

    pass


class ValidationError(PowerGridError):
    """Raised when input validation fails."""

    pass


class PowerGridGraph:
    """
    Manages the topology and transformation of power grid graphs.

    This class is the core of the `gridalyn` library, providing a comprehensive
    suite of tools for creating, manipulating, and analyzing power grid graphs.
    It is designed to handle the entire workflow of power grid modeling, from
    processing raw building data to generating a unified, multi-level grid
    representation suitable for simulation.

    The class supports the creation of low-voltage (LV), medium-voltage (MV),
    and high-voltage (HV) networks, and provides methods for merging these into
    a single, cohesive graph. It also includes functionalities for integrating
    with the Common Information Model (CIM) and exporting the grid to various
    formats.

    Attributes:
        building_data (gpd.GeoDataFrame): A GeoDataFrame containing building
            information, including geometries, centroids, and areas.
        building_centroids (np.ndarray): An array of building centroid coordinates,
            used for clustering and graph creation.
        graph_buildings (nx.Graph): A NetworkX graph representing the buildings,
            with load information assigned to each node.
        graph_lv_buses (nx.Graph): A NetworkX graph of the low-voltage buses and
            their connections.
        graph_mv_buses (nx.Graph): A NetworkX graph of the medium-voltage buses
            and their connections.
        graph_hv_buses (nx.Graph): A NetworkX graph of the high-voltage buses
            and their connections.ditto

        labels_lv (np.ndarray): Cluster labels for the low-voltage buses, used to
            group them into LV networks.
        labels_mv (np.ndarray): Cluster labels for the medium-voltage buses, used
            to group them into MV networks.
        labels_hv (np.ndarray): Cluster labels for the high-voltage buses, used
            to group them into HV networks.
        merged_graph (nx.Graph): The unified graph containing all voltage levels,
            with transformers connecting the different levels.
    """

    def __init__(self, building_data: Optional[gpd.GeoDataFrame] = None) -> None:
        """Initializes the PowerGridGraph with optional building data.

        Args:
            building_data (gpd.GeoDataFrame, optional): A GeoDataFrame
                containing building geometries. Defaults to None.

        Raises:
            ValidationError: If the provided `building_data` is not a valid
                GeoDataFrame or lacks a 'geometry' column.
        """
        self.logger = logging.getLogger(__name__)

        # Validate building data if provided
        if building_data is not None:
            if not isinstance(building_data, gpd.GeoDataFrame):
                raise ValidationError("building_data must be a GeoDataFrame")
            if "geometry" not in building_data.columns:
                raise ValidationError("building_data must have a geometry column")

        self.building_data = building_data
        self.building_centroids: Optional[np.ndarray] = None
        self.graph_buildings: Optional[nx.Graph] = None
        self.graph_mv_buses: Optional[nx.Graph] = None
        self.graph_lv_buses: Optional[nx.Graph] = None
        self.graph_hv_buses: Optional[nx.Graph] = None
        self.labels_lv: Optional[np.ndarray] = None
        self.labels_mv: Optional[np.ndarray] = None
        self.labels_hv: Optional[np.ndarray] = None
        self.merged_graph: Optional[nx.Graph] = None
        self.source_crs: Optional[str] = None
        self.clustering_crs: Optional[str] = None

    def extract_building_centers_and_areas(
        self,
        input_file: str,
        *,
        clustering_crs: str | int | None = None,
    ) -> gpd.GeoDataFrame:
        """Extracts building centroids and areas from a GeoJSON file.

        This method reads building geometries from a GeoJSON file, computes
        the centroid and area for each building, and stores the results in
        the `building_data` attribute.

        Args:
            input_file (str): The path to the input GeoJSON file containing
                building polygons.
            clustering_crs: Optional CRS used for K-Means and MST topology
                construction. Pass ``"auto"`` to use GeoPandas' estimated local
                UTM CRS. Coordinates stored on graph nodes remain longitude and
                latitude for downstream geodata and pandapower builders.

        Returns:
            gpd.GeoDataFrame: A GeoDataFrame with columns for Building ID,
                Longitude, Latitude, and Area.

        Raises:
            FileNotFoundError: If the specified GeoJSON file does not exist.
            ValueError: If the GeoJSON file has an invalid format.

        Example:
            >>> grid = PowerGridGraph()
            >>> buildings = grid.extract_building_centers_and_areas("buildings.geojson")
            >>> print(buildings.head())
        """

        try:
            buildings = gpd.read_file(input_file)
        except Exception as e:
            if "No such file or directory" in str(e):
                raise FileNotFoundError(f"GeoJSON file not found: {input_file}") from e
            if any(
                msg in str(e)
                for msg in [
                    "Invalid data source",
                    "not recognized as being in a supported file format",
                ]
            ):
                raise ValueError("Invalid GeoJSON file format") from e
            raise

        # Process buildings data
        if buildings.crs is None:
            buildings = buildings.set_crs("EPSG:4326")
        self.source_crs = str(buildings.crs)

        polygon_mask = buildings.geom_type.isin(["Polygon", "MultiPolygon"])
        buildings = buildings.loc[polygon_mask].copy()
        if buildings.empty:
            raise ValueError("GeoJSON contains no Polygon/MultiPolygon footprints")

        buildings["unique_id"] = range(1, len(buildings) + 1)

        # Project to Web Mercator for accurate area calculation
        buildings_projected = buildings.to_crs(epsg=3857)
        projected_centroids = buildings_projected.geometry.centroid
        buildings["area"] = buildings_projected.geometry.area

        # Convert back to WGS84 for standard lat/lon coordinates
        centroid_to_wgs84 = Transformer.from_crs(
            buildings_projected.crs,
            "EPSG:4326",
            always_xy=True,
        )
        centroid_x, centroid_y = centroid_to_wgs84.transform(
            projected_centroids.x.to_list(),
            projected_centroids.y.to_list(),
        )
        buildings["centroid_x"] = centroid_x  # Longitude
        buildings["centroid_y"] = centroid_y  # Latitude

        # Create result DataFrame with renamed columns
        result = buildings[["unique_id", "centroid_x", "centroid_y", "area"]].copy()
        result = result.rename(
            columns={
                "unique_id": "Building ID",
                "centroid_x": "Longitude",
                "centroid_y": "Latitude",
                "area": "Area (sq. meters)",
            }
        )

        self.building_data = result
        self.building_centroids = result[["Longitude", "Latitude"]].to_numpy()
        self.clustering_crs = self._resolve_clustering_crs(buildings, clustering_crs)

        return result

    def _resolve_clustering_crs(
        self,
        buildings: gpd.GeoDataFrame,
        clustering_crs: str | int | None,
    ) -> Optional[str]:
        """Resolve an optional metric CRS for clustering and MST construction."""
        if clustering_crs is None:
            return None
        if str(clustering_crs).lower() == "auto":
            estimated = buildings.estimate_utm_crs()
            return str(estimated) if estimated is not None else "EPSG:3857"
        return str(clustering_crs)

    def _points_for_clustering(self, lon_lat_points: np.ndarray) -> np.ndarray:
        """Return metric clustering coordinates while preserving lon/lat nodes."""
        if not self.clustering_crs:
            return lon_lat_points
        transformer = Transformer.from_crs(
            "EPSG:4326",
            self.clustering_crs,
            always_xy=True,
        )
        x_points, y_points = transformer.transform(
            lon_lat_points[:, 0].tolist(),
            lon_lat_points[:, 1].tolist(),
        )
        return np.column_stack((x_points, y_points))

    def _validate_cluster_inputs(
        self, points: np.ndarray, n_clusters: int, childs: Optional[List[int]]
    ) -> None:
        """Validate inputs for cluster graph creation.

        Args:
            points: Array of points to cluster
            n_clusters: Number of clusters to form
            childs: Optional list of child node IDs

        Raises:
            ValidationError: If any input is invalid
        """
        if points is None or len(points) == 0:
            raise ValidationError("No points provided for clustering")
        if not isinstance(points, np.ndarray):
            raise ValidationError("Points must be a numpy array")
        if points.ndim != 2 or points.shape[1] != 2:
            raise ValidationError("Points must be a 2D array with shape (n, 2)")

        n_clusters = min(n_clusters, len(points))
        if n_clusters < 1:
            raise ValidationError("Number of clusters must be at least 1")

        if childs is not None:
            if not isinstance(childs, list):
                raise ValidationError("childs must be a list")
            if len(childs) != len(points):
                raise ValidationError("childs length must match points length")

    def _add_point_nodes(
        self,
        graph: nx.Graph,
        points: np.ndarray,
        labels: np.ndarray,
        node_prefix: str,
        childs: List[int],
        node_coordinates: Optional[np.ndarray] = None,
    ) -> None:
        """Add point nodes to the graph.

        Args:
            graph: Graph to add nodes to
            points: Array of points
            labels: Cluster labels for each point
            node_prefix: Prefix for node names
            childs: List of child node IDs
        """
        coordinates = node_coordinates if node_coordinates is not None else points
        for i, point in enumerate(coordinates):
            node_id = f"{node_prefix}_{i}"
            payload = create_node_payload(
                node_id=node_id,
                x=float(point[0]),
                y=float(point[1]),
                node_type=node_prefix,
                cluster=int(labels[i]),
                child=childs[i],
            )
            graph.add_node(node_id, **payload)

    def _add_cluster_centers(
        self, graph: nx.Graph, cluster_centers: np.ndarray, cluster_prefix: str
    ) -> None:
        """Add cluster center nodes to the graph.

        Args:
            graph: Graph to add nodes to
            cluster_centers: Array of cluster centers
            cluster_prefix: Prefix for cluster center names
        """
        for i, center in enumerate(cluster_centers):
            node_id = f"{cluster_prefix}_{i}"
            payload = create_node_payload(
                node_id=node_id,
                x=float(center[0]),
                y=float(center[1]),
                node_type=cluster_prefix,
                cluster=i,
            )
            graph.add_node(node_id, **payload)

    def _create_cluster_mst(
        self,
        graph: nx.Graph,
        points: np.ndarray,
        labels: np.ndarray,
        cluster_id: int,
        node_prefix: str,
        cluster_prefix: str,
    ) -> None:
        """Create minimum spanning tree for a cluster.

        Args:
            graph: Graph to add edges to
            points: Array of all points
            labels: Cluster labels for each point
            cluster_id: ID of the current cluster
            node_prefix: Prefix for node names
            cluster_prefix: Prefix for cluster center names
        """
        cluster_points = points[labels == cluster_id]

        # Compute the Delaunay triangulation to infer street-corridor topological adjacencies
        from scipy.spatial import Delaunay

        # If less than 4 points, Delaunay fails on coplanar, so fallback to full cdist
        if len(cluster_points) < 4:
            dist_matrix = cdist(cluster_points, cluster_points)
        else:
            try:
                tri = Delaunay(cluster_points)
                indptr, indices = tri.vertex_neighbor_vertices
                dist_matrix = np.zeros((len(cluster_points), len(cluster_points)))

                for k in range(len(cluster_points)):
                    neighbors = indices[indptr[k] : indptr[k + 1]]
                    for n in neighbors:
                        # Euclidean distance *only* along Delaunay bounds
                        dist_matrix[k, n] = np.linalg.norm(
                            cluster_points[k] - cluster_points[n]
                        )
            except Exception:
                # Fallback if points are strictly collinear
                dist_matrix = cdist(cluster_points, cluster_points)

        mst_matrix = minimum_spanning_tree(dist_matrix).toarray()

        cluster_nodes = [
            f"{node_prefix}_{i}" for i in range(len(points)) if labels[i] == cluster_id
        ]

        # Add MST edges and build sub-graph for Centrality analysis
        sub_graph = nx.Graph()
        for i, source in enumerate(cluster_nodes):
            for j, target in enumerate(cluster_nodes):
                if mst_matrix[i, j] > 0:
                    weight = float(mst_matrix[i, j])
                    graph.add_edge(source, target, weight=weight)
                    sub_graph.add_edge(source, target, weight=weight)

        # Link cluster center to the topologically optimal load center (Betweenness)
        cluster_center = f"{cluster_prefix}_{cluster_id}"

        if len(sub_graph.nodes) > 0:
            # Find the topological center using closeness centrality
            # to minimize voltage drop across all radial arms
            centrality = nx.closeness_centrality(sub_graph, distance="weight")
            optimal_node = max(centrality, key=centrality.get)

            # Snap the abstract transformer location to this optimal node geometrically
            graph.nodes[cluster_center]["x"] = graph.nodes[optimal_node]["x"]
            graph.nodes[cluster_center]["y"] = graph.nodes[optimal_node]["y"]

            # Add negligible service drop link
            graph.add_edge(optimal_node, cluster_center, weight=0.1)
        elif len(cluster_nodes) == 1:
            graph.nodes[cluster_center]["x"] = graph.nodes[cluster_nodes[0]]["x"]
            graph.nodes[cluster_center]["y"] = graph.nodes[cluster_nodes[0]]["y"]
            graph.add_edge(cluster_nodes[0], cluster_center, weight=0.1)

    def create_cluster_graph(
        self,
        points: np.ndarray,
        n_clusters: int,
        node_prefix: str = "node",
        cluster_prefix: str = "cluster",
        childs: Optional[List[int]] = None,
        node_coordinates: Optional[np.ndarray] = None,
    ) -> Tuple[nx.Graph, np.ndarray]:
        """Creates a graph with clusters and a minimum spanning tree (MST).

        This method performs K-Means clustering on a set of points and then
        constructs a graph. Each cluster is connected internally by an MST,
        and each cluster's center is connected to the closest point within
        that cluster.

        Args:
            points (np.ndarray): An array of points to cluster.
            n_clusters (int): The number of clusters to form.
            node_prefix (str): A prefix for the node names (e.g., 'building').
            cluster_prefix (str): A prefix for the cluster center names
                (e.g., 'lv_transformer').
            childs (List[int], optional): A list of child node IDs for each
                node. Defaults to node indices.

        Returns:
            Tuple[nx.Graph, np.ndarray]: A tuple containing the resulting
                NetworkX graph and an array of cluster labels for each point.

        Raises:
            ValidationError: If the input `points` is empty or `n_clusters`
                is less than 1.
        """
        self._validate_cluster_inputs(points, n_clusters, childs)
        n_clusters = min(int(n_clusters), len(points))

        self.logger.info(f"Clustering {len(points)} points into {n_clusters} clusters")
        self.logger.debug(f"Sample point: {points[0]}")

        # Perform clustering
        kmeans = KMeans(n_clusters=n_clusters, random_state=0)
        labels = kmeans.fit_predict(points)
        cluster_centers = kmeans.cluster_centers_

        # Initialize graph
        graph = nx.Graph()
        if childs is None:
            childs = list(range(len(points)))

        if node_coordinates is not None:
            if not isinstance(node_coordinates, np.ndarray):
                raise ValidationError("node_coordinates must be a numpy array")
            if node_coordinates.shape != points.shape:
                raise ValidationError("node_coordinates shape must match points")

        display_centers = cluster_centers
        if node_coordinates is not None:
            display_centers = np.vstack(
                [
                    node_coordinates[labels == cluster_id].mean(axis=0)
                    for cluster_id in range(n_clusters)
                ]
            )
            self._add_point_nodes(
                graph,
                points,
                labels,
                node_prefix,
                childs,
                node_coordinates=node_coordinates,
            )
        else:
            self._add_point_nodes(graph, points, labels, node_prefix, childs)
        self._add_cluster_centers(graph, display_centers, cluster_prefix)

        # Create MST for each cluster
        for cluster_id in range(n_clusters):
            self._create_cluster_mst(
                graph, points, labels, cluster_id, node_prefix, cluster_prefix
            )

        return graph, labels

    def create_lv_graph(
        self,
        max_load_per_building: float | None = None,
        mv_lv_transformer_capacity: float | None = None,
        capacity_utilization_factor: float = 0.60,
        diversity_factor_lv: float = 5.0,
        *,
        avg_load_per_building: float | None = None,
    ) -> nx.Graph:
        """Creates the low-voltage (LV) graph from building centroids.

        This method generates a graph where buildings are represented as nodes
        and transformers are treated as cluster centers. The number of
        transformers is calculated based on the total estimated load and the
        capacity of each transformer.

        Args:
            max_load_per_building (float): The maximum installed non-coincident
                load per building in kW.
            mv_lv_transformer_capacity (float): The capacity of the MV-LV
                transformers in kW.
            capacity_utilization_factor (float): Target ratio of maximum transformer
                load vs rated capacity (e.g. 0.8 for 80% loading). Defaults to 0.60.
            diversity_factor_lv (float): Factor representing peak coincidence at LV level.
            avg_load_per_building (float): Legacy alias for
                `max_load_per_building`.

        Returns:
            nx.Graph: A NetworkX graph representing the LV network.

        Raises:
            ValueError: If `building_centroids` has not been initialized.

        Example:
            >>> grid = PowerGridGraph(building_data)
            >>> lv_graph = grid.create_lv_graph(25, 250)
        """
        if self.building_centroids is None:
            raise ValueError("Building centroids must be initialized first")
        if max_load_per_building is None:
            max_load_per_building = avg_load_per_building
        elif avg_load_per_building is not None:
            raise ValueError(
                "Pass either max_load_per_building or avg_load_per_building, not both"
            )
        if max_load_per_building is None:
            raise ValueError("max_load_per_building is required")
        if mv_lv_transformer_capacity is None:
            raise ValueError("mv_lv_transformer_capacity is required")
        num_buildings = len(self.building_centroids)

        total_installed_grid_power = num_buildings * max_load_per_building

        # Sum of non-coincident peaks is total_installed_grid_power.
        # Coincident peak = Non-Coincident Peak / Diversity Factor
        coincident_peak_kw = total_installed_grid_power / diversity_factor_lv

        num_lv_transformers = int(
            np.ceil(
                coincident_peak_kw
                / (mv_lv_transformer_capacity * capacity_utilization_factor)
            )
        )

        self.graph_lv_buses, self.labels_lv = self.create_cluster_graph(
            self._points_for_clustering(self.building_centroids),
            num_lv_transformers,
            node_prefix="lv_bus",
            cluster_prefix="lv_feeder",
            node_coordinates=self.building_centroids,
        )
        return self.graph_lv_buses

    def create_mv_graph(
        self,
        mv_lv_transformer_capacity: float,
        hv_mv_transformer_capacity: float,
        diversity_factor_mv: float = 1.3,
        num_mv_substations: int | None = None,
    ) -> nx.Graph:
        """Creates the medium-voltage (MV) graph from LV feeder positions.

        This method constructs a graph where LV feeders are the nodes and MV
        substations are the cluster centers. The number of MV substations is
        determined by the total capacity of the LV transformers and the
        capacity of the HV-MV transformers.

        Args:
            mv_lv_transformer_capacity (float): The capacity of the MV-LV
                transformers in kW.
            hv_mv_transformer_capacity (float): The capacity of the HV-MV
                transformers in kW.
            diversity_factor_mv (float): Factor representing peak coincidence at MV aggregation.

        Returns:
            nx.Graph: A NetworkX graph representing the MV network.

        Raises:
            ValueError: If the LV graph has not been initialized or if no LV
                feeders are found.
        """

        if self.graph_lv_buses is None:
            raise ValueError("LV graph must be created before creating MV graph")

        # Get LV transformer positions
        lv_feeder_nodes = [
            (node, data)
            for node, data in self.graph_lv_buses.nodes(data=True)
            if data["type"] == "lv_feeder"
        ]
        if not lv_feeder_nodes:
            raise ValueError("No LV feeder nodes found in the graph")

        lv_transformer_positions = np.array(
            [(data["x"], data["y"]) for node, data in lv_feeder_nodes]
        )

        if num_mv_substations is None:
            total_mv_load = (
                len(lv_transformer_positions) * mv_lv_transformer_capacity
            ) / diversity_factor_mv
            num_mv_substations = int(
                np.ceil(total_mv_load / hv_mv_transformer_capacity)
            )
        else:
            num_mv_substations = int(num_mv_substations)

        # Ensure at least 1 substation
        num_mv_substations = max(1, num_mv_substations)

        # Get cluster IDs from the same nodes we got positions from
        childs = [data["cluster"] for _, data in lv_feeder_nodes]

        # Log debug info
        self.logger.debug(f"Number of LV feeder nodes: {len(lv_feeder_nodes)}")
        self.logger.debug(f"Number of MV substations: {num_mv_substations}")
        self.logger.debug(f"Positions shape: {lv_transformer_positions.shape}")
        self.logger.debug(f"Number of childs: {len(childs)}")

        self.graph_mv_buses, self.labels_mv = self.create_cluster_graph(
            self._points_for_clustering(lv_transformer_positions),
            num_mv_substations,
            node_prefix="mv_bus",
            cluster_prefix="mv_feeder",
            childs=childs,
            node_coordinates=lv_transformer_positions,
        )
        return self.graph_mv_buses

    def create_hv_substation_graph(
        self,
        hv_mv_transformer_capacity: float,
        hv_substation_capacity: float,
        diversity_factor_hv: float = 1.1,
    ) -> nx.Graph:
        """Creates the high-voltage (HV) substation graph from MV feeder positions.

        This method generates a graph where MV feeders are the nodes and HV
        substations are the cluster centers. The number of HV substations is
        calculated based on the total capacity of the MV transformers and the
        capacity of the HV substations.

        Args:
            hv_mv_transformer_capacity (float): The capacity of the HV-MV
                transformers in kW.
            hv_substation_capacity (float): The capacity of the HV
                substations in kW.
            diversity_factor_hv (float): Factor representing peak coincidence at HV aggregation.

        Returns:
            nx.Graph: A NetworkX graph representing the HV network.

        Raises:
            ValueError: If the MV graph has not been initialized or if no MV
                feeders are found.
        """

        if self.graph_mv_buses is None:
            raise ValueError("MV graph must be created before creating HV graph")

        # Get MV transformer positions
        mv_feeder_nodes = [
            (node, data)
            for node, data in self.graph_mv_buses.nodes(data=True)
            if data["type"] == "mv_feeder"
        ]
        if not mv_feeder_nodes:
            raise ValueError("No MV feeder nodes found in the graph")

        mv_substation_positions = np.array(
            [(data["x"], data["y"]) for _node, data in mv_feeder_nodes]
        )

        childs = [data["cluster"] for _node, data in mv_feeder_nodes]

        total_hv_load = (
            len(mv_substation_positions) * hv_mv_transformer_capacity
        ) / diversity_factor_hv
        num_hv_substations = int(np.ceil(total_hv_load / hv_substation_capacity))

        # Ensure at least 1 substation
        num_hv_substations = max(1, num_hv_substations)

        self.graph_hv_buses, self.labels_hv = self.create_cluster_graph(
            self._points_for_clustering(mv_substation_positions),
            num_hv_substations,
            node_prefix="hv_bus",
            cluster_prefix="hv_feeder",
            childs=childs,
            node_coordinates=mv_substation_positions,
        )
        return self.graph_hv_buses

    def create_building_graph(
        self,
        max_load_per_building: float = 25.0,
        reactive_power_ratio: float = 0.1,
        diversity_factor_lv: float = 5.0,
    ) -> nx.Graph:
        """Creates a building graph from the LV bus graph.

        This method generates a copy of the LV bus graph, where each node
        represents a building with associated load parameters. Active and
        reactive power loads are assigned to each building based on the
        provided parameters.

        Args:
            max_load_per_building (float): The default maximum active power
                (kW) for each building.
            reactive_power_ratio (float): The ratio of reactive to active
                power (e.g., 0.1 for 10%).
            diversity_factor_lv (float): The block diversity factor for
                lowering the non-coincident static peak load for flow
                initialization.

        Returns:
            nx.Graph: A NetworkX graph representing the buildings and their
                loads.

        Raises:
            ValueError: If the LV graph has not been initialized.
        """
        if self.graph_lv_buses is None:
            raise ValueError("LV graph must be created before creating building graph")

        # Create a copy of graph_lv_buses and update node types to "building"
        self.graph_buildings = self.graph_lv_buses.copy()

        # We need to relabel the dict keys from 'lv_bus_idx' -> 'building_idx'
        mapping = {}

        building_idx = 0
        for node, data in self.graph_buildings.nodes(data=True):
            if data.get("type", "").startswith("lv_bus"):
                new_name = node.replace("lv_bus", "building")
                mapping[node] = new_name

                # Assign the properly smoothed non-coincident building demand peak
                load_kw = max_load_per_building / diversity_factor_lv

                # Update attributes with Pydantic validation
                payload = create_node_payload(
                    node_id=new_name,
                    x=data["x"],
                    y=data["y"],
                    node_type="building",
                    cluster=data.get("cluster"),
                    child=data.get("child"),
                    load_kw=load_kw,
                    load_kvar=load_kw * reactive_power_ratio,
                )
                data.clear()
                data.update(payload)
                building_idx += 1

        nx.relabel_nodes(self.graph_buildings, mapping, copy=False)

        self.logger.info(
            f"Created building graph with {len(self.graph_buildings.nodes)} nodes."
        )
        return self.graph_buildings

    def extend_graph_with_cim(self, graph_type: str) -> None:
        """Extends a specified graph with CIM (Common Information Model) classes.

        This method adds CIM class information to the nodes and edges of a
        specified graph. Nodes are assigned the class "cim:ConnectivityNode",
        and edges are assigned "cim:ACLineSegment" with a length calculated
        based on the geodesic distance between the connected nodes.

        Args:
            graph_type (str): The name of the graph attribute to extend
                (e.g., 'graph_lv_buses').

        Raises:
            ValueError: If the specified graph does not exist or has not been
                initialized.
        """
        if not hasattr(self, graph_type):
            raise ValueError(
                f"The graph type {graph_type!r} does not exist in the PowerGridGraph instance."
            )

        graph = getattr(self, graph_type)
        if graph is None:
            raise ValueError(f"The graph {graph_type!r} is not initialized.")

        # Extend nodes with CIM class
        for _node, data in graph.nodes(data=True):
            data["cimclass"] = "cim:ConnectivityNode"

        # Extend edges with CIM class and length
        for source, target, data in graph.edges(data=True):
            source_node = graph.nodes[source]
            target_node = graph.nodes[target]

            from_pos = (source_node["x"], source_node["y"])
            to_pos = (target_node["x"], target_node["y"])
            length = geodesic(from_pos, to_pos).meters
            if length < 1:
                length = 1  # Enforce minimum length

            data["cimclass"] = "cim:ACLineSegment"
            data["length"] = length

    def _connect_lv_to_mv_buses(self, merged_graph: nx.Graph) -> None:
        """Connects LV feeders to MV buses in the merged graph."""
        lv_feeder_nodes = []
        if self.graph_lv_buses is not None:
            lv_feeder_nodes = [
                node
                for node, data in self.graph_lv_buses.nodes(data=True)
                if data.get("type") == "lv_feeder"
            ]
        mv_bus_nodes = []
        if self.graph_mv_buses is not None:
            mv_bus_nodes = [
                node
                for node, data in self.graph_mv_buses.nodes(data=True)
                if data.get("type") == "mv_bus"
            ]

        for lv_node in lv_feeder_nodes:
            if self.graph_lv_buses is not None:
                lv_data = self.graph_lv_buses.nodes[lv_node]
                for mv_node in mv_bus_nodes:
                    if self.graph_mv_buses is not None:
                        mv_data = self.graph_mv_buses.nodes[mv_node]
                        if mv_data.get("child") == lv_data.get("cluster"):
                            merged_graph.add_edge(
                                lv_node, mv_node, cimclass="cim:PowerTransformer"
                            )

    def _connect_mv_to_hv_buses(self, merged_graph: nx.Graph) -> None:
        """Connects MV feeders to HV buses in the merged graph."""
        mv_feeder_nodes = []
        if self.graph_mv_buses is not None:
            mv_feeder_nodes = [
                node
                for node, data in self.graph_mv_buses.nodes(data=True)
                if data.get("type") == "mv_feeder"
            ]
        hv_bus_nodes = []
        if self.graph_hv_buses is not None:
            hv_bus_nodes = [
                node
                for node, data in self.graph_hv_buses.nodes(data=True)
                if data.get("type") == "hv_bus"
            ]

        for mv_node in mv_feeder_nodes:
            if self.graph_mv_buses is not None:
                mv_data = self.graph_mv_buses.nodes[mv_node]
                for hv_node in hv_bus_nodes:
                    if self.graph_hv_buses is not None:
                        hv_data = self.graph_hv_buses.nodes[hv_node]
                        if hv_data.get("child") == mv_data.get("cluster"):
                            merged_graph.add_edge(
                                mv_node, hv_node, cimclass="cim:PowerTransformer"
                            )

    def merge_graphs(self) -> nx.Graph:
        """Merges voltage level graphs into a unified power grid graph.

        This method combines the LV, MV, and HV graphs into a single, unified
        graph. It connects the different voltage levels by adding transformer
        edges based on their cluster relationships.

        Returns:
            nx.Graph: A NetworkX graph representing the complete power grid.

        Raises:
            ValueError: If any of the required graphs (LV, MV, HV) have not
                been initialized.
        """
        # Ensure all required graphs are initialized. `is None`, not
        # truthiness: `bool(nx.Graph())` is False for an empty-but-real
        # graph, which would wrongly fail this check on a legitimately
        # initialized, zero-node graph.
        required_graphs = (
            self.graph_lv_buses,
            self.graph_mv_buses,
            self.graph_hv_buses,
        )
        if any(graph is None for graph in required_graphs):
            raise ValueError(
                "All three graphs (graph_lv_buses, graph_mv_buses, graph_hv_buses) "
                "must be initialized."
            )

        # Create a new graph to store the merged result
        merged_graph = nx.Graph()

        # Merge nodes and edges from each graph into the merged_graph
        for graph in [self.graph_lv_buses, self.graph_mv_buses, self.graph_hv_buses]:
            if graph is not None:
                merged_graph.update(graph)

        self._connect_lv_to_mv_buses(merged_graph)
        self._connect_mv_to_hv_buses(merged_graph)

        self.logger.info(
            "Merged graph created with LV-MV and MV-HV connections as Power Transformers."
        )
        self.merged_graph = merged_graph
        return merged_graph

    def check_for_isolated_nodes(self) -> Dict[str, Optional[List[str]]]:
        """Checks for isolated nodes in the voltage level graphs.

        This method identifies nodes that have no connections in each of the
        voltage level graphs (LV, MV, and HV). The presence of isolated nodes
        can indicate potential issues in the grid topology.

        Returns:
            Dict[str, Optional[List[str]]]: A dictionary that maps graph names
                to lists of their isolated node IDs. If a graph has not been
                initialized, its value will be `None`.
        """
        isolated_nodes: Dict[str, Optional[List[str]]] = {}

        # Check LV graph for isolated nodes
        if self.graph_lv_buses is not None:
            lv_graph = self.graph_lv_buses
            isolated_nodes["graph_lv_buses"] = [
                node for node, degree in lv_graph.degree() if degree == 0
            ]
        else:
            isolated_nodes["graph_lv_buses"] = None

        # Check MV graph for isolated nodes
        if self.graph_mv_buses is not None:
            mv_graph = self.graph_mv_buses
            isolated_nodes["graph_mv_buses"] = [
                node for node, degree in mv_graph.degree() if degree == 0
            ]
        else:
            isolated_nodes["graph_mv_buses"] = None

        # Check HV graph for isolated nodes
        if self.graph_hv_buses is not None:
            hv_graph = self.graph_hv_buses
            isolated_nodes["graph_hv_buses"] = [
                node for node, degree in hv_graph.degree() if degree == 0
            ]
        else:
            isolated_nodes["graph_hv_buses"] = None

        # Log isolated nodes
        for graph_name, nodes in isolated_nodes.items():
            if nodes:
                self.logger.info(f"Isolated nodes in {graph_name}: {nodes}")
            elif nodes is None:
                self.logger.info(f"{graph_name} is not initialized.")
            else:
                self.logger.info(f"No isolated nodes in {graph_name}.")

        return isolated_nodes

    def export_to_graphml(self, filepath: str) -> None:
        """Exports the merged graph to GraphML format.

        This method saves the complete power grid graph to a GraphML file,
        which preserves all node and edge attributes, including CIM classes
        and electrical parameters.

        Args:
            filepath (str): The path where the GraphML file will be saved.

        Raises:
            ValueError: If the `merged_graph` has not been initialized.
            OSError: If the file cannot be written to the specified path.

        Example:
            >>> grid.export_to_graphml("power_grid.graphml")
        """
        if self.merged_graph is None:
            raise ValueError(
                "The merged_graph is not initialized. Please run merge_graphs() first."
            )

        # Scrub NoneType values since GraphML specification strictly forbids them
        clean_graph = self.merged_graph.copy()
        for _node, data in clean_graph.nodes(data=True):
            for k, v in list(data.items()):
                if v is None:
                    data[k] = ""

        for _u, _v, data in clean_graph.edges(data=True):
            for k, val in list(data.items()):
                if val is None:
                    data[k] = ""

        nx.write_graphml(clean_graph, filepath)
        self.logger.info(f"Merged graph exported to GraphML format at {filepath}")

    def export_building_data_to_json(self, filepath: str) -> None:
        """Exports building data to a JSON file.

        This method saves the extracted building information, including the
        Building ID, Latitude, Longitude, and Area, to a JSON file.

        Args:
            filepath (str): The path where the JSON file will be saved.

        Raises:
            ValueError: If the `building_data` has not been initialized.
            OSError: If the file cannot be written to the specified path.

        Example:
            >>> grid.export_building_data_to_json("building_data.json")
        """
        if self.building_data is None:
            raise ValueError(
                "Building data is not initialized. Please run "
                "extract_building_centers_and_areas() first."
            )

        buildings_list = []
        for _, row in self.building_data.iterrows():
            buildings_list.append(
                {
                    "ID": int(row["Building ID"]),  # Ensure Building ID is an integer
                    "Latitude": row["Latitude"],
                    "Longitude": row["Longitude"],
                    "Area (sq. meters)": row["Area (sq. meters)"],
                }
            )

        try:
            with open(filepath, "w") as f:
                json.dump(buildings_list, f, indent=4)
            self.logger.info(f"Building data exported to JSON format at {filepath}")
        except IOError as e:
            raise OSError(f"Error writing building data to {filepath}: {e}") from e
