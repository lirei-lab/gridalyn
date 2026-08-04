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

## A Note On Worked Examples

This page previously carried a worked two-stage CLS example -- Soft-CLS firm
day-ahead settlement, delivery penalties and Hard-CLS recourse, with Monte Carlo
cost figures. Those numbers came from a study that has since been retired, and
they were briefly re-attributed here to `ev_hosting_flex` during that removal.
That attribution was wrong: `ev_hosting_flex` offers **Hard CLS only** -- its
contract stage states plainly that "Soft CLS (building thermal flexibility) is
deliberately absent", and every provider it registers carries
`soft_cls_participant: False`.

Rather than restate figures no committed baseline can reproduce, the example is
removed. The KPI families and report pattern above are the durable content; for
live numbers, read a study's own `outputs/reports/operational_kpi_report.json`
and its pinned baseline.
