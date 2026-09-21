# LNG Design (open-source)

Interactive, open-source conceptual sizing tools for LNG process trains —
propane pre-cool refrigeration cycle, centrifugal compressor trains, amine
acid-gas absorbers, and a main cryogenic heat exchanger (MCHE) composite-curve
/ pinch check — built for design engineers who want a fast, transparent,
literature-grounded first pass before committing to a licensed process
simulator.

**[Try the app](#running-the-app)** · **[Methodology & citations](docs/METHODOLOGY.md)** · **[External validation](docs/VALIDATION.md)** · **[EOS sensitivity: HEOS vs. PR vs. SRK](docs/EOS_SENSITIVITY.md)** · **[Vendor reference](docs/VENDOR_REFERENCE.md)**

## What this is (and isn't)

This is an **independent reimplementation using public-domain chemical
engineering correlations** — the GPSA Engineering Data Book, the Kremser
equation (McCabe/Smith/Harriott), and Linnhoff pinch/composite-curve
analysis — combined with [CoolProp](http://www.coolprop.org/) for real
fluid thermodynamics (not simplified charts). It does **not** contain, was
not derived from, and does not reproduce any proprietary vendor simulator
output, client project data, or third-party confidential engineering
figures of any kind. Every numeric method is cited to a public source in
each module's docstring and in [docs/METHODOLOGY.md](docs/METHODOLOGY.md).

It is a **conceptual/screening-level tool**, not a rate-based process
simulator. It is meant to give engineers a fast, auditable estimate — and a
starting point for a real simulation in AVEVA PRO/II, Aspen HYSYS, UniSim,
or an open-source equation-oriented tool like
[IDAES-PSE](https://idaes-pse.readthedocs.io/) — not to replace one.

## What it sizes

| Module | Method | Output |
|---|---|---|
| `lng_design/precool.py` | Vapor-compression cycle (propane), CoolProp EOS | Evaporator temp, compressor power, refrigerant flow, COP |
| `lng_design/compressor.py` | Polytropic head/efficiency (GPSA Ch. 13) + frame matching | Per-stage head, power, discharge temp, matched standard frame |
| `lng_design/amine_absorber.py` | Souders-Brown flooding + Kremser equation | Column diameter, theoretical stages, packed height |
| `lng_design/mche.py` | Composite-curve / MITA pinch analysis + tech classification | Minimum approach, pinch location, UA/area, coil-wound vs. plate-fin |
| `lng_design/vessels.py` | Souders-Brown gas capacity + residence time | Vessel diameter (standard size), seam-to-seam height |
| `lng_design/exchangers.py` | LMTD/U-area sizing, TEMA shell matching | Required area, tube count estimate, standard shell OD |
| `lng_design/air_cooler.py` | GPSA Ch. 9 / API 661 fin-fan sizing | Bay count/size, air flow, fan power |
| `lng_design/water_system.py` | CTI cooling-tower water balance | Circulation rate, evaporation, blowdown, total makeup |
| `lng_design/loads.py` | Utility duty aggregation (HMB-stream-table style) | Plant-wide heating/cooling load by utility medium |
| `lng_design/equipment_catalog.py` | Standard-variant catalogs + matcher | Vessel/shell/bay/frame standard sizes for every module above |
| `lng_design/end_flash.py` | Isenthalpic 2-phase mixture flash (CoolProp) | Flash gas / LNG split, flash composition, flash temperature |
| `lng_design/refrigerant_makeup.py` | Charge + reserve, max-fill vessel sizing | Refrigerant storage vessel diameter, length, volume |
| `lng_design/berth.py` | Mass-balance storage + Erlang-C (M/M/c) queueing | Storage tank volume, berth utilization, expected ship wait time |
| `lng_design/air_supply.py` | ISA/GPSA instrument-air demand aggregation | Air demand, compressor capacity, receiver volume |
| `lng_design/nitrogen_system.py` | Vessel-volume-exchange purge + blanketing | Purge volume, N2 generator capacity, LN2 vaporizer duty |
| `lng_design/process_selection.py` | Literature-grounded cycle screening | C3MR vs. DMR vs. AP-X recommendation + rationale |
| `lng_design/mche_vendor_selection.py` | Literature-grounded vendor comparison | APCI vs. Linde structured comparison |
| `lng_design/molecular_sieve.py` | GPSA Ch. 20 adsorber sizing | Bed diameter/height, number of beds, regen heater duty |
| `lng_design/cascade_loops.py` | 3-loop cascade, real CoolProp mixture flashes | NG/LRC/PMR duties, compressor power, DMR-vs-C3 precool comparison |
| `lng_design/mche_tube_design.py` | Dittus-Boelter/Shah/falling-film local HTCs, RATING (not sizing) | Achievable NG rundown for a fixed tube bundle, area/MITA-limited |
| `lng_design/liquefaction.py` | **Entry point.** Chains inlet separator, amine, sieve, trim cooler, C3 precool, LRC/MCHE pinch, end-flash, storage, refrigerant storage - and optional NGL fractionation + make-up MR - on one basis | `LiquefactionDesign`: every vessel/exchanger/loop result, total compression power, disclosed scope notes |
| `lng_design/regasification.py` | **Entry point.** Chains tank BOG, BOG compressors, send-out pumps/ORV/SCV, recondenser at full and turndown send-out, HP BOG route | `RegasificationDesign`: BOG by mode, machine counts and power, vaporizer duty, recondenser limits, decision notes |
| `lng_design/lpg_terminal.py` | **Entry point.** Fully-refrigerated LPG import: storage mass balance, tank BOG, compress-condense-return re-liquefaction (flash penalty, optional sub-cooling), berth queueing, liquid send-out pump + heater | `LPGTerminalDesign`: tanks, BOG by source, flash fraction / recycle factor, compressor power, heater duty, disclosed notes |
| `lng_design/regas_terminal.py` | CoolProp pump/vaporizer duties, ORV seawater balance, SCV fuel, BOG recondenser enthalpy balance | LP/HP pump power, vaporizer duty, seawater flow, unit counts, fuel gas, LNG/BOG ratio |
| `lng_design/tank_bog.py` | Tank geometry, layered-insulation heat ingress, equilibrium-vapor latent heat, unloading displacement + flash, barometric flash | Tank D/H/areas, BOG by source and mode (t/h), BOR %/day, nitrogen-rich BOG composition |
| `lng_design/bog_compressor.py` | Polytropic head on the real cryogenic BOG, stage count from max ratio, redundancy, turndown check | Stages, shaft power per machine, discharge T, frame/machine type, turndown fraction |
| `lng_design/fractionation.py` | Fenske-Underwood-Gilliland (Molokanov) + Kirkbride + O'Connell with CoolProp K-values, Souders-Brown hydraulics | Min/actual stages, reflux, feed tray, diameter, height, condenser/reboiler duty, condenser service |
| `lng_design/refrigerant_supply.py` | **Entry point.** Refrigerant demand by component, bullet storage at 2.5-3x demand (ethane stored cold - it is supercritical at ambient), and an ethane/propane/butane fractionation train scaled to fill it | `RefrigerantSupplyDesign`: storage per component, feed scale, product coverage and fill time vs spec |
| `lng_design/refrigerant_generation.py` | Spec checks, non-negative least-squares MR blending, make-up rate | Pass/fail per spec, source flows per kmol MR, make-up kmol/h |
| `lng_design/flowsheet.py` | Graphviz PFD + HMB-style stream table | Interactive process flow diagram tying every module together |
| `lng_design/optimize.py` | NSGA-II (via [pymoo](https://pymoo.org/)) | Pareto front for any of the above (e.g. power vs. exergy) |

## Running the app

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Engineers enter feed conditions (gas composition, flow, temperatures,
pressures) in each tab's form and get sizing results and a Pareto-optimal
evaporator temperature, compressor power breakdown by stage, absorber
diameter/height, and a pinch-violation check — instantly, in the browser.

### Deploying it for a team

The app is a single `streamlit_app.py` with no external services or
secrets, so it deploys as-is to [Streamlit Community
Cloud](https://streamlit.io/cloud) (free) by pointing it at this repo, or
to any container host via:

```bash
docker build -t lng-design .   # see Dockerfile
docker run -p 8501:8501 lng-design
```

## Example: sizing real upcoming projects

`examples/gem_upcoming_projects_sizing.py` runs published train capacities
for seven major proposed/under-construction LNG liquefaction projects
(Qatar North Field, Plaquemines, Rio Grande, LNG Canada, Golden Pass,
Papua LNG, Arctic LNG 2) — sourced from the [Global Energy Monitor Global
Gas Infrastructure Tracker](https://globalenergymonitor.org/projects/global-gas-infrastructure-tracker/)
— through the precool and compressor modules, purely to demonstrate the
tool at real-world scale:

```bash
python examples/gem_upcoming_projects_sizing.py
```

GGIT publishes train capacity and status, not feed composition or process
conditions, so the script assumes a generic lean-gas feed for illustration
— see the script's docstring and printed sources for exactly what's
published data vs. assumption.

## Two design entry points: liquefaction and regasification

The modules above can be used one by one, or through two entry points that
compose them on a single consistent basis and return one result object
each (defaults reproduce the worked examples):

```python
from lng_design.liquefaction import LiquefactionBasis, size_liquefaction_train
from lng_design.regasification import RegasificationBasis, size_regasification_terminal

liq = size_liquefaction_train(LiquefactionBasis(capacity_mtpa=2.0))
print(liq.precool.compressor_power_kW, liq.total_compression_power_kW, liq.notes)

regas = size_regasification_terminal(RegasificationBasis(sendout_mtpa=5.0, n_tanks=2))
print(regas.bog_design.design_bog_kg_s, regas.train.duty_kW, regas.notes)
```

Liquefaction can also fractionate an NGL stream and blend its ethane and
propane distillates into make-up mixed refrigerant (pass
`ngl_feed_kmol_h`, `fractionation_specs`, `mr_target`). Conditions that need
a decision - the unsized subcooling loop, holding-mode turndown below the
compressor's stable minimum, BOG that the recondenser cannot absorb at low
send-out - come back in `.notes` instead of being raised, so a design that
fails a check is still visible in full.

## Example: refrigerant storage and supply

`examples/refrigerant_supply_worked_example.py` totals the refrigerant
demand of the propane precool loop and a mixed-refrigerant loop, sizes
storage for each liquid component at 2.5 to 3 times that demand, and sizes a
deethanizer / depropanizer / debutanizer train to fill it with ethane,
propane and butane within a chosen fill time. Also available from
`size_liquefaction_train(LiquefactionBasis(include_refrigerant_supply=True))`
and the app's "Refrigerant Supply" tab.

```bash
python examples/refrigerant_supply_worked_example.py
```

## Example: LPG import terminal

`examples/lpg_import_terminal_worked_example.py` sizes a 1 mtpa
fully-refrigerated propane/butane import terminal
(`lng_design/lpg_terminal.py`): storage, BOG by source, the BOG
re-liquefaction loop, berth, and the liquid send-out pump and heater. The
point of the example is what differs from LNG: condensed BOG let down to
the -40 C tank flashes about half its mass (so the compressors handle ~2x
the BOG, and refrigerated sub-cooling to 10 C cuts their power by about a
third), and the send-out is a warmed liquid rather than a vaporized gas.

```bash
python examples/lpg_import_terminal_worked_example.py
```

## Example: regas terminal, BOG and refrigerant generation

`examples/regas_bog_fractionation_worked_example.py` runs a 5 mtpa
terminal on one consistent basis: 2 x 160,000 m3 tanks and their BOG by
source (heat ingress, pump heat, vapor displacement, arrival flash,
barometric fall), the BOG compressors, the recondenser and send-out train
(pumps, ORV/SCV), then a deethanizer/depropanizer/debutanizer train whose
ethane and propane distillates are checked against refrigerant specs and
blended into a mixed refrigerant with its make-up rate:

```bash
python examples/regas_bog_fractionation_worked_example.py
```

[docs/VALIDATION.md](docs/VALIDATION.md) records what was independently
checked and what running it exposed (a CoolProp flash failure at 85 bar,
the barometric BOG term tripling static BOG, a propane spec failure caused
by upstream ethane slip).

## Using it as a library

```python
from lng_design.precool import optimal_evap_temperature
from lng_design.compressor import size_multistage
from lng_design.properties import GasMixture

result = optimal_evap_temperature(duty_kW=5000, T_cold_end_target_K=253.15,
                                   T_cond_K=313.15, mita_K=3.0)
print(result.compressor_power_kW)

gas = GasMixture({"Methane": 0.85, "Ethane": 0.08, "Propane": 0.04, "Nitrogen": 0.03})
stages = size_multistage(gas, T_in_K=303.15, P_in_Pa=5e5, P_out_Pa=45e5,
                          mass_flow_kg_s=50.0, n_stages=3)
```

## Validation

`tests/` validates every module against something *external* to the
module itself:

- **Published physical constants** (propane boiling point, methane
  critical temperature — NIST WebBook values) for the CoolProp property
  layer.
- **Closed-form textbook limits** — the ideal-gas polytropic work formula
  for the compressor module, the Kremser equation's analytic `A → 1` limit
  for the absorber module — computed independently of the module under
  test and compared.
- **Known physical monotonicity** (power rises with pressure ratio, COP
  falls as refrigeration lift increases, deeper removal needs more
  stages) as regression guards.
- **A deliberately constructed internal-pinch case** for the MCHE module,
  confirming it catches a mid-curve MITA violation that a naive
  terminal-only temperature check would miss.

- **A full published numeric worked example** for the compressor module
  (GPSA-sourced gas data, cheresources.com worksheet): reproduces the
  published polytropic head and gas power within 0.4% and discharge
  temperature within 3.2 °C — see
  [docs/VALIDATION.md](docs/VALIDATION.md) for the exact inputs, outputs,
  and why the small remaining gap exists.

No proprietary or client-specific validation data is used anywhere in this
repository or its history — see [docs/METHODOLOGY.md](docs/METHODOLOGY.md)
for the full citation list and [docs/VALIDATION.md](docs/VALIDATION.md)
for external cross-checks against published sources.

[docs/VENDOR_REFERENCE.md](docs/VENDOR_REFERENCE.md) goes one step
further: real, named equipment vendors (valves, heat exchangers,
pressure vessels, and — most directly — centrifugal-compressor OEM
**Baker Hughes**, whose own investor press release confirms a real,
quantified turbomachinery order for "Qatar North Field East": 4
mega-trains, 6 compressors per train — the SAME real project this
repo's own `examples/gem_upcoming_projects_sizing.py` already sizes at
8.0 MTPA/train, independently sourced from the Global Energy Monitor
tracker. Two unrelated real sources, same real project.

```bash
pip install -e ".[dev]"
pytest
```

## Extending toward rigorous optimization

`lng_design/optimize.py` wraps [pymoo](https://pymoo.org/)'s NSGA-II for
multi-objective trade-offs (power vs. exergy, matching the approach used in
published C3MR optimization studies). For equation-oriented, gradient-based
optimization at flowsheet scale, install the `advanced` extra:

```bash
pip install -e ".[advanced]"   # pyomo + idaes-pse
```

and use [IDAES-PSE](https://idaes-pse.readthedocs.io/)'s `PySMO`/`ALAMOPy`/
`OMLT` surrogate-modeling tools to fit fast surrogates around any of this
package's sizing functions for use inside a larger NLP.

## Disclaimer

This is a screening-level engineering tool. It uses simplified,
textbook-standard correlations and is **not a substitute for a licensed,
rate-based process simulator** or for review by a qualified process
engineer before any design decision. Always validate against a rigorous
simulator and vendor-certified equipment data before committing to
equipment specifications.

## License

MIT — see [LICENSE](LICENSE).
