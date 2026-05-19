# Market And Operations SDK

The market and operations modules manage flexibility providers, aggregators,
offers, locational clearing, dispatch, settlement, and operational scorecards.

## Separation Of Concerns

| Layer | Responsibility |
| --- | --- |
| `gridalyn.operations` | Public operations facade plus provider registry, clearing, dispatch, settlement, and scorecards. |
| `gridalyn.operations.market` | Lower-level market mechanics used by workflows and the facade. |
| `gridalyn.simulation.analytics` | Network-impact features, predictions, and validation helpers. |
| `gridalyn.foundation.platform` | Stable governance and report contracts that applications and projects can call. |

New SDK examples should use this structure directly: operations own market
decisions, simulation owns impact and validation analytics, and foundation owns
governed reports and lineage.

## Design Rule

Provider selection should be graph- and topology-aware. Aggregator bids are not
enough by themselves; the operation must understand where assets are connected
and whether the selected response relieves the targeted network constraint.

See [Utility Operations](../platform/operations.md) and
[Locational Clearing](../flexibility/clearing.md).
