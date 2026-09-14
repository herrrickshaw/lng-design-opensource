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

## A note on what was *not* used

Early in this project's development, a Dropbox folder that looked like it
might contain public reference material (named "GLUG") turned out, on
inspection, to be further confidential Shell/Sakhalin Energy project
deliverables (Process Flow Schemes, Process Control Narratives, Process
Safeguarding Memoranda by plant unit number) - not a public source. It was
not used anywhere in this repository, consistent with this project's
literature-only scope.
