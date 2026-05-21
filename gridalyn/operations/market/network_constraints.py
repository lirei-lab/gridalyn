"""Protocols for physical network constraints used by market operations."""

from __future__ import annotations

from typing import Any, Protocol


class NetworkConstraintModel(Protocol):
    """Network interface required by DSO dispatch and market simulation."""

    p_limit_kw: float
    thermal_model: Any

    def probabilistic_constraint_check(
        self,
        p_mean_kw: float,
        p_std_kw: float,
        *,
        ambient_c: float | None = None,
        epsilon: float = 0.05,
    ) -> dict:
        """Return probabilistic congestion status and relief requirement."""
