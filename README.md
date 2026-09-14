# LNG Design (open-source)

Interactive, open-source conceptual sizing tools for LNG process trains —
propane pre-cool refrigeration cycle, centrifugal compressor trains, amine
acid-gas absorbers, and a main cryogenic heat exchanger (MCHE) composite-curve
/ pinch check — built for design engineers who want a fast, transparent,
literature-grounded first pass before committing to a licensed process
simulator.

**[Try the app](#running-the-app)** · **[Methodology & citations](docs/METHODOLOGY.md)**

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
| `lng_design/compressor.py` | Polytropic head/efficiency (GPSA Ch. 13) | Per-stage head, power, discharge temp, pressure ratio |
| `lng_design/amine_absorber.py` | Souders-Brown flooding + Kremser equation | Column diameter, theoretical stages, packed height |
| `lng_design/mche.py` | Composite-curve / MITA pinch analysis | Minimum approach, pinch location, UA/area estimate |
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

No proprietary or client-specific validation data is used anywhere in this
repository or its history — see [docs/METHODOLOGY.md](docs/METHODOLOGY.md)
for the full citation list.

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
