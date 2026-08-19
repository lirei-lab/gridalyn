"""Gate ``export_pp_to_geojson``'s coordinate order.

Regression: the function once built ``Point(y, x)`` (lat, lon) and
``LineString`` endpoints as ``(lat, lon)`` tuples -- the reverse of the
GeoJSON/Shapely convention (``Point(x, y)`` = ``Point(lon, lat)``), which
``bus_x``/``bus_y`` are parsed to hold (``coords[0]``/``coords[1]`` from a
``[lon, lat]`` GeoJSON coordinate pair). The function has no other in-repo
caller and no declared schema pins its output shape, so this test is the
only thing that would catch the bug returning.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import geopandas as gpd
import pandapower as pp

from gridalyn.twin.io.geo import export_pp_to_geojson


def _net_with_geo() -> pp.pandapowerNet:
    net = pp.create_empty_network()
    lv_bus = pp.create_bus(net, vn_kv=0.4, name="lv_bus_0")
    mv_bus = pp.create_bus(net, vn_kv=25.0, name="mv_bus_0")
    net.bus["geo"] = None
    net.bus.at[lv_bus, "geo"] = "{'coordinates': [-72.5, 46.5], 'type': 'Point'}"
    net.bus.at[mv_bus, "geo"] = "{'coordinates': [-72.6, 46.6], 'type': 'Point'}"
    pp.create_line(
        net, from_bus=lv_bus, to_bus=mv_bus, length_km=0.1, std_type="NAYY 4x50 SE"
    )
    return net


def test_node_geometry_is_lon_lat_not_lat_lon() -> None:
    net = _net_with_geo()

    with tempfile.TemporaryDirectory() as tmp:
        export_pp_to_geojson(net, tmp)
        nodes = gpd.read_file(Path(tmp) / "grid_nodes_results.geojson")

    lv_row = nodes.loc[nodes["bus_idx"] == 0].iloc[0]
    assert lv_row.geometry.x == -72.5, "x must be longitude, not latitude"
    assert lv_row.geometry.y == 46.5, "y must be latitude, not longitude"


def test_line_geometry_endpoints_are_lon_lat_not_lat_lon() -> None:
    net = _net_with_geo()

    with tempfile.TemporaryDirectory() as tmp:
        export_pp_to_geojson(net, tmp)
        lines = gpd.read_file(Path(tmp) / "grid_lines_results.geojson")

    coords = list(lines.iloc[0].geometry.coords)
    assert coords[0] == (-72.5, 46.5)
    assert coords[1] == (-72.6, 46.6)
