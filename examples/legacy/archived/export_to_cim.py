import importlib
import os

import pandapower as pp

try:
    from cimgraph.databases import ConnectionParameters, RDFlibConnection
    from cimgraph.models import GraphModel
except ImportError as exc:
    raise SystemExit(
        "This archived CIM-Graph example requires the optional CIM integration. "
        "Install it with: uv sync --extra cim"
    ) from exc

from gridalyn.io.cim import CIMConverter
from gridalyn.core.graph import PowerGridGraph

cim_profile = "cimhub_2023"
cim = importlib.import_module(f"cimgraph.data_profile.{cim_profile}")
# RDFLib File Reader Connection
params = ConnectionParameters(
    filename="ieee13.xml", cim_profile=cim_profile, iec61970_301=8
)
rdf = RDFlibConnection(params)
feeder_mrid = "49AD8E07-3BF9-A4E2-CB8F-C3722F837B62"
feeder = cim.Feeder(mRID=feeder_mrid)
# Create a Network instance (required by CIMGridBuilder)

network = GraphModel(connection=rdf, container=feeder, distributed=False)

# Create a sample pandapower network
net = pp.create_empty_network()

# Create buses
bus1 = pp.create_bus(net, name="Bus1", vn_kv=20)
bus2 = pp.create_bus(net, name="Bus2", vn_kv=0.4)

# Create lines
pp.create_line(net, from_bus=bus1, to_bus=bus2, length_km=1, std_type="NAYY 4x50 SE")

# Create transformer
pp.create_transformer(net, hv_bus=bus1, lv_bus=bus2, std_type="0.4 MVA 20/0.4 kV")

# Create a PowerGridGraph instance (required by CIMGridBuilder)
power_grid = PowerGridGraph()

# Instantiate CIMGridBuilder
cim_builder = CIMConverter(net)


# Define the output file path
# Create output directory if it doesn't exist
output_dir = "examples/generated/outputs"
os.makedirs(output_dir, exist_ok=True)

output_file = os.path.join(output_dir, "exported_network.xml")

# Export the pandapower network to CIM
cim_builder.export_to_cim(output_file)

print(f"Pandapower network exported to {output_file}")
