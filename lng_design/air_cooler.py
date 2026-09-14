"""Air-cooled heat exchanger (fin-fan) conceptual sizing.

Method: GPSA Engineering Data Book Ch. 9 ("Air-Cooled Exchangers") and
API 661 conventions:

1. Air-side mass flow from the required duty and a chosen air temperature
   rise (GPSA typical design range: 8-20 K rise; smaller rise needs more
   air/bigger fans but gives a lower process outlet temperature approach).
2. Face area from air volumetric flow and a face velocity (GPSA typical
   range ~2.5-3.5 m/s for induced-draft units at design ambient).
3. Required face area is matched to a standard bay width (API 661
   permits 8-16 ft / 2.4-4.9 m) and length, from `equipment_catalog.py`.
4. Fan power from a standard fan-power relation (volumetric flow x static
   pressure drop / fan efficiency) - GPSA Ch. 9 quotes typical air-side
   static pressure drops of 12-25 mm H2O across a finned-tube bundle;
   axial fan static efficiencies of 60-70% are typical (API 661).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .equipment_catalog import (
    STANDARD_AIR_COOLER_BAY_LENGTHS_M,
    STANDARD_AIR_COOLER_BAY_WIDTHS_M,
)

AIR_CP_J_KGK = 1006.0       # dry air, ~300 K
AIR_DENSITY_KG_M3 = 1.15    # approx at typical hot-climate design ambient


@dataclass
class AirCoolerSizingResult:
    duty_kW: float
    air_mass_flow_kg_s: float
    air_volumetric_flow_m3_s: float
    required_face_area_m2: float
    bay_width_m: float
    bay_length_m: float
    n_bays: int
    fan_power_kW_per_bay: float
    total_fan_power_kW: float


def size_air_cooler(
    duty_kW: float,
    design_ambient_T_C: float,
    air_temperature_rise_K: float = 14.0,
    face_velocity_m_s: float = 3.0,
    static_pressure_drop_Pa: float = 180.0,  # ~18 mm H2O, mid-GPSA range
    fan_static_efficiency: float = 0.65,
) -> AirCoolerSizingResult:
    air_mass_flow = (duty_kW * 1000.0) / (AIR_CP_J_KGK * air_temperature_rise_K)
    air_vol_flow = air_mass_flow / AIR_DENSITY_KG_M3
    required_face_area = air_vol_flow / face_velocity_m_s

    # Pick the smallest standard bay (width x length) combination whose
    # area covers the requirement, preferring fewer, larger bays over many
    # small ones (fewer bays generally means fewer fans/motors to
    # maintain, a reasonable conceptual-design default).
    best = None
    for width in STANDARD_AIR_COOLER_BAY_WIDTHS_M:
        for length in STANDARD_AIR_COOLER_BAY_LENGTHS_M:
            bay_area = width * length
            n_bays = math.ceil(required_face_area / bay_area)
            total_area = n_bays * bay_area
            candidate = (n_bays, -bay_area, width, length, total_area)
            if best is None or candidate < best:
                best = candidate
    n_bays, _, bay_width, bay_length, total_area = best

    air_vol_flow_per_bay = air_vol_flow / n_bays
    fan_power_per_bay_kW = (air_vol_flow_per_bay * static_pressure_drop_Pa) / (fan_static_efficiency * 1000.0)

    return AirCoolerSizingResult(
        duty_kW=duty_kW,
        air_mass_flow_kg_s=air_mass_flow,
        air_volumetric_flow_m3_s=air_vol_flow,
        required_face_area_m2=required_face_area,
        bay_width_m=bay_width,
        bay_length_m=bay_length,
        n_bays=n_bays,
        fan_power_kW_per_bay=fan_power_per_bay_kW,
        total_fan_power_kW=fan_power_per_bay_kW * n_bays,
    )
