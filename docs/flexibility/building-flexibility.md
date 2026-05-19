# Stateful Flexibility Management for Building Portfolios

This document describes how flexibility providers (building aggregators) manage residential loads dynamically over time to participate in the **Soft-CLS (Firm Day-Ahead Contracted Capacity)**.

The core challenge in providing flexibility from residential buildings — particularly for heating loads in cold climates — is managing **thermal discomfort**. Unlike generic battery storage, a building's capacity to reduce power is constrained by the thermal losses of the envelope and the comfort limits of its occupants.

To model this realism, the aggregators employ a **Stateful Thermal Tracking Mechanism**.

---

## 1. Power Reference Hierarchy: $P_{nominal}$, $P_{baseline}$, $P_{limit}$

Three distinct power levels govern the building's participation in the CLS:

| Symbol | Definition | Nature | Source |
|--------|-----------|--------|--------|
| $P_{nominal}$ | **Installed heating capacity** of the building block | Fixed constant | Digital twin (p99 peak across MC scenarios) |
| $P_{baseline}(t)$ | **Actual heating demand** at time $t$ | Time-varying | Thermodynamic simulation of the building envelope |
| $P_{limit}(t)$ | **Contracted power cap** from the Soft-CLS DA contract | Discrete step function (30-min) | Market clearing result |

### Physical Interpretation

- **$P_{nominal}$** represents the aggregate rated capacity of all heating equipment in the block (baseboards, heat pumps). It is determined empirically from the building simulation digital twin: the 99th percentile of peak power across 30 Monte Carlo realizations of the coldest design day. On extreme cold days (e.g., -22.5°C in Trois-Rivières), the building operates **very close** to $P_{nominal}$ — load factors of 0.85–0.90 are typical.

- **$P_{baseline}(t)$** is the unconstrained demand — what the building would consume without any CLS intervention. It varies with outdoor temperature and occupancy patterns.

- **$P_{limit}(t)$** is the maximum power the building is allowed to draw under the firm DA contract. It is computed as $P_{limit}(t) = P_{baseline}(t) - P_{allocated}(t)$, where $P_{allocated}$ is the curtailment volume contracted per sub-period.

> [!IMPORTANT]
> **Curtailment is relative to demand, not capacity.** A building only accumulates thermal deficit when the contract forces it below its actual demand: $\Delta P_{curtail}(t) = \max(0,\; P_{baseline}(t) - P_{limit}(t))$. If $P_{limit}(t) \geq P_{baseline}(t)$, there is no curtailment and no deficit — even if $P_{limit}(t) < P_{nominal}$.

> [!NOTE]
> The `HEATING_OVERSIZE = 1.30` factor in the aggregator model defines the **dynamic rebound headroom** ($P_{heating,max}(t) = 1.30 \times P_{baseline}(t)$) used for thermal recovery after curtailment. This is distinct from $P_{nominal}$, which represents the static installed capacity of the equipment.

---

## 2. The Core Principle: Power Commitments vs. Energy Memory

There is a fundamental physical distinction in how the market interacts with the buildings and how the buildings track their own state:

*   **Market Commitment (Power — kW):** The DSO experiences congestion as instantaneous thermal overloads on the transformer. Therefore, the flexibility market requests, and the aggregators commit to, absolute **power limitations (kW)**.
*   **Internal State (Energy — kWh):** The aggregator manages the building's comfort internally. A reduction in power over a duration of time translates to a loss of thermal energy injected into the building. The aggregator tracks this cumulative thermal loss as an **energy deficit (kWh)**.

> [!IMPORTANT]
> All building flexibility is contracted as **firm Soft-CLS** in the Day-Ahead planning stage (Stage 1). Buildings do not participate in real-time recourse — that role belongs exclusively to EVs via Hard-CLS (Stage 2).

## 3. Stateful Thermal Tracking

Each `BuildingAggregator` maintains an internal state variable: `accumulated_deficit_kwh`. This variable acts as a proxy for the internal temperature drop of the building resulting from successive curtailment events.

### Deficit Accumulation

At the end of every market clearing period $t$ (e.g., 15 minutes), the aggregator receives the dispatched power reduction $P_{curtailed}$ (in kW). The curtailment is measured **relative to the building's baseline demand**, not to the installed capacity:

$$ P_{curtailed}(t) = \max(0,\; P_{baseline}(t) - P_{limit}(t)) $$

The thermal deficit increases proportionally to the duration of the period $\Delta t$:

$$ \text{Added Deficit (kWh)} = P_{curtailed} \times \Delta t $$

### Thermal Recovery (P-Controller Rebound)

Once a building is released from its firm Soft-CLS contract, it enters a recovery phase. The recovery is governed by a **proportional controller (P-control)** that drives the deficit back to zero:

$$ P_{rebound} = \min\left(K_P \cdot \text{Deficit},\; P_{headroom}\right) $$

Where:

- $K_P = 2.0\ \text{kW/kWh}$ — proportional gain calibrated for ~3.5h recovery dynamics in R2000-insulated buildings.
- $P_{headroom} = P_{heating,max} - P_{baseline}$ — available heating capacity above normal baseline.

The recovered energy per timestep is:

$$ \text{Recovered Energy (kWh)} = P_{rebound} \times \Delta t $$

The state is continuously updated and strictly bounded above zero:

$$ \text{Deficit}_{t+1} = \max(0,\; \text{Deficit}_t + \text{Added Deficit} - \text{Recovered Energy}) $$

> [!NOTE]
> The P-controller ensures **physically realistic recovery**: buildings with large deficits recover aggressively (high $P_{rebound}$), while buildings near equilibrium recover gently. Recovery is always clamped by the physical heating headroom of each building — no building can exceed its maximum heating capacity.

---

## 4. Dynamic Physical Constraints

The accumulated thermal deficit dynamically alters the physical capabilities of the building for the subsequent market periods.

### Survival Load ($P_{min}$)
Every building has a minimum load requirement ($P_{min}$) below which the aggregator will refuse to limit power to prevent severe structural freezing or extreme discomfort.

As the energy deficit grows, the building becomes colder, and its **absolute minimum survival load rises**. For every kWh of thermal deficit, the effective survival power floor rises by $0.5 \text{ kW}$:

$$ P_{min, effective} = \min(P_{req},\; P_{min, base} + 0.5 \times \text{Deficit}) $$

This ensures that a heavily curtailed building organically removes itself from the flexibility pool, refusing deep curtailment offers until it recovers.

---

## 5. Dynamic Economic Valuation

Because the Soft-CLS participation is market-based, buildings demand higher financial compensation as their discomfort increases.

### Marginal Discomfort Penalty
The bidding cost curve of the aggregator shifts upwards based on its internal state. The base marginal cost $C_{base}$ is penalized by a dynamic state multiplier:

$$ C_{effective} = C_{base} + (0.50 \times \text{Deficit}) $$

### Merit-Order Impact
This stateful pricing creates a realistic "rotation" effect within the flexibility market:

1. At the beginning of a congestion peak, a building offers cheap flexibility.
2. If curtailed, its energy deficit grows, and its price increases in the next sub-period.
3. As it becomes more expensive, the DSO's merit-order dispatch algorithm naturally skips this building and favors other, "warmer" buildings.
4. While being skipped, the P-controller recovers thermal energy, eventually dropping its price back down to become competitive again.

---

## 6. Interaction with the Two-Stage Framework

| Aspect | Stage 1 (Day-Ahead) | Stage 2 (Real-Time) |
|--------|---------------------|---------------------|
| **Building role** | Firm Soft-CLS contract provider | Executes DA-contracted limitation as planned |
| **Deficit tracking** | Expected deficit used for supply curve pricing | Actual deficit accumulated from realized curtailment |
| **Recovery** | Not applicable (contracts not yet active) | P-controller rebound after contract release |
| **Market participation** | Bids sub-period capacity at state-dependent prices | No additional bidding — contracts are firm |

> [!TIP]
> The key physical insight is that buildings provide **firm, plannable** flexibility because their thermal inertia allows advance preparation (pre-heating before the curtailment window). This makes them ideal for Stage 1 DA contracts. EVs, by contrast, have binary on/off charging behavior with no preparation benefit, making them natural candidates for Stage 2 real-time recourse (Hard-CLS).

---

## 7. Summary

By strictly separating the **external power commitments (kW)** required by the grid from the **internal energy tracking (kWh)** required for comfort, this stateful management framework allows for highly realistic modeling of residential flexibility. The three-level power hierarchy ($P_{nominal} > P_{baseline}(t) > P_{limit}(t)$) ensures that curtailment is always measured relative to actual demand, and the accumulated deficit ($\int P_{curtail}\,dt$) drives both the economic bidding and the physical recovery dynamics. Buildings participate exclusively as **firm Soft-CLS providers** in the Day-Ahead stage, with their thermal recovery governed by a proportional controller that ensures realistic post-curtailment dynamics. The real-time recourse role (Hard-CLS) belongs exclusively to EVs.
