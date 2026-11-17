# Examples and entry points

Moved verbatim from the README.

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

[docs/VALIDATION.md](VALIDATION.md) records what was independently
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
