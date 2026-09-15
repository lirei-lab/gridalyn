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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Tuple

import numpy as np
import pandapower as pp
import pandas as pd
from networkx import Graph

from gridalyn.twin.core.graph import PowerGridGraph, geodesic_length_m

if TYPE_CHECKING:  # pragma: no cover - typing only
    from gridalyn.twin.geoprocess.streets import StreetSnapper


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
            if data.get("cimclass") == "cim:ConnectivityNode":
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

                length_km = max(
                    geodesic_length_m(graph.nodes[source], graph.nodes[target]) / 1000,
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
        vm_pu = external_grid_vm_pu(self.config)
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
                vm_pu=vm_pu,
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
    snap_transformers_to_streets: bool | None = None,
    lv_assignment: str | None = None,
    block_penalty_km2: float | None = None,
) -> Tuple[PowerGridGraph, pp.pandapowerNet]:
    """Build a `PowerGridGraph` and `pandapower` network from building footprints.

    Pure topology construction: extracts building centroids, builds the
    LV/MV/HV graph hierarchy, and builds buses/lines/transformers/loads via
    `PandapowerGridBuilder` under the default uniform line-sizing mode. No
    power-flow solve and no load-aware line sizing -- both are
    `gridalyn.simulation`-layer concerns; see
    `gridalyn.simulation.simulators.powerflow.synthetic_network` for the full
    orchestration that adds them.

    The partition and siting options can be declared in ``config["topology"]``
    (keys in :data:`TOPOLOGY_KEYS`) and the slack setpoint in
    ``config["external_grid"]["vm_pu"]``, so a study pins them as data and a
    change to them changes the config hash every cache keys on. An explicit
    argument here overrides the config; a config without those blocks builds
    exactly what it built before they existed.

    Args:
        footprints_path: GeoJSON file with building polygons.
        config: Grid configuration mapping (buses/lines/transformers/loads, and
            optionally topology/external_grid).
        clustering_crs: Metric CRS for clustering. `"auto"` estimates a local
            UTM CRS from the footprint layer. Graph geodata stays
            longitude/latitude.
        snap_transformers_to_streets: When true, site every transformer on the
            nearest street instead of on the building it serves. Requires the
            `geo` extra and a network fetch. **Defaults to false, and the
            default is load-bearing**: the transformer-to-building link is a
            pandapower line, pinned today at `min_length_km` because the two
            nodes coincide. Siting on the street turns that stub into roughly
            20 m of conductor and moves the power flow, so enabling this is a
            deliberate re-base, not a display change. ``None`` takes the config's
            value.
        lv_assignment: How buildings are shared among MV/LV transformers, one of
            :data:`LV_ASSIGNMENT_METHODS`. ``"kmeans"`` (the default) partitions
            by geometry alone, which on the shipped footprints leaves 43 of 193
            transformers above 100% at the declared envelope. ``"capacitated"``
            caps every transformer at the building count it was sized for.
            **Defaults to kmeans, and the default is load-bearing**: changing
            the partition changes which buildings share a transformer, so
            enabling it is a deliberate re-base. ``None`` takes the config's
            value.
        block_penalty_km2: With ``"capacitated"``, the penalty in km^2 of
            squared distance for serving a building from a cluster centred on
            another street block. Capacity alone pushes edge buildings across
            the street; ``0.005`` was measured to recover that while keeping
            every transformer within its limit. Needs streets: a declared
            ``topology.street_layer`` file, or the ``geo`` extra and a live
            fetch. ``None`` takes the config's value, else ``0.0``.

    Returns:
        `(power_grid, net)`. `power_grid.building_data` carries the extracted
        building count and coordinates for a caller that needs them.
    """
    options = resolve_topology_options(
        config,
        footprints_path=footprints_path,
        lv_assignment=lv_assignment,
        block_penalty_km2=block_penalty_km2,
        snap_transformers_to_streets=snap_transformers_to_streets,
    )
    external_grid_vm_pu(config)  # refuse a bad setpoint before any IO
    power_grid = PowerGridGraph()
    power_grid.extract_building_centers_and_areas(
        str(Path(footprints_path)), clustering_crs=clustering_crs
    )
    block_ids = None
    if options.uses_streets:
        snapper = _street_snapper_for(power_grid, footprints_path, options)
        if options.snap_transformers_to_streets:
            power_grid.street_snapper = snapper
        if options.block_penalty_km2 > 0:
            assert power_grid.building_centroids is not None  # extracted above
            block_ids = snapper.block_ids(power_grid.building_centroids)
    _build_graph_hierarchy(power_grid, config, options=options, block_ids=block_ids)
    net = _build_uniform_pandapower_network(power_grid, config)
    return power_grid, net


LV_ASSIGNMENT_METHODS = ("kmeans", "capacitated")
"""Accepted values of ``build_power_grid_and_network(lv_assignment=...)``."""


def _check_lv_assignment(lv_assignment: str, block_penalty_km2: float) -> bool:
    """Validate the LV partition options before any file is read.

    Args:
        lv_assignment: The requested partition method.
        block_penalty_km2: The requested block penalty.

    Returns:
        Whether the partition is capacity-constrained.

    Raises:
        ValueError: If the method is unknown, or a block penalty is requested
            for plain K-means, which has no assignment step to add it to.
    """
    if lv_assignment not in LV_ASSIGNMENT_METHODS:
        raise ValueError(
            f"unknown lv_assignment {lv_assignment!r} "
            f"(known: {', '.join(LV_ASSIGNMENT_METHODS)})"
        )
    if block_penalty_km2 and lv_assignment != "capacitated":
        raise ValueError(
            "block_penalty_km2 only applies to lv_assignment='capacitated'; "
            "plain K-means has no assignment step to add the penalty to"
        )
    return lv_assignment == "capacitated"


TOPOLOGY_KEYS = (
    "block_penalty_km2",
    "lv_assignment",
    "max_customers_per_transformer",
    "note",
    "snap_transformers_to_streets",
    "street_layer",
)
"""Keys ``config["topology"]`` may declare; any other key is refused by name.

``note`` carries no behaviour: JSON has no comments, and a declared limit should
say where it comes from, the way transformer entries already carry a ``note``.
"""

EXTERNAL_GRID_KEYS = ("note", "vm_pu")
"""Keys ``config["external_grid"]`` may declare."""


@dataclass(frozen=True)
class TopologyOptions:
    """How a build partitions buildings and where it sites transformers.

    Resolved once by :func:`resolve_topology_options`, so the builder and the
    validation report cannot disagree about what was built.

    Attributes:
        lv_assignment: One of :data:`LV_ASSIGNMENT_METHODS`.
        max_customers_per_transformer: Declared building limit, or ``None`` for
            the sized count.
        block_penalty_km2: Penalty for leaving a cluster's dominant block.
        snap_transformers_to_streets: Whether transformers sit on the street.
        street_layer_path: Declared street layer, resolved against the
            footprints file's directory; ``None`` means a live fetch.
        street_layer_sha256: The digest the config declares for that layer.
    """

    lv_assignment: str = "kmeans"
    max_customers_per_transformer: Optional[int] = None
    block_penalty_km2: float = 0.0
    snap_transformers_to_streets: bool = False
    street_layer_path: Optional[Path] = None
    street_layer_sha256: Optional[str] = None

    @property
    def capacitated(self) -> bool:
        """Whether the LV partition honours a per-transformer limit."""
        return self.lv_assignment == "capacitated"

    @property
    def uses_streets(self) -> bool:
        """Whether the build needs a street layer at all."""
        return self.snap_transformers_to_streets or self.block_penalty_km2 > 0

    def to_report(self) -> Dict[str, Any]:
        """Return the options as a JSON-ready mapping for the validation report.

        Returns:
            The resolved options, with the street layer's path and digest.
        """
        street_layer = None
        if self.street_layer_path is not None:
            street_layer = {
                "path": str(self.street_layer_path),
                "sha256": self.street_layer_sha256,
            }
        return {
            "lv_assignment": self.lv_assignment,
            "max_customers_per_transformer": self.max_customers_per_transformer,
            "block_penalty_km2": self.block_penalty_km2,
            "snap_transformers_to_streets": self.snap_transformers_to_streets,
            "street_layer": street_layer,
        }


def resolve_topology_options(
    config: Mapping[str, Any],
    *,
    footprints_path: str | Path,
    lv_assignment: str | None = None,
    block_penalty_km2: float | None = None,
    snap_transformers_to_streets: bool | None = None,
) -> TopologyOptions:
    """Resolve the topology options a build uses.

    An explicit argument wins over ``config["topology"]``, which wins over the
    defaults: plain K-means, no streets. Validated before any file is read.

    Args:
        config: The grid configuration.
        footprints_path: The footprint GeoJSON; a relative
            ``street_layer.path`` resolves against its directory.
        lv_assignment: Explicit partition method, or ``None``.
        block_penalty_km2: Explicit block penalty, or ``None``.
        snap_transformers_to_streets: Explicit siting choice, or ``None``.

    Returns:
        The resolved :class:`TopologyOptions`.

    Raises:
        ValueError: On an unknown key, a wrong type, or options that contradict
            each other, naming the key and the remedy.
    """
    block = _topology_block(config)
    method = str(_pick(lv_assignment, block, "lv_assignment", "kmeans"))
    penalty = float(_pick(block_penalty_km2, block, "block_penalty_km2", 0.0))
    snap = _pick(
        snap_transformers_to_streets, block, "snap_transformers_to_streets", False
    )
    if not isinstance(snap, bool):
        raise ValueError(
            "config.topology.snap_transformers_to_streets must be true or false, "
            f"found {type(snap).__name__}"
        )
    _check_lv_assignment(method, penalty)
    street_path, street_sha256 = _street_layer(
        block, footprints_path, uses_streets=snap or penalty > 0
    )
    return TopologyOptions(
        lv_assignment=method,
        max_customers_per_transformer=_max_customers(block, method),
        block_penalty_km2=penalty,
        snap_transformers_to_streets=snap,
        street_layer_path=street_path,
        street_layer_sha256=street_sha256,
    )


def external_grid_vm_pu(config: Mapping[str, Any]) -> float:
    """Return the slack setpoint a build uses, ``1.0`` pu unless declared.

    Args:
        config: The grid configuration.

    Returns:
        ``config["external_grid"]["vm_pu"]``, or ``1.0``.

    Raises:
        ValueError: On an unknown key, or a setpoint outside [0.9, 1.1] pu.
    """
    block = config.get("external_grid", {})
    if not isinstance(block, Mapping):
        raise ValueError(
            f"config.external_grid must be a mapping, found {type(block).__name__}"
        )
    unknown = sorted(set(block) - set(EXTERNAL_GRID_KEYS))
    if unknown:
        raise ValueError(
            f"config.external_grid has unsupported keys: {', '.join(unknown)} "
            f"(supported: {', '.join(EXTERNAL_GRID_KEYS)})"
        )
    vm_pu = float(block.get("vm_pu", 1.0))
    if not 0.9 <= vm_pu <= 1.1:
        raise ValueError(
            f"config.external_grid.vm_pu must lie in [0.9, 1.1] pu, found {vm_pu}"
        )
    return vm_pu


def _topology_block(config: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return ``config["topology"]``, refusing unknown keys by name.

    Args:
        config: The grid configuration.

    Returns:
        The block, empty when absent.

    Raises:
        ValueError: If it is not a mapping or carries an unsupported key.
    """
    block = config.get("topology", {})
    if not isinstance(block, Mapping):
        raise ValueError(
            f"config.topology must be a mapping, found {type(block).__name__}"
        )
    unknown = sorted(set(block) - set(TOPOLOGY_KEYS))
    if unknown:
        raise ValueError(
            f"config.topology has unsupported keys: {', '.join(unknown)} "
            f"(supported: {', '.join(TOPOLOGY_KEYS)})"
        )
    return block


def _pick(explicit: Any, block: Mapping[str, Any], key: str, default: Any) -> Any:
    """Return an explicit value, else the block's, else the default.

    Args:
        explicit: The caller's argument, ``None`` when not given.
        block: ``config["topology"]``.
        key: The key to read.
        default: The value when neither declares one.

    Returns:
        The resolved value.
    """
    return explicit if explicit is not None else block.get(key, default)


def _max_customers(block: Mapping[str, Any], method: str) -> Optional[int]:
    """Return the declared per-transformer limit, validated.

    Args:
        block: ``config["topology"]``.
        method: The resolved partition method.

    Returns:
        The limit, or ``None`` when not declared.

    Raises:
        ValueError: If it is not a positive integer, or K-means is in use.
    """
    value = block.get("max_customers_per_transformer")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(
            "config.topology.max_customers_per_transformer must be a positive "
            f"integer, found {value!r}"
        )
    if method != "capacitated":
        raise ValueError(
            "config.topology.max_customers_per_transformer only applies to "
            "lv_assignment='capacitated'; K-means has no limit to honour"
        )
    return int(value)


def _street_layer(
    block: Mapping[str, Any], footprints_path: str | Path, *, uses_streets: bool
) -> Tuple[Optional[Path], Optional[str]]:
    """Return the declared street layer's resolved path and digest.

    Args:
        block: ``config["topology"]``.
        footprints_path: The footprint GeoJSON the path is relative to.
        uses_streets: Whether any option needs streets.

    Returns:
        ``(path, sha256)``, or ``(None, None)`` when not declared.

    Raises:
        ValueError: If declared without a use, or without ``path``/``sha256``.
    """
    declared = block.get("street_layer")
    if declared is None:
        return None, None
    if not uses_streets:
        raise ValueError(
            "config.topology.street_layer is declared but nothing uses it: set "
            "block_penalty_km2 or snap_transformers_to_streets, or remove it"
        )
    if not isinstance(declared, Mapping) or not declared.get("path"):
        raise ValueError(
            "config.topology.street_layer must be a mapping with 'path' and "
            '\'sha256\', e.g. {"path": "streets.geojson", "sha256": "<hex>"}'
        )
    if not declared.get("sha256"):
        raise ValueError(
            "config.topology.street_layer.sha256 is required: the digest is what "
            "makes a changed layer change the config every cache keys on"
        )
    path = Path(str(declared["path"]))
    if not path.is_absolute():
        path = Path(footprints_path).parent / path
    return path, str(declared["sha256"])


def _street_snapper_for(
    power_grid: PowerGridGraph,
    footprints_path: str | Path,
    options: TopologyOptions,
) -> "StreetSnapper":
    """Return the street snapper a build uses: the declared layer, or a fetch.

    Args:
        power_grid: The graph whose buildings have already been extracted, so
            its resolved `clustering_crs` can be reused.
        footprints_path: The GeoJSON the buildings came from.
        options: The resolved topology options.

    Returns:
        A `StreetSnapper` measuring in the same metric CRS the clustering used,
        so siting, blocks and clustering cannot disagree about distance.
    """
    import geopandas as gpd

    from gridalyn.twin.geoprocess.streets import (
        BLOCK_BBOX_PADDING_DEG,
        DEFAULT_BBOX_PADDING_DEG,
        load_street_snapper,
        load_street_snapper_from_file,
    )

    footprints = None
    metric_crs = power_grid.clustering_crs
    if metric_crs is None:
        footprints = gpd.read_file(str(Path(footprints_path)))
        metric_crs = str(footprints.estimate_utm_crs())
    if options.street_layer_path is not None:
        return load_street_snapper_from_file(
            options.street_layer_path,
            metric_crs=metric_crs,
            expected_sha256=options.street_layer_sha256,
        )
    if footprints is None:
        footprints = gpd.read_file(str(Path(footprints_path)))
    padding = (
        BLOCK_BBOX_PADDING_DEG
        if options.block_penalty_km2 > 0
        else DEFAULT_BBOX_PADDING_DEG
    )
    return load_street_snapper(
        footprints.total_bounds, metric_crs=metric_crs, padding_deg=padding
    )


def _build_graph_hierarchy(
    power_grid: PowerGridGraph,
    config: Dict[str, Any],
    *,
    options: Optional[TopologyOptions] = None,
    block_ids: Optional[np.ndarray] = None,
) -> None:
    """Build and merge the LV/MV/HV `PowerGridGraph` hierarchy in place."""
    options = options or TopologyOptions()
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
        capacitated=options.capacitated,
        block_ids=block_ids,
        block_penalty_km2=options.block_penalty_km2,
        max_customers=options.max_customers_per_transformer,
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
    if "external_grid" in config:
        # The builder reads the slack setpoint from its own config; dropping the
        # block here would silently build every declared setpoint at 1.0 pu.
        pp_config["external_grid"] = config["external_grid"]
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
