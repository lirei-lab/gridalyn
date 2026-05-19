# Operational KPIs And Economic Validation

Operational KPIs evaluate whether a market, control policy, or transactive
mechanism improved grid operation and produced credible economic outcomes. They
should be comparable across demos: flexibility clearing, prosumer markets,
voltage optimization, RL control, and future utility workflows.

## KPI Families

| Family | Typical metrics |
| --- | --- |
| Grid impact | voltage improvement, overload relief, violation count, thermal margin, hosting margin |
| Delivery | requested energy, delivered energy, shortfall, delivery ratio, rebound or side effects |
| Economics | total cost, clearing price, settlement, penalties, payment concentration |
| Fairness and concentration | aggregator share, provider rotation, locational concentration, repeated curtailment |
| Reliability | failed delivery, unavailable providers, constraint residual, emergency activation |
| Control quality | reward, regret, constraint violations, policy stability, solver feasibility |

## Operation Report Pattern

Each operation should publish a report that links:

- model version and scenario;
- selected mechanism or policy;
- input constraints and resource universe;
- dispatch/control instructions;
- physical verification;
- settlement or score;
- warnings, shortfalls, and residual risk.

## CLS Example

The Flexibility CLS workflow is one example of this KPI pattern. It evaluates
the economic efficiency of a **Soft-CLS firm day-ahead contract with sub-period
clearing** under Monte Carlo uncertainty.

The evaluation assesses the behavior of building aggregators (firm Soft-CLS,
Stage 1) and the residual recourse cost from EV interruptions (Hard-CLS, Stage
2) under stochastic load variability.

## Two-Stage Cost Structure

The total expected cost decomposes into:

1. **Soft-CLS Settlement (Stage 1 — Firm DA Cost):** The cost of firm capacity contracted with buildings in the Day-Ahead sub-period clearing. This is a deterministic cost — once contracted, it is paid regardless of the realized scenario.
2. **Soft-CLS Penalties (Stage 1 — Delivery Failures):** Financial penalties collected from aggregators whose buildings fail to deliver their firm commitments (due to EMS failures or thermal exhaustion).
3. **Hard-CLS Penalty (Stage 2 — Recourse Cost):** The cost of real-time EV interruptions activated when the realized load exceeds the thermal limit even after Soft-CLS execution. This is the stochastic recourse cost that varies by scenario.

## Monte Carlo Simulation Results (100 Scenarios)

```text
--- Soft-CLS Firm DA Contract (Sub-period Clearing) ---
Expected Operational Cost: $44,337.22
  ├─ Soft-CLS DA Settlement (Firm): $14,898.27
  ├─ Soft-CLS Delivery Penalties:   $549.90
  └─ Hard-CLS Recourse Penalty:     $29,438.95
Expected Soft Flexibility Procured: 6,708.36 kWh
Expected Hard Interruption Volume:  2,943.89 kWh
```

## Analysis: Sub-period Clearing Efficiency

> [!TIP]
> **Precise DA Procurement**
> The sub-period clearing allocates firm capacity that tracks the exact shape of the expected congestion curve. This avoids over-procurement during the "tails" of the congestion window, reducing the DA settlement cost to $14.8k — matching only the capacity mathematically needed per sub-period.

> [!NOTE]
> **Minimal Delivery Penalties ($549.90)**
> Because the sub-period clearing demands flexibility only when needed and rotates aggregators via the merit-order mechanism, buildings maintain their thermal state and avoid failure. The near-zero penalty level confirms that the firm contracts are physically viable — buildings can deliver what they commit to.

> [!IMPORTANT]
> **Hard-CLS Recourse as Uncertainty Absorber**
> The Hard-CLS cost ($29.4k) represents the expected cost of real-time recourse across 100 stochastic scenarios. This is the price of uncertainty — scenarios where the realized load exceeds the expected load $\mu$ require additional EV interruptions beyond what the DA-planned Soft-CLS can cover. In the two-stage framework, this recourse cost is explicitly optimized: the Newsvendor formulation in Stage 1 dimensions the Soft-CLS contracts to minimize the sum of firm DA cost and expected recourse cost.

## Two-Stage Cost Decomposition

| Cost Component | Nature | Stage | Value |
|----------------|--------|-------|-------|
| Soft-CLS DA Settlement | Deterministic (firm) | Stage 1 | $14,898.27 |
| Soft-CLS Penalties | Stochastic (delivery risk) | Stage 1 | $549.90 |
| Hard-CLS Recourse | Stochastic (scenario-dependent) | Stage 2 | $29,438.95 |
| **Total Expected Cost** | | | **$44,337.22** |

## Conclusion

The simulation validates the core thesis of the two-stage stochastic CLS:

1. **Firm DA contracts (Soft-CLS)** with sub-period granularity provide cost-efficient, physically viable flexibility from buildings by respecting their dynamic thermal constraints and rotating dispatch via merit-order.
2. **Real-time recourse (Hard-CLS)** absorbs the residual uncertainty between expected and realized load at the margin, activated only when physically necessary.
3. The Newsvendor-optimal dimensioning of Stage 1 contracts minimizes the **total expected system cost** — neither over-procuring expensive firm capacity nor under-procuring and relying excessively on costly recourse actions.
