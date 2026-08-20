"""North America residential building archetypes.

The defaults are intentionally lightweight. They are inspired by pyCity's
entity-oriented philosophy, but they stay dependency-free and deterministic so
that project workflows can generate repeatable building model artifacts from
the digital twin base layer.

**`heating_kw_per_m2`/`cooling_kw_per_m2` are deliberately independent of
`gridalyn.assets.datagen.agents.buildings`'s RC thermal simulator
(`P_HEAT_MAX_KW`/`R_MEAN`/etc.; R27/Phase 32, 2026-08-20).** This module is a
static per-archetype capacity lookup (no time dimension), consumed by
`synthesis.py` to populate structural asset tables; the datagen module is a
dynamic RC simulator that produces load *curves* consumed by studies with
pinned regression baselines. See that module's docstring for the full
rationale before assuming one is a stale duplicate of the other.
"""

from __future__ import annotations

from dataclasses import dataclass

NORTH_AMERICA_RESIDENTIAL_PROFILE = "north_america_residential_v1"


@dataclass(frozen=True)
class BuildingArchetype:
    """Compact archetype used to synthesize building and thermal entities."""

    archetype_id: str
    use_type: str
    area_min_m2: float
    area_max_m2: float | None
    dwelling_units: int
    thermal_resistance_c_per_kw: float
    thermal_capacitance_kwh_per_c: float
    heating_kw_per_m2: float
    cooling_kw_per_m2: float
    base_load_kw_per_m2: float
    annual_kwh_per_m2: float
    flexibility_class: str

    def contains(self, area_m2: float) -> bool:
        if area_m2 < self.area_min_m2:
            return False
        return self.area_max_m2 is None or area_m2 < self.area_max_m2


NORTH_AMERICA_RESIDENTIAL_ARCHETYPES = (
    BuildingArchetype(
        archetype_id="na_residential_small",
        use_type="residential_detached_or_rowhouse",
        area_min_m2=0.0,
        area_max_m2=160.0,
        dwelling_units=1,
        thermal_resistance_c_per_kw=12.0,
        thermal_capacitance_kwh_per_c=2.2,
        heating_kw_per_m2=0.055,
        cooling_kw_per_m2=0.018,
        base_load_kw_per_m2=0.006,
        annual_kwh_per_m2=160.0,
        flexibility_class="thermal_soft_cls",
    ),
    BuildingArchetype(
        archetype_id="na_residential_medium",
        use_type="residential_detached_or_lowrise",
        area_min_m2=160.0,
        area_max_m2=300.0,
        dwelling_units=1,
        thermal_resistance_c_per_kw=11.0,
        thermal_capacitance_kwh_per_c=2.6,
        heating_kw_per_m2=0.048,
        cooling_kw_per_m2=0.016,
        base_load_kw_per_m2=0.005,
        annual_kwh_per_m2=145.0,
        flexibility_class="thermal_soft_cls",
    ),
    BuildingArchetype(
        archetype_id="na_residential_multifamily",
        use_type="residential_multifamily",
        area_min_m2=300.0,
        area_max_m2=None,
        dwelling_units=2,
        thermal_resistance_c_per_kw=9.5,
        thermal_capacitance_kwh_per_c=3.0,
        heating_kw_per_m2=0.035,
        cooling_kw_per_m2=0.014,
        base_load_kw_per_m2=0.004,
        annual_kwh_per_m2=120.0,
        flexibility_class="thermal_soft_cls",
    ),
)


def select_archetype(
    area_m2: float | int | None,
    *,
    profile: str = NORTH_AMERICA_RESIDENTIAL_PROFILE,
) -> BuildingArchetype:
    """Return a deterministic residential archetype for a floor area."""

    if profile != NORTH_AMERICA_RESIDENTIAL_PROFILE:
        raise ValueError(f"Unsupported building model profile: {profile}")
    area = 100.0 if area_m2 is None else max(float(area_m2), 1.0)
    for archetype in NORTH_AMERICA_RESIDENTIAL_ARCHETYPES:
        if archetype.contains(area):
            return archetype
    return NORTH_AMERICA_RESIDENTIAL_ARCHETYPES[-1]
