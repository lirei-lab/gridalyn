"""
Creates a pandapower network from a `PowerGridGraph`.

This module provides the `PandapowerGridBuilder` class, a powerful tool for
converting a `PowerGridGraph` into a `pandapower` network. It automates the
creation of all essential power grid components, including buses, lines,
transformers, loads, and external grid connections, making it easy to move
from a geospatial grid model to a detailed power flow simulation.

The class is designed to be highly configurable, allowing users to specify
the electrical parameters of the network components through a configuration
dictionary. It also includes validation methods to ensure the consistency
and correctness of the resulting `pandapower` network.

**Where this lives.** This builder used to live under
``gridalyn.simulation.simulators.powerflow`` because that is where the
power-flow need first surfaced. Its only ``gridalyn`` dependency is
:class:`~gridalyn.twin.core.graph.PowerGridGraph`, already in ``twin`` -- it
builds a network's *topology*, which is what a network looks like, not how
it is solved. Moved down to ``gridalyn.twin.adapters`` (Phase 28, 2026-08-19)
so the twin layer finally has a real construction capability instead of only
ever adapting a network someone else already built.

**Building from source.** :func:`build_power_grid_and_network` (Phase 29,
2026-08-19) is the twin-native construction entry point: building footprints
in, a built :class:`PowerGridGraph` and :class:`pp.pandapowerNet` out, no
power-flow solve and no load-aware line sizing -- both stay
``gridalyn.simulation`` concerns.
:func:`gridalyn.simulation.simulators.powerflow.synthetic_network.build_synthetic_network_from_config`
calls this for topology, then adds the optional load-aware sizing pass and
power-flow solve on top; :class:`~gridalyn.twin.adapters.network.SyntheticPandapowerAdapter`
calls it directly so ``gridalyn.twin`` can build a network from source, not
only adapt one someone else already built.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandapower as pp
import pandas as pd
from geopy.distance import geodesic
from networkx import Graph

from gridalyn.twin.core.graph import PowerGridGraph


class PandapowerGridBuilder:
    """
    Builds a `pandapower` network from a `PowerGridGraph` instance.

    This class serves as a bridge between the geospatial grid representation
    in `PowerGridGraph` and the power flow simulation capabilities of
    `pandapower`. It provides a suite of methods for systematically
    constructing a complete `pandapower` network, including buses, lines,
    transformers, and loads, based on the topology and data defined in a
    `PowerGridGraph`.

    The builder is highly configurable, allowing users to specify the
    electrical parameters of the network components through a configuration
    dictionary. It also includes validation methods to ensure the consistency
    and correctness of the resulting `pandapower` network.

    Attributes:
        power_grid (PowerGridGraph): The `PowerGridGraph` instance containing
            the network topology.
        net (pp.pandapowerNet): The `pandapower` network being built.
        config (Dict): A configuration dictionary for the network components.
        node_to_bus_mapping (Dict[str, int]): A mapping from graph node names
            to `pandapower` bus indices.
    """

    def __init__(self, power_grid: "PowerGridGraph", config: Dict) -> None:
        """Initializes the PandapowerGridBuilder.

        Args:
            power_grid (PowerGridGraph): An instance of `PowerGridGraph`
                containing the network topology.
            config (Dict): A configuration dictionary for the network
                components, including buses, lines, and transformers.

        Raises:
            ValueError: If the configuration dictionary is missing any
                required sections.
        """
        # Validate config structure
        required_sections = ["buses", "lines", "transformers"]
        if not all(section in config for section in required_sections):
            raise ValueError(
                f"Config must contain all required sections: {required_sections}"
            )

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        self.power_grid = power_grid
        self.net = pp.create_empty_network()
        self.config = config
        self.node_to_bus_mapping: Dict[str, int] = {}

    def _ensure_transformer_std_type(
        self,
        transformer_config: Dict,
        high_level: str,
        low_level: str,
    ) -> None:
        """Register configured custom transformer types before bulk creation."""
        std_type = transformer_config["std_type"]
        available = pp.available_std_types(self.net, "trafo")
        if std_type in available.index:
            return

        if not transformer_config.get("custom_type", False):
            return

        sn_mva = float(transformer_config["capacity_kva"]) / 1000.0
        params = {
            "sn_mva": sn_mva,
            "vn_hv_kv": float(self.config["buses"][high_level]["voltage_kv"]),
            "vn_lv_kv": float(self.config["buses"][low_level]["voltage_kv"]),
            "vk_percent": float(transformer_config.get("vk_percent", 8.5)),
            "vkr_percent": float(transformer_config.get("vkr_percent", 0.45)),
            "pfe_kw": float(transformer_config.get("pfe_kw", 10.0)),
            "i0_percent": float(transformer_config.get("i0_percent", 0.08)),
            "shift_degree": float(transformer_config.get("shift_degree", 0)),
            "vector_group": transformer_config.get("vector_group", "Dyn11"),
            "tap_side": transformer_config.get("tap_side", "hv"),
            "tap_neutral": int(transformer_config.get("tap_neutral", 0)),
            "tap_min": int(transformer_config.get("tap_min", -8)),
            "tap_max": int(transformer_config.get("tap_max", 8)),
            "tap_step_percent": float(transformer_config.get("tap_step_percent", 1.25)),
            "tap_step_degree": float(transformer_config.get("tap_step_degree", 0)),
            "tap_pos": int(transformer_config.get("tap_pos", 0)),
            "tap_phase_shifter": bool(
                transformer_config.get("tap_phase_shifter", False)
            ),
        }
        pp.create_std_type(self.net, params, name=std_type, element="trafo")

    def _build_buses_and_lines(
        self, graph: Optional[Graph], voltage_level: str
    ) -> Tuple[int, int]:
        """Generic method to build buses and lines for any voltage level.

        Args:
            graph: NetworkX graph containing the network topology
            voltage_level: Voltage level identifier ('lv', 'mv', or 'hv')

        Returns:
            Tuple containing count of added buses and lines

        Raises:
            ValueError: If graph is None or voltage level is invalid
        """
        if graph is None:
            raise ValueError(
                f"graph_{voltage_level}_buses is not initialized in the "
                "PowerGridGraph object."
            )

        if voltage_level not in ["lv", "mv", "hv"]:
            raise ValueError(f"Invalid voltage level: {voltage_level}")

        bus_config = self.config["buses"][voltage_level]
        line_config = self.config["lines"][voltage_level]

        node_to_bus_mapping = {}

        # Collect data for vectorized bus creation
        valid_nodes = []
        geodata_list = []
        for node, data in graph.nodes(data=True):
            if data.get("cimclass") == "cim.ConnectivityNode":
                valid_nodes.append(node)
                geodata_list.append((data["x"], data["y"]))

        if valid_nodes:
            self.logger.info(
                f"Vectorizing creation of {len(valid_nodes)} {voltage_level.upper()} buses..."
            )
            bus_indices = pp.create_buses(
                self.net,
                len(valid_nodes),
                vn_kv=bus_config["voltage_kv"],
                name=valid_nodes,
                type=bus_config["type"],
                geodata=geodata_list,
            )
            node_to_bus_mapping = dict(zip(valid_nodes, bus_indices, strict=True))
            self.node_to_bus_mapping.update(node_to_bus_mapping)

        # Collect data for vectorized line creation
        from_buses = []
        to_buses = []
        lengths_km = []
        names = []

        for source, target, _edge_data in graph.edges(data=True):
            if source in node_to_bus_mapping and target in node_to_bus_mapping:
                from_buses.append(node_to_bus_mapping[source])
                to_buses.append(node_to_bus_mapping[target])

                from_pos = (graph.nodes[source]["y"], graph.nodes[source]["x"])
                to_pos = (graph.nodes[target]["y"], graph.nodes[target]["x"])
                length_km = max(
                    geodesic(from_pos, to_pos).meters / 1000,
                    line_config["min_length_km"],
                )
                lengths_km.append(length_km)
                names.append(f"{voltage_level.upper()}_Line_{source}_to_{target}")

        added_lines = len(from_buses)

        if added_lines > 0:
            self.logger.info(
                f"Vectorizing creation of {added_lines} {voltage_level.upper()} lines..."
            )
            pp.create_lines(
                self.net,
                from_buses,
                to_buses,
                length_km=lengths_km,
                std_type=line_config["std_type"],
                name=names,
            )

        self.logger.info(
            f"Successfully added {len(node_to_bus_mapping)} {voltage_level.upper()} buses and "
            f"{added_lines} {voltage_level.upper()} lines."
        )

        return len(node_to_bus_mapping), added_lines

    def build_lv_buses_and_lines(self) -> Tuple[int, int]:
        """Builds the LV buses and lines in the `pandapower` network.

        Returns:
            Tuple[int, int]: A tuple containing the number of added buses
                and lines.
        """
        return self._build_buses_and_lines(self.power_grid.graph_lv_buses, "lv")

    def build_mv_buses_and_lines(self) -> Tuple[int, int]:
        """Builds the MV buses and lines in the `pandapower` network.

        Returns:
            Tuple[int, int]: A tuple containing the number of added buses
                and lines.
        """
        return self._build_buses_and_lines(self.power_grid.graph_mv_buses, "mv")

    def build_hv_buses_and_lines(self) -> Tuple[int, int]:
        """Builds the HV buses and lines in the `pandapower` network.

        Returns:
            Tuple[int, int]: A tuple containing the number of added buses
                and lines.
        """
        return self._build_buses_and_lines(self.power_grid.graph_hv_buses, "hv")

    def _build_transformers(
        self,
        high_graph: Optional[Graph],
        low_graph: Optional[Graph],
        high_level: str,
        low_level: str,
    ) -> List[str]:
        """Generic method to build transformers between voltage levels.

        Args:
            high_graph: NetworkX graph containing the higher voltage level topology
            low_graph: NetworkX graph containing the lower voltage level topology
            high_level: Higher voltage level identifier ('hv' or 'mv')
            low_level: Lower voltage level identifier ('mv' or 'lv')

        Returns:
            List of created transformer names

        Raises:
            ValueError: If graphs are None or voltage levels are invalid
        """
        if high_graph is None or low_graph is None:
            raise ValueError(
                f"Both graph_{high_level}_buses and graph_{low_level}_buses must be "
                "initialized in the PowerGridGraph object."
            )

        valid_pairs = [("hv", "mv"), ("mv", "lv")]
        if (high_level, low_level) not in valid_pairs:
            raise ValueError(
                f"Invalid voltage level pair: {high_level}-{low_level}. "
                f"Must be one of {valid_pairs}"
            )

        # Define node types based on voltage levels
        high_node_type = f"{high_level}_bus"
        low_node_type = f"{low_level}_feeder"

        high_transformer_nodes = {
            node: data
            for node, data in high_graph.nodes(data=True)
            if data.get("type") == high_node_type
        }
        low_transformer_nodes = {
            node: data
            for node, data in low_graph.nodes(data=True)
            if data.get("type") == low_node_type
        }

        transformer_config = self.config["transformers"][f"{low_level}_{high_level}"]
        self._ensure_transformer_std_type(transformer_config, high_level, low_level)
        # Pre-calculate potential transformer pairs based on cluster matching
        potential_pairs = [
            (high_node, low_node)
            for high_node, high_data in high_transformer_nodes.items()
            for low_node, low_data in low_transformer_nodes.items()
            if high_data.get("child") == low_data.get("cluster")
        ]

        added_transformers = 0

        # Gather valid pairs
        hv_buses = []
        lv_buses = []
        names = []

        for high_node, low_node in potential_pairs:
            high_bus = self.node_to_bus_mapping.get(high_node)
            low_bus = self.node_to_bus_mapping.get(low_node)

            if high_bus is not None and low_bus is not None:
                hv_buses.append(high_bus)
                lv_buses.append(low_bus)
                names.append(f"Transformer_{high_node}_to_{low_node}")

        added_transformers = len(hv_buses)

        if added_transformers > 0:
            self.logger.info(
                f"Vectorizing creation of {added_transformers} "
                f"{high_level.upper()}-{low_level.upper()} transformers..."
            )

            # Using single dataframe concat methodology to mass-insert transformers
            transformer_df = pd.DataFrame(
                {
                    "hv_bus": hv_buses,
                    "lv_bus": lv_buses,
                    "std_type": transformer_config["std_type"],
                    "name": names,
                    "in_service": True,
                    "parallel": 1,
                    "df": 1.0,
                    "tap_pos": float("nan"),
                }
            )

            # Retrieve trafo specs to populate native sn_mva, vn_hv, vn_lv etc
            std_type_params = pp.std_types.load_std_type(
                self.net, transformer_config["std_type"], "trafo"
            )

            # Combine the parameters so they are written perfectly via pp.create_transformer
            for key, val in std_type_params.items():
                transformer_df[key] = val

            self.net.trafo = pd.concat(
                [self.net.trafo, transformer_df], ignore_index=True
            )

            # Update pp types/dtypes correctly
            self.net.trafo["in_service"] = self.net.trafo["in_service"].astype(bool)
            tap_phase = self.net.trafo.get("tap_phase_shifter")
            if tap_phase is None:
                self.net.trafo["tap_phase_shifter"] = False
            else:
                tap_phase = tap_phase.copy()
                tap_phase.loc[tap_phase.isna()] = False
                self.net.trafo["tap_phase_shifter"] = tap_phase.astype(bool)

        self.logger.info(
            f"Successfully added {added_transformers} {high_level.upper()}-{low_level.upper()} "
            "transformers."
        )

        return names

    def build_lv_mv_power_transformers(self) -> List[str]:
        """Builds the LV-MV power transformers in the `pandapower` network.

        Returns:
            List[str]: A list of the names of the created transformers.

        Raises:
            ValueError: If the required graphs have not been initialized.
        """
        return self._build_transformers(
            self.power_grid.graph_mv_buses, self.power_grid.graph_lv_buses, "mv", "lv"
        )

    def build_mv_hv_power_transformers(self) -> List[str]:
        """Builds the MV-HV power transformers in the `pandapower` network.

        Returns:
            List[str]: A list of the names of the created transformers.

        Raises:
            ValueError: If the required graphs have not been initialized.
        """
        return self._build_transformers(
            self.power_grid.graph_hv_buses, self.power_grid.graph_mv_buses, "hv", "mv"
        )

    def connect_hv_bus_to_ext_grid(self) -> List[int]:
        """Connects the HV buses to the external grid.

        Returns:
            List[int]: A list of the indices of the created external grid
                connections.

        Raises:
            ValueError: If the HV graph has not been initialized or if the
                buses are not found.
        """
        if self.power_grid.graph_hv_buses is None:
            raise ValueError(
                "graph_hv_buses is not initialized in the PowerGridGraph " "object."
            )

        hv_graph = self.power_grid.graph_hv_buses

        hv_substation_nodes = {
            node: data
            for node, data in hv_graph.nodes(data=True)
            if data.get("type") == "hv_feeder"
        }

        ext_grids = []
        added_ext_grids = 0
        for hv_node, _hv_data in hv_substation_nodes.items():
            hv_bus = self.node_to_bus_mapping.get(hv_node)
            if hv_bus is None:
                raise ValueError(
                    f"Bus not found for HV substation node {hv_node!r}. "
                    "Ensure HV buses are created."
                )

            ext_grid = pp.create_ext_grid(
                self.net,
                bus=hv_bus,
                vm_pu=1.0,
                va_degree=0.0,
                name=f"External Grid {hv_node}",
            )
            ext_grids.append(ext_grid)
            added_ext_grids += 1

        self.logger.debug(f"Connected {added_ext_grids} HV buses to the external grid.")
        return ext_grids

    def build_loads_from_graph_buildings(self) -> Tuple[int, List[str]]:
        """Builds loads in the `pandapower` network based on building data.

        Returns:
            Tuple[int, List[str]]: A tuple containing the number of loads
                added and a list of any building nodes that could not be
                matched to a bus.

        Raises:
            ValueError: If the building graph has not been initialized.
        """
        graph = self.power_grid.graph_buildings
        if graph is None:
            raise ValueError(
                "graph_buildings is not initialized in the PowerGridGraph " "object."
            )

        unmatched_buildings = []

        lv_buses = []
        p_mws = []
        q_mvars = []
        names = []

        for building_node, building_data in graph.nodes(data=True):
            if building_data.get("type") != "building":
                continue

            # Reconstruct the lv_bus name from the building node ID
            lv_bus_name = building_node.replace("building", "lv_bus")
            lv_bus_index = self.node_to_bus_mapping.get(lv_bus_name)

            if lv_bus_index is None:
                unmatched_buildings.append(building_node)
                continue

            lv_buses.append(lv_bus_index)
            p_mws.append(building_data.get("p_mw", 0))
            q_mvars.append(building_data.get("q_mvar", 0))
            names.append(f"Load_{building_node}")

        load_count = len(lv_buses)

        if load_count > 0:
            self.logger.info(f"Vectorizing creation of {load_count} building loads...")
            # Create the pandapower loads natively in mass arrays
            pp.create_loads(
                self.net,
                buses=lv_buses,
                p_mw=p_mws,
                q_mvar=q_mvars,
                name=names,
            )

        # Log summary
        self.logger.info(f"Added {load_count} loads to the pandapower network.")
        if unmatched_buildings:
            self.logger.warning(
                f"{len(unmatched_buildings)} buildings could not be matched "
                f"to an LV bus: {unmatched_buildings}"
            )
        return load_count, unmatched_buildings

    def create_bus_geodata(self) -> None:
        """Creates the bus_geodata table from the graph nodes."""
        bus_coords = []
        for node, bus_idx in self.node_to_bus_mapping.items():
            graph = None
            if "lv" in node:
                graph = self.power_grid.graph_lv_buses
            elif "mv" in node:
                graph = self.power_grid.graph_mv_buses
            elif "hv" in node:
                graph = self.power_grid.graph_hv_buses

            if graph and node in graph.nodes:
                node_data = graph.nodes[node]
                bus_coords.append(
                    {"bus": bus_idx, "x": node_data["x"], "y": node_data["y"]}
                )

        if bus_coords:
            bus_geodata = pd.DataFrame(bus_coords).set_index("bus")
            self.net.bus_geodata = bus_geodata

    def get_pandapower_net(self) -> pp.pandapowerNet:
        """Returns the constructed `pandapower` network.

        Returns:
            pp.pandapowerNet: The complete `pandapower` network instance.
        """
        return self.net

    def validate_network_consistency(self) -> bool:
        """Validates the consistency of the `pandapower` network.

        This method performs a comprehensive validation by checking that all
        nodes and edges in the underlying graphs have corresponding buses and
        lines in the `pandapower` network, and that there are no orphaned
        elements.

        Returns:
            bool: `True` if the validation passes, `False` otherwise.

        Raises:
            ValueError: If any of the required graphs have not been
                initialized.
        """
        if (
            self.power_grid.graph_lv_buses is None
            or self.power_grid.graph_mv_buses is None
            or self.power_grid.graph_hv_buses is None
        ):
            raise ValueError(
                "All graph types (LV, MV, HV) must be initialized in the "
                "PowerGridGraph object."
            )

        pp_bus_names = set(self.net.bus["name"].values)
        bus_index_to_name = self.net.bus["name"].to_dict()
        pp_lines = set(
            (
                bus_index_to_name[self.net.line.at[idx, "from_bus"]],
                bus_index_to_name[self.net.line.at[idx, "to_bus"]],
            )
            for idx in self.net.line.index
        )

        lv_graph = self.power_grid.graph_lv_buses
        mv_graph = self.power_grid.graph_mv_buses
        hv_graph = self.power_grid.graph_hv_buses

        lv_node_names = {node for node in lv_graph.nodes()}
        mv_node_names = {node for node in mv_graph.nodes()}
        hv_node_names = {node for node in hv_graph.nodes()}

        lv_edges = {(source, target) for source, target in lv_graph.edges()}
        mv_edges = {(source, target) for source, target in mv_graph.edges()}
        hv_edges = {(source, target) for source, target in hv_graph.edges()}

        all_graph_node_names = lv_node_names | mv_node_names | hv_node_names
        all_graph_edges = lv_edges | mv_edges | hv_edges

        unmatched_buses = pp_bus_names - all_graph_node_names
        unmatched_graph_nodes = all_graph_node_names - pp_bus_names

        unmatched_lines = pp_lines - all_graph_edges
        unmatched_graph_edges = all_graph_edges - pp_lines

        if (
            not unmatched_buses
            and not unmatched_graph_nodes
            and not unmatched_lines
            and not unmatched_graph_edges
        ):
            self.logger.info(
                "Validation successful: All buses and lines match between "
                "the network and the graphs."
            )
            return True
        else:
            self.logger.error("Validation failed:")
            if unmatched_buses:
                self.logger.error(
                    f"Buses in pandapower network not matching any graph "
                    f"nodes: {unmatched_buses}"
                )
            if unmatched_graph_nodes:
                self.logger.error(
                    f"Nodes in the graphs not matching any pandapower buses: "
                    f"{unmatched_graph_nodes}"
                )
            if unmatched_lines:
                self.logger.error(
                    f"Lines in pandapower network not matching any graph "
                    f"edges: {unmatched_lines}"
                )
            if unmatched_graph_edges:
                self.logger.error(
                    f"Edges in the graphs not matching any pandapower lines: "
                    f"{unmatched_graph_edges}"
                )
            return False


def build_power_grid_and_network(
    *,
    footprints_path: str | Path,
    config: Dict[str, Any],
    clustering_crs: str | int | None = "auto",
) -> Tuple[PowerGridGraph, pp.pandapowerNet]:
    """Build a `PowerGridGraph` and `pandapower` network from building footprints.

    Pure topology construction: extracts building centroids, builds the
    LV/MV/HV graph hierarchy, and builds buses/lines/transformers/loads via
    `PandapowerGridBuilder` under the default uniform line-sizing mode. No
    power-flow solve and no load-aware line sizing -- both are
    `gridalyn.simulation`-layer concerns; see
    `gridalyn.simulation.simulators.powerflow.synthetic_network` for the full
    orchestration that adds them.

    Args:
        footprints_path: GeoJSON file with building polygons.
        config: Grid configuration mapping (buses/lines/transformers/loads).
        clustering_crs: Metric CRS for clustering. `"auto"` estimates a local
            UTM CRS from the footprint layer. Graph geodata stays
            longitude/latitude.

    Returns:
        `(power_grid, net)`. `power_grid.building_data` carries the extracted
        building count and coordinates for a caller that needs them.
    """
    power_grid = PowerGridGraph()
    power_grid.extract_building_centers_and_areas(
        str(Path(footprints_path)), clustering_crs=clustering_crs
    )
    _build_graph_hierarchy(power_grid, config)
    net = _build_uniform_pandapower_network(power_grid, config)
    return power_grid, net


def _build_graph_hierarchy(power_grid: PowerGridGraph, config: Dict[str, Any]) -> None:
    """Build and merge the LV/MV/HV `PowerGridGraph` hierarchy in place."""
    loads = config["loads"]
    transformers = config["transformers"]
    max_load_per_building = float(loads["max_load_per_building"])
    diversity_factor_lv = float(loads.get("diversity_factor_lv", 5.0))
    diversity_factor_mv = float(loads.get("diversity_factor_mv", 1.3))
    diversity_factor_hv = float(loads.get("diversity_factor_hv", 1.1))
    mv_lv_capacity = float(transformers["lv_mv"]["capacity_kva"])
    hv_mv_capacity = float(transformers["mv_hv"]["capacity_kva"])
    utilization = float(transformers["lv_mv"].get("utilization_margin", 0.8))

    power_grid.create_lv_graph(
        max_load_per_building=max_load_per_building,
        mv_lv_transformer_capacity=mv_lv_capacity,
        capacity_utilization_factor=utilization,
        diversity_factor_lv=diversity_factor_lv,
    )
    power_grid.extend_graph_with_cim("graph_lv_buses")
    power_grid.create_building_graph(
        max_load_per_building=max_load_per_building,
        diversity_factor_lv=diversity_factor_lv,
    )

    power_grid.create_mv_graph(
        mv_lv_transformer_capacity=mv_lv_capacity,
        hv_mv_transformer_capacity=hv_mv_capacity,
        diversity_factor_mv=diversity_factor_mv,
    )
    power_grid.extend_graph_with_cim("graph_mv_buses")

    hv_substation_capacity = (
        len(power_grid.labels_mv) if power_grid.labels_mv is not None else 1
    ) * hv_mv_capacity
    power_grid.create_hv_substation_graph(
        hv_mv_transformer_capacity=hv_mv_capacity,
        hv_substation_capacity=hv_substation_capacity,
        diversity_factor_hv=diversity_factor_hv,
    )
    power_grid.extend_graph_with_cim("graph_hv_buses")
    power_grid.merge_graphs()


def _build_uniform_pandapower_network(
    power_grid: PowerGridGraph,
    config: Dict[str, Any],
) -> pp.pandapowerNet:
    """Build the `pandapower` network under the default uniform sizing mode.

    Load-aware line sizing is an opt-in `gridalyn.simulation`-layer post-pass
    (`config["lines"]["sizing"]["mode"] == "load_aware"`) applied by the
    caller, not here -- keeping this function's only dependency
    `PandapowerGridBuilder`, already in `twin`.
    """
    pp_config = {
        "buses": config["buses"],
        "lines": config["lines"],
        "transformers": {
            "lv_mv": dict(config["transformers"]["lv_mv"]),
            "mv_hv": dict(config["transformers"]["mv_hv"]),
        },
    }
    builder = PandapowerGridBuilder(power_grid=power_grid, config=pp_config)
    builder.build_lv_buses_and_lines()
    builder.build_mv_buses_and_lines()
    builder.build_hv_buses_and_lines()
    builder.build_loads_from_graph_buildings()
    builder.validate_network_consistency()
    builder.build_lv_mv_power_transformers()
    builder.build_mv_hv_power_transformers()
    builder.connect_hv_bus_to_ext_grid()
    builder.create_bus_geodata()
    return builder.get_pandapower_net()
