# dr_agent_interaction

A CI contract fixture: one winter day of a demand-response program, run through
the `dr_program` protocol over a lossy channel. Twenty Québec all-electric homes
take part. The whole run takes seconds.

```bash
gridalyn project run projects/dr_agent_interaction
gridalyn project regression projects/dr_agent_interaction
```

## What it runs

- **Homes.** Twenty homes, each one VEN in the `active_customer` role. Each has
  a Québec-calibrated `Building` (the SDK agent) and one level-2 `EVCharger`.
- **Day.** The coldest synthetic winter day, with a minimum of −21.9 °C.
- **Resolution.** Steps of 5 minutes.
- **Program.** The program administrator is OpenADR's business logic, `BL`. Its
  program is declared in `spec.inputs.drProgram` and loaded by
  `load_demand_response_program`. It has three events, each capping household
  import at 4 kW:

  | Event | Notified | Window | Outcome declared |
  | --- | --- | --- | --- |
  | `evt-morning-peak` | 00:00 | 06:00–09:00 | runs |
  | `evt-midday-cancelled` | 10:00 | 13:00–15:00 | cancelled at 12:00 |
  | `evt-evening-peak` | 14:00 | 17:00–20:00 | runs |

- **Channel.** Every message crosses the declared `spec.simulation.channelModel`,
  a `bernoulli_loss` channel with loss probability 0.15 and a latency of 1 minute.
  Its seed comes from the `channel` stream and is recorded in
  `provenance.channel_model`.
- **Holding the cap.** While an event is active, a home holds the cap. Heating
  gets the power first, and the charger gets whatever is left.
- **Opt-out.** A home opts out when its indoor temperature falls below 19 °C.
- **Reports.** When an event ends, a home that curtailed reports what it
  delivered, rounded to 0.1 kWh.

Two views are kept apart on purpose:

- **What the receiver knows.** A conversation advances only on messages that
  were delivered.
- **What the home decided.** A home that opts out stops curtailing at once,
  whether or not its opt-out arrives.

Every home is also simulated a second time from the same seeds, with no
program. The difference between the two runs is the curtailment.

## What it pins

These are the first run's numbers, pinned in `baselines/results_baseline.json`:

| Metric | Value |
| --- | --- |
| Messages sent, lost | 119, 13 |
| Event notifications delivered | 88.3 % |
| Response rate: live conversations that completed | 0.40 (16 of 40) |
| Opt-outs decided by homes, and delivered | 21, 20 |
| Homes that curtailed through the cancelled event, because their cancellation was lost | 3 |
| Curtailment ordered, and delivered | 260.1 kWh, 130.5 kWh (50.2 %) |
| Curtailment reported, in delivered reports | 59.9 kWh in 16 reports |
| Event peak, without and with the program | 155.5 kW, 152.2 kW |
| Largest indoor drop the program caused | 2.09 °C |
| Homes below 19 °C with **no** program | 3 |

`tests/test_dr_agent_interaction_project.py` tests the pins in two ways:

- It mutates a `dr_program` transition and shows the regression against these
  pins turns red.
- It checks non-vacuity floors (messages lost, opt-outs, a cancellation, a
  response rate strictly between 0 and 1), and shows that a degenerate day with an
  ideal channel and no comfort limit trips them.

## What running it found

- **`dr_program` version 1 could not survive a lossy channel.** An administrator
  cancels an event without knowing whether each home received it. An opt-out and
  a cancellation can also cross in flight. Version 1 refused both situations, so
  the day stopped at the first lost notification. Version 2 defines the races
  instead. See `gridalyn/operations/interaction/dr_program.py`.
- **The SDK's `Building` sampler produces homes that cannot hold the setpoint on
  this day, even with no program.** On these seeds, 3 of the 20 homes have
  heaters of 3.5–3.7 kW against 4.4–6.0 kW of heat loss. The study reports them
  as `homes_below_comfort_without_program_count` rather than counting their cold
  against the program. Fixing the sampler would move other calibrated studies,
  so it is tracked separately as bd 45u.

## Reproducibility

- **What drives the run.** Two seed streams do: `agents` covers the home
  envelopes, the EV sessions and the appliance background; `channel` covers the
  loss draws.
- **Why rounding matters.** A message's id is its content, and a lossy channel
  draws from that id. Reports are rounded to 0.1 kWh so that a floating-point
  difference cannot change whether a report arrives.
- **Measured stability.** Perturbing the outdoor temperature by 1e-9 °C and by
  1e-6 °C changed no count, rate or energy. See the note in the baseline file.

## Limits

- Enrolment in the program is not modelled.
- The payload types for the cap and for the reported reduction are gridalyn's
  own (`flexint:`). OpenADR 3.1.0 allows privately defined payload types.
- The baseline is counterfactual. A real VEN would estimate its baseline.
