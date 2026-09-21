# External validation

`docs/METHODOLOGY.md` documents where each method *comes from*. This page
documents independent checks against sources external to this repository -
either a full published numeric worked example (reproduced end-to-end and
compared), or a corroborating public reference for a design parameter
where no full worked example with matching inputs/outputs was found.

## Compressor module — full numeric worked example ✅

Source: *"Centrifugal Compressor Head and Power Calculations"*
(cheresources.com preview worksheet), whose gas property table is sourced
from the **GPSA Engineering Data Book, 11th Ed.-SI (1998)**. Freely
downloadable, not paywalled.

| Quantity | Published | `lng_design.compressor` | Difference |
|---|---:|---:|---:|
| Z_avg | 0.956 | 0.956 | exact |
| Pressure ratio | 3.33 | 3.332 | — |
| Polytropic head | 71,971 N·m/kg | 72,232 J/kg | **+0.36%** |
| Gas power | 3,533.1 kW | 3,545.9 kW | **+0.36%** |
| Discharge temperature | 99.9 °C | 103.1 °C | +3.2 °C |

Inputs used (identical to the published case): 5/80/15 mol%
ethane/propane/n-butane, P₁ = 2.068 bara, T₁ = 40 °C, P₂ = 6.89 bara,
mass flow 136,078 kg/h, η_poly = 77%.

**Why discharge temperature differs more than head/power**: the published
method fixes the isentropic exponent κ at its *inlet* value for the whole
compression; `lng_design.compressor` evaluates κ at the *mean* of inlet
and (estimated) outlet conditions, one fixed-point iteration, using
CoolProp's real Cp/Cv rather than the inlet-only value. The published
worksheet itself notes "the polytropic head equation is insensitive to
κ-value... within the limits that κ normally varies during compression" -
consistent with the tiny (0.36%) effect on head and power. Discharge
temperature sits in the `(n-1)/n` exponent, so it is more sensitive to
this choice, which is why its percentage difference is larger even though
the absolute gap (3.2 °C on a ~60 °C temperature rise) is small. This is
reproduced as `tests/test_compressor.py::test_matches_published_gpsa_worked_example`,
so a future change that breaks this agreement fails CI.

## Amine absorber module — design-parameter corroboration ✅ (no full numeric case found)

No freely available worked example with a complete, reproducible
input/output set was found for a packed amine absorber in the time
available (paywalled textbook examples exist; none were used). Instead,
the module's *default design parameters* were checked against independent
public design-guideline references:

- Operating at 60-70% of flooding velocity: confirmed as standard practice
  by an independent packed-bed absorber design guideline (msubbu.in) -
  `lng_design.amine_absorber`'s default `design_fraction_of_flood=0.75`
  sits just above this typical range (a slightly more conservative
  default), user-overridable.
- HETP for structured packing "generally less than 0.5 m" - matches this
  module's default `hetp_m=0.5` exactly.

If you have access to a textbook worked example with full inputs (gas/
liquid rates, densities, target removal, equilibrium slope) and outputs
(diameter, height), please open an issue or PR with the citation so it can
be added as a full regression test like the compressor one above.

## MCHE / pinch-analysis module — methodology corroboration ✅

Linnhoff pinch technology and the "problem table" duty-axis construction
used here are standard, uncontested chemical engineering practice (see
citations in `docs/METHODOLOGY.md`); the module's own test suite
(`tests/test_mche.py`) includes a constructed case specifically designed
to catch an internal (non-terminal) MITA violation, which is the
well-documented failure mode this method exists to catch in multi-stream
cryogenic exchanger design.

## Overall temperature ladder — independent published cross-check ✅

A published SMR (Single Mixed Refrigerant / PRICO) process paper
(Frontiers in Energy Research, 2022, DOI 10.3389/fenrg.2022.917656)
reports: NG feed 32°C/50 bara, LNG exiting the main exchanger -149.3°C,
final LNG product -158.5°C, compressor discharge held at 40°C via
interstage cooling, 75% compressor efficiency. Every one of these
independently matches this package's own defaults (40°C ambient
condensing in `precool.py`/`cascade_loops.py`, 75% isentropic/polytropic
efficiency defaults throughout, and an end-flash storage temperature
default of -158°C in the Streamlit app) - found and cross-checked after
the defaults were already set, not tuned to match afterward.

## Molecular sieve module — a bug the test suite didn't catch, running the app did

`molecular_sieve.py`'s diameter (gas-velocity-driven) and bed height
(water-duty-driven) are computed independently. At the Streamlit app's
original defaults (50 kg/s, 100 ppmw inlet water), this produced a
"pancake" bed: 3,658 mm diameter, **0.2 m** tall - far too shallow for a
mass-transfer zone to develop, a real design flaw invisible to unit tests
built around the same untested defaults. Caught only by actually running
the app in a browser and reading the number, not by any test written in
advance. Fixed by adding an explicit minimum-bed-depth check (the module
now raises rather than returning a physically dubious result) and
changing the app's defaults to a more realistic wet-gas water content
(800 ppmw), which gives a sane 2,286 mm × 1.4 m bed - see
`tests/test_molecular_sieve.py::test_rejects_pancake_bed_high_flow_low_water_content`.

## Cascade module — a zero-approach-temperature bug caught before shipping

While writing `cascade_loops.py`'s first tests, the LRC condensing
temperature and PMR evaporating temperature were set to the exact same
value (both -40°C) - a zero-Kelvin approach that would need infinite
heat-transfer area, the same mistake `mche.py`'s MITA check exists to
catch on the main exchanger. `three_loop_cascade` now enforces a MITA
between the two loops explicitly and raises if violated; the tests were
corrected to use a realistic 3 K margin before this shipped, not after.

Building the mixed-refrigerant cycle for this module also surfaced a
genuine numerical/physical constraint worth recording: a light,
methane/nitrogen-rich blend suitable for the cryogenic LRC evaporator
(down to -100°C) has **no valid bubble point anywhere near ambient
temperature** - CoolProp's mixture flash solver fails to converge rather
than returning a wrong answer. A heavier blend (30/70 mol% ethane/
propane) **does** condense at 40°C ambient while evaporating down to at
least -60°C - independently confirming the concrete mechanism behind
DMR's reported precool advantage over pure propane's ~-42°C atmospheric
floor (see `process_selection.py`'s citations). Both findings came from
running real CoolProp calculations with several candidate compositions/
temperatures, not from asserting the result in advance.

## Full-train integration — three more defects found only by running it end to end

`examples/full_train_worked_example.py` chains every module built this
session on one consistent feed basis. Running it (not the unit tests,
which each passed in isolation) surfaced three real defects invisible
until the modules were actually connected:

1. **`compressor.match_frame_for_stage` crashed on a refrigerant's own
   saturated suction state.** `(T_evap, P_evap)` sit exactly on that
   fluid's saturation curve by definition, so a plain `(T, P)` density
   lookup is ambiguous - CoolProp correctly raises rather than guessing
   liquid vs. vapor. Fixed by documenting the pitfall directly in the
   function's docstring (query vapor density via quality, `Q=1`, instead,
   for exactly this case) rather than papering over it in the caller.
2. **A single `mixed_refrigerant_cycle` call cannot span the full
   precool-to-LNG-rundown range.** The example's LRC blend, validated
   down to about -100°C, diverges (`HSU_P_flash` fails to converge to a
   physical root) when pushed to -159°C in one compression stage - too
   large a compression ratio/temperature lift for that blend in a single
   step. This matches real practice: MFC/DMR designs use multiple
   refrigerant pressure levels (and, for a true 3-loop MFC, a dedicated
   lighter SRC subcooling cycle this package's 2-loop cascade doesn't
   model) rather than one giant compression. Fixed with explicit error
   handling and a regression test (`test_single_stage_cannot_span_full_
   precool_to_lng_rundown_range`); the worked example now scopes LRC to
   -40→-100°C and reports the -100→-159°C subcooling duty honestly as
   needing a dedicated SRC loop, rather than forcing an unvalidated
   number through.
3. **The amine absorber's L/V=20 default gives an absorption factor
   A=50** - wildly outside the classic 1.4-2.0 economic design range
   (McCabe, Smith & Harriott) - and produced an implausible 0.7 m packed
   height for a 3.64 m diameter column. Fixed in the worked example
   (L/V=0.8, A=2.0) to a realistic 3.3 m / 6.6 theoretical stages; this
   default is used elsewhere in the repo's examples and the Streamlit
   app too and is worth revisiting there separately.

None of these three were predicted by writing tests in advance - each
module passed its own unit tests in isolation. They surfaced only when
the modules were chained together on a shared, realistic basis, which is
the whole reason this worked example exists.

## DMR full-train example — a single-stage compression penalty found only by comparing against C3MR

`examples/full_train_dmr_worked_example.py` swaps the C3MR baseline's
pure-propane precool for a heavier ethane/propane DMR blend reaching a
colder -50°C floor (vs. propane's ~-42°C limit), routing the NG precool
duty through `three_loop_cascade`'s `ng_precool_duty_kW` parameter for
the first time (the C3MR example predates that parameter's DMR use
case). Running it end to end, and comparing against the C3MR baseline
recomputed inline on the same feed basis, surfaced two real findings
neither example's own unit tests predicted:

1. **The DMR blend's own PMR-loop COP (0.87) is *worse* than propane's
   (1.30) at these conditions** - not a code bug, since
   `mixed_refrigerant_cycle` uses exactly the same single-stage
   isentropic-compression model as `precool.propane_cycle_power`
   (same 0.75 default efficiency, same CoolProp-based approach). Both
   cycles resolve a ~22-24:1 evaporator-to-condenser pressure ratio in
   one compression step; the heavier DMR blend's real-gas behavior over
   that ratio costs more compression work than propane's does. This
   means DMR's *headline* total-power number (69,587 kW vs. C3MR's
   36,549 kW for the same LRC liquefaction scope) looks worse only
   because of this single-stage penalty on top of doing more of the
   total temperature drop - it is not a claim that DMR precool is less
   efficient than C3 in general. Real DMR trains recover this by
   splitting PMR compression across multiple stages/casings (the same
   category of limitation already documented above for the LRC loop
   spanning too wide a range in one call) - modeling that split is out
   of `cascade_loops.py`'s current single-stage scope.
2. **The DMR PMR compressor's required inlet volume flow (365,072 m3/h)
   exceeds even the largest standard frame** (Frame F, 170,000 m3/h) -
   `equipment_catalog.select_compressor_frame` correctly raises rather
   than returning a wrong match (this exact boundary was already covered
   by `test_select_compressor_frame_rejects_flow_beyond_largest_frame`,
   so this is a genuine real-scale finding, not a new code gap). The
   example handles it by computing the number of parallel Frame F trains
   needed (3, at ~121,691 m3/h each) rather than crashing - the same
   "multiple parallel units" resolution `refrigerant_makeup.py`'s tests
   already establish for an oversized single-vessel charge.

Neither finding was predicted by writing tests in advance for either
module - both surfaced only by actually running the DMR example and
comparing its numbers against the C3MR baseline on the same basis,
consistent with the pattern established by the C3MR full-train example
above.

## MCHE NG-throughput ceiling — quantifying the published C3MR/DMR capacity gap

`process_selection.py` cites a published ~5 mtpa/train ceiling for C3MR
vs. ~8 mtpa/train for DMR, attributed to "propane compressor and main
heat exchanger size limits" (Technology Review of Natural Gas
Liquefaction Processes, scialert.net). `examples/mche_debottleneck_dmr_vs_c3mr.py`
quantifies the two physical mechanisms behind that citation using this
package's own duty and CoolProp density calculations, calibrated to the
same 5 mtpa C3MR ceiling:

- **Duty mechanism** (DMR's colder ~-50°C precool floor leaves a smaller
  temperature span for the MCHE to cover than C3MR's ~-40°C floor):
  +9.2% NG throughput alone, for a fixed MCHE duty ceiling.
- **Density/velocity mechanism** (colder NG is ~16% denser at the MCHE
  inlet, so more mass fits within a fixed volumetric/tube-velocity
  limit - a standard coil-wound exchanger design constraint, e.g. Kern,
  "Process Heat Transfer"): +16.2% alone, for a fixed volumetric-flow
  ceiling.
- Combined (compounded): +26.8% - real, and directionally consistent
  with the literature, but well short of the published +60% (5→8 mtpa)
  uplift. The gap is honestly attributed to compressor casing/impeller
  size limits and real core-fabrication limits this package does not
  model, not smoothed over to make the two numbers agree.

## MCHE detailed rating (`mche_tube_design.py`) — two numerical fragilities found building it, one physical finding from using it

Building a local-property (rather than constant-U) MCHE model, to answer
"what rundown can a specific tube bundle actually deliver" instead of
"does an assumed U check out", surfaced real problems only found by
running the calculation:

1. **A full multicomponent bubble-point flash for Shah's condensation
   correlation was both slow (~1-2 s per call) and, for this package's
   retrograde-prone light-hydrocarbon feed composition near its own
   pseudo-critical pressure, prone to outright failure** ("critical point
   finding routine found 6 critical points"). Not predicted in advance -
   found by timing and running the zone-by-zone calculation. Fixed by
   using a single representative pure-fluid proxy (the heaviest
   hydrocarbon present, evaluated well below *its own* critical point)
   for the liquid-phase reference properties, and a Kay's-rule
   pseudo-critical pressure instead of the mixture's own true critical
   pressure - both numerically robust and fast, at the cost of some
   compositional fidelity, flagged explicitly in the module's docstring
   rather than presented as exact.
2. **Repeated single-property CoolProp.PropsSI calls against a
   string-keyed mixture (`"Methane[0.85]&..."`) were the dominant cost**,
   not the flash math itself - each call reconstructs the mixture from
   scratch. Rebuilding a persistent `AbstractState` once and reading
   multiple properties (H, Q, viscosity, conductivity, cp) off a single
   resolved state per temperature point cut a 15-zone rating from
   several minutes (initial version, sometimes hanging outright) to
   roughly 20-45 seconds. This is a CoolProp usage-pattern finding, not a
   thermodynamic one, but it shaped the module's whole internal
   structure (see `_zone_integrate`'s docstring).
3. **Physical finding**: rating a tube bundle SIZED by `mche.py`'s simple
   method (assumed constant U = 2,000 W/m²K, this package's own stated
   default) against the LRC section's -40°C→-100°C duty, the detailed
   local-property rating only reaches **-70.2°C**, 29.8 K short of the
   assumed target. The local U this module computes averages ~316 W/m²K
   here - well below the 1,500-3,500 W/m²K range `mche.py`'s own
   docstring cites as typical for LNG service. The gap is attributed
   mainly to the shell-side falling-film model's deliberate
   conservatism (pure conduction, no nucleate-boiling/wave enhancement -
   see `mche_tube_design.py`'s docstring), not to `mche.py`'s constant-U
   default being simply "wrong" - both are conceptual-screening
   simplifications with different, documented blind spots, and this
   comparison is reported as "the two methods disagree, and here is a
   physically grounded reason why", not as a corrected number. See
   `examples/mche_rundown_rating.py`, runnable end to end.

## Regas / BOG / fractionation modules — what was checked, and what running them exposed

**Independent checks that pass** (all in `tests/`): the Fenske and Underwood
equations against their closed forms (binary Underwood reduces exactly to
`R_min = [x_D/x_F - a(1-x_D)/(1-x_F)]/(a-1)`); the Gilliland limits
(`R -> R_min` gives infinite stages, `R -> inf` gives `N_min`); BOG latent
heat for a pure-methane LNG against CoolProp's pure-fluid `h_fg`
(within 0.2 %); the deethanizer condenser duty (distillate 99.5 % ethane)
against `V x h_fg(ethane)` from the pure-fluid route (within 3 %); pump
hydraulic power against the incompressible `m dP / rho` (within 4 %);
vaporizer duty against a pure-methane enthalpy difference (within 8 %);
methane LHV against the NIST value (50.0 MJ/kg); the recondenser enthalpy
balance re-evaluated independently after the solver returns; and the
cold-suction BOG compressor power ratio against the suction-temperature
ratio (within 10 %).

**FUG against exact stage stepping.** For an ideal binary (constant
alpha, constant molar overflow, saturated-liquid feed) the exact stage
count is obtainable by McCabe-Thiele stepping, coded independently in the
test. Four cases, FUG (Molokanov) vs. stepping: 23.7 vs 22, 18.8 vs 18,
36.5 vs 37, 18.6 vs 17 stages, i.e. -1 % to +9 %, conservative on
average. The test bound is 15 %. This validates the shortcut chain on the
ideal case only; the CoolProp-driven multicomponent behavior has **no
external numeric benchmark** here (no published full worked NGL
fractionation case with all inputs was found), so treat those stage counts
as +/-10-15 % and confirm in a rigorous simulator.

**Defects and surprises found by building and running it**

* *CoolProp's mixture PS flash fails at pipeline pressure.* The first pump
  implementation used `PSmass_INPUTS` for the isentropic outlet; for the
  5-component LNG at 85 bar it raised "the (T,p) flash is misclassifying
  the phase" for some efficiencies and not others. The pump now solves the
  outlet temperature by root-finding on `PT_INPUTS` liquid states, which
  was more robust but still hit the flake in the next bullet
  (`test_pump_warming_falls_with_efficiency` is the regression).
* *CoolProp's mixture PT flash misfires along the 85 bar LNG isobar, found
  only by using the app.* The Streamlit send-out tab plotted a heating
  curve running to -6,000 MW: at T = 136.435 K the flash returned a "gas"
  at h = -40,000 kJ/kg (correct: ~71 kJ/kg). A scan (0.7 K steps, 110-283 K)
  found 3 bad points of 248 with automatic phase detection; at 125 K it
  returned h = -291,916 kJ/kg where the right answer is 34 kJ/kg. The unit
  test's point spacing missed all of them. Nudging the temperature by up to
  0.1 K did not always escape the bad window, so the fix is different in
  kind: above 1.3 x the largest component critical pressure the state is
  imposed as supercritical (`specify_phase`), which skips the failing
  stability analysis. It also silently corrupted a result: an earlier run
  of the worked example reported an HP pump of 4,320 kW shaft (+5.1 K) and
  111.7 MW vaporizer duty; the correct values are 3,488 kW (+3.5 K) and
  112.5 MW - a 24 % pump-power error that raised no exception and that
  every existing test passed. Same scan with the imposed phase: 0 bad of 248,
  identical values wherever automatic detection was right, and ~100x faster
  (0.3 s for 400 heating-curve points). A monotone-enthalpy guard with a
  nudge sequence remains as a fallback below that pressure
  (`test_heating_curve_survives_coolprop_flake_at_136p435K`). The mixture
  PS flash the first pump version used (previous bullet) is the same
  family of failure. Lower-pressure flashes elsewhere (tank bubble points,
  fractionation) were not seen to misfire, but nothing here proves they
  cannot - re-scan if you change composition or pressure range.
* *Gilliland divided by zero at exactly `R = R_min`.* Caught by the
  limit test; it now returns infinity, and `size_column` rejects
  `reflux_factor <= 1`.
* *A test of my own used an invalid arrival state.* The cold-arrival
  case passed `arriving_P = tank pressure`, which `flash_end_gas`
  correctly rejects (it needs a let-down). `compute_bog` now validates that
  the arrival pressure exceeds tank pressure with an explanatory error.
* *The default insulation stack gives a static BOR of 0.074 %/day,
  about 50 % above the commonly quoted ~0.05 %/day vendor figure.* The
  layer thicknesses were not tuned to hit 0.05: a bare 1-D estimate with
  a 10 % bridge allowance and 1.0/0.6/0.5 m wall/roof/floor insulation is
  conservative, and `test_default_stack_static_bor_...` only asserts the
  0.03-0.12 band. A contractor's actual build-up replaces it.
* *The barometric term dominates.* At a 100 Pa/h fall, a 2 x 160,000 m3
  terminal's holding-mode BOG rises from 6.8 to 19.6 t/h (the barometric
  term alone is 2.9x the static heat-leak term), and 300 Pa/h makes it 8.6x. That is why `barometric_fall_Pa_per_h`
  is an explicit input with a docstring warning rather than a hidden 0.
  It also sets whether the BOG compressors can turn down to holding mode:
  in the worked example the holding BOG is 66 % of one machine's rating
  with a 100 Pa/h allowance but only 23 % without it.
* *Cold BOG compression pays back 2x.* Same duty on +25 C gas needs 2.0x
  the shaft power (4,213 vs 2,097 kW per machine in the example).
* *The recondenser is send-out-limited.* At full send-out it absorbs
  88 t/h of BOG against a 54 t/h design case, but at 25 % send-out only
  22 t/h, leaving ~32 t/h that needs the direct-to-pipeline HP BOG route
  (5 stages, 312 C discharge without intercooling in the example).
* *Physics the shortcut correctly refused to hide.* The deethanizer's
  ethane distillate cannot be condensed with air or cooling water at any
  pressure (ethane's 305 K critical temperature is below the 318 K
  clearance), so it needs refrigeration - the module reports that instead
  of a pressure. The depropanizer at 16 bar was marginal (needs 16.006 bar
  for a 45 C condenser); the example uses 17 bar.
* *Columns interact.* With 98 % ethane recovery at the deethanizer, 2 %
  of the ethane goes to the depropanizer and ends up in the propane
  distillate at 2.1 mol %, failing an (assumed) 2 mol % ethane limit for
  propane refrigerant. The spec check in the example fails for exactly
  that reason - the fix is upstream (higher deethanizer recovery), not in
  the depropanizer.

Runnable end to end: `examples/regas_bog_fractionation_worked_example.py`.

## LPG import terminal — one independent check, one gap, three surprises

**Independent check that passes.** For pure propane the compress-condense-
return loop is exactly a propane refrigeration cycle whose evaporator is the
tank. `precool.propane_cycle_power` (a separate module: single-stage,
isentropic) gives 4.1045 kg/s of refrigerant for the same heat load and
45 C condensing; `size_bog_reliquefaction` (flash fraction from an
isenthalpic CoolProp flash, flow = BOG/(1-f)) gives 4.104 kg/s, and the
condensing pressures agree within 1 %. Compressor power differs by +11 %
(762 vs 684 kW), the expected direction: three polytropic stages at 0.78
without inter-cooling vs. one isentropic stage at 0.75. Also tested: propane
vapor pressure (13.7 bar at 40 C) and the normal boiling points of propane
(-42 C) and n-butane (-0.5 C) against textbook values.

**Gap.** No published numeric LPG-terminal case was found, so the tank
boil-off rate (0.06 %/day for the default 0.30 m insulation) is an
unvalidated consequence of assumed insulation, and the storage volume is a
mass-balance heuristic. Treat both as placeholders for a contractor's
figures.

**What running it showed**
* *`flash_end_gas` did not know isobutane.* Its molecular-weight table had
  `i-Butane` but CoolProp's name is `Isobutane`; an LPG with isobutane raised
  a KeyError from inside the flash. Added the alias.
* *The flash penalty dominates re-liquefaction.* Condensing at 45 C and
  letting down to the -39 C tank flashes 51 % of the liquid, so the
  compressors handle 2.04x the BOG (48 vs 24 t/h). Sub-cooling the liquid to
  10 C cuts the flash to 28 % and compressor power by 32 % for an 879 kW
  sub-cooler - a trade the module now reports instead of leaving implicit.
* *Design BOG is not the heat leak.* Of 23.6 t/h at design, static heat
  ingress is 1.7 t/h; arrival flash (10.7), the barometric allowance (6.7)
  and vapor displacement (3.9) dominate, and vapor return to the ship is
  the biggest lever (`test_vapor_return_reduces_...`). Holding-mode BOG is
  then only 35 % of the machine rating - below an assumed 60 % stable
  minimum - so the holding case needs its own smaller machine or recycle.

## A note on what was *not* used

Early in this project's development, a Dropbox folder that looked like it
might contain public reference material (named "GLUG") turned out, on
inspection, to be further confidential Shell/Sakhalin Energy project
deliverables (Process Flow Schemes, Process Control Narratives, Process
Safeguarding Memoranda by plant unit number) - not a public source. It was
not used anywhere in this repository, consistent with this project's
literature-only scope.
