"""Cooling water system demand estimation (evaporation, blowdown, drift,
total makeup).

Method: the standard cooling-tower water-balance rules of thumb (Cooling
Tower Institute practice, reproduced in GPSA Engineering Data Book Ch. 9
and most utilities/plant-design texts):

    evaporation_fraction_of_circulation = 0.00085 * delta_T_F

(delta_T_F = cooling range across the tower, in Fahrenheit degrees; the
0.00085 constant already bakes in a typical climate correction, matching
the commonly quoted "~1% evaporation per 10 F of range" rule of thumb).

    blowdown_fraction = evaporation_fraction / (cycles_of_concentration - 1)
    drift_fraction = a small fixed fraction set by the drift eliminator design
    makeup_fraction = evaporation_fraction + blowdown_fraction + drift_fraction

Cycles of concentration (COC): 3-5 is typical, cited practice for
hydrocarbon-plant cooling towers (higher COC needs more water treatment
but uses less makeup water); modern high-efficiency drift eliminators
achieve drift well under 0.001% of circulation (older designs closer to
0.02%) - both figures are commonly quoted API 661/CTI ranges.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CoolingWaterDemandResult:
    circulation_rate_m3_h: float
    evaporation_m3_h: float
    blowdown_m3_h: float
    drift_m3_h: float
    total_makeup_m3_h: float


def cooling_water_demand(
    total_cooling_duty_kW: float,
    supply_temp_C: float,
    return_temp_C: float,
    cycles_of_concentration: float = 4.0,
    drift_fraction: float = 0.0005,
    water_cp_kJ_kgK: float = 4.186,
    water_density_kg_m3: float = 995.0,  # ~35 C, typical CW return temp
) -> CoolingWaterDemandResult:
    """total_cooling_duty_kW: total heat rejected to cooling water across
    the plant (sum of all cooling-water-served exchanger duties).
    supply_temp_C / return_temp_C: cooling water supply (cold, to
    exchangers) and return (warm, to tower) temperatures.
    """
    delta_T_C = return_temp_C - supply_temp_C
    if delta_T_C <= 0:
        raise ValueError("return_temp_C must exceed supply_temp_C")
    delta_T_F = delta_T_C * 9.0 / 5.0

    mass_flow_kg_s = (total_cooling_duty_kW) / (water_cp_kJ_kgK * delta_T_C)
    circulation_m3_h = mass_flow_kg_s / water_density_kg_m3 * 3600.0

    evap_fraction = 0.00085 * delta_T_F
    evaporation_m3_h = evap_fraction * circulation_m3_h

    if cycles_of_concentration <= 1.0:
        raise ValueError("cycles_of_concentration must exceed 1.0")
    blowdown_fraction = evap_fraction / (cycles_of_concentration - 1.0)
    blowdown_m3_h = blowdown_fraction * circulation_m3_h

    drift_m3_h = drift_fraction * circulation_m3_h

    return CoolingWaterDemandResult(
        circulation_rate_m3_h=circulation_m3_h,
        evaporation_m3_h=evaporation_m3_h,
        blowdown_m3_h=blowdown_m3_h,
        drift_m3_h=drift_m3_h,
        total_makeup_m3_h=evaporation_m3_h + blowdown_m3_h + drift_m3_h,
    )
