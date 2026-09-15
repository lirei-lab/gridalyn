"""Gates for the ev_hosting_flex demand-response replay stage (bd 4ky.10).

Tier 1 -- synthetic kernel tests, run in CI:

* the per-EV backstop the replay restates equals ``simulate_curtailment`` on every
  aggregate it returns, so the restatement cannot drift from the mechanism;
* windows, adoption points and the step-level notice figures hold their
  definitions;
* the replay drives real ``dr_program`` conversations to completion, and replaying
  its log reproduces them.

Tier 2 -- governed reproduce-and-pin over ``outputs/json/dr_replay.json``, skipped
when the gitignored artifacts are absent (CI), like the study's other
cache-dependent tests.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from gridalyn.operations.interaction import MessageBus
from gridalyn.operations.interaction.log import build_conversation_book
from projects.ev_hosting_flex.scripts._annual import simulate_curtailment
from projects.ev_hosting_flex.scripts._dr_replay import (
    DAY_AHEAD_NOTICE_MINUTES,
    _notice_quality,
    group_windows,
    replay_adoption_point,
    replay_fair_backstop,
    resolve_adoption_points,
)
from projects.ev_hosting_flex.scripts.config import PROJECT_OUTPUTS_DIR

_REPLAY = PROJECT_OUTPUTS_DIR / "json" / "dr_replay.json"
_HOSTING = PROJECT_OUTPUTS_DIR / "json" / "curtailment_hosting.json"
_DATA = PROJECT_OUTPUTS_DIR / "data"
_REPORT = PROJECT_OUTPUTS_DIR / "reports" / "dr_replay_report.json"
_SKIP_REASON = (
    "outputs/json/dr_replay.json not present; run replay_dr_program.py first "
    "(outputs are gitignored)"
)
_RES = 15


def _fleet(seed: int, *, horizon: int = 96 * 3, n_evs: int = 5) -> tuple:
    """A small congesting feeder: evening charging on a base near the rating."""
    rng = np.random.default_rng(seed)
    base = rng.uniform(20.0, 40.0, horizon).astype("float32")
    demand = np.zeros((n_evs, horizon), dtype="float32")
    for ev in range(n_evs):
        start = int(rng.integers(60, 80))
        for day in range(horizon // 96):
            demand[ev, day * 96 + start : day * 96 + start + 12] = 7.2
    forecast = (base + rng.normal(0.0, 4.0, horizon)).astype("float32")
    return base, demand, forecast


# ─── Tier 1: synthetic kernel tests ──────────────────────────────────────


@pytest.mark.parametrize("seed", [7, 11])
@pytest.mark.parametrize("hourly", [False, True])
def test_the_restated_backstop_equals_simulate_curtailment(
    seed: int, hourly: bool
) -> None:
    """Every aggregate the replay reads is the mechanism's own, exactly."""
    base, demand, _ = _fleet(seed)
    limit = np.full(base.shape, 45.0, dtype="float32")
    if hourly:
        limit[150:170] = 60.0
    ours = replay_fair_backstop(base, demand, limit, res_minutes=_RES)
    reference = simulate_curtailment(
        base,
        demand,
        np.ones(demand.shape[0], bool),
        45.0,
        fair=True,
        res_minutes=_RES,
        rating_series=limit,
    )
    assert reference["curtailed_steps"].sum() > 0, "the fixture must congest"
    for key in (
        "curtailed_kwh_by_ev",
        "events_by_ev",
        "curtailed_steps",
        "served_ev_kw",
    ):
        assert np.array_equal(ours[key], reference[key]), key
    assert ours["cuts_kw"].sum(axis=1) * _RES / 60.0 == pytest.approx(
        reference["curtailed_kwh_by_ev"], abs=1e-4
    )


def test_group_windows_returns_each_run_of_steps() -> None:
    steps = np.array([0, 1, 1, 0, 1, 0, 1, 1, 1], dtype=bool)
    assert group_windows(steps) == [(1, 3), (4, 5), (6, 9)]
    assert group_windows(np.zeros(5, dtype=bool)) == []


def test_adoption_points_mark_what_the_pool_cannot_hold() -> None:
    points = resolve_adoption_points([0.0, 0.5, 1.0, 3.0], homes=6, pool_size=16)
    assert [point["ev_count"] for point in points] == [0, 3, 6, 18]
    assert [point["representable"] for point in points] == [True, True, True, False]
    with pytest.raises(ValueError, match="negative"):
        resolve_adoption_points([-0.5], homes=6, pool_size=16)
    with pytest.raises(ValueError, match="homes"):
        resolve_adoption_points([1.0], homes=0, pool_size=16)


def test_notice_quality_restates_the_stage_definition() -> None:
    called = np.array([1, 1, 0, 0, 1], dtype=bool)
    actual = np.array([1, 0, 1, 0, 0], dtype=bool)
    quality = _notice_quality(called, actual)
    assert quality["planned_percent"] == pytest.approx(50.0)
    assert quality["surprise_percent"] == pytest.approx(50.0)
    assert quality["false_alarm_percent"] == pytest.approx(200.0 / 3.0, abs=1e-4)


def test_a_level_that_never_congests_publishes_nothing() -> None:
    base, demand, forecast = _fleet(7)
    limit = np.full(base.shape, 500.0, dtype="float32")
    bus = MessageBus()
    summary = replay_adoption_point(
        bus,
        point_index=0,
        evs_per_home=1.0,
        ev_count=demand.shape[0],
        base=base,
        pool=demand,
        limit=limit,
        forecast=forecast,
        res_minutes=_RES,
        program_prefix="synthetic",
    )
    assert summary["curtailment_window_count"] == 0
    assert summary["conversation_count"] == 0
    assert summary["message_count"] == 0
    assert len(bus.log) == 0


def test_the_replay_completes_its_conversations_and_replays_identically() -> None:
    base, demand, forecast = _fleet(7)
    limit = np.full(base.shape, 45.0, dtype="float32")
    limit[150:170] = 60.0
    bus = MessageBus()
    summaries = [
        replay_adoption_point(
            bus,
            point_index=index,
            evs_per_home=count / 6,
            ev_count=count,
            base=base,
            pool=demand,
            limit=limit,
            forecast=forecast,
            res_minutes=_RES,
            program_prefix="synthetic",
        )
        for index, count in enumerate((5, 3))
    ]
    epoch = base.shape[0] * _RES
    assert [summary["epoch_offset_minutes"] for summary in summaries] == [0, epoch]
    book = bus.conversations
    assert len(book) == sum(summary["conversation_count"] for summary in summaries) > 0
    assert {book[key].state for key in book} == {"completed"}
    replayed = build_conversation_book(bus.log, until=2 * epoch)
    assert all(replayed[key].state == book[key].state for key in book)
    for summary in summaries:
        assert summary["message_count"] == 2 * summary["conversation_count"]
        assert (
            summary["notified_window_count"] + summary["backstop_window_count"]
            == summary["curtailment_window_count"]
        )

    frame = bus.log.to_frame()
    events = frame.loc[frame["message_type"] == "event"]
    reports = frame.loc[frame["message_type"] == "report"]
    leads = []
    for _, row in events.iterrows():
        active_from = json.loads(row["payload_json"])["flexint:activeFrom"]
        epoch_start = (active_from // epoch) * epoch
        # A called window is published a day ahead, clamped to its epoch's start
        # because a bus refuses a message sent before its current time.
        full_notice = min(float(DAY_AHEAD_NOTICE_MINUTES), active_from - epoch_start)
        lead = active_from - row["sent_at"]
        assert lead in (0.0, full_notice), (row["conversation_id"], lead, full_notice)
        leads.append(lead)
    assert 0.0 in leads, "an uncalled window is the backstop acting without notice"
    assert any(lead > 0.0 for lead in leads), "a called window is published ahead"
    delivered = sum(
        resource["intervals"][0]["payloads"][0]["values"][0]
        for payload_json in reports["payload_json"]
        for resource in json.loads(payload_json)["resources"]
    )
    assert delivered == pytest.approx(
        sum(summary["curtailed_kwh"] for summary in summaries), abs=0.1 * len(reports)
    )


def test_each_window_is_announced_exactly_when_the_forecast_called_it() -> None:
    """A window is published a day ahead if and only if the day-ahead call covered it.

    Counts cannot see a swap between announced and unannounced windows -- both
    still add up -- so every event is checked against the call mask recomputed
    from its own adoption level.
    """
    base, demand, forecast = _fleet(7)
    limit = np.full(base.shape, 45.0, dtype="float32")
    limit[150:170] = 60.0
    counts = (5, 3)
    bus = MessageBus()
    for index, count in enumerate(counts):
        replay_adoption_point(
            bus,
            point_index=index,
            evs_per_home=count / 6,
            ev_count=count,
            base=base,
            pool=demand,
            limit=limit,
            forecast=forecast,
            res_minutes=_RES,
            program_prefix="synthetic",
        )
    epoch = base.shape[0] * _RES
    demand64 = np.asarray(demand, dtype="float64")
    forecast64 = np.asarray(forecast, dtype="float64")
    limit64 = np.asarray(limit, dtype="float64")
    frame = bus.log.to_frame()
    kinds = set()
    for _, row in frame.loc[frame["message_type"] == "event"].iterrows():
        payload = json.loads(row["payload_json"])
        active_from = float(payload["flexint:activeFrom"])
        active_until = float(payload["flexint:activeUntil"])
        level = int(active_from // epoch)
        epoch_start = level * epoch
        called = (forecast64 + demand64[: counts[level]].sum(axis=0)) > limit64
        first = int(round((active_from - epoch_start) / _RES))
        stop = int(round((active_until - epoch_start) / _RES))
        notified = bool(called[first:stop].any())
        expected_lead = (
            min(float(DAY_AHEAD_NOTICE_MINUTES), active_from - epoch_start)
            if notified
            else 0.0
        )
        assert active_from - row["sent_at"] == expected_lead, (
            row["conversation_id"],
            notified,
        )
        kinds.add(notified)
    assert kinds == {True, False}, "the fixture must hold both kinds of window"


# ─── Tier 2: governed reproduce-and-pin ──────────────────────────────────


@pytest.mark.skipif(not _REPLAY.is_file(), reason=_SKIP_REASON)
def test_governed_replay_holds_the_studys_verified_band() -> None:
    """At ~1 EV per dwelling this feeder does not congest; the replay agrees."""
    payload = json.loads(_REPLAY.read_text(encoding="utf-8"))
    points = {point["evs_per_home"]: point for point in payload["points"]}
    for level in (0.0, 0.5, 1.0):
        assert points[level]["conversation_count"] == 0, level
    assert points[3.0]["representable"] is False
    assert payload["first_adoption_with_curtailment_evs_per_home"] == 1.5
    assert payload["channel_model_id"] == "ideal"


@pytest.mark.skipif(not (_REPLAY.is_file() and _HOSTING.is_file()), reason=_SKIP_REASON)
def test_governed_replay_curtails_what_the_contract_stage_curtails() -> None:
    """The replayed energy at 12 EVs is the contract stage's own curve point."""
    payload = json.loads(_REPLAY.read_text(encoding="utf-8"))
    hosting = json.loads(_HOSTING.read_text(encoding="utf-8"))
    point = next(point for point in payload["points"] if point["ev_count"] == 12)
    pool = np.load(_DATA / "ev_fleet_annual.npy").astype("float32")
    energy_kwh = float(pool[:12].sum()) * _RES / 60.0
    expected_kwh = hosting["curtailed_energy_percent_curve"][12] / 100.0 * energy_kwh
    assert point["curtailed_kwh"] == pytest.approx(expected_kwh, rel=1e-4)


@pytest.mark.skipif(not _REPORT.is_file(), reason=_SKIP_REASON)
def test_governed_replay_report_is_valid_and_leaves_no_open_conversation() -> None:
    report = json.loads(_REPORT.read_text(encoding="utf-8"))
    assert report["validation"]["valid"] is True
    assert report["summary"]["open_conversation_count"] == 0
    assert (
        report["summary"]["message_count"]
        == 2 * report["summary"]["conversation_count"]
    )


@pytest.mark.skipif(not _REPLAY.is_file(), reason=_SKIP_REASON)
def test_governed_replay_announces_what_the_day_ahead_call_covers() -> None:
    """The published counts of windows announced a day ahead, per congested level."""
    payload = json.loads(_REPLAY.read_text(encoding="utf-8"))
    points = {point["evs_per_home"]: point for point in payload["points"]}
    assert points[1.5]["curtailment_window_count"] == 2
    assert points[1.5]["notified_window_count"] == 0
    assert points[2.0]["curtailment_window_count"] == 14
    assert points[2.0]["notified_window_count"] == 2
