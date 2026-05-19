# Applications And Interfaces

Applications sit above the digital twin and project artifacts. They should not
own hidden domain logic. Their role is to make validated model, scenario,
operation, and report outputs usable by people and systems.

## Current Interfaces

| Interface | Status | Consumes |
| --- | --- | --- |
| CLI | Active | Project contracts, digital twin artifacts, market inputs, semantic graph inputs. |
| Python SDK | Active | `gridalyn` public APIs and local artifact paths. |
| Dashboard | Active | Dashboard catalog, canonical reports, scenario data, network-impact outputs. |
| Reports | Active | Project outputs, digital twin metadata, simulation outputs, market outputs. |
| Semantic graph | Active | Base topology, buildings, scenarios, assets, time-series metadata, flexibility contracts. |

## Future Interfaces

| Interface | Intended role |
| --- | --- |
| Model service | Query partial network models by feeder, transformer, zone, or asset. |
| Operations API | Submit operational requests and retrieve clearing, dispatch, and verification results. |
| Graph database backend | Persist semantic graph data in FalkorDB or a compatible graph store. |
| Utility data adapters | Ingest GIS, CIM, AMI, SCADA, DMS, DER, and market data through stable contracts. |

## Design Rule

Applications must consume declared artifacts or documented SDK functions. If an
application needs to call a project script directly, the reusable behavior
probably belongs in the Gridalyn SDK first.
