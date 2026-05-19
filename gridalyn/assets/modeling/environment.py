"""Modeling environment metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from gridalyn.assets.modeling.archetypes import NORTH_AMERICA_RESIDENTIAL_PROFILE


@dataclass(frozen=True)
class ModelingEnvironment:
    """Metadata shared by synthesized building model artifacts."""

    model_profile: str = NORTH_AMERICA_RESIDENTIAL_PROFILE
    region: str = "north_america"
    timezone: str = "America/Toronto"
    weather_source: str = "project_weather_or_typical_meteorological_year"
    power_unit: str = "kW"
    energy_unit: str = "kWh"
    temperature_unit: str = "degC"

    def to_record(self) -> dict[str, object]:
        return asdict(self)
