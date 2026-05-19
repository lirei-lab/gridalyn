"""CIM Grid Builder for creating CIM-compliant power grid models.

This module provides classes for building CIM-compliant power grid models
from PowerGridGraph objects. It includes functionality for converting
pandapower network elements to their CIM equivalents.
"""

import logging

import pandapower as pp
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF


class CIMConverter:
    def __init__(self, net: "pp.pandapowerNet") -> None:
        """Initializes the CIMConverter class.
        This class is an alternative CIM grid builder that uses RDFLib directly
        to construct the CIM graph.
        Args:
            net (pp.pandapowerNet): A pandapower network.
        """
        self.network: "pp.pandapowerNet" = net
        self.cim = Namespace("http://iec.ch/TC57/2013/CIM-schema-cim16#")
        self.graph = Graph()
        self.graph.bind("cim", self.cim)
        self.bus_mapping: dict[int, URIRef] = {}
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

    def _add_base_voltages(self) -> None:
        """Adds base voltage levels to the CIM graph."""
        voltages = {
            "hv": 115000,
            "mv": 13000,
            "lv": 480,
        }
        for name, voltage in voltages.items():
            base_voltage_ref = URIRef(f"#{name.upper()}_Voltage")
            self.graph.add((base_voltage_ref, RDF.type, self.cim.BaseVoltage))
            self.graph.add(
                (
                    base_voltage_ref,
                    self.cim["BaseVoltage.nominalVoltage"],
                    Literal(voltage),
                )
            )

    def convert_buses(self) -> None:
        """Converts pandapower buses to CIM BusbarSections.
        This method iterates through the buses in the pandapower network
        and creates corresponding BusbarSection instances in the CIM graph.
        """
        for idx, bus in self.network.bus.iterrows():
            bus_id = f"Bus_{idx}"
            bus_ref = URIRef(f"#Bus_{bus_id}")
            self.graph.add((bus_ref, RDF.type, self.cim.BusbarSection))
            self.graph.add(
                (bus_ref, self.cim["IdentifiedObject.name"], Literal(bus["name"]))
            )
            self.graph.add(
                (bus_ref, self.cim["VoltageLevel.BaseVoltage"], Literal(bus["vn_kv"]))
            )
            self.bus_mapping[idx] = bus_ref

    def convert_lines(self) -> None:
        """Converts pandapower lines to CIM ACLineSegments.
        This method iterates through the lines in the pandapower network
        and creates corresponding ACLineSegment instances in the CIM graph.
        """
        for idx, line in self.network.line.iterrows():
            line_id = f"Line_{idx}"
            line_ref = URIRef(f"#Line_{line_id}")
            self.graph.add((line_ref, RDF.type, self.cim.ACLineSegment))
            self.graph.add(
                (line_ref, self.cim["IdentifiedObject.name"], Literal(line["name"]))
            )
            self.graph.add(
                (line_ref, self.cim["ACLineSegment.length"], Literal(line["length_km"]))
            )
            self.graph.add(
                (
                    line_ref,
                    self.cim["ConductingEquipment.BaseVoltage"],
                    Literal(self.network.bus.loc[line["from_bus"], "vn_kv"]),
                )
            )
            self.graph.add(
                (line_ref, self.cim["ACLineSegment.r"], Literal(line["r_ohm_per_km"]))
            )
            self.graph.add(
                (line_ref, self.cim["ACLineSegment.x"], Literal(line["x_ohm_per_km"]))
            )
            self.graph.add(
                (line_ref, self.cim["ACLineSegment.bch"], Literal(line["c_nf_per_km"]))
            )

    def convert_transformers(self) -> None:
        """Converts pandapower transformers to CIM PowerTransformers.
        This method iterates through the transformers in the pandapower network
        and creates corresponding PowerTransformer and PowerTransformerEnd
        instances in the CIM graph.
        """
        for idx, trafo in self.network.trafo.iterrows():
            trafo_id = f"Trafo_{idx}"
            trafo_ref = URIRef(f"#Trafo_{trafo_id}")
            self.graph.add((trafo_ref, RDF.type, self.cim.PowerTransformer))
            self.graph.add(
                (trafo_ref, self.cim["IdentifiedObject.name"], Literal(trafo["name"]))
            )

            # Transformer ends
            for end, bus in enumerate([trafo["hv_bus"], trafo["lv_bus"]]):
                end_id = f"{trafo_id}_End_{end+1}"
                end_ref = URIRef(f"#TrafoEnd_{end_id}")
                self.graph.add((end_ref, RDF.type, self.cim.PowerTransformerEnd))
                self.graph.add(
                    (end_ref, self.cim["TransformerEnd.endNumber"], Literal(end + 1))
                )
                self.graph.add(
                    (
                        end_ref,
                        self.cim["TransformerEnd.BaseVoltage"],
                        Literal(self.network.bus.loc[bus, "vn_kv"]),
                    )
                )
                self.graph.add(
                    (
                        end_ref,
                        self.cim["PowerTransformerEnd.PowerTransformer"],
                        trafo_ref,
                    )
                )

    def convert_loads(self) -> None:
        """Converts pandapower loads to CIM EnergyConsumers.
        This method iterates through the loads in the pandapower network
        and creates corresponding EnergyConsumer instances in the CIM graph.
        """
        for idx, load in self.network.load.iterrows():
            load_id = f"Load_{idx}"
            load_ref = URIRef(f"#Load_{load_id}")
            self.graph.add((load_ref, RDF.type, self.cim.EnergyConsumer))
            self.graph.add(
                (load_ref, self.cim["IdentifiedObject.name"], Literal(load["name"]))
            )
            self.graph.add(
                (load_ref, self.cim["EnergyConsumer.pfixed"], Literal(load["p_mw"]))
            )
            self.graph.add(
                (load_ref, self.cim["EnergyConsumer.qfixed"], Literal(load["q_mvar"]))
            )

    def convert_external_grid(self) -> None:
        """Converts pandapower external grids to CIM ExternalNetworkInjections.
        This method iterates through the external grids in the pandapower network
        and creates corresponding ExternalNetworkInjection instances in the CIM graph.
        """
        for idx, ext_grid in self.network.ext_grid.iterrows():
            ext_grid_id = f"ExtGrid_{idx}"
            ext_grid_ref = URIRef(f"#ExtGrid_{ext_grid_id}")
            self.graph.add((ext_grid_ref, RDF.type, self.cim.ExternalNetworkInjection))
            self.graph.add(
                (
                    ext_grid_ref,
                    self.cim["IdentifiedObject.name"],
                    Literal(ext_grid["name"]),
                )
            )
            self.graph.add(
                (ext_grid_ref, self.cim["Terminal.connected"], Literal("true"))
            )
            self.graph.add(
                (
                    ext_grid_ref,
                    self.cim["ACDCTerminal.Voltage"],
                    Literal(ext_grid["vm_pu"]),
                )
            )

    def convert_switches(self) -> None:
        """Converts pandapower switches to CIM Switches.
        This method iterates through the switches in the pandapower network
        and creates corresponding Switch instances in the CIM graph.
        """
        for idx, switch in self.network.switch.iterrows():
            switch_id = f"Switch_{idx}"
            switch_ref = URIRef(f"#Switch_{switch_id}")
            self.graph.add((switch_ref, RDF.type, self.cim.Switch))
            self.graph.add(
                (switch_ref, self.cim["IdentifiedObject.name"], Literal(switch["name"]))
            )
            self.graph.add(
                (
                    switch_ref,
                    self.cim["Switch.normalOpen"],
                    Literal(not switch["closed"]),
                )
            )

    def export_to_cim(self, output_file: str = "output_cim.xml") -> None:
        """Exports the constructed CIM RDF graph to an XML file.
        This method orchestrates the conversion of all pandapower elements
        and then serializes the resulting CIM graph to an RDF/XML file.
        Args:
            output_file (str): The path to the output XML file.

        Example:
            >>> builder_x.export_to_cim("my_grid_x.xml")
        """
        self._add_base_voltages()
        self.convert_buses()
        self.convert_lines()
        self.convert_transformers()
        self.convert_loads()
        self.convert_external_grid()
        self.convert_switches()

        # Serialize to RDF/XML
        serialized_graph = self.graph.serialize(format="xml")
        with open(output_file, "wb") as f:
            f.write(serialized_graph)
        self.logger.info(f"CIM XML exported to {output_file}")
