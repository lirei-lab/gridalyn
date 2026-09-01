"""Read the published OCHRE/EnergyPlus receipts as typed records.

The harness measures things the SDK cannot: an external white-box reference for
the RC building model. Its results were previously readable only as raw JSON in
a gitignored directory, so nothing checked that they said what they claim to.

This module gives them a typed home. The error bound is returned as the
:class:`~gridalyn.simulation.surrogates.contract.ErrorBound` the harness was
written to produce -- its docstring calls the scalar "the surrogate's
ErrorBound" and ``rc_error_bound.json`` matches that dataclass field for field
-- so constructing it here runs the contract's own validation over the file.

Why this lives in ``tools/`` rather than in the SDK: ``gridalyn/assets/`` holds
the RC building agent and sits BELOW ``gridalyn/simulation/`` in the layer
order, so it may not import ``ErrorBound``. ``tools/`` is outside the layer
graph and may. Formally registering a component as the surrogate that carries
this bound is separate work.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:  # pragma: no cover - import-path bootstrap
    sys.path.insert(0, str(REPO_ROOT))

from gridalyn.simulation.surrogates.contract import ErrorBound  # noqa: E402

RECEIPTS_DIR = Path(__file__).resolve().parent / "receipts"


def _read(name: str) -> dict[str, Any]:
    """Return one published receipt as a mapping.

    Args:
        name: File name inside the receipts directory.

    Returns:
        The parsed JSON object.

    Raises:
        FileNotFoundError: If the receipt is absent, naming the directory and
            the publisher that fills it.
    """
    path = RECEIPTS_DIR / name
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} not found. Published receipts live in {RECEIPTS_DIR}; "
            "regenerate them with "
            "`python tools/ochre_calibration/publish_receipts.py` on a machine "
            "that has run the OCHRE harness."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def load_rc_error_bound() -> ErrorBound:
    """Return the RC model's measured error bound against EnergyPlus.

    The bound is *promised relief minus delivered relief* over a holdout the
    bound was not fitted on, so a positive magnitude with ``promised`` below
    ``delivered`` means the RC model UNDERSTATES the relief it will get.

    Returns:
        A ``measured`` :class:`ErrorBound`, validated by its own contract.

    Raises:
        FileNotFoundError: If the receipt is absent.
        ValueError: If the receipt does not satisfy the ErrorBound contract.
    """
    payload = _read("rc_error_bound.json")
    return ErrorBound(
        metric=payload["metric"],
        units=payload["units"],
        value=float(payload["value"]),
        sample_size=int(payload["sample_size"]),
        method=payload["method"],
        reference=payload["reference"],
        status=payload["status"],
    )


@dataclass(frozen=True)
class FlexibilityResult:
    """One arm of the EnergyPlus-validated flexibility dispatch.

    Attributes:
        dwellings: How many dwellings this arm covers.
        mean_relief_kw_per_home: Load shed during the curtail window.
        peak_relief_kw_per_home: Largest shed in any step of the window.
        rebound_kw_per_home: Load above baseline after the window closes.
        net_energy_kwh_per_home: Energy difference over the whole episode.
        comfort_drift_c_mean: Mean indoor temperature depression.
        comfort_drift_c_worst: Worst indoor temperature depression -- the
            constraint the household cares about, as opposed to the feeder.
    """

    dwellings: int
    mean_relief_kw_per_home: float
    peak_relief_kw_per_home: float
    rebound_kw_per_home: float
    net_energy_kwh_per_home: float
    comfort_drift_c_mean: float
    comfort_drift_c_worst: float


def load_flexibility_holdout() -> FlexibilityResult:
    """Return the flexibility dispatch measured on the disjoint holdout.

    This is the citable arm: dwellings the decision was not fitted on.

    Returns:
        The holdout arm of ``flexbound.json``.

    Raises:
        FileNotFoundError: If the receipt is absent.
    """
    arm = _read("flexbound.json")["holdout"]
    return FlexibilityResult(
        dwellings=int(arm["dwellings"]),
        mean_relief_kw_per_home=float(arm["mean_relief_kw_per_home"]),
        peak_relief_kw_per_home=float(arm["peak_relief_kw_per_home"]),
        rebound_kw_per_home=float(arm["rebound_kw_per_home"]),
        net_energy_kwh_per_home=float(arm["net_energy_kwh_per_home"]),
        comfort_drift_c_mean=float(arm["comfort_drift_c_mean"]),
        comfort_drift_c_worst=float(arm["comfort_drift_c_worst"]),
    )


def load_coincidence_curve(split: str = "validation") -> dict[int, float]:
    """Return the EnergyPlus coincidence factor by group size.

    Args:
        split: ``"calibration"`` or ``"validation"`` half of the dwelling pool.

    Returns:
        Group size -> coincidence factor.

    Raises:
        FileNotFoundError: If the receipt is absent.
        KeyError: If ``split`` is not one of the two halves, naming both.
    """
    payload = _read("hq_split_targets.json")
    if split not in payload:
        raise KeyError(f"unknown split {split!r} (known: {', '.join(sorted(payload))})")
    return {int(row["homes"]): float(row["cf"]) for row in payload[split]["curve"]}
