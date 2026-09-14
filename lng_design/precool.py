"""Single-stage propane (C3) pre-cooling refrigeration cycle.

Standard vapor-compression cycle sizing (any refrigeration textbook, e.g.
ASHRAE Fundamentals Ch. 2): evaporate at T_evap, compress to condensing
pressure at a given isentropic efficiency, condense at T_cond, throttle
back to T_evap. Uses CoolProp's propane equation of state rather than a
simplified chart lookup, so results are consistent to the underlying
reference EOS (Lemmon et al.) rather than to a digitized chart.

This is the C3 stage of a C3MR-style LNG process: propane pre-cools the
natural gas (and the mixed-refrigerant loop) ahead of the cryogenic
(MCHE) section.
"""
from __future__ import annotations

from dataclasses import dataclass

import CoolProp.CoolProp as CP


@dataclass
class PrecoolCycleResult:
    T_evap_K: float
    T_cond_K: float
    P_evap_Pa: float
    P_cond_Pa: float
    refrigerant_mass_flow_kg_s: float
    compressor_power_kW: float
    cop: float


def propane_cycle_power(
    duty_kW: float,
    T_evap_K: float,
    T_cond_K: float,
    isentropic_efficiency: float = 0.75,
) -> PrecoolCycleResult:
    """Compressor power for a single-stage propane refrigeration cycle
    delivering `duty_kW` of refrigeration at evaporator temperature
    T_evap_K, rejecting heat at condenser temperature T_cond_K.
    """
    fluid = "Propane"
    h1 = CP.PropsSI("H", "T", T_evap_K, "Q", 1, fluid)
    s1 = CP.PropsSI("S", "T", T_evap_K, "Q", 1, fluid)
    P_evap = CP.PropsSI("P", "T", T_evap_K, "Q", 1, fluid)
    P_cond = CP.PropsSI("P", "T", T_cond_K, "Q", 0, fluid)

    h2s = CP.PropsSI("H", "P", P_cond, "S", s1, fluid)
    h2 = h1 + (h2s - h1) / isentropic_efficiency

    h3 = CP.PropsSI("H", "T", T_cond_K, "Q", 0, fluid)
    # h4 = h3 (isenthalpic throttle)

    refrig_effect = h1 - h3  # J/kg
    if refrig_effect <= 0:
        raise ValueError(
            "Non-physical cycle: condensing enthalpy exceeds evaporator "
            "vapor enthalpy - check T_evap/T_cond ordering"
        )
    mdot = duty_kW * 1000.0 / refrig_effect
    power_kW = mdot * (h2 - h1) / 1000.0
    cop = duty_kW / power_kW if power_kW > 0 else float("inf")

    return PrecoolCycleResult(
        T_evap_K=T_evap_K,
        T_cond_K=T_cond_K,
        P_evap_Pa=P_evap,
        P_cond_Pa=P_cond,
        refrigerant_mass_flow_kg_s=mdot,
        compressor_power_kW=power_kW,
        cop=cop,
    )


def optimal_evap_temperature(
    duty_kW: float,
    T_cold_end_target_K: float,
    T_cond_K: float,
    mita_K: float = 3.0,
    isentropic_efficiency: float = 0.75,
) -> PrecoolCycleResult:
    """Find the propane evaporation temperature that minimizes compressor
    power for a fixed duty, subject to a MITA pinch constraint against the
    process stream's cold-end target temperature.

    For a single evaporation level and fixed condensing temperature, power
    monotonically decreases as T_evap rises (better COP), so the
    MITA-limited boundary is the true optimum - this function evaluates a
    small bracket near that boundary and returns the best feasible point,
    which also serves as a sanity check that the boundary is in fact where
    the minimum lands (it also generalizes correctly if a future variant
    adds temperature-dependent isentropic efficiency, which can shift the
    optimum off the boundary).
    """
    from scipy.optimize import minimize_scalar

    T_evap_max = T_cold_end_target_K - mita_K
    T_evap_min = CP.PropsSI("Ttriple", "Propane") + 1.0
    if T_evap_max <= T_evap_min:
        raise ValueError(
            "Infeasible: MITA constraint leaves no valid evaporator "
            "temperature range above propane's triple point"
        )

    def objective(T_evap: float) -> float:
        try:
            return propane_cycle_power(duty_kW, T_evap, T_cond_K, isentropic_efficiency).compressor_power_kW
        except ValueError:
            return float("inf")

    result = minimize_scalar(objective, bounds=(T_evap_min, T_evap_max), method="bounded")
    return propane_cycle_power(duty_kW, result.x, T_cond_K, isentropic_efficiency)
