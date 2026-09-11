"""Gate: simulated-time scheduling and channel models between agents.

syntgrid-4ky.5. Before this module the repository had no event queue (measured
2026-09-11: 0 uses of ``heapq``, ``sched``, ``asyncio`` or ``threading``), and
every study modelled communication by hand: ``ev_hosting_flex`` decides and acts
in the same step, ``run_policy_episode`` applies a decision at the next step,
and ``admm_thermal_consensus`` removes an exact ``round(fraction * N)`` agents
as nested prefixes of one seeded permutation.

The tests pin the four things the design promises:

* events pop in ``(time, priority, key, sequence)`` order whatever order they
  were scheduled in, and simulated time only moves forward;
* a stochastic channel's delivery is a function of the seed and the message,
  not of call order, so the same seed gives a byte-identical event trace;
* the fixed-outage channel reproduces the exact, nested, seeded subsets the
  ADMM study draws by hand;
* an ideal channel reproduces the synchronous ``run_policy_episode`` loop
  exactly -- on the real voltage-control environment, not a toy.
"""

from __future__ import annotations

import json
import math
import unittest
from typing import Any

import numpy as np

from gridalyn.simulation.backends.contract import PANDAPOWER_NATIVE_BACKEND_ID
from gridalyn.simulation.channels import (
    BernoulliLossChannel,
    ChannelModel,
    ChannelModelDescriptor,
    ChannelModelRegistry,
    FixedLatencyChannel,
    FixedOutageChannel,
    IdealChannel,
    UnknownChannelModelError,
    default_channel_model_registry,
    register_channel_model_extension,
    resolve_channel_model,
)
from gridalyn.simulation.environments.voltage_control import (
    VoltageControlEnvironment,
    observe_network,
    run_policy_episode,
)
from gridalyn.simulation.policies.registry import SensitivityDispatchPolicy
from gridalyn.simulation.scheduler import EventScheduler, ScheduledEvent
from tests.test_voltage_control_environment import _long_profile_spec


def _pop_all(scheduler: EventScheduler) -> list[ScheduledEvent]:
    events = []
    while len(scheduler):
        events.append(scheduler.pop())
    return events


class SchedulerOrderTest(unittest.TestCase):
    SPECS = (
        (2.0, 0, "b"),
        (1.0, 1, "a"),
        (1.0, 0, "z"),
        (1.0, 0, "c"),
        (0.0, 5, "q"),
    )

    def test_events_pop_by_time_priority_key_whatever_the_insertion_order(
        self,
    ) -> None:
        expected = sorted(self.SPECS)
        orders = (
            list(self.SPECS),
            list(reversed(self.SPECS)),
            list(self.SPECS[2:] + self.SPECS[:2]),
        )
        for order in orders:
            with self.subTest(order=order):
                scheduler = EventScheduler()
                for time, priority, key in order:
                    scheduler.schedule(time=time, priority=priority, key=key)
                popped = [(e.time, e.priority, e.key) for e in _pop_all(scheduler)]
                self.assertEqual(popped, expected)

    def test_identical_keys_keep_their_insertion_order(self) -> None:
        scheduler = EventScheduler()
        scheduler.schedule(time=1.0, key="k", payload="first")
        scheduler.schedule(time=1.0, key="k", payload="second")
        self.assertEqual([e.payload for e in _pop_all(scheduler)], ["first", "second"])

    def test_simulated_time_only_moves_forward(self) -> None:
        scheduler = EventScheduler()
        scheduler.schedule(time=5.0, key="later")
        scheduler.pop()
        self.assertEqual(scheduler.now, 5.0)
        with self.assertRaises(ValueError) as ctx:
            scheduler.schedule(time=4.0, key="past")
        self.assertIn("moves forward", str(ctx.exception))
        with self.assertRaises(ValueError):
            scheduler.schedule(time=math.nan, key="nan")
        with self.assertRaises(ValueError):
            scheduler.run_until(4.0, lambda event: None)
        with self.assertRaises(IndexError):
            scheduler.pop()

    def test_run_until_handles_what_handlers_schedule_inside_the_window(
        self,
    ) -> None:
        scheduler = EventScheduler()
        scheduler.schedule(time=1.0, key="seed")
        handled: list[str] = []

        def handler(event: ScheduledEvent) -> None:
            handled.append(event.key)
            if event.key == "seed":
                scheduler.schedule(time=scheduler.now, key="same-time")
                scheduler.schedule(time=scheduler.now + 0.5, key="half-step")
                scheduler.schedule(time=3.0, key="outside")

        self.assertEqual(scheduler.run_until(2.0, handler), 3)
        self.assertEqual(handled, ["seed", "same-time", "half-step"])
        self.assertEqual(scheduler.now, 2.0)
        self.assertEqual(len(scheduler), 1)
        self.assertEqual(scheduler.peek_time(), 3.0)

    def test_drain_refuses_to_run_forever(self) -> None:
        scheduler = EventScheduler()
        scheduler.schedule(time=0.0, key="tick")

        def forever(event: ScheduledEvent) -> None:
            scheduler.schedule(time=scheduler.now + 1.0, key="tick")

        with self.assertRaises(RuntimeError) as ctx:
            scheduler.drain(forever, limit=50)
        self.assertIn("rescheduling forever", str(ctx.exception))


def _outcomes(channel: ChannelModel, keys: list[str]) -> dict[str, float | None]:
    return {
        key: channel.transmit(
            key=key, sender="aggregator", receiver=f"home:{key}", sent_at=3.0
        ).deliver_at
        for key in keys
    }


class ChannelModelTest(unittest.TestCase):
    def test_ideal_and_fixed_latency_delivery_times(self) -> None:
        ideal = IdealChannel().transmit(key="m", sender="a", receiver="b", sent_at=2.5)
        late = FixedLatencyChannel(latency=1.5).transmit(
            key="m", sender="a", receiver="b", sent_at=2.5
        )
        self.assertEqual((ideal.delivered, ideal.deliver_at), (True, 2.5))
        self.assertEqual((late.delivered, late.deliver_at), (True, 4.0))

    def test_parameters_outside_their_domain_are_refused(self) -> None:
        refusals = (
            lambda: FixedLatencyChannel(latency=-1.0),
            lambda: FixedLatencyChannel(latency=math.inf),
            lambda: BernoulliLossChannel(loss_probability=1.5, seed=0),
            lambda: BernoulliLossChannel(loss_probability=0.1, seed=-1),
            lambda: BernoulliLossChannel(loss_probability=0.1, seed=True),
            lambda: FixedOutageChannel(["a", "a"], outage_fraction=0.5, seed=0),
            lambda: FixedOutageChannel(["a", "b"], outage_fraction=-0.1, seed=0),
        )
        for index, build in enumerate(refusals):
            with self.subTest(case=index), self.assertRaises(ValueError):
                build()

    def test_bernoulli_loss_depends_on_the_message_not_on_call_order(self) -> None:
        keys = [f"msg:{index:04d}" for index in range(300)]
        forward = _outcomes(BernoulliLossChannel(0.4, seed=11), keys)
        backward = _outcomes(BernoulliLossChannel(0.4, seed=11), list(reversed(keys)))
        other_seed = _outcomes(BernoulliLossChannel(0.4, seed=12), keys)
        self.assertEqual(forward, backward)
        self.assertNotEqual(forward, other_seed)
        self.assertTrue(any(v is None for v in forward.values()))
        self.assertTrue(any(v is not None for v in forward.values()))

    def test_bernoulli_loss_rate_matches_its_probability(self) -> None:
        keys = [f"msg:{index:05d}" for index in range(20000)]
        for probability in (0.0, 0.3, 1.0):
            with self.subTest(loss_probability=probability):
                outcomes = _outcomes(BernoulliLossChannel(probability, seed=5), keys)
                lost = sum(v is None for v in outcomes.values()) / len(keys)
                bound = 3.0 * math.sqrt(probability * (1 - probability) / len(keys))
                self.assertLessEqual(abs(lost - probability), bound)

    def test_fixed_outage_silences_an_exact_nested_seeded_subset(self) -> None:
        endpoints = [f"agent_{index:03d}" for index in range(74)]
        previous: set[str] = set()
        for fraction in (0.0, 0.2, 0.35, 0.5, 1.0):
            with self.subTest(outage_fraction=fraction):
                channel = FixedOutageChannel(
                    endpoints, outage_fraction=fraction, seed=7
                )
                silent = set(channel.silent_endpoints)
                recipe = np.random.default_rng(7).permutation(74)[
                    : round(fraction * 74)
                ]
                self.assertEqual(silent, {endpoints[int(i)] for i in recipe})
                self.assertEqual(len(silent), round(fraction * 74))
                self.assertLessEqual(previous, silent)
                previous = silent
                for endpoint in endpoints[:10]:
                    delivery = channel.transmit(
                        key=f"x:{endpoint}",
                        sender="coordinator",
                        receiver=endpoint,
                        sent_at=0.0,
                    )
                    self.assertEqual(delivery.delivered, endpoint not in silent)

    def test_every_shipped_model_records_a_json_descriptor(self) -> None:
        models: tuple[ChannelModel, ...] = (
            IdealChannel(),
            FixedLatencyChannel(latency=0.25),
            BernoulliLossChannel(0.1, seed=3),
            FixedOutageChannel(["a", "b", "c"], outage_fraction=0.34, seed=3),
        )
        for model in models:
            with self.subTest(model=type(model).__name__):
                self.assertIsInstance(model, ChannelModel)
                payload = model.descriptor.as_dict()
                self.assertEqual(json.loads(json.dumps(payload)), payload)
        for stochastic in models[2:]:
            self.assertEqual(stochastic.descriptor.parameters["seed"], 3)


class ChannelRegistryTest(unittest.TestCase):
    def test_the_default_registry_ships_the_four_core_models(self) -> None:
        registry = default_channel_model_registry()
        ids = [d.channel_model_id for d in registry.list_descriptors()]
        self.assertEqual(
            ids, ["bernoulli_loss", "fixed_latency", "fixed_outage", "ideal"]
        )
        for model_id in ids:
            self.assertEqual(registry.registration_source(model_id), "core")

    def test_resolution_builds_a_parameterised_model(self) -> None:
        channel = resolve_channel_model("fixed_latency", latency=2.0)
        self.assertEqual(channel.descriptor.parameters, {"latency": 2.0})
        delivery = channel.transmit(key="m", sender="a", receiver="b", sent_at=1.0)
        self.assertEqual(delivery.deliver_at, 3.0)
        self.assertIsInstance(resolve_channel_model(), IdealChannel)

    def test_an_unknown_model_is_refused_naming_the_available_set(self) -> None:
        with self.assertRaises(UnknownChannelModelError) as ctx:
            resolve_channel_model("carrier_pigeon")
        self.assertIn("carrier_pigeon", str(ctx.exception))
        self.assertIn("fixed_outage", str(ctx.exception))

    def test_a_host_extension_is_recorded_as_host(self) -> None:
        registry = ChannelModelRegistry()
        register_channel_model_extension(
            IdealChannel,
            descriptor=ChannelModelDescriptor(
                channel_model_id="radio_mesh", name="radio mesh"
            ),
            version="1.2.0",
            registry=registry,
        )
        self.assertEqual(registry.registration_source("radio_mesh"), "host")
        self.assertEqual(registry.registration_version("radio_mesh"), "1.2.0")


def _message_trace(seed: int) -> str:
    """Run a small many-agent protocol and return its popped-event trace."""
    channel = BernoulliLossChannel(0.2, seed=seed, latency=0.5)
    scheduler = EventScheduler()
    for step in range(20):
        scheduler.schedule(time=float(step), priority=1, key=f"step:{step:03d}")
    trace: list[tuple[float, int, str]] = []

    def handler(event: ScheduledEvent) -> None:
        trace.append((event.time, event.priority, event.key))
        if not event.key.startswith("step:"):
            return
        for agent in range(30):
            # Deliveries get their own prefix: a key starting with "step:" would
            # be handled as another step and fan out 30 messages of its own.
            key = f"msg:{event.key}:agent:{agent:02d}"
            delivery = channel.transmit(
                key=key,
                sender="coordinator",
                receiver=f"agent:{agent}",
                sent_at=event.time,
            )
            if delivery.deliver_at is not None:
                scheduler.schedule(time=delivery.deliver_at, priority=0, key=key)

    scheduler.drain(handler)
    return json.dumps(trace)


class DeterminismTest(unittest.TestCase):
    def test_the_same_seed_gives_a_byte_identical_event_trace(self) -> None:
        first = _message_trace(seed=11)
        self.assertEqual(first, _message_trace(seed=11))
        self.assertNotEqual(first, _message_trace(seed=12))
        delivered = first.count(":agent:")
        self.assertGreater(delivered, 0)
        self.assertLess(delivered, 20 * 30)


def _policy(spec: Any) -> SensitivityDispatchPolicy:
    return SensitivityDispatchPolicy(
        sensitivity_pu_per_mw=0.05,
        action_space_mw=spec.der.action_space_mw,
        controlled_bus_id=spec.der.controlled_bus_id,
        voltage_target_pu=spec.voltage_target_pu,
    )


def _scheduled_episode(spec: Any, channel: ChannelModel, step_count: int) -> list[dict]:
    """``run_policy_episode`` rebuilt on the scheduler, with decisions as messages.

    Each step is an event at ``time=step`` (priority 1). The policy's decision
    after step ``t`` is sent through ``channel`` and, if it arrives, applied at
    the first step event at or after its delivery time (deliveries carry
    priority 0, so they land before a step at the same time).
    """
    env = VoltageControlEnvironment(spec, backend_id=PANDAPOWER_NATIVE_BACKEND_ID)
    env.reset()
    scheduler = EventScheduler()
    for step in range(step_count):
        scheduler.schedule(
            time=float(step), priority=1, key=f"step:{step:06d}", payload=step
        )
    applied_action = {"mw": 0.0}
    records: list[dict] = []

    def handler(event: ScheduledEvent) -> None:
        if event.key.startswith("action:"):
            applied_action["mw"] = event.payload
            return
        step = int(event.payload)
        records.append(env.step(step, applied_action["mw"]))
        decision = policy.decide(
            observe_network(env.net), soc_mwh=env.soc_mwh, step=step
        )
        key = f"action:{step:06d}"
        delivery = channel.transmit(
            key=key, sender="policy", receiver="environment", sent_at=float(step)
        )
        if delivery.deliver_at is not None:
            scheduler.schedule(
                time=delivery.deliver_at, priority=0, key=key, payload=decision
            )

    policy = _policy(spec)
    scheduler.drain(handler)
    return records


class IdealChannelParityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = _long_profile_spec()
        self.steps = len(self.spec.load_multiplier_profile)
        self.synchronous = run_policy_episode(
            self.spec,
            _policy(self.spec),
            step_count=self.steps,
            backend_id=PANDAPOWER_NATIVE_BACKEND_ID,
        )

    def _actions(self, records: list[dict]) -> list[float]:
        return [record["action_mw"] for record in records]

    def test_the_synchronous_episode_is_not_vacuous(self) -> None:
        self.assertGreater(len(set(self._actions(self.synchronous))), 1)

    def test_an_ideal_channel_reproduces_the_synchronous_loop_exactly(self) -> None:
        scheduled = _scheduled_episode(self.spec, IdealChannel(), self.steps)
        self.assertEqual(scheduled, self.synchronous)

    def test_a_late_or_silent_channel_changes_the_episode(self) -> None:
        late = _scheduled_episode(
            self.spec, FixedLatencyChannel(latency=1.5), self.steps
        )
        silent = _scheduled_episode(
            self.spec,
            FixedOutageChannel(["policy", "environment"], outage_fraction=0.5, seed=0),
            self.steps,
        )
        self.assertNotEqual(self._actions(late), self._actions(self.synchronous))
        self.assertEqual(set(self._actions(silent)), {0.0})


if __name__ == "__main__":
    unittest.main()
