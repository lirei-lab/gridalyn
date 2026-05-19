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

Compatibility aliases such as `gridalyn.market`, `gridalyn.analytics`, and
`gridalyn.platform` remain available for older scripts, but new SDK examples
should use the seven-module structure above.

## Design Rule

Provider selection should be graph- and topology-aware. Aggregator bids are not
enough by themselves; the operation must understand where assets are connected
and whether the selected response relieves the targeted network constraint.

See [Utility Operations](../platform/operations.md) and
[Locational Clearing](../flexibility/clearing.md).
