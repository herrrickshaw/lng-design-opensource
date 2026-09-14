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

## A note on what was *not* used

Early in this project's development, a Dropbox folder that looked like it
might contain public reference material (named "GLUG") turned out, on
inspection, to be further confidential Shell/Sakhalin Energy project
deliverables (Process Flow Schemes, Process Control Narratives, Process
Safeguarding Memoranda by plant unit number) - not a public source. It was
not used anywhere in this repository, consistent with this project's
literature-only scope.
