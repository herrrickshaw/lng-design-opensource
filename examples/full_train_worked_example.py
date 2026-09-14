"""End-to-end worked example: size every major vessel and heat exchanger
in a representative ~2 mtpa LNG train, using ONE consistent feed basis
carried forward through every module built in this package.

This is the "prove it all fits together" example - each step's output
feeds the next step's input, the way an actual train works, rather than
each module's tests using their own disconnected demo numbers. Basis:

  Feed gas:  85/8/4/3 mol% CH4/C2H6/C3H8/N2, 25 C, 50 bara, 2.0 mtpa train
  Train temperature ladder (cross-validated in docs/VALIDATION.md against
  a published SMR/PRICO paper): ambient -> -40 C (C3 precool) -> -159 C
  (MCHE exit) -> end-flash -> storage.

Run: python examples/full_train_worked_example.py
"""
from __future__ import annotations

import CoolProp.CoolProp as CP

from lng_design.air_cooler import size_air_cooler
from lng_design.amine_absorber import size_packed_absorber
from lng_design.berth import size_storage_tank
from lng_design.cascade_loops import three_loop_cascade
from lng_design.compressor import size_centrifugal_stage
from lng_design.end_flash import flash_end_gas
from lng_design.equipment_catalog import select_compressor_frame
from lng_design.exchangers import size_shell_and_tube
from lng_design.mche import analyze_composite_curves, classify_mche_type, StreamSegment
from lng_design.molecular_sieve import size_molecular_sieve_bed
from lng_design.precool import optimal_evap_temperature
from lng_design.properties import GasMixture
from lng_design.refrigerant_makeup import size_refrigerant_storage
from lng_design.vessels import size_vertical_separator

MTPA_TO_KG_S = 1.0e9 / (365.25 * 24 * 3600)

# ---------------------------------------------------------------------
# Basis
# ---------------------------------------------------------------------
TRAIN_CAPACITY_MTPA = 2.0
FEED_GAS = GasMixture({"Methane": 0.85, "Ethane": 0.08, "Propane": 0.04, "Nitrogen": 0.03})
FEED_T_K, FEED_P_PA = 298.15, 50e5   # 25 C, 50 bara
AMBIENT_T_K = 313.15                  # 40 C design ambient

feed_mass_flow = TRAIN_CAPACITY_MTPA * MTPA_TO_KG_S
feed_density = FEED_GAS.density(FEED_T_K, FEED_P_PA)
feed_vol_flow = feed_mass_flow / feed_density

print("=" * 78)
print(f"FULL TRAIN WORKED EXAMPLE — {TRAIN_CAPACITY_MTPA:.1f} mtpa")
print("=" * 78)
print(f"Feed: {feed_mass_flow:.1f} kg/s ({feed_vol_flow:.2f} m3/s actual), "
      f"{feed_density:.1f} kg/m3 @ 25 C / 50 bara")

# ---------------------------------------------------------------------
# V-101 Inlet separator
# ---------------------------------------------------------------------
v101 = size_vertical_separator(
    gas_volumetric_flow_m3_s=feed_vol_flow,
    gas_density_kg_m3=feed_density,
    liquid_density_kg_m3=550.0,        # light condensate
    liquid_volumetric_flow_m3_s=0.015,  # illustrative condensate rate
)
print(f"\nV-101 Inlet Separator: {v101.standard_diameter_mm:,.0f} mm dia x "
      f"{v101.seam_to_seam_height_m:.1f} m S/S")

# ---------------------------------------------------------------------
# T-301 Amine absorber (CO2 removal)
# ---------------------------------------------------------------------
t301 = size_packed_absorber(
    gas_volumetric_flow_m3_s=feed_vol_flow,
    gas_density_kg_m3=feed_density,
    liquid_density_kg_m3=1010.0,
    y_in_mole_frac=0.02, y_out_target_mole_frac=0.0005, x_in_mole_frac=0.001,
    # L/V chosen to land the absorption factor A=L/(m*V) in the classic
    # ~1.4-2.0 economic design range (McCabe, Smith & Harriott) rather
    # than an arbitrary round number - A=50 (from an earlier L/V=20) gave
    # an implausible 0.7 m packed height, caught by actually running this
    # script. See docs/VALIDATION.md.
    equilibrium_slope_m=0.4, liquid_to_gas_molar_ratio=0.8,
)
print(f"T-301 Amine Absorber: {t301.diameter_m:.2f} m dia x "
      f"{t301.packed_height_m:.1f} m packed height ({t301.n_theoretical_stages:.1f} stages)")

# ---------------------------------------------------------------------
# V-201 Molecular sieve dehydration
# ---------------------------------------------------------------------
v201 = size_molecular_sieve_bed(
    gas_mass_flow_kg_s=feed_mass_flow, gas_density_kg_m3=feed_density,
    inlet_water_content_ppm_wt=700.0,
)
print(f"V-201 Molecular Sieve: {v201.standard_diameter_mm:,.0f} mm dia x "
      f"{v201.bed_height_m:.1f} m, {v201.n_beds} beds, "
      f"{v201.regen_heater_duty_kW:,.0f} kW regen heater")

# ---------------------------------------------------------------------
# A-101 Trim air cooler (dry gas back to near-ambient before precool)
# ---------------------------------------------------------------------
trim_cool_duty_kW = feed_mass_flow * 2.3 * (60.0 - 40.0)  # ~60C post-sieve -> 40C
a101 = size_air_cooler(trim_cool_duty_kW, design_ambient_T_C=35.0)
print(f"A-101 Trim Air Cooler: {a101.n_bays} x {a101.bay_width_m:.1f}x"
      f"{a101.bay_length_m:.1f} m bays, {a101.total_fan_power_kW:.0f} kW fans "
      f"({trim_cool_duty_kW:,.0f} kW duty)")

# ---------------------------------------------------------------------
# C3-100 Precool loop: 40 C -> -40 C ahead of the MCHE
# ---------------------------------------------------------------------
precool_duty_kW = feed_mass_flow * 2.4 * (40.0 - (-40.0))
precool = optimal_evap_temperature(precool_duty_kW, T_cold_end_target_K=233.15, T_cond_K=AMBIENT_T_K)
print(f"C3-100 Precool Loop: duty {precool_duty_kW:,.0f} kW, "
      f"T_evap {precool.T_evap_K-273.15:.1f} C, power {precool.compressor_power_kW:,.0f} kW")

# NOTE: propane at (T_evap, P_evap) sits EXACTLY on its saturation curve by
# definition (it's the compressor's saturated-vapor suction state) - a
# plain (T, P) density lookup is ambiguous there (CoolProp correctly
# refuses to guess liquid vs. vapor), so query the vapor density directly
# via quality (Q=1) instead of routing through GasMixture.density()'s
# (T, P) inputs, which are only safe for single-phase states.
suction_density = CP.PropsSI("D", "T", precool.T_evap_K, "Q", 1, "Propane")
suction_vol_flow_m3_h = (precool.refrigerant_mass_flow_kg_s / suction_density) * 3600.0
frame = select_compressor_frame(suction_vol_flow_m3_h)
print(f"  C3 compressor matched to Frame {frame.name} ({suction_vol_flow_m3_h:,.0f} m3/h inlet)")

# ---------------------------------------------------------------------
# E-201 MCHE + Refrigerant (LRC) loop: -40 C -> -159 C
#
# A single mixed_refrigerant_cycle call cannot span this whole range in
# one compression stage (confirmed by running this exact script - see
# cascade_loops.py's docstring and docs/VALIDATION.md): the LRC_BLEND
# below validates cleanly down to about -100 C, matching real MFC/DMR
# practice of using multiple refrigerant pressure levels (and, for a
# true 3-refrigerant-loop MFC, a dedicated lighter "SRC" subcooling
# cycle) rather than one giant compression ratio. This example therefore
# sizes LRC for the -40 C to -100 C liquefaction portion only, and
# reports the -100 C to -159 C subcooling duty as a duty figure (what a
# dedicated SRC loop would need to absorb) without sizing that loop -
# genuinely out of this module's current 2-refrigerant-loop scope,
# flagged honestly rather than forced through an unvalidated blend/range.
# ---------------------------------------------------------------------
total_span_C = 159.0 - 40.0          # -40 C to -159 C
lrc_span_C = 100.0 - 40.0             # -40 C to -100 C (LRC's validated floor)
src_span_C = total_span_C - lrc_span_C  # -100 C to -159 C (needs a dedicated SRC loop)

total_liquefaction_duty_kW = feed_mass_flow * 2.9 * total_span_C  # avg cp over full range, illustrative
lrc_duty_kW = total_liquefaction_duty_kW * lrc_span_C / total_span_C
src_duty_kW = total_liquefaction_duty_kW * src_span_C / total_span_C

lrc_blend = GasMixture({"Nitrogen": 0.05, "Methane": 0.30, "Ethane": 0.35, "Propane": 0.30})
cascade = three_loop_cascade(
    ng_precool_duty_kW=0.0,  # precool already accounted above via C3-100
    ng_liquefaction_duty_kW=lrc_duty_kW,
    pmr_T_evap_K=233.15, pmr_T_cond_K=AMBIENT_T_K,
    lrc_refrigerant=lrc_blend, lrc_T_evap_K=173.15, lrc_T_cond_K=236.15,
)
print(f"E-201 MCHE (liquefaction, -40 to -100 C): duty {lrc_duty_kW:,.0f} kW, "
      f"LRC power {cascade.lrc.compressor_power_kW:,.0f} kW")
print(f"  Subcooling (-100 to -159 C): duty {src_duty_kW:,.0f} kW - needs a dedicated "
      "SRC loop, out of this module's current scope (not sized here)")

hot = [StreamSegment(233.15, 173.15, lrc_duty_kW)]
cold = [StreamSegment(173.15 - 5, 233.15 - 5, lrc_duty_kW)]
mche_pinch = analyze_composite_curves(hot, cold, min_approach_K=3.0, overall_U_W_m2K=2500.0)
print(f"  MITA check (liquefaction section): {mche_pinch.min_approach_K:.1f} K, area estimate "
      f"{mche_pinch.area_estimate_m2:,.0f} m2")

tech = classify_mche_type(TRAIN_CAPACITY_MTPA)
print(f"  Technology at this scale: {tech['typical_technology']}")

# ---------------------------------------------------------------------
# V-401 End-flash drum + K-401 flash gas compressor
# ---------------------------------------------------------------------
lng_composition = {"Methane": 0.85, "Ethane": 0.08, "Propane": 0.04, "Nitrogen": 0.03}
end_flash = flash_end_gas(lng_composition, inlet_T_K=113.15, inlet_P_Pa=4.5e5,
                            outlet_P_Pa=1.10e5, total_mass_flow_kg_s=feed_mass_flow)
print(f"V-401 End-Flash: {end_flash.vapor_mass_fraction*100:.2f}% flash "
      f"({end_flash.vapor_mass_flow_kg_s:.2f} kg/s), LNG out "
      f"{end_flash.liquid_mass_flow_kg_s:.1f} kg/s @ {end_flash.flash_temperature_K-273.15:.1f} C")

if end_flash.vapor_mass_flow_kg_s > 0:
    flash_gas = GasMixture(end_flash.vapor_composition_mole_frac)
    k401 = size_centrifugal_stage(flash_gas, end_flash.flash_temperature_K,
                                    1.10e5, 5e5, end_flash.vapor_mass_flow_kg_s)
    print(f"K-401 Flash Gas Compressor: {k401.gas_power_kW:.0f} kW")

# ---------------------------------------------------------------------
# TK-501 Storage tank
# ---------------------------------------------------------------------
lng_density = 450.0  # representative LNG density at storage conditions
tank = size_storage_tank(end_flash.liquid_mass_flow_kg_s, lng_density,
                           average_shipping_interval_days=4.0, contingency_days=1.5,
                           cargo_size_m3=170000.0)
print(f"TK-501 Storage Tank: {tank.required_volume_m3:,.0f} m3 "
      f"({tank.cargo_equivalent:.2f}x a 170,000 m3 cargo)")

# ---------------------------------------------------------------------
# V-102 Refrigerant makeup (C3 inventory)
# ---------------------------------------------------------------------
c3_charge_kg = precool.refrigerant_mass_flow_kg_s * 300.0  # ~5 min system holdup, illustrative
v102 = size_refrigerant_storage(c3_charge_kg, refrigerant_density_kg_m3=500.0)
print(f"V-102 Refrigerant Makeup: {v102.standard_diameter_mm:,.0f} mm dia x "
      f"{v102.vessel_length_m:.1f} m ({c3_charge_kg:,.0f} kg charge)")

# ---------------------------------------------------------------------
print("\n" + "=" * 78)
print("Total compressor power (precool + LRC + flash gas):",
      f"{precool.compressor_power_kW + cascade.lrc.compressor_power_kW:,.0f} kW "
      "(+ flash gas compressor above)")
print("=" * 78)
print(
    "\nNote: illustrative specific-heat/duty assumptions are flagged inline; "
    "this demonstrates every module chaining together on ONE consistent feed "
    "basis, not a substitute for a real heat-and-material balance from a "
    "licensed simulator."
)
