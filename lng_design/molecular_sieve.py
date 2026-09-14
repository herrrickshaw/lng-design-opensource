"""Molecular sieve dehydration bed sizing (post-amine, pre-cryogenic).

Amine treating removes acid gases (CO2, H2S) but not water; LNG trains
need water removed to well under 1 ppmv before the gas reaches cryogenic
temperatures, or ice/hydrates will plug the MCHE and downstream piping.
4A molecular sieve is the standard adsorbent for this duty (vs. 3A or 5A
- 4A is reported to have higher water uptake capacity than 3A and less
hydrocarbon co-adsorption than 5A for natural gas service).

Method: standard two-part adsorber sizing (GPSA Engineering Data Book
Ch. 20, "Dehydration"; Campbell, "Gas Conditioning and Processing" Vol.
2; widely reproduced in vendor/industry literature):

1. **Diameter** - a design superficial gas velocity limits pressure drop
   across the packed adsorbent bed (0.15-0.30 m/s is a commonly cited
   design range; this module defaults to a mid-range 0.20 m/s,
   overridable).
2. **Bed mass/height** - from the water to be removed per adsorption
   cycle, divided by the sieve's working (design) capacity - commonly
   cited in industry/vendor literature as roughly 10-13 wt% for a
   standard-length cycle on 4A sieve (this module defaults to 11%,
   overridable; actual capacity depends on cycle length, sieve age/
   fouling, and vendor-specific isotherm data your project's actual
   vendor datasheet should confirm).
3. **Number of beds** - two beds work only if regeneration+cooldown time
   fits within the adsorption time of the other bed; if not, a third bed
   is needed so one is always adsorbing while the other two cycle through
   regeneration and cooldown (a well-documented dehydration-system
   design point).
4. **Regeneration heater duty** - computed rigorously from the
   regeneration gas flow (typically 10-20% of feed, per common industry
   practice) and a temperature rise to a typical ~550°F (288°C)
   regeneration temperature, using the gas mixture's real Cp via
   CoolProp rather than a fixed heat-capacity assumption.

Water content of the inlet gas (`inlet_water_content_ppm_wt`) is taken as
a direct input - it depends on upstream saturation conditions and is
normally read from a water-content chart (e.g. the McKetta-Wehe chart) or
an upstream simulation, not re-derived here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .equipment_catalog import STANDARD_VESSEL_DIAMETERS_MM, match_standard_size
from .properties import GasMixture


@dataclass
class MolecularSieveBedResult:
    water_removed_per_cycle_kg: float
    bed_mass_kg: float
    bed_volume_m3: float
    standard_diameter_mm: float
    bed_height_m: float
    n_beds: int
    regen_gas_flow_kg_s: float
    regen_heater_duty_kW: float


def size_molecular_sieve_bed(
    gas_mass_flow_kg_s: float,
    gas_density_kg_m3: float,
    inlet_water_content_ppm_wt: float,
    adsorption_time_h: float = 8.0,
    regen_time_h: float = 4.0,
    cooldown_time_h: float = 1.5,
    design_velocity_m_s: float = 0.20,
    working_capacity_wt_pct: float = 11.0,
    sieve_bulk_density_kg_m3: float = 721.0,
    regen_gas_fraction_of_feed: float = 0.15,
    regen_gas: GasMixture | None = None,
    feed_temperature_K: float = 303.15,
    regen_temperature_C: float = 288.0,
    regen_pressure_Pa: float = 5e5,
    min_bed_height_m: float = 1.0,
) -> MolecularSieveBedResult:
    """
    min_bed_height_m: the velocity-sized diameter and the water-duty-sized
    adsorbent volume are computed independently and can produce a
    physically dubious "pancake" bed (wide diameter, very shallow depth)
    when gas flow is high relative to water duty - a shallow bed cannot
    develop a proper mass-transfer zone and would under-perform badly in
    practice. This function raises rather than silently returning such a
    result; a widely-used practical minimum packed bed depth for adequate
    mass transfer is on the order of 1-1.5 m (GPSA/vendor practice), so
    this defaults to 1.0 m. If you hit this, increase `design_velocity_m_s`
    (shrinks the diameter) or reconsider whether a single vessel is the
    right configuration for this flow/duty combination.
    """
    if inlet_water_content_ppm_wt <= 0:
        raise ValueError("inlet_water_content_ppm_wt must be positive")

    water_removed_kg = (
        gas_mass_flow_kg_s * 3600.0 * adsorption_time_h * inlet_water_content_ppm_wt * 1e-6
    )
    bed_mass_kg = water_removed_kg / (working_capacity_wt_pct / 100.0)
    bed_volume_m3 = bed_mass_kg / sieve_bulk_density_kg_m3

    gas_vol_flow_m3_s = gas_mass_flow_kg_s / gas_density_kg_m3
    required_area = gas_vol_flow_m3_s / design_velocity_m_s
    required_diameter_m = math.sqrt(4.0 * required_area / math.pi)
    standard_diameter_mm = match_standard_size(required_diameter_m * 1000.0, STANDARD_VESSEL_DIAMETERS_MM)
    standard_area = math.pi / 4.0 * (standard_diameter_mm / 1000.0) ** 2
    bed_height_m = bed_volume_m3 / standard_area

    if bed_height_m < min_bed_height_m:
        raise ValueError(
            f"Computed bed height ({bed_height_m:.2f} m) is below the practical "
            f"minimum ({min_bed_height_m:.2f} m) for a mass-transfer zone to "
            "develop properly - the velocity-sized diameter "
            f"({standard_diameter_mm:.0f} mm) is oversized relative to the "
            "water-removal duty for this flow. Increase design_velocity_m_s "
            "to shrink the diameter, or reconsider vessel configuration."
        )

    n_beds = 2 if (regen_time_h + cooldown_time_h) <= adsorption_time_h else 3

    regen_gas = regen_gas or GasMixture({"Methane": 0.95, "Ethane": 0.05})
    regen_mdot = regen_gas_fraction_of_feed * gas_mass_flow_kg_s
    cp_regen = regen_gas.prop("Cpmass", feed_temperature_K, regen_pressure_Pa)
    regen_duty_kW = regen_mdot * cp_regen * (regen_temperature_C + 273.15 - feed_temperature_K) / 1000.0

    return MolecularSieveBedResult(
        water_removed_per_cycle_kg=water_removed_kg,
        bed_mass_kg=bed_mass_kg,
        bed_volume_m3=bed_volume_m3,
        standard_diameter_mm=standard_diameter_mm,
        bed_height_m=bed_height_m,
        n_beds=n_beds,
        regen_gas_flow_kg_s=regen_mdot,
        regen_heater_duty_kW=regen_duty_kW,
    )
