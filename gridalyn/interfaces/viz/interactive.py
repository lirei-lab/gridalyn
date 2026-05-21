# noqa: B950
"""
Provides visualization capabilities for power grid networks.

This module contains the `GridPlotter` class, a powerful tool for creating
interactive map visualizations of power grid networks using Folium. It is
designed to provide a clear and intuitive representation of the grid,
supporting the visualization of building locations, LV, MV, and HV network
components, and the overall network topology.

The class can also be used to visualize the results of power flow simulations,
such as voltage deviations and line loadings, making it an essential tool for
analyzing and understanding the behavior of the power grid.
"""

import json
from typing import Any, Dict, Optional

import folium
import matplotlib.colors as mcolors
import networkx as nx
import numpy as np
import pandapower as pp
import pandas as pd
from branca.colormap import LinearColormap
from geopy.distance import geodesic
from matplotlib import cm, colormaps

from gridalyn.twin.core.graph import PowerGridGraph


class GridPlotter:
    """
    Handles the visualization of power grid networks.

    This class provides a suite of methods for creating interactive, geographic
    visualizations of power grid networks using Folium. It is designed to work with the
    `PowerGridGraph` class to provide a clear and intuitive representation of
    the grid, supporting the visualization of building locations, LV, MV, and
    HV network components, and the overall network topology.

    The class can also be used to visualize the results of power flow
    simulations, such as voltage deviations and line loadings, making it an
    essential tool for analyzing and understanding the behavior of the power
    grid.

    Attributes:
        power_grid (PowerGridGraph): The `PowerGridGraph` instance to be
            visualized.
    """

    def __init__(self, power_grid: PowerGridGraph) -> None:
        """Initializes the GridPlotter with a power grid graph.

        Args:
            power_grid (PowerGridGraph): An initialized `PowerGridGraph`
                instance containing valid LV, MV, and HV graphs.
        """
        if not isinstance(power_grid, PowerGridGraph):
            raise TypeError("power_grid must be an instance of PowerGridGraph")
        self.power_grid = power_grid

    def _get_cluster_colors(self, graph_lv_buses: nx.Graph) -> Dict[Any, str]:
        """Generates distinct colors for each LV bus cluster."""
        cluster_colors: Dict[Any, str] = {}
        if graph_lv_buses is not None and nx.get_node_attributes(
            graph_lv_buses, "cluster"
        ):
            clusters = set(nx.get_node_attributes(graph_lv_buses, "cluster").values())
            cmap = colormaps.get_cmap("tab20")
            colors = cmap(np.linspace(0, 1, len(clusters)))
            cluster_colors = {
                cluster: mcolors.to_hex(colors[i]) for i, cluster in enumerate(clusters)
            }
        return cluster_colors

    def _add_bus_nodes_to_map(
        self,
        m: folium.Map,
        graph: Optional[nx.Graph],
        node_type: str,
        radius: int,
        color: str,
        feature_group: folium.FeatureGroup,
        cluster_colors: Dict[Any, str],
    ) -> None:
        """Adds bus nodes to the Folium map."""
        if graph is None:
            return

        for node, data in graph.nodes(data=True):
            if data.get("type") == node_type:
                cluster_color = (
                    cluster_colors.get(data.get("cluster", 0), "#000000")
                    if node_type == "lv_bus"
                    else color
                )
                popup_text = folium.Html(
                    f"<b>Bus ID:</b> {node}<br>"
                    f"<b>Cluster:</b> {data.get('cluster', 'N/A')}",
                    script=True,
                )
                folium.Circle(
                    location=(data["y"], data["x"]),
                    radius=radius,
                    color=cluster_color,
                    fill=True,
                    fill_color=cluster_color,
                    fill_opacity=0.8,
                    popup=folium.Popup(popup_text, max_width=300),
                ).add_to(feature_group)
        feature_group.add_to(m)

    def _add_edges_to_map(
        self,
        m: folium.Map,
        graph: Optional[nx.Graph],
        feature_group: folium.FeatureGroup,
        color: str,
        weight: int,
    ) -> None:
        """Adds edges between nodes to the Folium map."""
        if graph is None:
            return

        for source, target, _data in graph.edges(data=True):
            source_node = graph.nodes[source]
            target_node = graph.nodes[target]

            from_pos = (source_node["y"], source_node["x"])
            to_pos = (target_node["y"], target_node["x"])
            length = geodesic(from_pos, to_pos).meters
            if length < 1:
                length = 1  # Enforce minimum length

            coords = [from_pos, to_pos]

            folium.PolyLine(
                locations=coords,
                color=color,
                weight=weight,
                opacity=0.7,
                popup=folium.Popup(
                    f"Edge: {source_node} ↔ {target_node}<br>Length: {length:.2f}",
                    max_width=300,
                ),
            ).add_to(feature_group)
        feature_group.add_to(m)

    def plot_building_and_centroid_graph(
        self,
        plot_lv_edges: bool = True,
        plot_mv_edges: bool = True,
        plot_hv_edges: bool = True,
    ) -> folium.Map:
        """Plots the power grid on a Folium map.

        This method visualizes the LV, MV, and HV components of the power
        grid on an interactive map. It includes options to toggle the
        visibility of edges for each voltage level.

        Args:
            plot_lv_edges (bool): Whether to display the low-voltage edges.
            plot_mv_edges (bool): Whether to display the medium-voltage edges.
            plot_hv_edges (bool): Whether to display the high-voltage edges.

        Returns:
            folium.Map: An interactive Folium map of the power grid.
        """
        # Step 1: Extract graphs for plotting
        graph_lv_buses = self.power_grid.graph_lv_buses
        graph_mv_buses = self.power_grid.graph_mv_buses
        graph_hv_buses = self.power_grid.graph_hv_buses

        # Step 2: Generate distinct colors for each LV bus cluster
        cluster_colors = self._get_cluster_colors(graph_lv_buses)

        # Step 3: Create a Folium map
        if graph_lv_buses is None:
            raise ValueError("LV graph must be initialized to plot.")

        positions_lon = nx.get_node_attributes(graph_lv_buses, "x")
        positions_lat = nx.get_node_attributes(graph_lv_buses, "y")
        center_lat = sum(pos for pos in positions_lat.values()) / len(positions_lat)
        center_lon = sum(pos for pos in positions_lon.values()) / len(positions_lon)
        m = folium.Map(
            location=[center_lat, center_lon], zoom_start=15, tiles="cartodbpositron"
        )
        m._location = [center_lat, center_lon]  # Explicitly set location for testing

        # Step 4: Create FeatureGroups
        lv_bus_group = folium.FeatureGroup(name="LV Buses")
        mv_bus_group = folium.FeatureGroup(name="MV Buses")
        hv_bus_group = folium.FeatureGroup(name="HV Buses")
        lv_edge_group = folium.FeatureGroup(name="LV Lines")
        mv_edge_group = folium.FeatureGroup(name="MV Lines")
        hv_edge_group = folium.FeatureGroup(name="HV Lines")

        # Step 5: Add bus nodes
        self._add_bus_nodes_to_map(
            m, graph_lv_buses, "lv_bus", 5, "", lv_bus_group, cluster_colors
        )
        self._add_bus_nodes_to_map(
            m, graph_mv_buses, "mv_bus", 8, "#808080", mv_bus_group, cluster_colors
        )
        self._add_bus_nodes_to_map(
            m, graph_hv_buses, "hv_bus", 10, "#FFA500", hv_bus_group, cluster_colors
        )

        # Step 6: Add edge layers only if requested
        if plot_lv_edges:
            self._add_edges_to_map(m, graph_lv_buses, lv_edge_group, "#444444", 3)
        if plot_mv_edges:
            self._add_edges_to_map(m, graph_mv_buses, mv_edge_group, "#222222", 4)
        if plot_hv_edges:
            self._add_edges_to_map(m, graph_hv_buses, hv_edge_group, "#222222", 4)

        # Step 7: Add LayerControl for toggling visibility
        folium.LayerControl(collapsed=False).add_to(m)

        # Step 8: Return the map
        return m

    def plot_voltage_deviations_folium(self, net: "pp.pandapowerNet") -> folium.Map:
        # Step 1: Import the "turbo_r" and "inferno" colormaps from matplotlib
        voltage_colormap = cm.get_cmap("turbo_r")  # Reverse colormap for voltages
        line_colormap = cm.get_cmap("inferno")  # Colormap for line intensities

        # Step 2: Extract voltage deviations, angles, nominal voltages, and bus names
        voltage_deviations = net.res_bus.vm_pu
        voltage_angles = net.res_bus.va_degree
        nominal_voltages = net.bus.vn_kv
        bus_names = net.bus["name"]

        # Step 3: Extract bus geodata
        geo_data = net.bus["geo"].apply(lambda x: json.loads(x.replace("'", '"')))
        bus_geodata = pd.DataFrame(
            {
                "Longitude": geo_data.apply(lambda x: x["coordinates"][0]),
                "Latitude": geo_data.apply(lambda x: x["coordinates"][1]),
            }
        )

        # Step 4: Combine the results into a DataFrame
        df = pd.DataFrame(
            {
                "bus_id": voltage_deviations.index,
                "Magnitude": voltage_deviations.values,
                "Voltage_Angle": voltage_angles.values,
                "Nominal_Voltage": nominal_voltages.values,
                "Name": bus_names.values,
                "Longitude": bus_geodata["Longitude"],
                "Latitude": bus_geodata["Latitude"],
            }
        )

        # Step 5: Add bus type categorization based on the 'Name' field
        df["Bus_Type"] = df["Name"].apply(
            lambda x: (
                "Main_HV_Bus"
                if "Main_HV_Bus" in x
                else "Centered_MV" if "MV_mv_substation" in x else "Other"
            )
        )

        # Step 6: Reset index for better readability
        df.reset_index(drop=True, inplace=True)

        # Step 7: Prepare line connections and colors
        line_coords = []
        intensities = []
        line_info = []

        net.res_line["loading_percent"] = (
            net.res_line["loading_percent"].replace([None], np.nan).fillna(0)
        )

        for line in net.line.itertuples():
            from_bus = line.from_bus
            to_bus = line.to_bus

            from_bus_pos = bus_geodata.loc[from_bus]
            to_bus_pos = bus_geodata.loc[to_bus]

            line_coords.append(
                [
                    (from_bus_pos["Latitude"], from_bus_pos["Longitude"]),
                    (to_bus_pos["Latitude"], to_bus_pos["Longitude"]),
                ]
            )
            intensities.append(net.res_line.loading_percent[line.Index])
            line_info.append(
                {
                    "from_bus": from_bus,
                    "to_bus": to_bus,
                    "intensity": net.res_line.loading_percent[line.Index],
                }
            )

        # Step 8: Normalize data for colormaps
        voltage_norm = mcolors.Normalize(
            vmin=df["Magnitude"].min(), vmax=df["Magnitude"].max()
        )
        intensity_norm = mcolors.Normalize(vmin=min(intensities), vmax=max(intensities))

        # Step 9: Create a base map
        min_lat, max_lat = df["Latitude"].min(), df["Latitude"].max()
        min_lon, max_lon = df["Longitude"].min(), df["Longitude"].max()
        m = folium.Map(
            location=[(min_lat + max_lat) / 2, (min_lon + max_lon) / 2],
            tiles="cartodbpositron",
            zoom_start=13,
        )
        m.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])

        # Step 10: Add lines to the map
        for coords, intensity, info in zip(
            line_coords, intensities, line_info, strict=True
        ):
            intensity_color = mcolors.to_hex(line_colormap(intensity_norm(intensity)))
            line_popup = folium.Popup(
                f"From Bus: {info['from_bus']}<br>"
                f"To Bus: {info['to_bus']}<br>"
                f"Line Intensity: {info['intensity']:.2f}%",
                max_width=300,
            )
            folium.PolyLine(
                locations=coords,
                color=intensity_color,
                weight=4,
                opacity=0.8,
                popup=line_popup,
            ).add_to(m)

        # Step 11: Add markers for each bus
        for _, row in df.iterrows():
            voltage_color = mcolors.to_hex(
                voltage_colormap(voltage_norm(row["Magnitude"]))
            )
            popup_text = (
                f"Bus ID: {row['bus_id']}<br>"
                f"Bus Type: {row['Bus_Type']}<br>"
                f"Voltage: {row['Magnitude']:.2f} p.u.<br>"
                f"Nominal Voltage: {row['Nominal_Voltage']:.2f} kV<br>"
                f"Voltage Angle: {row['Voltage_Angle']:.2f}°"
            )

            if row["Bus_Type"] == "Main_HV_Bus":
                folium.Marker(
                    location=(row["Latitude"], row["Longitude"]),
                    icon=folium.Icon(icon="info-sign", color="red"),
                    popup=folium.Popup(popup_text, max_width=400),
                ).add_to(m)
            elif row["Bus_Type"] == "Centered_MV":
                folium.Marker(
                    location=(row["Latitude"], row["Longitude"]),
                    icon=folium.Icon(icon="info-sign", color="orange"),
                    popup=folium.Popup(popup_text, max_width=400),
                ).add_to(m)
            else:
                folium.Circle(
                    location=(row["Latitude"], row["Longitude"]),
                    radius=4,
                    color=voltage_color,
                    fill=True,
                    fill_color=voltage_color,
                    fill_opacity=0.9,
                    popup=folium.Popup(popup_text, max_width=400),
                ).add_to(m)

        # Step 12: Create and add colorbars
        voltage_cbar = LinearColormap(
            colors=[
                mcolors.to_hex(voltage_colormap(voltage_norm(v)))
                for v in np.linspace(df["Magnitude"].min(), df["Magnitude"].max(), 256)
            ],
            vmin=df["Magnitude"].min(),
            vmax=df["Magnitude"].max(),
            caption="Voltage Deviation (p.u.)",
        )
        line_cbar = LinearColormap(
            colors=[
                mcolors.to_hex(line_colormap(intensity_norm(v)))
                for v in np.linspace(min(intensities), max(intensities), 256)
            ],
            vmin=min(intensities),
            vmax=max(intensities),
            caption="Line Intensity (%)",
        )
        voltage_cbar.add_to(m)
        line_cbar.add_to(m)

        return m

    def plot_stochastic_bounds(self, mc_ext_p_mw, mc_raw_p_mw, mc_max_line, resolution_minutes, output_path):
        """
        Creates the Stochastic boundary plot matrix for Monte Carlo simulations.
        """
        print("\n====== Generating Stochastic Probabilistic Bounds ======")
        import matplotlib.pyplot as plt
        import numpy as np

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
        
        time_steps = len(mc_ext_p_mw[0])
        time_axis = np.linspace(0, 24, time_steps)
        
        ext_arr = np.array(mc_ext_p_mw)
        ext_mean = ext_arr.mean(axis=0)
        ext_std = ext_arr.std(axis=0).mean()
        print(f"Stochastic Bounds: Average Realization Standard Deviation around mean is {ext_std:.3f} MW")
        
        ext_5 = np.percentile(ext_arr, 5, axis=0)
        ext_95 = np.percentile(ext_arr, 95, axis=0)
        
        # Shade the region instead of trying to draw 30 tiny microscopic lines that merge
        ax1.fill_between(time_axis, ext_5, ext_95, color="tab:green", alpha=0.2, label="5th - 95th Percentile Band")
        
        # Draw some ghost traces
        for sim_idx, ext_traj in enumerate(ext_arr[:3]):
            label = "Individual Realizations" if sim_idx == 0 else None
            ax1.plot(time_axis, ext_traj, color="tab:green", alpha=0.4, linewidth=0.5, label=label)
            
        ax1.plot(time_axis, ext_mean, label="Substation Import (Mean)", color="#27ae60", linewidth=3.0)
        
        raw_arr = np.array(mc_raw_p_mw)
        ax1.plot(time_axis, raw_arr.mean(axis=0), label="Raw Datagen Aggregation (Mean)", color="#2c3e50", linestyle="--", linewidth=1.5)
        
        ax1.set_ylabel("Active Power [MW]", fontweight="bold")
        ax1.set_title(f"Stochastic Substation Demand ({len(ext_arr)} Realizations)", fontweight="bold")
        ax1.grid(True, alpha=0.3, linestyle="--")
        ax1.legend(loc="upper left")
        
        line_arr = np.array(mc_max_line) 
        line_mean = line_arr.mean(axis=0)
        line_99 = np.percentile(line_arr, 99, axis=0) 
        
        for sim_idx, line_traj in enumerate(line_arr):
            label = "Individual Hazards" if sim_idx == 0 else None
            ax2.plot(time_axis, line_traj, color="#e67e22", alpha=0.2, linewidth=1.5, label=label)
            
        ax2.plot(time_axis, line_mean, label="Grid Expected Max Congestion (Mean)", color="#d35400", linewidth=3)
        ax2.plot(time_axis, line_99, label="Grid Extreme Congestion (99th Pct Constraint)", color="#c0392b", linewidth=2, linestyle="--")
        
        ax2.axhline(100, color="black", linestyle=":", linewidth=2, label="Physical Capacity Limit (100%)")
        
        ax2.set_xlabel("Time of Day [Hours]", fontweight="bold")
        ax2.set_ylabel("Loading [%]", fontweight="bold")
        ax2.set_title("Probabilistic Grid Congestion Analytics", fontweight="bold")
        ax2.set_xticks(np.arange(0, 25, 4))
        ax2.grid(True, alpha=0.3, linestyle="--")
        ax2.legend(loc="upper left")
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=300)
        plt.close()
        print(f"Stochastic envelope visual plots saved to {output_path}")
