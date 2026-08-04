"""Render the documentation hero background from the digital-twin network.

The homepage used a stock isometric illustration, which showed nothing the
platform actually produces. This draws the real thing: the Trois-Rivières feeder
held in the digital twin, with the medium-voltage backbone coloured by
**electrical depth** -- the impedance-weighted distance from the substation,
which is what governs voltage drop and hosting headroom along a feeder. The
colour is a computed quantity, not decoration.

The frame is deliberately off-centre: the hero renders text over the left third,
so the crop places the network from the centre rightwards and leaves that band
as flat navy.

Inputs come from ``instances/default/digital_twin/base/``, which is generated,
not committed -- the artifact policy forbids tracking twin parquets. Build the
twin base first::

    uv run python gridalyn/projects/workflows/scripts/export_digital_twin_base.py

Then::

    uv run python tools/render_hero_network.py

The output is committed so the site does not depend on a local build.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
TWIN_BASE = REPO_ROOT / "instances" / "default" / "digital_twin" / "base"
DEFAULT_OUT = REPO_ROOT / "docs" / "assets" / "feeder-hero.png"

# Matches --gridalyn-navy-deep in docs/stylesheets/extra.css, so the image edges
# dissolve into the hero card instead of ending on a visible seam.
NAVY = "#0d1b2e"
LATITUDE = 46.34  # Trois-Rivières, for the longitude/latitude aspect correction

# Crop, as a fraction of the network's latitude span, and how much of the frame
# sits right of centre. Tuned so the left third stays clear for the hero text.
ZOOM = 0.22
RIGHT_BIAS = 0.72
FIGSIZE = (26.0, 9.0)
DPI = 100


def _load_network() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the twin's base network tables.

    Returns:
        The bus, line and transformer frames.

    Raises:
        FileNotFoundError: If the twin base has not been exported yet.
    """
    missing = [
        name
        for name in ("grid_buses", "grid_lines", "grid_transformers")
        if not (TWIN_BASE / f"{name}.parquet").is_file()
    ]
    if missing:
        raise FileNotFoundError(
            f"digital-twin base tables missing from {TWIN_BASE}: "
            f"{', '.join(missing)}. These are generated, not committed. Run "
            "`python gridalyn/projects/workflows/scripts/export_digital_twin_base.py` "
            "to build them, then re-run this script."
        )
    return (
        pd.read_parquet(TWIN_BASE / "grid_buses.parquet"),
        pd.read_parquet(TWIN_BASE / "grid_lines.parquet"),
        pd.read_parquet(TWIN_BASE / "grid_transformers.parquet"),
    )


def _electrical_depth(
    buses: pd.DataFrame, lines: pd.DataFrame, transformers: pd.DataFrame
) -> dict[str, float]:
    """Impedance-weighted distance from the nearest HV source, per bus.

    Args:
        buses: Bus table carrying ``bus_id`` and ``category``.
        lines: Line table carrying endpoints and ``length_km``.
        transformers: Transformer table carrying HV/LV endpoints.

    Returns:
        Mapping of bus id to depth in km; unreachable buses are omitted.
    """
    graph = nx.Graph()
    for _, line in lines.iterrows():
        graph.add_edge(line.from_bus_id, line.to_bus_id, weight=float(line.length_km))
    for _, trafo in transformers.iterrows():
        graph.add_edge(trafo.hv_bus_id, trafo.lv_bus_id, weight=0.0)

    depth: dict[str, float] = {}
    for source in buses.loc[buses.category == "HV", "bus_id"]:
        if source not in graph:
            continue
        reached = nx.single_source_dijkstra_path_length(graph, source, weight="weight")
        for bus, distance in reached.items():
            depth[bus] = min(depth.get(bus, float("inf")), distance)
    return depth


def render(out_path: Path) -> Path:
    """Render the hero image and write it to ``out_path``.

    Args:
        out_path: Destination PNG.

    Returns:
        The path written.
    """
    buses, lines, transformers = _load_network()
    position = buses.set_index("bus_id")[["lon", "lat"]].to_dict("index")
    category = buses.set_index("bus_id")["category"].to_dict()
    depth = _electrical_depth(buses, lines, transformers)
    deepest = max(depth.values()) if depth else 1.0

    segments, is_backbone, normalized_depth = [], [], []
    for _, line in lines.iterrows():
        start, end = position.get(line.from_bus_id), position.get(line.to_bus_id)
        if start is None or end is None:
            continue
        segments.append(
            [(start["lon"], start["lat"]), (end["lon"], end["lat"])]
        )
        is_backbone.append(
            category.get(line.from_bus_id) == "MV"
            and category.get(line.to_bus_id) == "MV"
        )
        near = min(
            depth.get(line.from_bus_id, deepest), depth.get(line.to_bus_id, deepest)
        )
        normalized_depth.append(near / deepest)

    segments = np.asarray(segments)
    is_backbone = np.asarray(is_backbone)
    normalized_depth = np.asarray(normalized_depth)

    figure, axes = plt.subplots(figsize=FIGSIZE, dpi=DPI)
    figure.patch.set_facecolor(NAVY)
    axes.set_facecolor(NAVY)

    axes.add_collection(
        LineCollection(
            segments[~is_backbone], colors="#31648f", linewidths=0.9, alpha=0.55
        )
    )
    backbone_colours = plt.cm.viridis(
        0.30 + 0.65 * (1.0 - normalized_depth[is_backbone])
    )
    axes.add_collection(
        LineCollection(
            segments[is_backbone], colors=backbone_colours, linewidths=3.2, alpha=0.95
        )
    )

    medium = buses[buses.category == "MV"]
    axes.scatter(
        medium.lon, medium.lat, s=14, c="#8ff2cd", alpha=0.9, linewidths=0, zorder=3
    )
    source = buses[buses.category == "HV"]
    axes.scatter(source.lon, source.lat, s=260, c="#ffffff", marker="*", zorder=5)

    aspect = 1.0 / np.cos(np.radians(LATITUDE))
    centre_lon, centre_lat = buses.lon.mean(), buses.lat.mean()
    half_lat = (buses.lat.max() - buses.lat.min()) * ZOOM
    half_lon = half_lat * aspect * (FIGSIZE[0] / FIGSIZE[1])
    axes.set_xlim(
        centre_lon - half_lon * (1.0 - RIGHT_BIAS), centre_lon + half_lon * RIGHT_BIAS
    )
    axes.set_ylim(centre_lat - half_lat, centre_lat + half_lat)
    axes.set_aspect(aspect)
    axes.axis("off")
    figure.subplots_adjust(left=0, right=1, top=1, bottom=0)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out_path, facecolor=NAVY, pad_inches=0)
    plt.close(figure)
    return out_path


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    written = render(args.out)
    size_kb = written.stat().st_size / 1024
    print(f"render_hero_network: wrote {written} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
