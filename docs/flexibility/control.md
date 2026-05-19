# Control And Optimization

Control is a first-class operations family in Gridalyn. Markets decide through
offers, prices, and obligations; control mechanisms decide through policies,
optimization, feedback, and setpoints. Both should use the same digital twin,
constraint, dispatch, and verification contracts.

## Control Families

| Family | Typical method | Gridalyn expectation |
| --- | --- | --- |
| Rule-based control | thresholds, priorities, emergency rules | Produce explicit actions and explain why each rule fired. |
| Convex optimization | CVXPY, linearized sensitivities, constrained dispatch | Store objective, constraints, setpoints, and validation replay. |
| OPF-style control | AC/DC OPF, DER dispatch, voltage/VAR support | Keep solver-specific data behind SDK adapters. |
| Model predictive control | rolling horizon with forecasts and state updates | Persist horizon, forecast version, state, and realized replay. |
| Reinforcement learning | simulator environment, reward, policy, episodes | Treat the learned policy as an action selector that must be verified physically. |
| Hybrid mechanisms | market selection plus local control refinement | Keep market award, control adjustment, and settlement evidence separate. |

## Common Control Contract

Every control mechanism should produce:

| Artifact | Purpose |
| --- | --- |
| `control_problem` | Objective, constraints, action space, state variables, and model version. |
| `control_policy` | Rule set, optimization method, trained policy, or solver configuration. |
| `control_candidates` | Candidate actions before final selection. |
| `dispatch_instructions` | Final setpoints, caps, charging/discharging commands, or envelope changes. |
| `physical_verification` | Powerflow or simulator replay of the selected actions. |
| `control_kpis` | Voltage improvement, overload relief, cost, constraint violation, comfort/fairness, and reliability. |

The same structure applies whether the policy is a simple threshold controller,
a CVXPY optimization, or an RL agent.

## RL Positioning

The `rl_voltage_control_lightsim` demo should be read as a control example, not
as an isolated ML script. Its role in the platform is:

1. build or load a network model through Gridalyn;
2. expose a simulator-backed environment with observations and action space;
3. train or evaluate a policy;
4. convert policy actions into dispatch/control instructions;
5. verify the resulting grid state with a physical simulator;
6. publish reports and sense checks.

RL is useful for sequential control where actions affect future states, such as
battery dispatch, voltage support, congestion management, or restoration
sequencing. It should not bypass the operational contract. A trained policy is
only one selector inside the broader operation lifecycle.

## Optimization Positioning

The `der_voltage_optimization` demo exercises a more classical control family:

```text
network state + DER capabilities + voltage constraints
        -> optimization problem
        -> DER setpoints
        -> pandapower verification
        -> KPI report
```

This is the pattern to reuse for OPF, voltage/VAR control, constrained battery
dispatch, hosting-capacity relief, or local feeder support.

## Verification Boundary

Control outputs should be treated as proposals until they are replayed against a
grid model. Gridalyn distinguishes:

- **selector result:** what the market, optimizer, rule, or RL policy chose;
- **dispatch instruction:** what would be sent to a provider/device/portfolio;
- **verified impact:** what the grid model says happened after replay;
- **settlement or score:** how the action is paid, penalized, or evaluated.

This keeps advanced control methods useful without making them opaque to
operators or project reviewers.

## Related Pages

- [Operational Functions](overview.md)
- [Markets And Transactions](clearing.md)
- [Network Impact Verification](network-impact-surrogate.md)
- [DER Voltage Optimization Demo](../projects/der-voltage-optimization.md)
- [RL Voltage Control With LightSim2Grid](../projects/rl-voltage-control-lightsim.md)
