"""End-to-end worked example: size a full ~2 mtpa LNG train using a DMR
(Dual Mixed Refrigerant) precool loop instead of pure-propane C3 precool -
see examples/full_train_worked_example.py for the C3MR baseline this
directly compares against.

Same feed basis and downstream equipment as the C3MR example; the only
process change is the precool loop:

  C3MR: pure propane, ambient -> -40 C (propane's practical atmospheric-
        pressure floor - see docs/VALIDATION.md).
  DMR:  a heavier ethane/propane blend (30/70 mol%, verified in
        cascade_loops.py / docs/VALIDATION.md to condense at 40 C ambient
        while evaporating well below propane's floor), ambient -> -50 C.

Because DMR's PMR loop reaches a colder floor, the downstream Refrigerant
(LRC) loop has less span left to cover (-50 to -100 C here, vs. -40 to
-100 C in the C3MR case) before the same -100 to -159 C subcooling duty
that both examples leave to a dedicated SRC loop (out of this package's
current 2-refrigerant-loop cascade scope - see cascade_loops.py).

This is also the first worked example to route the NG precool duty
THROUGH `three_loop_cascade`'s `ng_precool_duty_kW` parameter (via
`pmr_refrigerant=DMR_PRECOOL_BLEND`) rather than sizing precool
separately - the C3MR example predates that parameter's DMR-comparison
use case, so it still calls `precool.optimal_evap_temperature` directly.

Run: python examples/full_train_dmr_worked_example.py
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
from lng_design.mche import analyze_composite_curves, classify_mche_type, StreamSegment
from lng_design.molecular_sieve import size_molecular_sieve_bed
from lng_design.precool import optimal_evap_temperature
from lng_design.properties import GasMixture
from lng_design.refrigerant_makeup import size_refrigerant_storage
from lng_design.vessels import size_vertical_separator

MTPA_TO_KG_S = 1.0e9 / (365.25 * 24 * 3600)

# ---------------------------------------------------------------------
# Basis (identical to full_train_worked_example.py, the C3MR case)
# ---------------------------------------------------------------------
TRAIN_CAPACITY_MTPA = 2.0
FEED_GAS = GasMixture({"Methane": 0.85, "Ethane": 0.08, "Propane": 0.04, "Nitrogen": 0.03})
FEED_T_K, FEED_P_PA = 298.15, 50e5   # 25 C, 50 bara
AMBIENT_T_K = 313.15                  # 40 C design ambient

# DMR precool floor: colder than propane's ~-42 C atmospheric-pressure
# limit (empirically verified achievable at 40 C ambient condensing -
# see cascade_loops.py / docs/VALIDATION.md).
DMR_PMR_T_EVAP_K = 223.15  # -50 C
DMR_PRECOOL_BLEND = GasMixture({"Ethane": 0.30, "Propane": 0.70})
LRC_BLEND = GasMixture({"Nitrogen": 0.05, "Methane": 0.30, "Ethane": 0.35, "Propane": 0.30})

feed_mass_flow = TRAIN_CAPACITY_MTPA * MTPA_TO_KG_S
feed_density = FEED_GAS.density(FEED_T_K, FEED_P_PA)
feed_vol_flow = feed_mass_flow / feed_density

print("=" * 78)
print(f"FULL TRAIN WORKED EXAMPLE (DMR precool) — {TRAIN_CAPACITY_MTPA:.1f} mtpa")
print("=" * 78)
print(f"Feed: {feed_mass_flow:.1f} kg/s ({feed_vol_flow:.2f} m3/s actual), "
      f"{feed_density:.1f} kg/m3 @ 25 C / 50 bara")

# ---------------------------------------------------------------------
# V-101 / T-301 / V-201 / A-101 — identical to the C3MR example; the
# refrigerant loops downstream are the only thing this example changes.
# ---------------------------------------------------------------------
v101 = size_vertical_separator(
    gas_volumetric_flow_m3_s=feed_vol_flow,
    gas_density_kg_m3=feed_density,
    liquid_density_kg_m3=550.0,
    liquid_volumetric_flow_m3_s=0.015,
)
print(f"\nV-101 Inlet Separator: {v101.standard_diameter_mm:,.0f} mm dia x "
      f"{v101.seam_to_seam_height_m:.1f} m S/S")

t301 = size_packed_absorber(
    gas_volumetric_flow_m3_s=feed_vol_flow,
    gas_density_kg_m3=feed_density,
    liquid_density_kg_m3=1010.0,
    y_in_mole_frac=0.02, y_out_target_mole_frac=0.0005, x_in_mole_frac=0.001,
    equilibrium_slope_m=0.4, liquid_to_gas_molar_ratio=0.8,
)
print(f"T-301 Amine Absorber: {t301.diameter_m:.2f} m dia x "
      f"{t301.packed_height_m:.1f} m packed height ({t301.n_theoretical_stages:.1f} stages)")

v201 = size_molecular_sieve_bed(
    gas_mass_flow_kg_s=feed_mass_flow, gas_density_kg_m3=feed_density,
    inlet_water_content_ppm_wt=700.0,
)
print(f"V-201 Molecular Sieve: {v201.standard_diameter_mm:,.0f} mm dia x "
      f"{v201.bed_height_m:.1f} m, {v201.n_beds} beds, "
      f"{v201.regen_heater_duty_kW:,.0f} kW regen heater")

trim_cool_duty_kW = feed_mass_flow * 2.3 * (60.0 - 40.0)
a101 = size_air_cooler(trim_cool_duty_kW, design_ambient_T_C=35.0)
print(f"A-101 Trim Air Cooler: {a101.n_bays} x {a101.bay_width_m:.1f}x"
      f"{a101.bay_length_m:.1f} m bays, {a101.total_fan_power_kW:.0f} kW fans "
      f"({trim_cool_duty_kW:,.0f} kW duty)")

# ---------------------------------------------------------------------
# PMR + LRC cascade: 40 C -> -50 C (DMR precool) -> -100 C (LRC)
#
# Unlike the C3MR example (which sizes precool separately via
# `precool.optimal_evap_temperature` and passes ng_precool_duty_kW=0.0
# to the cascade), this example routes the NG precool duty THROUGH
# `three_loop_cascade` itself via `pmr_refrigerant=DMR_PRECOOL_BLEND` -
# the cascade link (PMR duty = NG precool duty + LRC condensing heat)
# is exactly what this DMR-vs-C3MR comparison needs to exercise.
# ---------------------------------------------------------------------
precool_duty_kW = feed_mass_flow * 2.4 * (40.0 - (-50.0))  # ambient -> -50 C

# Post-precool span left for LRC + (unsized) SRC: -50 C to -159 C.
# Same illustrative avg-cp approach as the C3MR example; the SRC portion
# (-100 to -159 C) is the same physical duty either way, so DMR's colder
# precool floor only shrinks the LRC portion, not the SRC leftover.
total_span_C = 159.0 - 50.0            # -50 C to -159 C
lrc_span_C = 100.0 - 50.0              # -50 C to -100 C (LRC's validated floor)
src_span_C = total_span_C - lrc_span_C  # -100 C to -159 C (dedicated SRC, not sized here)

total_liquefaction_duty_kW = feed_mass_flow * 2.9 * total_span_C
lrc_duty_kW = total_liquefaction_duty_kW * lrc_span_C / total_span_C
src_duty_kW = total_liquefaction_duty_kW * src_span_C / total_span_C

cascade = three_loop_cascade(
    ng_precool_duty_kW=precool_duty_kW,
    ng_liquefaction_duty_kW=lrc_duty_kW,
    pmr_T_evap_K=DMR_PMR_T_EVAP_K, pmr_T_cond_K=AMBIENT_T_K,
    lrc_refrigerant=LRC_BLEND, lrc_T_evap_K=173.15,
    lrc_T_cond_K=DMR_PMR_T_EVAP_K + 3.0,  # 3 K MITA margin above PMR's evaporator
    pmr_refrigerant=DMR_PRECOOL_BLEND,
)
print(f"\nPMR (DMR) Precool Loop: NG duty {precool_duty_kW:,.0f} kW, "
      f"T_evap {cascade.pmr.T_evap_K-273.15:.1f} C, "
      f"total duty (NG + LRC condensing) {cascade.pmr_total_duty_kW:,.0f} kW, "
      f"power {cascade.pmr.compressor_power_kW:,.0f} kW, COP {cascade.pmr.cop:.2f}")

# Suction density for frame matching: the PMR refrigerant's own T_evap/
# P_evap sit exactly on its dew-point curve by definition, so (like the
# C3MR example's propane case) query vapor density directly via quality
# rather than through GasMixture.density()'s ambiguous (T, P) lookup.
_dmr_names = list(DMR_PRECOOL_BLEND.composition.keys())
_dmr_fracs = list(DMR_PRECOOL_BLEND.composition.values())
_dmr_vapor = CP.AbstractState("HEOS", "&".join(_dmr_names))
_dmr_vapor.set_mole_fractions(_dmr_fracs)
_dmr_vapor.update(CP.QT_INPUTS, 1.0, cascade.pmr.T_evap_K)
pmr_suction_density = _dmr_vapor.rhomass()
pmr_suction_vol_flow_m3_h = (cascade.pmr.refrigerant_mass_flow_kg_s / pmr_suction_density) * 3600.0

# Found by running this example, not predicted in advance: at -50 C evap /
# 40 C ambient condensing the DMR blend's dew point sits at ~0.96 bara
# while its bubble point sits at ~23.4 bara - a ~24:1 single-stage
# pressure ratio. That alone doesn't exceed any single frame's range, but
# combined with this blend's low evaporator vapor density it drives a
# single-train inlet volume flow beyond even the largest standard frame
# (F, 170,000 m3/h) - a real compressor train would split across multiple
# parallel casings, exactly as `size_refrigerant_storage` already forces
# for an oversized vessel charge (see docs/VALIDATION.md). This is NOT the
# same "solver refuses to converge" failure the LRC loop hits when spanning
# too wide a temperature range in one call (see cascade_loops.py) - here
# the single-stage cycle DOES resolve to a valid thermodynamic state, it
# is just too large for one physical machine.
try:
    pmr_frame = select_compressor_frame(pmr_suction_vol_flow_m3_h)
    print(f"  PMR compressor matched to Frame {pmr_frame.name} "
          f"({pmr_suction_vol_flow_m3_h:,.0f} m3/h inlet)")
except ValueError:
    from lng_design.equipment_catalog import COMPRESSOR_FRAMES
    import math
    max_frame_capacity = COMPRESSOR_FRAMES[-1].inlet_volume_flow_m3_h_max
    n_trains = math.ceil(pmr_suction_vol_flow_m3_h / max_frame_capacity)
    per_train_vol_flow = pmr_suction_vol_flow_m3_h / n_trains
    pmr_frame = select_compressor_frame(per_train_vol_flow)
    print(f"  PMR compressor: {pmr_suction_vol_flow_m3_h:,.0f} m3/h inlet exceeds a single "
          f"Frame {COMPRESSOR_FRAMES[-1].name} train - needs {n_trains} parallel Frame "
          f"{pmr_frame.name} trains ({per_train_vol_flow:,.0f} m3/h each)")

print(f"\nE-201 MCHE (LRC liquefaction, -50 to -100 C): duty {lrc_duty_kW:,.0f} kW, "
      f"LRC power {cascade.lrc.compressor_power_kW:,.0f} kW")
print(f"  Subcooling (-100 to -159 C): duty {src_duty_kW:,.0f} kW - needs a dedicated "
      "SRC loop, out of this module's current scope (not sized here)")

hot = [StreamSegment(cascade.pmr.T_evap_K, cascade.lrc.T_evap_K, lrc_duty_kW)]
cold = [StreamSegment(cascade.lrc.T_evap_K - 5, cascade.pmr.T_evap_K - 5, lrc_duty_kW)]
mche_pinch = analyze_composite_curves(hot, cold, min_approach_K=3.0, overall_U_W_m2K=2500.0)
print(f"  MITA check (LRC section): {mche_pinch.min_approach_K:.1f} K, area estimate "
      f"{mche_pinch.area_estimate_m2:,.0f} m2")

tech = classify_mche_type(TRAIN_CAPACITY_MTPA)
print(f"  Technology at this scale: {tech['typical_technology']}")

# ---------------------------------------------------------------------
# V-401 End-flash drum + K-401 flash gas compressor (identical to C3MR)
# ---------------------------------------------------------------------
lng_composition = {"Methane": 0.85, "Ethane": 0.08, "Propane": 0.04, "Nitrogen": 0.03}
end_flash = flash_end_gas(lng_composition, inlet_T_K=113.15, inlet_P_Pa=4.5e5,
                            outlet_P_Pa=1.10e5, total_mass_flow_kg_s=feed_mass_flow)
print(f"\nV-401 End-Flash: {end_flash.vapor_mass_fraction*100:.2f}% flash "
      f"({end_flash.vapor_mass_flow_kg_s:.2f} kg/s), LNG out "
      f"{end_flash.liquid_mass_flow_kg_s:.1f} kg/s @ {end_flash.flash_temperature_K-273.15:.1f} C")

if end_flash.vapor_mass_flow_kg_s > 0:
    flash_gas = GasMixture(end_flash.vapor_composition_mole_frac)
    k401 = size_centrifugal_stage(flash_gas, end_flash.flash_temperature_K,
                                    1.10e5, 5e5, end_flash.vapor_mass_flow_kg_s)
    print(f"K-401 Flash Gas Compressor: {k401.gas_power_kW:.0f} kW")

# ---------------------------------------------------------------------
# TK-501 Storage tank (identical to C3MR)
# ---------------------------------------------------------------------
lng_density = 450.0
tank = size_storage_tank(end_flash.liquid_mass_flow_kg_s, lng_density,
                           average_shipping_interval_days=4.0, contingency_days=1.5,
                           cargo_size_m3=170000.0)
print(f"TK-501 Storage Tank: {tank.required_volume_m3:,.0f} m3 "
      f"({tank.cargo_equivalent:.2f}x a 170,000 m3 cargo)")

# ---------------------------------------------------------------------
# V-102 Refrigerant makeup (DMR blend inventory - liquid density taken
# at the PMR condenser's own bubble point, not an assumed round number)
# ---------------------------------------------------------------------
_dmr_liquid = CP.AbstractState("HEOS", "&".join(_dmr_names))
_dmr_liquid.set_mole_fractions(_dmr_fracs)
_dmr_liquid.update(CP.QT_INPUTS, 0.0, AMBIENT_T_K)
dmr_liquid_density = _dmr_liquid.rhomass()
dmr_charge_kg = cascade.pmr.refrigerant_mass_flow_kg_s * 300.0  # ~5 min system holdup, illustrative
v102 = size_refrigerant_storage(dmr_charge_kg, refrigerant_density_kg_m3=dmr_liquid_density)
print(f"V-102 Refrigerant Makeup: {v102.standard_diameter_mm:,.0f} mm dia x "
      f"{v102.vessel_length_m:.1f} m ({dmr_charge_kg:,.0f} kg charge, "
      f"{dmr_liquid_density:.0f} kg/m3 liquid)")

dmr_total_power_kW = cascade.pmr.compressor_power_kW + cascade.lrc.compressor_power_kW

# ---------------------------------------------------------------------
# Comparison vs. C3MR baseline (full_train_worked_example.py), recomputed
# here inline on the same feed basis so the two are directly comparable
# rather than quoting remembered numbers from a separate run.
# ---------------------------------------------------------------------
c3mr_precool_duty_kW = feed_mass_flow * 2.4 * (40.0 - (-40.0))
c3mr_precool = optimal_evap_temperature(c3mr_precool_duty_kW, T_cold_end_target_K=233.15, T_cond_K=AMBIENT_T_K)

c3mr_total_span_C = 159.0 - 40.0
c3mr_lrc_span_C = 100.0 - 40.0
c3mr_total_liquefaction_duty_kW = feed_mass_flow * 2.9 * c3mr_total_span_C
c3mr_lrc_duty_kW = c3mr_total_liquefaction_duty_kW * c3mr_lrc_span_C / c3mr_total_span_C

c3mr_cascade = three_loop_cascade(
    ng_precool_duty_kW=0.0,  # C3MR example sizes precool separately, matching full_train_worked_example.py
    ng_liquefaction_duty_kW=c3mr_lrc_duty_kW,
    pmr_T_evap_K=233.15, pmr_T_cond_K=AMBIENT_T_K,
    lrc_refrigerant=LRC_BLEND, lrc_T_evap_K=173.15, lrc_T_cond_K=236.15,
)
c3mr_total_power_kW = c3mr_precool.compressor_power_kW + c3mr_cascade.lrc.compressor_power_kW

print("\n" + "=" * 78)
print("DMR vs. C3MR — precool + LRC compressor power (flash gas compressor excluded, both cases)")
print("=" * 78)
print(f"  C3MR (propane, -40 C floor):  {c3mr_total_power_kW:,.0f} kW")
print(f"  DMR  (C2/C3 blend, -50 C floor): {dmr_total_power_kW:,.0f} kW")
delta_kW = dmr_total_power_kW - c3mr_total_power_kW
delta_pct = 100.0 * delta_kW / c3mr_total_power_kW
sign = "more" if delta_kW > 0 else "less"
print(f"  DMR uses {abs(delta_kW):,.0f} kW ({abs(delta_pct):.1f}%) {sign} power than C3MR "
      "for the same LRC liquefaction scope.")
print(
    "\nNote: this reflects a colder DMR precool floor doing more of the total "
    "temperature drop, shrinking what the LRC loop must cover - it is NOT a "
    "claim that DMR is more efficient in general. Found by running this "
    f"example: the DMR PMR loop's own COP ({cascade.pmr.cop:.2f}) is WORSE than "
    f"propane's ({c3mr_precool.cop:.2f}) at these conditions, because "
    "mixed_refrigerant_cycle (like precool.py) models compression as a "
    "single stage - a ~24:1 pressure ratio in one stage penalizes this "
    "heavier blend's real-gas compression work more than it penalizes "
    "propane's. DMR's headline power number above looks better only because "
    "its colder floor lets the LRC loop do less; real DMR designs recover "
    "the single-stage penalty by splitting PMR compression across multiple "
    "stages/casings (see the multi-parallel-train finding above) - modeling "
    "that split is out of this module's current single-stage scope. A "
    "second refrigerant inventory/composition to manage, and this toy "
    "model's segment-wise illustrative specific-heat assumptions (not a "
    "real heat-and-material balance), both further limit how far this "
    "comparison should be read. See process_selection.py's "
    "compare_liquefaction_cycles() for the citation-backed C3MR-vs-DMR "
    "selection guidance this package actually stands behind."
)
