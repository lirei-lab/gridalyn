# Scenarios

Scenarios describe how the base digital twin is altered for a study,
simulation, operation, or dashboard view. A scenario should be explicit enough
to reproduce asset participation, time-series inputs, flexibility roles, and
validation results.

## Scenario Responsibilities

| Responsibility | Example |
| --- | --- |
| Adoption level | EV penetration, DER participation, building cohort. |
| Asset registry | Which buildings, EVSEs, contracts, and providers are active. |
| Controllability | Soft CLS, Hard CLS, normal EV charging, non-participating load. |
| Time-series inputs | Load, EV demand, thermal limits, forecasts, dispatch profiles. |
| Network validation | Powerflow, transformer loading, voltage drops, network-impact verification. |

## General Scenario Pattern

Some demos use scenarios to represent adoption levels, DER participation,
market conditions, or operational stress cases. The scenario layer must remain
general: the dashboard and SDK should read scenario metadata programmatically
rather than assuming one study type.

## Good Scenario Design

- Use stable IDs.
- Store source lineage.
- Keep scenario metadata separate from time-series payloads.
- Record validation status.
- Link scenario assets to topology through the digital twin.
