"""Spatial allocation helpers for mapping aggregate CLS to network loads."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SpatialClsResult:
    managed_building_kw: np.ndarray
    managed_ev_kw: np.ndarray
    soft_curtailed_kw: np.ndarray
    hard_curtailed_kw: np.ndarray
    soft_delivered_kw: np.ndarray
    hard_delivered_kw: np.ndarray


def allocate_reduction(
    load_kw: np.ndarray,
    target_kw: np.ndarray,
    eligible: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Allocate an aggregate reduction proportionally across eligible loads."""
    load = np.asarray(load_kw, dtype=float)
    target = np.asarray(target_kw, dtype=float)
    mask = np.asarray(eligible, dtype=bool)
    if load.ndim != 2:
        raise ValueError("load_kw must be a 2D matrix [time, load]")
    if target.shape != (load.shape[0],):
        raise ValueError("target_kw must have one value per timestep")
    if mask.shape != (load.shape[1],):
        raise ValueError("eligible must have one value per load")

    curtailed = np.zeros_like(load)
    eligible_load = np.where(mask[np.newaxis, :], load, 0.0)
    capacity = eligible_load.sum(axis=1)
    delivered = np.minimum(np.maximum(target, 0.0), capacity)

    active = capacity > 0.0
    curtailed[active] = eligible_load[active] * (
        delivered[active] / capacity[active]
    )[:, np.newaxis]
    return curtailed, delivered


def allocate_addition_by_headroom(
    load_kw: np.ndarray,
    target_kw: np.ndarray,
    eligible: np.ndarray,
    charger_kw: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Allocate rebound/additional EV load across eligible charger headroom."""
    load = np.asarray(load_kw, dtype=float)
    target = np.asarray(target_kw, dtype=float)
    mask = np.asarray(eligible, dtype=bool)
    charger = np.asarray(charger_kw, dtype=float)
    if load.ndim != 2:
        raise ValueError("load_kw must be a 2D matrix [time, load]")
    if target.shape != (load.shape[0],):
        raise ValueError("target_kw must have one value per timestep")
    if mask.shape != (load.shape[1],) or charger.shape != (load.shape[1],):
        raise ValueError("eligible and charger_kw must have one value per load")

    added = np.zeros_like(load)
    headroom = np.maximum(charger[np.newaxis, :] - load, 0.0)
    eligible_headroom = np.where(mask[np.newaxis, :], headroom, 0.0)
    capacity = eligible_headroom.sum(axis=1)
    delivered = np.minimum(np.maximum(target, 0.0), capacity)

    active = capacity > 0.0
    added[active] = eligible_headroom[active] * (
        delivered[active] / capacity[active]
    )[:, np.newaxis]
    return added, delivered


def apply_spatial_cls(
    building_kw: np.ndarray,
    ev_kw: np.ndarray,
    soft_cls_kw: np.ndarray,
    hard_cls_kw: np.ndarray,
    soft_eligible: np.ndarray,
    hard_preferred: np.ndarray,
    ev_eligible: np.ndarray,
) -> SpatialClsResult:
    """Apply aggregate Soft and Hard CLS targets to per-load matrices."""
    building = np.asarray(building_kw, dtype=float)
    ev = np.asarray(ev_kw, dtype=float)
    if building.shape != ev.shape:
        raise ValueError("building_kw and ev_kw must have matching shapes")

    soft_curtailed, soft_delivered = allocate_reduction(
        building, np.asarray(soft_cls_kw, dtype=float), soft_eligible
    )

    hard_curtailed, hard_delivered = allocate_reduction(
        ev, np.asarray(hard_cls_kw, dtype=float), hard_preferred & ev_eligible
    )
    residual = np.maximum(np.asarray(hard_cls_kw, dtype=float) - hard_delivered, 0.0)
    fallback_curtailed, fallback_delivered = allocate_reduction(
        ev - hard_curtailed, residual, ev_eligible
    )
    hard_curtailed = hard_curtailed + fallback_curtailed
    hard_delivered = hard_delivered + fallback_delivered

    return SpatialClsResult(
        managed_building_kw=np.maximum(building - soft_curtailed, 0.0),
        managed_ev_kw=np.maximum(ev - hard_curtailed, 0.0),
        soft_curtailed_kw=soft_curtailed,
        hard_curtailed_kw=hard_curtailed,
        soft_delivered_kw=soft_delivered,
        hard_delivered_kw=hard_delivered,
    )
