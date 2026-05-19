from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import networkx as nx
import numpy as np


class NetworkAnalyzer:
    """
    Analyzes power grid networks and calculates network metrics.

    This class provides a comprehensive suite of tools for analyzing the
    topological properties of power grid networks. It is designed to work
    with NetworkX graphs created by the `PowerGridGraph` class, and provides
    methods for calculating a wide range of network metrics, including
    connectivity, centrality, and efficiency.

    The class can be used to assess the resilience and robustness of a power
    grid, identify critical components, and understand the overall structure
    and characteristics of the network.

    Attributes:
        graph (nx.Graph): The power grid graph to be analyzed.
    """

    def __init__(self, graph: nx.Graph) -> None:
        """Initializes the NetworkAnalyzer with a power grid graph.

        Args:
            graph (nx.Graph): A NetworkX graph representing the power grid.

        Raises:
            ValueError: If the graph is empty or `None`.
        """
        if graph is None or graph.number_of_nodes() == 0:
            raise ValueError("Graph cannot be empty or None")

        # Validate graph attributes
        for node, data in graph.nodes(data=True):
            if "x" not in data or "y" not in data:
                raise ValueError(f"Node {node} missing required coordinates (x, y)")

        self.graph = graph
        self._cache: Dict[str, Any] = {}  # Cache for expensive computations

    def _clear_cache(self) -> None:
        """Clear the computation cache."""
        self._cache.clear()

    def _get_cached_or_compute(self, key: str, computation: Callable[[], Any]) -> Any:
        """Get a cached value or compute and cache it.

        Args:
            key: Cache key for the computation
            computation: Function to compute the value if not cached

        Returns:
            Cached or newly computed value
        """
        if key not in self._cache:
            self._cache[key] = computation()
        return self._cache[key]

    @property
    def is_connected(self) -> bool:
        """Checks if the graph is fully connected.

        Returns:
            bool: `True` if the graph is connected, `False` otherwise.
        """
        return self._get_cached_or_compute(
            "is_connected", lambda: nx.is_connected(self.graph)
        )

    def calculate_network_metrics(
        self, include_expensive: bool = True
    ) -> Dict[str, Union[int, float, None, Tuple[np.ndarray, np.ndarray]]]:
        """Calculates key network metrics for the power grid.

        This method computes a variety of metrics to assess the structure
        and characteristics of the network, including basic graph properties,
        connectivity measures, and clustering coefficients.

        Args:
            include_expensive (bool): Whether to include computationally
                expensive metrics.

        Returns:
            Dict[str, Union[int, float, None, Tuple[np.ndarray, np.ndarray]]]:
                A dictionary containing the calculated network metrics.
        """
        metrics = {}

        # Basic metrics
        metrics["node_count"] = self.graph.number_of_nodes()
        metrics["edge_count"] = self.graph.number_of_edges()
        metrics["avg_degree"] = (
            sum(dict(self.graph.degree()).values()) / metrics["node_count"]
        )

        # Connectivity metrics
        if nx.is_connected(self.graph):
            metrics["diameter"] = nx.diameter(self.graph)
            metrics["avg_path_length"] = nx.average_shortest_path_length(self.graph)
            metrics["global_efficiency"] = nx.global_efficiency(self.graph)
        else:
            metrics["diameter"] = None
            metrics["avg_path_length"] = None
            metrics["global_efficiency"] = None

        # Graph density
        num_nodes = self.graph.number_of_nodes()
        num_edges = self.graph.number_of_edges()
        if num_nodes > 1:
            metrics["density"] = 2 * num_edges / (num_nodes * (num_nodes - 1))
        else:
            metrics["density"] = 0

        # Degree distribution
        degree_sequence = sorted([d for n, d in self.graph.degree()])
        metrics["degree_distribution"] = np.histogram(degree_sequence, bins="auto")

        # Clustering
        metrics["clustering_coeff"] = nx.average_clustering(self.graph)

        return metrics

    def find_critical_nodes(self, n: int = 5) -> Dict[str, List[Tuple[str, float]]]:
        """Identifies the most critical nodes in the network.

        This method calculates several centrality metrics (betweenness, degree,
        eigenvector, and closeness) to identify the nodes that are most
        important for the network's connectivity and operation.

        Args:
            n (int): The number of top critical nodes to return for each
                centrality measure.

        Returns:
            Dict[str, List[Tuple[str, float]]]: A dictionary that maps the
                names of the centrality measures to lists of (node_id, score)
                tuples, sorted in descending order by score.
        """
        if not nx.is_connected(self.graph):
            print(
                "Warning: Graph is not connected. Centrality measures may not be meaningful."
            )
            return {}

        centrality = {}

        # Betweenness centrality
        betweenness = nx.betweenness_centrality(self.graph)
        centrality["betweenness"] = sorted(
            betweenness.items(), key=lambda x: x[1], reverse=True
        )[:n]

        # Degree centrality
        degree = nx.degree_centrality(self.graph)
        centrality["degree"] = sorted(degree.items(), key=lambda x: x[1], reverse=True)[
            :n
        ]

        # Eigenvector centrality
        try:
            eigenvector = nx.eigenvector_centrality(self.graph)
            centrality["eigenvector"] = sorted(
                eigenvector.items(), key=lambda x: x[1], reverse=True
            )[:n]
        except nx.NetworkXError:
            print(
                "Warning: Eigenvector centrality could not be computed (graph may not be "
                "strongly connected)."
            )
            centrality["eigenvector"] = []

        # Closeness centrality
        try:
            closeness = nx.closeness_centrality(self.graph)
            centrality["closeness"] = sorted(
                closeness.items(), key=lambda x: x[1], reverse=True
            )[:n]
        except nx.NetworkXError:
            print(
                "Warning: Closeness centrality could not be computed (graph may not be "
                "strongly connected)."
            )
            centrality["closeness"] = []

        return centrality

    def calculate_graph_density(self) -> float:
        """Calculates the density of the graph.

        The density of a graph is the ratio of its actual number of edges to
        the maximum possible number of edges. A higher density indicates a
        more connected graph.

        Returns:
            float: The density of the graph, a value between 0 and 1.
        """
        num_nodes = self.graph.number_of_nodes()
        num_edges = self.graph.number_of_edges()
        if num_nodes > 1:
            return 2 * num_edges / (num_nodes * (num_nodes - 1))
        else:
            return 0

    def calculate_global_efficiency(self) -> Optional[float]:
        """Calculates the global efficiency of the graph.

        Global efficiency measures how efficiently information or power can
        be exchanged across the network. It is calculated as the average of
        the reciprocal of the shortest path lengths between all pairs of
        nodes.

        Returns:
            Optional[float]: The global efficiency of the graph, or `None` if
                the graph is disconnected.
        """
        if nx.is_connected(self.graph):
            return nx.global_efficiency(self.graph)
        else:
            return None

    def calculate_local_efficiency(self) -> Optional[float]:
        """Calculates the local efficiency of the graph.

        Local efficiency is a measure of the fault tolerance of the network.
        It quantifies how well information is exchanged within the
        neighborhood of a node when that node is removed.

        Returns:
            Optional[float]: The local efficiency of the graph, or `None` if
                the graph is disconnected.
        """
        if nx.is_connected(self.graph):
            return nx.local_efficiency(self.graph)
        else:
            return None
