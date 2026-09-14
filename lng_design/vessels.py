"""Vertical two-phase (gas/liquid) separator vessel sizing.

Method: Souders-Brown gas-capacity sizing for diameter (GPSA Engineering
Data Book Ch. 7, "Separators"; also Campbell, "Gas Conditioning and
Processing" Vol. 2) plus a liquid-residence-time holdup for height - the
same two-part approach used for the amine absorber's diameter method in
`amine_absorber.py`, applied here to a knockout/flash-drum style vessel
rather than a packed column.

    v_max = K_SB * sqrt((rho_L - rho_V) / rho_V)

K_SB (the Souders-Brown/API constant) depends on whether a wire-mesh mist
eliminator is fitted: GPSA Ch. 7 quotes approximately 0.107 m/s (0.35
ft/s) for a vertical separator WITHOUT a mesh pad and approximately
0.11-0.12 m/s (0.35-0.40 ft/s) WITH one - the values are close because the
mesh pad mainly improves separation efficiency at a given velocity rather
than raising the velocity limit much; this module defaults to the
with-mesh-pad case as it is the more common design.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .equipment_catalog import STANDARD_VESSEL_DIAMETERS_MM, match_standard_size


@dataclass
class SeparatorSizingResult:
    required_diameter_m: float
    standard_diameter_mm: float
    vapor_velocity_design_m_s: float
    vapor_velocity_max_m_s: float
    liquid_holdup_volume_m3: float
    seam_to_seam_height_m: float


def size_vertical_separator(
    gas_volumetric_flow_m3_s: float,
    gas_density_kg_m3: float,
    liquid_density_kg_m3: float,
    liquid_volumetric_flow_m3_s: float,
    liquid_residence_time_min: float = 5.0,
    K_SB: float = 0.107,
    design_fraction_of_vmax: float = 0.80,
) -> SeparatorSizingResult:
    """Size a vertical two-phase separator.

    liquid_residence_time_min: typical GPSA/Campbell guidance is 3-5
    minutes for a standard surge/knockout drum, longer (10 min) if the
    liquid feeds a control loop with slow response, or if degassing time
    matters, per Campbell Vol. 2. Default here is a middle-of-range 5 min.
    """
    v_max = K_SB * math.sqrt((liquid_density_kg_m3 - gas_density_kg_m3) / gas_density_kg_m3)
    v_design = design_fraction_of_vmax * v_max
    area = gas_volumetric_flow_m3_s / v_design
    diameter = math.sqrt(4.0 * area / math.pi)

    standard_diameter_mm = match_standard_size(diameter * 1000.0, STANDARD_VESSEL_DIAMETERS_MM)
    standard_area = math.pi / 4.0 * (standard_diameter_mm / 1000.0) ** 2
    v_actual = gas_volumetric_flow_m3_s / standard_area

    liquid_holdup_m3 = liquid_volumetric_flow_m3_s * liquid_residence_time_min * 60.0
    # Liquid holdup height from the standard vessel's cross section, plus a
    # fixed disengagement space above the liquid level and a vapor inlet
    # nozzle allowance - the GPSA/Campbell rule-of-thumb minimum vapor
    # space is about 1x the vessel diameter (or 1 m, whichever is
    # greater), a widely used conceptual-design default.
    liquid_height = liquid_holdup_m3 / standard_area
    vapor_disengagement_height = max(standard_diameter_mm / 1000.0, 1.0)
    seam_to_seam = liquid_height + vapor_disengagement_height

    return SeparatorSizingResult(
        required_diameter_m=diameter,
        standard_diameter_mm=standard_diameter_mm,
        vapor_velocity_design_m_s=v_actual,
        vapor_velocity_max_m_s=v_max,
        liquid_holdup_volume_m3=liquid_holdup_m3,
        seam_to_seam_height_m=seam_to_seam,
    )
