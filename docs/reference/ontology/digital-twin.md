# gridalyn digital-twin vocabulary

Scenarios, simulation runs, time-series datasets, scenario devices and the local topology shortcuts of gridalyn's model-first semantic graph.

- **Namespace:** `https://w3id.org/gridalyn/ontology/digital-twin#` (prefix `dt:`)
- **Turtle:** [digital-twin.ttl](../../ontology/digital-twin.ttl)
- **Generated** from the declarations in `gridalyn/twin/semantic/` by `tools/export_ontology.py`, and held to them by `tests/test_ontology_documents.py`; edit the declarations, not this page.

## Classes

| Class | IRI |
| --- | --- |
| <a id="Scenario"></a>`dt:Scenario` | `https://w3id.org/gridalyn/ontology/digital-twin#Scenario` |
| <a id="ScenarioDevice"></a>`dt:ScenarioDevice` | `https://w3id.org/gridalyn/ontology/digital-twin#ScenarioDevice` |
| <a id="SimulationRun"></a>`dt:SimulationRun` | `https://w3id.org/gridalyn/ontology/digital-twin#SimulationRun` |
| <a id="TimeSeriesDataset"></a>`dt:TimeSeriesDataset` | `https://w3id.org/gridalyn/ontology/digital-twin#TimeSeriesDataset` |

## Properties

| Property | Domain | Range | Relationship | Note |
| --- | --- | --- | --- | --- |
| <a id="connectedTo"></a>`dt:connectedTo` | `cim:EnergyConsumer` | `cim:ConnectivityNode` | `CONNECTED_TO` | Local shortcut: CIM reaches a ConnectivityNode from equipment through a Terminal (Terminal.ConductingEquipment, Terminal.ConnectivityNode), and this graph collapses the Terminal. Until 2026-09-10 these edges carried the class IRI cim:ConnectivityNode as their predicate. |
| <a id="connects"></a>`dt:connects` | `cim:ACLineSegment` | `cim:ConnectivityNode` | `CONNECTS` | Local shortcut: CIM reaches a ConnectivityNode from equipment through a Terminal (Terminal.ConductingEquipment, Terminal.ConnectivityNode), and this graph collapses the Terminal. Until 2026-09-10 these edges carried the class IRI cim:ConnectivityNode as their predicate. |
| <a id="feeds"></a>`dt:feeds` | `cim:PowerTransformer` | `cim:ConnectivityNode` | `FEEDS` | Local shortcut: CIM reaches a ConnectivityNode from equipment through a Terminal (Terminal.ConductingEquipment, Terminal.ConnectivityNode), and this graph collapses the Terminal. Until 2026-09-10 these edges carried the class IRI cim:ConnectivityNode as their predicate. |
| <a id="hasEVSE"></a>`dt:hasEVSE` | `brick:Building` | `brick:Electric_Vehicle_Charging_Station` | `HAS_EVSE` | — |
| <a id="hasFlexibilityResource"></a>`dt:hasFlexibilityResource` | `brick:Building` / `flexint:FlexibilityProvider` | `dt:ScenarioDevice` / `efont:ThermallyActivatedBuildingSystem` | `HAS_FLEXIBILITY_RESOURCE` | One predicate for building-to-EFOnt-resource and provider-to-device edges; until 2026-09-10 the provider-to-device edges carried cls:hasFlexibilityResource. |
| <a id="hasLoad"></a>`dt:hasLoad` | `brick:Building` | `cim:EnergyConsumer` | `HAS_LOAD` | — |
| <a id="includesAsset"></a>`dt:includesAsset` | `dt:Scenario` | `brick:Building` / `brick:Electric_Vehicle_Charging_Station` / `flexint:CurtailmentContract` / `flexint:FlexibilityAggregator` / `flexint:FlexibilityProvider` | `INCLUDES_ASSET` | — |
| <a id="observes"></a>`dt:observes` | `dt:TimeSeriesDataset` | `dt:Scenario` | `OBSERVES` | — |
| <a id="produced"></a>`dt:produced` | `dt:SimulationRun` | `dt:TimeSeriesDataset` | `PRODUCED` | — |
