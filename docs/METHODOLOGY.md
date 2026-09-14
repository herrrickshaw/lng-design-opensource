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

## MCHE detailed tube-side/shell-side rating (`lng_design/mche_tube_design.py`)

Answers a different question than `mche.py` above: not "does an assumed
constant U check out for a target rundown" (a **sizing** calculation) but
"what rundown can a specific, fixed tube bundle actually deliver" (a
**rating** calculation) — the standard distinction process engineers draw
between the two (Kern, *Process Heat Transfer*; Sinnott & Towler,
*Chemical Engineering Design*). Local heat transfer coefficients are
computed from real CoolProp properties at many points along the
exchanger's duty axis rather than one assumed number:

- **Tube side, single-phase**: Dittus-Boelter (1930), Nu = 0.023 Re^0.8
  Pr^n — reproduced in Incropera, *Fundamentals of Heat and Mass
  Transfer*. Valid for turbulent flow (Re ≥ 10,000); raises otherwise.
- **Tube side, condensing**: Shah (1979), M.M. Shah, "A general
  correlation for heat transfer during film condensation inside pipes",
  *Int. J. Heat and Mass Transfer* 22(4), 547–556. Liquid-phase reference
  properties use a single representative pure fluid (the heaviest
  hydrocarbon present) rather than a full multicomponent bubble-point
  flash — see docs/VALIDATION.md for why that flash was abandoned
  (numerically fragile and slow for a retrograde-prone gas mixture).
  Reduced pressure uses a Kay's-rule pseudo-critical pressure (standard
  natural-gas engineering practice, e.g. GPSA Engineering Data Book), not
  the mixture's own true critical pressure (same fragility issue).
- **Shell side**: a simplified laminar falling-film coefficient — the
  standard Nusselt laminar-film-thickness relation (Incropera Ch. 10;
  Bird, Stewart & Lightfoot, *Transport Phenomena*) combined with a
  conduction-through-the-film approximation. This deliberately omits
  nucleate-boiling and wave/turbulence enhancement, so it is a
  conservative (likely low) estimate of the true coefficient — flagged
  explicitly rather than presented as a complete design correlation.
- **Combination**: standard cylindrical-wall series-resistance formula
  (Kern), referenced to outer tube area.

None of this reproduces any licensor's proprietary spiral-wound
exchanger correlation — it is a generic, textbook-level rating model
appropriate to conceptual screening, not certified detailed design. See
`examples/mche_rundown_rating.py` for a worked cross-check against
`mche.py`'s simple constant-U estimate, and docs/VALIDATION.md for what
that cross-check found.

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

## Liquefaction cycle screening (`lng_design/process_selection.py`)

`compare_liquefaction_cycles()` screens among C3MR, DMR, and AP-X based
on target train capacity and site ambient temperature swing, grounded in
published comparative studies (train-capacity ceilings, and DMR's
reported efficiency advantage across wide ambient ranges vs. C3MR's
single-component propane precool) - full citations in the module's
docstring. Like `classify_mche_type()`, this is an illustrative screening
heuristic, not a techno-economic optimization; real selection also weighs
capital cost, licensor terms, driver availability, and commercial
factors this module doesn't model.

## Post-MCHE end-flash (`lng_design/end_flash.py`)

A rigorous isenthalpic (Joule-Thomson) two-phase flash of subcooled LNG
down to storage pressure, using CoolProp's `AbstractState` interface on
the mixture HEOS equation of state - not a shortcut correlation. Verified
empirically (see [docs/VALIDATION.md](VALIDATION.md)) that CoolProp's
`Q()` for a mixture is a **molar** vapor fraction; this module always
converts explicitly to a mass basis using the flashed-phase mole
fractions and component molecular weights, since conflating the two is
an easy, consequential error (a ~5-10% relative difference in this
package's own test cases).

## Refrigerant storage/makeup (`lng_design/refrigerant_makeup.py`)

Vessel sized to hold one full system refrigerant charge plus a reserve
fraction for makeup losses, at a maximum liquid fill fraction (typically
85%, consistent with the fill-limit/outage practice used broadly for
pressurized liquefied-gas storage, e.g. NFPA 58-style requirements for
LPG-class storage) leaving vapor space for thermal expansion.

## Storage tank and berth (`lng_design/berth.py`)

**Storage**: a mass-balance buffer between continuous liquefaction
production and periodic (discrete) ship departures - required volume
covers the average shipping interval plus a contingency allowance for
weather/queueing delays, consistent with the commonly cited industry rule
of thumb of roughly 1.5-2x a single cargo size (e.g. GIIGNL LNG terminal
design guidance) without using that figure as the sizing basis itself.
**Berth occupancy**: the Erlang C (M/M/c) queueing formula (Erlang, 1917;
standard operations-research mathematics, e.g. Hillier & Lieberman,
"Introduction to Operations Research") gives the probability an arriving
ship must wait for a berth and the expected wait time, from the ship
arrival rate (derived from annual offtake and cargo size) and mean berth
service (turnaround) time.

## Utility systems (`lng_design/air_supply.py`, `nitrogen_system.py`, `water_system.py`)

**Instrument/plant air**: aggregated per-instrument demand with a
diversity factor (ISA/GPSA-style conceptual utility-system sizing),
compressor capacity with a design margin, receiver volume as a target
number of minutes of average demand. **Nitrogen**: purge demand via the
standard "vessel volume exchange" approach used throughout process-safety
inerting practice (e.g. NFPA 69 guidance, typically 3-5 exchanges),
continuous blanketing flow as a direct input (tank/site-specific, not
derived from a generic correlation), and a liquid-nitrogen vaporizer duty
computed rigorously via CoolProp's nitrogen EOS latent heat. **Service
water**: potable demand from a per-person-per-day figure (100-150 L/
person/day is the typical industrial-site range) plus a general service
allowance, converted to a peak design flow via a standard peaking factor.

## Molecular sieve dehydration (`lng_design/molecular_sieve.py`)

Standard two-part adsorber sizing (GPSA Engineering Data Book Ch. 20,
"Dehydration"; Campbell, "Gas Conditioning and Processing" Vol. 2): a
design superficial velocity sets diameter, water-removal duty divided by
the sieve's working capacity sets adsorbent mass/bed height, and the
relationship between adsorption time and regeneration+cooldown time
determines whether two or three beds are needed. The two sizing paths
(velocity-driven diameter, duty-driven volume) are computed independently
and can disagree - see the "pancake bed" finding in
[docs/VALIDATION.md](VALIDATION.md) for why this module validates the
resulting bed depth rather than trusting either path alone.

## APCI vs. Linde MCHE comparison (`lng_design/mche_vendor_selection.py`)

A structured, factor-by-factor comparison (exchanger technology, number
of refrigeration cycles, proven capacity track record) rather than a
forced single recommendation - unlike `process_selection.py`'s C3MR/DMR/
AP-X screening, the published APCI-vs-Linde comparisons don't reduce to
one clean decision variable. Full citations in the module's docstring.

## Three-loop cascade (`lng_design/cascade_loops.py`)

Models the structural pattern behind Linde's MFC process: a PMR
(pre-cooling mixed refrigerant, or pure propane by default) loop
condensing at ambient, and a Refrigerant/LRC loop that condenses against
the PMR loop's cold duty rather than ambient directly - the defining
"cascade" link, where each cycle pre-cools the next one down the
temperature ladder. Rigorous CoolProp mixture flashes throughout
(`AbstractState` with `QT_INPUTS`/`PSmass_INPUTS`), with an enforced MITA
between the LRC condenser and PMR evaporator (heat must actually flow
from warmer to colder - see [docs/VALIDATION.md](VALIDATION.md) for a
case this caught before it shipped). Also demonstrates the concrete
mechanism behind DMR's reported precool advantage over pure propane: a
heavier mixed-refrigerant blend (e.g. ethane/propane) can evaporate
colder than propane's ~-42°C atmospheric-pressure floor while still
condensing at ambient - verified empirically, not asserted.

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
