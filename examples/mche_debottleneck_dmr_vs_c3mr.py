"""Why does a colder DMR precool floor raise the MCHE's NG throughput
ceiling, compared to C3MR's pure-propane floor?

`process_selection.py` already cites a published per-train capacity
ceiling driven by "propane compressor and main heat exchanger size
limits": ~5 mtpa/train for C3MR vs. ~8 mtpa/train for DMR (Technology
Review of Natural Gas Liquefaction Processes, scialert.net). That
citation states the WHAT; this script quantifies the two physical
mechanisms behind the WHY, using this package's own duty and density
calculations rather than restating the citation as-is:

1. **Duty mechanism**: for a fixed NG mass flow, the MCHE only has to
   cool the gas from the precool floor down to LNG rundown temperature.
   A colder precool floor (DMR's ~-50 C vs. C3MR's ~-42 C practical
   propane limit) means a SMALLER temperature span left for the MCHE to
   cover, so a smaller total duty per unit mass of NG - which means
   MORE NG mass flow fits within a fixed maximum MCHE duty (a proxy for
   "largest fabricable coil-wound core").
2. **Density/velocity mechanism**: colder gas is denser at the same
   pressure. Coil-wound cryogenic exchangers are also commonly limited
   by a maximum tube-side velocity (flow-induced vibration/erosion,
   standard heat-exchanger design practice - see e.g. Kern, "Process
   Heat Transfer"), i.e. by volumetric flow, not mass flow. A colder,
   denser MCHE inlet stream carries MORE mass per unit of volumetric
   flow, so MORE NG mass flow fits within a fixed maximum MCHE
   volumetric throughput.

Both mechanisms push the same direction (colder precool -> higher NG
throughput through a fixed-size MCHE); this script computes each one
separately against the SAME calibration point (C3MR's published 5 mtpa
ceiling) to see how much of the published DMR ceiling (+60% over C3MR)
each mechanism alone would predict, and is explicit that the true vendor
ceiling almost certainly reflects both mechanisms together plus
compressor/mechanical constraints this package does not model.

Run: python examples/mche_debottleneck_dmr_vs_c3mr.py
"""
from __future__ import annotations

from lng_design.process_selection import compare_liquefaction_cycles
from lng_design.properties import GasMixture

MTPA_TO_KG_S = 1.0e9 / (365.25 * 24 * 3600)

# ---------------------------------------------------------------------
# Basis - same feed and temperature ladder as the full-train examples.
# ---------------------------------------------------------------------
FEED_GAS = GasMixture({"Methane": 0.85, "Ethane": 0.08, "Propane": 0.04, "Nitrogen": 0.03})
MCHE_INLET_P_PA = 50e5  # illustrative: pressure held ~constant through precool, as in the worked examples

C3MR_PRECOOL_FLOOR_K = 233.15   # -40 C, propane's practical atmospheric-pressure limit
DMR_PRECOOL_FLOOR_K = 223.15    # -50 C, DMR blend (see cascade_loops.py / docs/VALIDATION.md)
LNG_RUNDOWN_K = 114.15          # -159 C, this package's cross-validated MCHE exit target (docs/VALIDATION.md)

CP_AVG_KJ_KGK = 2.9  # same illustrative average specific heat used in the full-train worked examples

# Literature calibration point (process_selection.py's own citation).
C3MR_PUBLISHED_CEILING_MTPA = 5.0
DMR_PUBLISHED_CEILING_MTPA = 8.0

print("=" * 78)
print("MCHE NG-throughput ceiling: why DMR's colder precool floor helps")
print("=" * 78)

c3mr_span_K = C3MR_PRECOOL_FLOOR_K - LNG_RUNDOWN_K
dmr_span_K = DMR_PRECOOL_FLOOR_K - LNG_RUNDOWN_K
print(f"\nMCHE temperature span to cover:")
print(f"  C3MR ({C3MR_PRECOOL_FLOOR_K-273.15:.0f} C floor -> {LNG_RUNDOWN_K-273.15:.0f} C): {c3mr_span_K:.1f} K")
print(f"  DMR  ({DMR_PRECOOL_FLOOR_K-273.15:.0f} C floor -> {LNG_RUNDOWN_K-273.15:.0f} C): {dmr_span_K:.1f} K")
print(f"  DMR's span is {100.0*(1 - dmr_span_K/c3mr_span_K):.1f}% smaller than C3MR's.")

# ---------------------------------------------------------------------
# Mechanism 1: fixed MCHE DUTY ceiling, calibrated from C3MR's published
# 5 mtpa/train capacity limit at its own precool floor.
# ---------------------------------------------------------------------
c3mr_mdot_ceiling_kg_s = C3MR_PUBLISHED_CEILING_MTPA * MTPA_TO_KG_S
mche_duty_ceiling_kW = c3mr_mdot_ceiling_kg_s * CP_AVG_KJ_KGK * c3mr_span_K

dmr_mdot_max_duty_kg_s = mche_duty_ceiling_kW / (CP_AVG_KJ_KGK * dmr_span_K)
dmr_mtpa_max_duty = dmr_mdot_max_duty_kg_s / MTPA_TO_KG_S
duty_increase_pct = 100.0 * (dmr_mtpa_max_duty / C3MR_PUBLISHED_CEILING_MTPA - 1.0)

print(f"\nMechanism 1 - fixed MCHE duty ceiling ({mche_duty_ceiling_kW:,.0f} kW, "
      f"calibrated to C3MR's published {C3MR_PUBLISHED_CEILING_MTPA:.0f} mtpa ceiling):")
print(f"  DMR's smaller span alone lets this same duty ceiling support "
      f"{dmr_mtpa_max_duty:.2f} mtpa ({duty_increase_pct:+.1f}% vs. C3MR).")

# ---------------------------------------------------------------------
# Mechanism 2: fixed MCHE volumetric-flow (tube-velocity) ceiling,
# calibrated the same way, using this package's own CoolProp mixture
# density at each precool floor temperature.
# ---------------------------------------------------------------------
c3mr_inlet_density = FEED_GAS.density(C3MR_PRECOOL_FLOOR_K, MCHE_INLET_P_PA)
dmr_inlet_density = FEED_GAS.density(DMR_PRECOOL_FLOOR_K, MCHE_INLET_P_PA)
density_ratio = dmr_inlet_density / c3mr_inlet_density

c3mr_vol_flow_ceiling_m3_s = c3mr_mdot_ceiling_kg_s / c3mr_inlet_density
dmr_mdot_max_vol_kg_s = c3mr_vol_flow_ceiling_m3_s * dmr_inlet_density
dmr_mtpa_max_vol = dmr_mdot_max_vol_kg_s / MTPA_TO_KG_S
vol_increase_pct = 100.0 * (dmr_mtpa_max_vol / C3MR_PUBLISHED_CEILING_MTPA - 1.0)

print(f"\nMechanism 2 - fixed MCHE volumetric-flow ceiling "
      f"({c3mr_vol_flow_ceiling_m3_s:.3f} m3/s, same calibration point):")
print(f"  NG density at MCHE inlet: {c3mr_inlet_density:.2f} kg/m3 (C3MR, "
      f"{C3MR_PRECOOL_FLOOR_K-273.15:.0f} C) vs. {dmr_inlet_density:.2f} kg/m3 (DMR, "
      f"{DMR_PRECOOL_FLOOR_K-273.15:.0f} C) - a {100.0*(density_ratio-1.0):.1f}% density increase.")
print(f"  A fixed velocity/volumetric limit alone lets DMR's denser inlet support "
      f"{dmr_mtpa_max_vol:.2f} mtpa ({vol_increase_pct:+.1f}% vs. C3MR).")

# ---------------------------------------------------------------------
# Reality check against the published DMR ceiling.
# ---------------------------------------------------------------------
published_increase_pct = 100.0 * (DMR_PUBLISHED_CEILING_MTPA / C3MR_PUBLISHED_CEILING_MTPA - 1.0)
print("\n" + "=" * 78)
print("Comparison against the published DMR ceiling")
print("=" * 78)
print(f"  Published (process_selection.py citation): "
      f"{C3MR_PUBLISHED_CEILING_MTPA:.0f} -> {DMR_PUBLISHED_CEILING_MTPA:.0f} mtpa "
      f"({published_increase_pct:+.0f}%)")
print(f"  Duty mechanism alone predicts:              {duty_increase_pct:+.1f}%")
print(f"  Volumetric/velocity mechanism alone predicts: {vol_increase_pct:+.1f}%")
print(f"  Combined (both mechanisms compounded):        "
      f"{100.0*((1+duty_increase_pct/100.0)*(1+vol_increase_pct/100.0)-1.0):+.1f}%")

# Sanity-check against the existing screening function, same capacity point.
guidance_at_c3mr_ceiling = compare_liquefaction_cycles(
    target_train_capacity_mtpa=C3MR_PUBLISHED_CEILING_MTPA + 0.1, ambient_temp_swing_K=15.0,
)
print(f"\ncompare_liquefaction_cycles() at {C3MR_PUBLISHED_CEILING_MTPA + 0.1:.1f} mtpa "
      f"(just above C3MR's ceiling) recommends: {guidance_at_c3mr_ceiling.recommended}")

print(
    "\nReading these numbers: neither mechanism alone reaches the published "
    "+60% DMR ceiling uplift - the duty mechanism is modest (it only "
    "reflects a smaller precool-to-rundown span) and the volumetric/"
    "velocity mechanism is the larger of the two, but still short of +60% "
    "on its own. The published ceiling almost certainly also reflects "
    "compressor casing/impeller size limits (not modeled here - see "
    "equipment_catalog.py's frame table, which is sized for GAS "
    "compression, not this analysis) and real coil-wound core fabrication "
    "limits beyond a simple velocity proxy. Both mechanisms computed here "
    "are genuine and point the same direction as the literature; treat the "
    "magnitude as a lower-bound illustration of WHY DMR's ceiling is "
    "higher, not a reproduction of the vendor engineering behind the "
    "published 8 mtpa figure."
)
