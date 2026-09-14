"""Refrigerant (propane / mixed-refrigerant) storage and makeup vessel
sizing.

An LNG train's refrigerant loops (C3 precool, mixed refrigerant) are
closed systems, but small losses (seal leakage, flare/vent events,
sampling, maintenance draining and refilling) mean every train carries a
refrigerant storage/makeup vessel sized to hold at least one full system
charge plus a reserve for top-up between replenishment deliveries.

Method: total required liquid volume from the system charge (a known
process quantity - MCHE + piping + drum holdup - typically taken from the
process design, not derived here) plus a reserve fraction, sized as a
horizontal pressurized vessel at a standard length-to-diameter ratio
(3-5 is typical bullet-tank practice), and limited to a maximum liquid
fill fraction for thermal-expansion vapor space - 85% is the fill limit
widely used for refrigerated/pressurized liquefied-gas storage (consistent
with NFPA 58-style outage requirements for LPG-class storage; the "no
more than 85% full" figure is a very commonly quoted rule of thumb in gas
processing / GPSA Ch. 7 for pressurized liquid storage in general, not
specific to propane).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .equipment_catalog import STANDARD_VESSEL_DIAMETERS_MM, match_standard_size


@dataclass
class RefrigerantStorageResult:
    required_liquid_volume_m3: float
    vessel_volume_m3: float
    standard_diameter_mm: float
    vessel_length_m: float


def size_refrigerant_storage(
    system_charge_kg: float,
    refrigerant_density_kg_m3: float,
    reserve_fraction: float = 0.20,
    max_fill_fraction: float = 0.85,
    length_to_diameter_ratio: float = 4.0,
) -> RefrigerantStorageResult:
    if not (0.0 < max_fill_fraction < 1.0):
        raise ValueError("max_fill_fraction must be between 0 and 1")

    required_liquid_volume = (system_charge_kg * (1.0 + reserve_fraction)) / refrigerant_density_kg_m3
    vessel_volume = required_liquid_volume / max_fill_fraction

    # Solve V = (pi/4) * D^2 * (L/D * D) = (pi/4) * D^3 * (L/D) for D
    diameter = (vessel_volume / (math.pi / 4.0 * length_to_diameter_ratio)) ** (1.0 / 3.0)
    standard_diameter_mm = match_standard_size(diameter * 1000.0, STANDARD_VESSEL_DIAMETERS_MM)
    standard_diameter_m = standard_diameter_mm / 1000.0
    length = vessel_volume / (math.pi / 4.0 * standard_diameter_m ** 2)

    return RefrigerantStorageResult(
        required_liquid_volume_m3=required_liquid_volume,
        vessel_volume_m3=vessel_volume,
        standard_diameter_mm=standard_diameter_mm,
        vessel_length_m=length,
    )
