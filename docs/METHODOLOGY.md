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

## Separator vessels (`lng_design/vessels.py`)

**Diameter**: Souders-Brown gas-capacity correlation, the same functional
form used for the amine absorber's diameter (GPSA Engineering Data Book
Ch. 7, "Separators"; Campbell, *Gas Conditioning and Processing* Vol. 2).
**Height**: liquid residence time (3-5 minutes typical for a standard
knockout/surge drum per GPSA/Campbell) sets the liquid holdup, plus a
vapor disengagement allowance of roughly one vessel diameter (or 1 m,
whichever is larger) — both are widely used conceptual-design defaults,
not a substitute for a full mechanical/process datasheet.

## Shell-and-tube exchangers (`lng_design/exchangers.py`)

Standard LMTD/overall-U area sizing (any heat-transfer text, e.g. Kern,
*Process Heat Transfer*; Sinnott & Towler, *Chemical Engineering Design*).
The shell-diameter estimate deliberately avoids reproducing a specific
numeric tube-count-per-shell table from memory (published K1/n1
correlations vary by source/edition and are easy to misquote); instead it
uses a transparent, independently-checkable tube-bundle area-utilization
fraction — see the module's docstring for the reasoning and how to
override it with your own trusted tube-count table.

## Air-cooled exchangers (`lng_design/air_cooler.py`)

GPSA Engineering Data Book Ch. 9 ("Air-Cooled Exchangers") and API 661
conventions: air mass flow from duty and a design temperature rise
(8-20 K typical range), face area from a design face velocity
(2.5-3.5 m/s typical), matched to standard API 661 bay widths (8-16 ft).
Fan power uses a standard fan-power relation (volumetric flow × static
pressure drop ÷ fan efficiency) with GPSA's typical 12-25 mm H₂O
finned-bundle pressure-drop range and API 661's 60-70% typical axial fan
static efficiency.

## Cooling water demand (`lng_design/water_system.py`)

Cooling Tower Institute practice, reproduced in GPSA Engineering Data
Book Ch. 9: evaporation loss as a fraction of circulation is
`0.00085 × range(°F)` (this constant already incorporates a typical
climate correction, consistent with the commonly quoted "~1% evaporation
per 10°F of range" rule of thumb). Blowdown follows from a target cycles
of concentration (3-5 typical for hydrocarbon-plant cooling towers);
drift loss is a small fixed fraction set by the drift eliminator design
(under 0.001% for modern high-efficiency eliminators, up to ~0.02% for
older designs).

## Equipment catalog / standard-variant matching (`lng_design/equipment_catalog.py`)

Every sizing function above produces a continuous number; this module
holds the standard commercial series each gets rounded up against —
process vessel diameters (GPSA Ch. 7 / Campbell), TEMA shell sizes (Kern;
Sinnott & Towler), API 661 air-cooler bay widths, and a centrifugal
compressor frame table reproduced from *Pipeline Rules of Thumb
Handbook*, E.W. McAllister, 3rd Ed., Gulf Publishing — the same public
source this package's compressor module is validated against (see
[docs/VALIDATION.md](VALIDATION.md)). `classify_mche_type()` in
`mche.py` is a deliberately coarse, illustrative screening heuristic
(coil-wound for large base-load trains vs. parallel plate-fin cores for
smaller/peak-shaving scale) reflecting general, widely published LNG
technology comparisons — not a rigorous technology-selection tool.

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
