"""Cross-checks mche.py's SIMPLE constant-U area estimate against
mche_tube_design.py's DETAILED local-property RATING calculation, on the
same LRC section duty used in the full-train worked examples.

The question this answers: if you size a tube bundle using the simple
method (assume a target rundown temperature, use one assumed constant
overall U to get a required area), does that SAME bundle, when rated
with real tube-side/shell-side heat transfer coefficients computed from
actual CoolProp properties at every point along its length, actually
reach that target rundown temperature - or does the assumed constant U
turn out to have been optimistic or conservative?

This is the standard process-engineering sizing-vs-rating cross-check
(Kern, "Process Heat Transfer"): a good sizing method should roughly
agree with a rating of the equipment it specifies.

Run: python examples/mche_rundown_rating.py (takes ~30-60s - the rating
calculation does real CoolProp property lookups at many points along the
exchanger, not one assumed number - see mche_tube_design.py's docstring)
"""
from __future__ import annotations

import math

from lng_design.cascade_loops import mixed_refrigerant_cycle
from lng_design.mche import StreamSegment, analyze_composite_curves
from lng_design.mche_tube_design import DEFAULT_TUBE_LENGTH_M, DEFAULT_TUBE_OD_M, TubeBundleGeometry, rate_mche_bundle
from lng_design.properties import GasMixture

MTPA_TO_KG_S = 1.0e9 / (365.25 * 24 * 3600)

# Same basis as examples/full_train_worked_example.py's LRC section.
TRAIN_CAPACITY_MTPA = 2.0
FEED_GAS = GasMixture({"Methane": 0.85, "Ethane": 0.08, "Propane": 0.04, "Nitrogen": 0.03})
FEED_P_PA = 50e5
LRC_BLEND = GasMixture({"Nitrogen": 0.05, "Methane": 0.30, "Ethane": 0.35, "Propane": 0.30})

PRECOOL_FLOOR_K = 233.15   # -40 C, LRC section's hot end
LRC_T_EVAP_K = 173.15      # -100 C, LRC section's target cold end
LRC_T_COND_K = 236.15      # -37 C, LRC condensing against the PMR loop

feed_mass_flow = TRAIN_CAPACITY_MTPA * MTPA_TO_KG_S

total_span_C = 159.0 - 40.0
lrc_span_C = 100.0 - 40.0
total_liquefaction_duty_kW = feed_mass_flow * 2.9 * total_span_C
lrc_duty_kW = total_liquefaction_duty_kW * lrc_span_C / total_span_C

print("=" * 78)
print("MCHE LRC section: simple SIZING estimate vs. detailed RATING")
print("=" * 78)
print(f"Basis: {feed_mass_flow:.1f} kg/s NG through the LRC section, "
      f"{PRECOOL_FLOOR_K-273.15:.0f} C -> {LRC_T_EVAP_K-273.15:.0f} C target, "
      f"duty {lrc_duty_kW:,.0f} kW")

# ---------------------------------------------------------------------
# Step 1: the SIMPLE method (mche.py) - assume the -100 C target and one
# constant overall U (2000 W/m2K, this package's own stated default),
# get the required area.
# ---------------------------------------------------------------------
hot = [StreamSegment(PRECOOL_FLOOR_K, LRC_T_EVAP_K, lrc_duty_kW)]
cold = [StreamSegment(LRC_T_EVAP_K - 5, PRECOOL_FLOOR_K - 5, lrc_duty_kW)]
simple = analyze_composite_curves(hot, cold, min_approach_K=3.0, overall_U_W_m2K=2000.0)
print(f"\nSimple method (assumed U=2000 W/m2K): required area "
      f"{simple.area_estimate_m2:,.0f} m2 to reach {LRC_T_EVAP_K-273.15:.0f} C")

# ---------------------------------------------------------------------
# Step 2: build a tube bundle SIZED to exactly that area (standard tube
# geometry - see mche_tube_design.py's cited defaults), then RATE it.
# ---------------------------------------------------------------------
n_tubes = math.ceil(simple.area_estimate_m2 / (math.pi * DEFAULT_TUBE_OD_M * DEFAULT_TUBE_LENGTH_M))
geometry = TubeBundleGeometry(n_tubes=n_tubes)
print(f"\nBundle sized to match: {n_tubes:,} tubes x {geometry.tube_od_m*1000:.1f} mm OD x "
      f"{geometry.tube_length_m:.1f} m ({geometry.outer_area_m2:,.0f} m2 actual)")

lrc_cycle = mixed_refrigerant_cycle(LRC_BLEND, lrc_duty_kW, LRC_T_EVAP_K, LRC_T_COND_K)
print(f"LRC refrigerant mass flow (from mixed_refrigerant_cycle): "
      f"{lrc_cycle.refrigerant_mass_flow_kg_s:.2f} kg/s")

print("\nRating this bundle with real local tube-side/shell-side heat "
      "transfer coefficients (this takes a while - see module docstring)...")
rating = rate_mche_bundle(
    geometry, FEED_GAS, feed_mass_flow, FEED_P_PA, PRECOOL_FLOOR_K,
    LRC_BLEND, lrc_cycle.refrigerant_mass_flow_kg_s, LRC_T_EVAP_K,
    min_approach_K=3.0, n_zones=15,
)

print(f"\nDetailed rating: achievable rundown "
      f"{rating.achievable_rundown_T_K-273.15:.1f} C "
      f"({rating.binding_constraint}-limited), local U range "
      f"[{rating.min_local_U_W_m2K:.0f}, {rating.max_local_U_W_m2K:.0f}] W/m2K")

# ---------------------------------------------------------------------
# Step 3: the cross-check.
# ---------------------------------------------------------------------
delta_K = rating.achievable_rundown_T_K - LRC_T_EVAP_K
print("\n" + "=" * 78)
print("Cross-check: does the simple method's assumed U hold up?")
print("=" * 78)
print(f"  Target (simple method's assumption): {LRC_T_EVAP_K-273.15:.1f} C")
print(f"  Achieved (detailed rating, same bundle): {rating.achievable_rundown_T_K-273.15:.1f} C")
if delta_K > 0.5:
    print(
        f"  The bundle falls {delta_K:.1f} K SHORT of the assumed target - the "
        f"simple method's U=2000 W/m2K default was OPTIMISTIC for this "
        "service (local U computed here averages "
        f"{0.5*(rating.min_local_U_W_m2K+rating.max_local_U_W_m2K):.0f} W/m2K, "
        "well below 2000, mostly driven by the falling-film shell-side "
        "coefficient's deliberately conservative conduction-only model - "
        "see mche_tube_design.py's docstring and docs/VALIDATION.md)."
    )
elif delta_K < -0.5:
    print(f"  The bundle beats the assumed target by {-delta_K:.1f} K - the simple "
          "method's U=2000 W/m2K default was CONSERVATIVE for this service.")
else:
    print("  The bundle essentially hits the assumed target - the simple "
          "method's U=2000 W/m2K default holds up well for this service.")

print(
    "\nNote: mche_tube_design.py's own local-U estimate is itself a "
    "deliberately simplified, conservative model (a laminar conduction-"
    "only falling film, no nucleate-boiling/wave enhancement, and a "
    "single representative pure-fluid liquid-property proxy rather than "
    "the true multicomponent liquid composition - see the module's "
    "docstring for why). Read this cross-check as 'the two methods "
    "disagree, and here is a physically grounded reason why' rather than "
    "as a corrected, production-ready number - both are conceptual-"
    "screening tools, not a substitute for a certified exchanger rating."
)
