# Methodology & citations

Every correlation used in this package traces to a public source. This
page collects them in one place; each module's docstring repeats the
relevant citation next to the code that implements it.

## Propane pre-cool cycle (`lng_design/precool.py`)

Standard single-stage vapor-compression refrigeration cycle: evaporate,
compress (fixed isentropic efficiency), condense, throttle. Any
refrigeration engineering text covers this (e.g. ASHRAE *Fundamentals*,
Ch. 2, "Thermodynamics and Refrigeration Cycles"). State points are
computed with [CoolProp](http://www.coolprop.org/)'s propane equation of
state (Lemmon, McLinden & Wagner reference EOS), not a digitized
pressure-enthalpy chart, so results are reproducible to the reference
fluid model rather than to chart-reading precision.

For a single evaporation level and fixed condensing temperature,
compressor power decreases monotonically as the evaporator temperature
rises (better COP) — so the power-minimizing evaporator temperature for a
fixed duty is the MITA-limited boundary against the process cold-end
target. This matches the qualitative conclusion in the published C3MR
literature that the precool pinch constraint is typically active
("binding") at the optimum (see the multi-objective C3MR optimization
papers cited below for the full multi-stream case, where this simple
single-stream intuition no longer holds exactly).

## Centrifugal compressor sizing (`lng_design/compressor.py`)

Polytropic head / polytropic efficiency method — GPSA Engineering Data
Book, 14th ed., Section 13 ("Compressors"); also standard in Boyce, *Gas
Turbine Engineering Handbook*, compressor chapters. The polytropic
exponent `n` is derived from the isentropic exponent `k` (evaluated from
CoolProp's real-gas Cp/Cv, not an ideal-gas assumption) and the polytropic
efficiency via `(n-1)/n = (k-1)/(k·η_p)`. Multistage sizing splits the
overall pressure ratio evenly on a log basis across stages — GPSA's
standard "equal pressure ratio per stage" heuristic for a first-pass
frame selection.

Typical polytropic efficiencies (70–80% for multistage centrifugal
compressors) are also GPSA Ch. 13 values; override with vendor
performance-curve data once one exists — that vendor curve, not this
formula, becomes the basis of record for detailed design.

## Amine acid-gas absorber (`lng_design/amine_absorber.py`)

**Diameter**: Souders-Brown flooding velocity correlation,
`v_flood = K_SB · √((ρ_L − ρ_V)/ρ_V)`, as presented in GPSA Engineering
Data Book Ch. 19 ("Hydrocarbon Treating") and Kohl & Nielsen, *Gas
Purification*, 5th ed., Ch. 2. `K_SB` is packing-factor dependent;
0.03–0.05 m/s is a typical structured-packing range cited in both
references. Operating at 70–80% of flood is standard design margin.

**Height**: the Kremser equation (McCabe, Smith & Harriott, *Unit
Operations of Chemical Engineering*, absorption chapter) for the number
of theoretical stages needed to hit a target removal, given a linearized
local equilibrium slope `m` and absorption factor `A = L/(m·V)`, converted
to packed height via a literature HETP for the chosen packing (Kohl &
Nielsen cite 0.4–0.6 m as typical for structured packing in amine
service).

This is a simplified, non-rate-based method: it does not model reaction
kinetics or heat effects within the column, which a rigorous simulator
(rate-based absorber models in Aspen HYSYS/PRO/II/ProMax, or a
first-principles model in IDAES-PSE) does. It is a conceptual/screening
sizing only.

## MCHE composite curve / pinch check (`lng_design/mche.py`)

Linnhoff pinch technology (Linnhoff & Hindmarsh, "The pinch design method
for heat exchanger networks", *Chem. Eng. Sci.* 38(5), 1983); standard
textbook treatment in Smith, *Chemical Process Design and Integration*,
2nd ed. Hot/cold composite curves are compared on a shared cumulative-duty
axis (not just at terminal temperatures) specifically to catch an internal
pinch violation that a naive terminal-only check would miss — a
well-documented failure mode in multi-stream cryogenic exchanger design
(LNG main cryogenic heat exchangers being the canonical example, since the
mixed-refrigerant side changes phase at a very different rate than the
natural-gas side across the exchanger).

Published brazed-aluminum plate-fin exchanger overall U-values for LNG
service commonly cited in the open literature fall in the
1,500–3,500 W/m²·K range depending on stream side and fouling allowance;
the app defaults to 2,000 W/m²·K and lets the engineer override it.

## Optimization (`lng_design/optimize.py`)

NSGA-II via [pymoo](https://pymoo.org/), matching the approach used across
the published C3MR LNG process optimization literature for trading off
compressor power against exergy efficiency or cost proxies, e.g.:

- Multi-objective optimization of propane pre-cooled mixed refrigerant
  (C3MR) LNG process, *Energy*, 185 (2019) 492–504.
- Surrogate-assisted constrained hybrid particle swarm optimization for
  C3MR LNG process optimization, *Energy* (2024).
- Operation optimization of C3MR LNG process via knowledge-based and
  constrained Bayesian optimization, *Chemical Engineering Science*
  (2024).

These papers motivate the *pattern* (multi-objective search around a
process model) implemented here; no numeric results, base-case figures, or
process parameters from any specific paper or from any client project are
reproduced in this repository.
