"""Build the study's semantic graph with the capability its declared extension adds.

The build asks for ``feeder_criticality``, a capability gridalyn does not ship.
It exists in this process only because the study declares the extension that
contributes it, and ``resolve_extensions`` routes that extension to the semantic
capability registry. Remove the declaration and the build fails, naming the
capabilities that are registered.
"""

from __future__ import annotations

import pandas as pd

from gridalyn.projects.scripting import project_script
from gridalyn.twin.semantic.mappings import build_semantic_graph
from gridalyn.twin.semantic.profile import profile_with_capabilities
from gridalyn.twin.semantic.validation import validate_semantic_graph

#: The capabilities this stage builds with; one of them is contributed.
CAPABILITIES = {"feeder_criticality"}

_TABLES = ("buses", "lines", "transformers", "buildings", "connectivity")


def main() -> int:
    """Build, validate and report the semantic graph.

    Returns:
        ``0`` when the graph validates, ``1`` otherwise.
    """
    script = project_script()
    contributed = script.resolve_extensions()
    network = script.read_json("inputs/network.json")
    tables = {name: pd.DataFrame(network[name]) for name in _TABLES}
    nodes, edges, manifest = build_semantic_graph(capabilities=CAPABILITIES, **tables)
    validation = validate_semantic_graph(
        nodes, edges, profile_with_capabilities(CAPABILITIES)
    )
    nodes_path = script.path("outputs/data/semantic_nodes.parquet")
    edges_path = script.path("outputs/data/semantic_edges.parquet")
    nodes.to_parquet(nodes_path, index=False)
    edges.to_parquet(edges_path, index=False)
    types = nodes["semantic_type"].value_counts()
    script.write_report(
        "semantic_graph_report",
        inputs=[
            {"name": "network", "type": "network_tables", "path": "inputs/network.json"}
        ],
        artifacts=[
            script.file_reference(nodes_path),
            script.file_reference(edges_path),
        ],
        summary={
            "capabilities": list(manifest["capabilities"]),
            "contributed_extensions": [
                descriptor.extension_id for descriptor in contributed
            ],
            "node_count": int(len(nodes)),
            "edge_count": int(len(edges)),
            "criticality_assessments": int(types.get("crit:CriticalityAssessment", 0)),
        },
        validation={
            "valid": bool(validation["valid"]),
            "errors": list(validation["errors"]),
            "warnings": list(validation["warnings"]),
        },
    )
    return 0 if validation["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
