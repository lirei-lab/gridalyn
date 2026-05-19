# Model States

Distribution-grid models are not static. A utility platform needs to distinguish
between the nominal network, observed operating state, planned changes, and
study assumptions.

## State Types

| State | Meaning |
| --- | --- |
| Base | Canonical model snapshot used as the starting point. |
| Normal | Expected normal operating configuration. |
| Current | Observed or simulated current operating configuration. |
| Planned | Future network or asset changes being evaluated. |
| Study case | Scenario-specific assumptions used for analysis or experimentation. |

## Why This Matters

Flexibility clearing, hosting-capacity analysis, and dashboard views can produce
different answers depending on switch state, transformer availability, load
forecast, DER availability, or scenario membership. The model state must be
explicit so that reports and decisions are reproducible.

## Current Status

Gridalyn already records project runs, scenarios, and digital twin metadata. The
roadmap is to make model state a first-class query and validation dimension in
the network repository and future service interfaces.
