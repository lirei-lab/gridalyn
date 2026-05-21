"""
settlement.py - Deterministic Financial Settlement Engine

This module implements the explicit financial settlement mechanisms defined mathematically
in Equation 7 of the methodology. It calculates the upfront reservation compensation
for successful Merit-Order clearance and applies structural penalties for deterministic
telemetry violations of the absolute power envelope ($P_{\text{cap}}$).
"""

from dataclasses import dataclass
from typing import Dict


@dataclass
class AggregatorSettlementReceipt:
    block_id: int
    reservation_payment: float
    volume_cleared_kw: float
    penalty_deduction: float
    net_profit: float
    violation_kwh: float


def calculate_period_settlement(
    allocations_kw: Dict[str, float],
    c_mcp_lambda: float,
    actual_p_meter_kw: float,
    dt_h: float,
    lambda_pen_penalty: float = 10.0,
    p_cap_limit_kw: float = None
) -> AggregatorSettlementReceipt:
    """
    Evaluates baseline-free CLS settlement with deterministic AMI penalties.
    
    Parameters
    ----------
    allocations_kw : Dict[str, float]
        Dictionary of cleared limitation volumes ΔP^soft = max(0, P^H - P_cap)
        per accepted block (e.g. {"building_hvac_b1": 15.0, ...}). These are
        derived deterministically from the contractual cap and the DSO-validated
        reference import at clearing time; they are not ex-post estimates.
    c_mcp_lambda : float
        Uniform market clearing price (lambda) in $/(kW*h).
    actual_p_meter_kw : float
        The physical native load telemetry captured during the window.
    dt_h : float
        Resolution of this specific telemetry check in hours (e.g. 5/60 for 5-minute data).
    lambda_pen_penalty : float
        Punitive cost metric ($/(kW*h)) for breaching the structural envelope. Defaults
        to $10.0 to logically anchor against the social cost of Hard CLS.
    p_cap_limit_kw : float, optional
        Absolute contractual cap recorded at clearing. Mainline settlement passes this
        explicitly so payments and penalties do not depend on a reconstructed baseline.
        
    Returns
    -------
    AggregatorSettlementReceipt
        Immutable statement containing the precise cash flows for the aggregator.
    """
    # 1. Pay the cleared limitation volume ΔP^soft at the uniform price λ.
    c_soft_cleared = sum(allocations_kw.values())
    
    revenue = c_soft_cleared * c_mcp_lambda * dt_h
    
    if c_soft_cleared <= 0:
        return AggregatorSettlementReceipt(
            block_id=-1,
            reservation_payment=0.0,
            volume_cleared_kw=0.0,
            penalty_deduction=0.0,
            net_profit=0.0,
            violation_kwh=0.0
        )
        
    # 2. Strict Deterministic Boundary Evaluation
    if p_cap_limit_kw is None:
        raise ValueError("p_cap_limit_kw is required when cleared volume is positive")
    p_cap_limit = p_cap_limit_kw
    
    # Did the meter structurally breach the cap?
    breach_kw = max(0.0, actual_p_meter_kw - p_cap_limit)
    breach_kwh = breach_kw * dt_h
    
    # Apply deterministic structural penalty independent of baselines
    penalty = breach_kwh * lambda_pen_penalty
    
    net = revenue - penalty
    
    return AggregatorSettlementReceipt(
        block_id=-1,  # Will be mapped externally
        reservation_payment=revenue,
        volume_cleared_kw=c_soft_cleared,
        penalty_deduction=penalty,
        net_profit=net,
        violation_kwh=breach_kwh
    )
