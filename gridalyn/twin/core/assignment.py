"""Assign customers to transformers without exceeding a per-transformer limit.

``PowerGridGraph.create_lv_graph`` works out HOW MANY transformers a footprint
layer needs from its coincident load, then hands that count to K-means, which
partitions by geometry alone. The count is capacity-aware; the allocation is
not. Measured on the shipped 3235 footprints (bd syntgrid-4os.7): 7 to 26
customers per 210 kVA unit with 43 of 193 units above 100% at the declared
envelope, and under the 75 kVA flagship config 1 to 12 homes per unit with 209
of 540 above 100%.

:func:`assign_capacitated` supplies the missing constraint. It runs Lloyd
iterations whose assignment step is an exact capacitated transportation problem
instead of "nearest centre", so no transformer receives more than ``capacity``
customers. On the same two builds a capacity of ``ceil(customers / transformers)``
-- the count the existing formula already sized for -- leaves 0 units above
100%.

Two measured findings shape the API:

- **The limit is a customer count the caller sized for, not the nameplate.** A
  nameplate-derived cap piles clusters exactly at the limit, and power-flow
  loading is current-based at depressed voltage, so MORE units exceed 100% than
  under plain K-means (43 -> 52, 209 -> 265).
- **Capacity and street blocks do not pull together on their own.** The
  constraint pushes edge customers into the neighbouring cluster across the
  street: block crossings forced by the partition rise from 308 to 433 on the
  flagship config. A penalty for leaving a cluster's dominant block recovers
  them (308 -> 197 at 0.005 km^2) while keeping 0 overloads. That is what
  ``block_ids`` and ``block_penalty_km2`` are for.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

DEFAULT_CANDIDATES = 32
"""Nearest transformers each customer may be assigned to in one step.

Each step is solved exactly over these candidates rather than over every
transformer, so memory grows with ``customers x candidates`` instead of
``customers x transformers``. When the restricted problem has no solution the
candidate set doubles and the step is solved again, up to every transformer.
"""

_SQUARED_METRES_PER_KM2 = 1e6


@dataclass(frozen=True)
class CapacitatedAssignment:
    """The result of :func:`assign_capacitated`.

    Attributes:
        labels: Transformer index for each customer.
        centers: Final centre of each cluster, in the input coordinates.
        capacity: The per-transformer customer limit that was enforced.
        block_penalty_km2: The block penalty applied, ``0.0`` when none.
        iterations: Assignment steps run, over both phases.
        converged: Whether the labels stopped changing within ``max_iter``.
    """

    labels: np.ndarray
    centers: np.ndarray
    capacity: int
    block_penalty_km2: float
    iterations: int
    converged: bool


def assign_capacitated(
    points: np.ndarray,
    initial_centers: np.ndarray,
    capacity: int,
    *,
    block_ids: np.ndarray | None = None,
    block_penalty_km2: float = 0.0,
    candidates: int = DEFAULT_CANDIDATES,
    max_iter: int = 100,
) -> CapacitatedAssignment:
    """Partition customers into clusters of at most ``capacity`` members.

    Lloyd iterations: assign every customer under the capacity limit at minimum
    total squared distance, move each centre to the mean of its members, repeat
    until the labels stop changing. With ``block_penalty_km2`` a second phase
    starts from that result and adds the penalty to every candidate transformer
    whose cluster's dominant street block differs from the customer's own.

    Args:
        points: ``(n, 2)`` customer coordinates. Distances are read as metres,
            so pass a projected CRS whenever ``block_penalty_km2`` is used.
        initial_centers: ``(k, 2)`` starting centres, e.g. K-means centres.
        capacity: Maximum customers per transformer.
        block_ids: ``(n,)`` street block of each customer, ``-1`` for a
            customer outside every block (it is never penalised).
        block_penalty_km2: Cost, in km^2 of squared distance, of assigning a
            customer to a cluster whose dominant block is not its own.
            ``0.005`` is the cost of moving about 71 m.
        candidates: Nearest transformers considered per customer per step. See
            :data:`DEFAULT_CANDIDATES`.
        max_iter: Iteration limit for each phase.

    Returns:
        The labels, final centres and convergence record.

    Raises:
        ValueError: If the shapes disagree, ``capacity`` cannot hold every
            customer, or a penalty is given without ``block_ids``.
    """
    points = np.asarray(points, dtype=float)
    centers = np.asarray(initial_centers, dtype=float).copy()
    _check_inputs(points, centers, capacity, block_ids, block_penalty_km2, candidates)
    labels, centers, iterations, converged = _lloyd(
        points, centers, capacity, candidates, max_iter
    )
    if block_ids is not None and block_penalty_km2 > 0:
        labels, centers, extra, converged = _lloyd(
            points,
            centers,
            capacity,
            candidates,
            max_iter,
            labels=labels,
            block_ids=np.asarray(block_ids, dtype=int),
            block_penalty_km2=block_penalty_km2,
        )
        iterations += extra
    return CapacitatedAssignment(
        labels=labels,
        centers=centers,
        capacity=int(capacity),
        block_penalty_km2=float(block_penalty_km2),
        iterations=iterations,
        converged=converged,
    )


def _check_inputs(
    points: np.ndarray,
    centers: np.ndarray,
    capacity: int,
    block_ids: np.ndarray | None,
    block_penalty_km2: float,
    candidates: int,
) -> None:
    """Reject inputs the assignment cannot honour, naming what would fix them.

    Args:
        points: Customer coordinates.
        centers: Starting centres.
        capacity: Maximum customers per transformer.
        block_ids: Optional block of each customer.
        block_penalty_km2: Penalty for leaving the dominant block.
        candidates: Nearest transformers considered per customer.

    Raises:
        ValueError: On the first input that cannot be honoured.
    """
    if points.ndim != 2 or points.shape[1] != 2 or len(points) == 0:
        raise ValueError(f"points must be a non-empty (n, 2) array, got {points.shape}")
    if centers.ndim != 2 or centers.shape[1] != 2 or len(centers) == 0:
        raise ValueError(
            f"initial_centers must be a non-empty (k, 2) array, got {centers.shape}"
        )
    if capacity < 1 or candidates < 1:
        raise ValueError(
            f"capacity and candidates must be at least 1, got {capacity} and "
            f"{candidates}"
        )
    customers, transformers = len(points), len(centers)
    if customers > transformers * capacity:
        raise ValueError(
            f"{customers} customers cannot fit {transformers} transformers of "
            f"capacity {capacity}; pass capacity >= "
            f"{math.ceil(customers / transformers)} or place more transformers"
        )
    if block_penalty_km2 < 0:
        raise ValueError(f"block_penalty_km2 must be >= 0, got {block_penalty_km2}")
    if block_penalty_km2 > 0 and block_ids is None:
        raise ValueError(
            "block_penalty_km2 needs block_ids: without the block of each "
            "customer there is nothing to penalise"
        )
    if block_ids is not None and np.shape(block_ids) != (customers,):
        raise ValueError(
            f"block_ids must hold one block per customer ({customers}), got "
            f"shape {np.shape(block_ids)}"
        )


def _lloyd(
    points: np.ndarray,
    centers: np.ndarray,
    capacity: int,
    candidates: int,
    max_iter: int,
    *,
    labels: np.ndarray | None = None,
    block_ids: np.ndarray | None = None,
    block_penalty_km2: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, int, bool]:
    """Alternate capacitated assignment and re-centring until labels settle.

    Args:
        points: Customer coordinates.
        centers: Starting centres.
        capacity: Maximum customers per transformer.
        candidates: Nearest transformers considered per customer.
        max_iter: Iteration limit.
        labels: Labels to start from, required for the block penalty because
            dominant blocks are read from the current membership.
        block_ids: Optional block of each customer.
        block_penalty_km2: Penalty for leaving the dominant block.

    Returns:
        ``(labels, centers, iterations, converged)``.
    """
    current = labels
    for iteration in range(1, max_iter + 1):
        dominant = None
        if block_ids is not None and current is not None:
            dominant = _dominant_blocks(current, block_ids, len(centers))
        assigned = _assign_step(
            points,
            centers,
            capacity,
            candidates,
            block_ids,
            dominant,
            block_penalty_km2,
        )
        if current is not None and np.array_equal(assigned, current):
            return assigned, centers, iteration, True
        current = assigned
        centers = _recenter(points, current, centers)
    assert current is not None  # max_iter >= 1 always assigns once
    return current, centers, max_iter, False


def _assign_step(
    points: np.ndarray,
    centers: np.ndarray,
    capacity: int,
    candidates: int,
    block_ids: np.ndarray | None,
    dominant: np.ndarray | None,
    block_penalty_km2: float,
) -> np.ndarray:
    """Solve one capacitated assignment, widening the candidates if needed.

    Args:
        points: Customer coordinates.
        centers: Current centres.
        capacity: Maximum customers per transformer.
        candidates: Nearest transformers considered per customer at first.
        block_ids: Optional block of each customer.
        dominant: Optional dominant block of each cluster, ``-1`` for none.
        block_penalty_km2: Penalty for leaving the dominant block.

    Returns:
        The transformer index of each customer.

    Raises:
        RuntimeError: If even the unrestricted problem returns no integral
            solution, which a feasible transportation problem cannot do.
    """
    from scipy.spatial import cKDTree

    transformers = len(centers)
    tree = cKDTree(centers)
    width = min(candidates, transformers)
    while True:
        distances, nearest = tree.query(points, k=width)
        distances = np.asarray(distances, dtype=float).reshape(len(points), width)
        nearest = np.asarray(nearest, dtype=int).reshape(len(points), width)
        cost = distances**2 / _SQUARED_METRES_PER_KM2
        if dominant is not None and block_ids is not None:
            leaves = (
                (block_ids[:, None] >= 0)
                & (dominant[nearest] >= 0)
                & (block_ids[:, None] != dominant[nearest])
            )
            cost = cost + block_penalty_km2 * leaves
        labels = _solve_transport(cost, nearest, capacity, transformers)
        if labels is not None:
            return labels
        if width == transformers:
            raise RuntimeError(
                "capacitated assignment returned no integral solution over every "
                f"transformer ({transformers}) at capacity {capacity}"
            )
        width = min(2 * width, transformers)


def _solve_transport(
    cost: np.ndarray, nearest: np.ndarray, capacity: int, transformers: int
) -> np.ndarray | None:
    """Solve the restricted transportation problem as a linear programme.

    The constraint matrix is totally unimodular, so a simplex vertex is
    integral; the check below guards the solver rather than the maths.

    Args:
        cost: ``(n, m)`` cost of each customer's ``m`` candidates.
        nearest: ``(n, m)`` transformer index of each candidate.
        capacity: Maximum customers per transformer.
        transformers: Number of transformers.

    Returns:
        The transformer index of each customer, or ``None`` when the restricted
        problem is infeasible or the solver returned a fractional point.
    """
    from scipy.optimize import linprog
    from scipy.sparse import coo_matrix

    customers, width = cost.shape
    rows = np.repeat(np.arange(customers), width)
    columns = nearest.ravel()
    variables = np.arange(customers * width)
    ones = np.ones(customers * width)
    result = linprog(
        cost.ravel(),
        A_ub=coo_matrix((ones, (columns, variables)), shape=(transformers, len(ones))),
        b_ub=np.full(transformers, capacity),
        A_eq=coo_matrix((ones, (rows, variables)), shape=(customers, len(ones))),
        b_eq=np.ones(customers),
        bounds=(0, 1),
        method="highs-ds",
    )
    if result.status != 0 or result.x is None:
        return None
    chosen = result.x > 0.5
    if int(chosen.sum()) != customers or not np.allclose(result.x[chosen], 1.0):
        return None
    labels = np.empty(customers, dtype=int)
    labels[rows[chosen]] = columns[chosen]
    return labels


def _recenter(
    points: np.ndarray, labels: np.ndarray, centers: np.ndarray
) -> np.ndarray:
    """Move each centre to the mean of its members; an empty cluster stays put.

    Args:
        points: Customer coordinates.
        labels: Transformer index of each customer.
        centers: Current centres.

    Returns:
        The new centres.
    """
    counts = np.bincount(labels, minlength=len(centers))
    sums = np.zeros_like(centers)
    np.add.at(sums, labels, points)
    moved = centers.copy()
    occupied = counts > 0
    moved[occupied] = sums[occupied] / counts[occupied, None]
    return moved


def _dominant_blocks(
    labels: np.ndarray, block_ids: np.ndarray, transformers: int
) -> np.ndarray:
    """Return the most common block among each cluster's members.

    Args:
        labels: Transformer index of each customer.
        block_ids: Block of each customer, ``-1`` outside every block.
        transformers: Number of clusters.

    Returns:
        ``(k,)`` dominant block per cluster, ``-1`` for a cluster with no
        member inside a block. Ties go to the lowest block id.
    """
    dominant = np.full(transformers, -1, dtype=int)
    inside = block_ids >= 0
    if not inside.any():
        return dominant
    pairs = np.column_stack((labels[inside], block_ids[inside]))
    unique, counts = np.unique(pairs, axis=0, return_counts=True)
    order = np.lexsort((unique[:, 1], -counts, unique[:, 0]))
    ranked = unique[order]
    first = np.ones(len(ranked), dtype=bool)
    first[1:] = ranked[1:, 0] != ranked[:-1, 0]
    dominant[ranked[first, 0]] = ranked[first, 1]
    return dominant


__all__ = ["CapacitatedAssignment", "DEFAULT_CANDIDATES", "assign_capacitated"]
