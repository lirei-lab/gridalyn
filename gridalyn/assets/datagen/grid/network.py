"""Simplified MV-network model for synthetic flexibility studies.

The module provides a configurable aggregate substation and feeder-block model.
It is intentionally lightweight: it supports repeatable market and thermal-limit
experiments without claiming to be a calibrated utility planning model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from gridalyn.assets.modeling.transformers import TransformerThermalModel

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_GRID_CONFIG_PATH = REPO_ROOT / "configs" / "grid" / "config.json"

DEFAULT_TRANSFORMER_KVA = 15_000.0
DEFAULT_VOLTAGE_HV_KV = 120.0
DEFAULT_VOLTAGE_MV_KV = 25.0
DEFAULT_PF_NOMINAL = 0.95
DEFAULT_THETA_MAX_C = 110.0
DEFAULT_EMERGENCY_MULTIPLIER = 1.20
DEFAULT_N_UNITS_PER_BLOCK = 50

TRANSFORMER_KVA = DEFAULT_TRANSFORMER_KVA
TRANSFORMER_MVA = TRANSFORMER_KVA / 1000.0
VOLTAGE_HV_KV = DEFAULT_VOLTAGE_HV_KV
VOLTAGE_MV_KV = DEFAULT_VOLTAGE_MV_KV
PF_NOMINAL = DEFAULT_PF_NOMINAL
P_RATED_KW = TRANSFORMER_KVA * PF_NOMINAL
P_EMERGENCY_KW = P_RATED_KW * DEFAULT_EMERGENCY_MULTIPLIER
P_LIMIT_KW = TRANSFORMER_KVA
THETA_MAX = DEFAULT_THETA_MAX_C
I_MAX_A = (TRANSFORMER_KVA * 1000) / (1.732 * VOLTAGE_MV_KV * 1000)
N_UNITS_PER_BLOCK = DEFAULT_N_UNITS_PER_BLOCK
N_BLOCKS_TOTAL = 160


@dataclass(frozen=True)
class MVNetworkConfig:
    """Configuration for the aggregate MV-network model."""

    transformer_kva: float = DEFAULT_TRANSFORMER_KVA
    voltage_hv_kv: float = DEFAULT_VOLTAGE_HV_KV
    voltage_mv_kv: float = DEFAULT_VOLTAGE_MV_KV
    power_factor: float = DEFAULT_PF_NOMINAL
    theta_max_c: float = DEFAULT_THETA_MAX_C
    emergency_multiplier: float = DEFAULT_EMERGENCY_MULTIPLIER
    n_units_per_block: int = DEFAULT_N_UNITS_PER_BLOCK

    @property
    def transformer_mva(self) -> float:
        return self.transformer_kva / 1000.0

    @property
    def p_rated_kw(self) -> float:
        return self.transformer_kva * self.power_factor

    @property
    def p_emergency_kw(self) -> float:
        return self.p_rated_kw * self.emergency_multiplier

    @property
    def p_limit_kw(self) -> float:
        return self.transformer_kva

    @property
    def i_max_a(self) -> float:
        return (self.transformer_kva * 1000.0) / (1.732 * self.voltage_mv_kv * 1000.0)


def load_mv_network_config(
    config_path: Path | str = DEFAULT_GRID_CONFIG_PATH,
) -> MVNetworkConfig:
    """Load an MV-network configuration from a Gridalyn grid config JSON file."""
    path = Path(config_path)
    payload = json.loads(path.read_text())
    transformer = payload.get("transformers", {}).get("mv_hv", {})
    buses = payload.get("buses", {})
    return MVNetworkConfig(
        transformer_kva=float(transformer.get("capacity_kva", DEFAULT_TRANSFORMER_KVA)),
        voltage_hv_kv=float(
            buses.get("hv", {}).get("voltage_kv", DEFAULT_VOLTAGE_HV_KV)
        ),
        voltage_mv_kv=float(
            buses.get("mv", {}).get("voltage_kv", DEFAULT_VOLTAGE_MV_KV)
        ),
        power_factor=float(transformer.get("power_factor", DEFAULT_PF_NOMINAL)),
        theta_max_c=float(transformer.get("theta_max_c", DEFAULT_THETA_MAX_C)),
    )


@dataclass
class Feeder:
    """One radial MV branch of an :class:`MVNetwork`.

    A feeder is sized by the number of load blocks hanging off it; the block
    count times ``MVNetwork.n_units_per_block`` gives the dwellings it serves,
    which is what the network's aggregate demand and thermal-limit checks are
    computed from. The default network is four 40-block feeders.

    Attributes:
        name: Feeder label used in artifacts and per-feeder reporting.
        n_blocks: Number of load blocks connected along the branch.
        impedance_pu: Series impedance in per unit, on the network base.
    """

    name: str
    n_blocks: int
    impedance_pu: float = 0.02


@dataclass
class MVNetwork:
    """Aggregate radial MV network with dynamic thermal-limit checks."""

    feeders: list[Feeder] = field(
        default_factory=lambda: [
            Feeder("Feeder-1", n_blocks=40),
            Feeder("Feeder-2", n_blocks=40),
            Feeder("Feeder-3", n_blocks=40),
            Feeder("Feeder-4", n_blocks=40),
        ]
    )
    p_limit_kw: float = P_LIMIT_KW
    p_emergency_kw: float = P_EMERGENCY_KW
    p_rated_kw: float = P_RATED_KW
    transformer_mva: float = TRANSFORMER_MVA
    n_units_per_block: int = N_UNITS_PER_BLOCK
    thermal_model: TransformerThermalModel = field(
        default_factory=lambda: TransformerThermalModel(
            theta_max=THETA_MAX, s_rated_kva=TRANSFORMER_KVA
        )
    )

    @classmethod
    def from_config(cls, config: MVNetworkConfig) -> "MVNetwork":
        """Create a network from explicit configuration values."""
        return cls(
            p_limit_kw=config.p_limit_kw,
            p_emergency_kw=config.p_emergency_kw,
            p_rated_kw=config.p_rated_kw,
            transformer_mva=config.transformer_mva,
            n_units_per_block=config.n_units_per_block,
            thermal_model=TransformerThermalModel(
                theta_max=config.theta_max_c,
                s_rated_kva=config.transformer_kva,
            ),
        )

    @classmethod
    def from_grid_config(
        cls, config_path: Path | str = DEFAULT_GRID_CONFIG_PATH
    ) -> "MVNetwork":
        """Create a network from ``configs/grid/config.json`` or a compatible file."""
        return cls.from_config(load_mv_network_config(config_path))

    @property
    def n_blocks(self) -> int:
        return sum(f.n_blocks for f in self.feeders)

    @property
    def n_units(self) -> int:
        return self.n_blocks * self.n_units_per_block

    def check_constraint(
        self, p_total_kw: float, ambient_c: float | None = None
    ) -> dict:
        """
        Return constraint status dict.
        - ``ok``: load is below the static or ambient-dependent limit.
        - ``amber``: load exceeds the normal limit but remains below emergency loading.
        - ``red``: load exceeds emergency loading.
        """
        # If ambient is provided, use the thermal model steady-state limit
        limit_kw = self.p_limit_kw
        if ambient_c is not None:
            limit_kw = self.thermal_model.max_load_for_temp(ambient_c)

        if p_total_kw <= limit_kw:
            status = "ok"
        elif p_total_kw <= self.p_emergency_kw:
            status = "amber"
        else:
            status = "red"

        congestion_relief_kw = max(0.0, p_total_kw - limit_kw)

        res = {
            "p_total_kw": p_total_kw,
            "p_total_mw": round(p_total_kw / 1000, 2),
            "p_limit_kw": limit_kw,
            "status": status,
            "congestion_relief_kw": congestion_relief_kw,
            "loading_pct": 100 * p_total_kw / self.p_rated_kw,
        }

        if ambient_c is not None:
            res["theta_h_steady_state_c"] = self.thermal_model.steady_state(
                p_total_kw, ambient_c
            )

        return res

    def probabilistic_constraint_check(
        self,
        p_mean_kw: float,
        p_std_kw: float,
        ambient_c: float | None = None,
        epsilon: float = 0.05,
    ) -> dict:
        """
        Declare congestion when the probability of exceeding the thermal limit is
        greater than ``epsilon``. If ambient temperature is provided, the limit is
        computed from the thermal model for that ambient condition.
        """
        limit_kw = self.p_limit_kw
        if ambient_c is not None:
            limit_kw = self.thermal_model.max_load_for_temp(ambient_c)

        if p_std_kw <= 1e-6:
            prob_exceed = 1.0 if p_mean_kw > limit_kw else 0.0
        else:
            from scipy.stats import norm

            prob_exceed = 1 - norm.cdf(limit_kw, loc=p_mean_kw, scale=p_std_kw)

        congested = prob_exceed > epsilon
        if p_std_kw <= 1e-6:
            relief_kw = max(0.0, p_mean_kw - limit_kw)
        else:
            z_score = norm.ppf(1 - epsilon)
            target_mean = limit_kw - (z_score * p_std_kw)
            relief_kw = max(0.0, p_mean_kw - target_mean)

        return {
            "p_mean_kw": p_mean_kw,
            "p_mean_mw": round(p_mean_kw / 1000, 2),
            "p_std_kw": p_std_kw,
            "P(exceed_thermal_limit)": round(float(prob_exceed), 4),
            "congested": congested,
            "congestion_relief_kw": relief_kw,
            "thermal_limit_kw": limit_kw,
            "ambient_c": ambient_c,
        }


NETWORK = MVNetwork()


if __name__ == "__main__":
    print(f"Network: {NETWORK.transformer_mva} MVA substation")
    print(
        f"  {NETWORK.n_blocks} residential blocks × {NETWORK.n_units_per_block} households "
        f"= {NETWORK.n_units:,} virtual customers"
    )
    print(
        f"  P_rated={NETWORK.p_rated_kw/1000:.2f} MW  "
        f"P_LIMIT={NETWORK.p_limit_kw/1000:.1f} MW  "
        f"I_max={I_MAX_A:.0f} A @ {VOLTAGE_MV_KV} kV"
    )
    for p in [15_000, 20_000, 25_000, 30_000]:
        r = NETWORK.check_constraint(p)
        print(
            f"  P={p/1000:.0f} MW → {r['status'].upper()}  "
            f"(loading={r['loading_pct']:.1f}%)"
        )
