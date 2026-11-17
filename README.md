# LNG Design (open-source)

Conceptual sizing tools for LNG process trains and terminals, for design engineers who want a fast,
transparent, literature-grounded first pass before committing to a licensed process simulator.
It covers the propane pre-cool refrigeration cycle, centrifugal compressor trains, amine acid-gas
absorbers, molecular sieves, the main cryogenic heat exchanger (MCHE) composite-curve / pinch check,
regasification, BOG handling, NGL fractionation and LPG import. Outputs are Python result objects,
a Streamlit app (sizing tables, charts, a process flow diagram and an HMB-style stream table) and
printed worked examples.

> Status: active. Screening-level tool, not a rate-based simulator and not a substitute for review by a
> qualified process engineer. Independent reimplementation of public-domain correlations (GPSA
> Engineering Data Book, Kremser equation, Linnhoff pinch analysis) with CoolProp for real-fluid
> properties; it contains no proprietary vendor or client simulation data.

New here? See [How to use this repo with AI](HOW_TO_USE_WITH_AI.md).

## What it does
- Sizes the pre-cool loop, multistage compressors, amine absorber, sieve beds, separators, shell-and-tube
  exchangers, air coolers and cooling-water systems from cited correlations.
- Runs an MCHE composite-curve / MITA pinch check, a 3-loop cascade model and a rating-mode tube-bundle model.
- Chains modules on one basis through three entry points: `size_liquefaction_train`,
  `size_regasification_terminal` and `size_lpg_import_terminal` (plus `size_refrigerant_supply`).
- Models tank BOG, BOG compressors, recondensers, vaporizers and NGL fractionation with refrigerant make-up.
- Wraps pymoo NSGA-II (`lng_design/optimize.py`) for Pareto trade-offs such as power vs. exergy.
- Serves everything in a 23-tab Streamlit app (`streamlit_app.py`).

## Quick start
```bash
git clone https://github.com/herrrickshaw/lng-design-opensource.git
cd lng-design-opensource
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
streamlit run streamlit_app.py
```
Library use:
```python
from lng_design.liquefaction import LiquefactionBasis, size_liquefaction_train
liq = size_liquefaction_train(LiquefactionBasis(capacity_mtpa=2.0))
print(liq.precool.compressor_power_kW, liq.total_compression_power_kW, liq.notes)
```
Docker: `docker build -t lng-design . && docker run -p 8501:8501 lng-design`. The app needs no external
services or secrets, so it also deploys to Streamlit Community Cloud as is.

## How it works
Each `lng_design/*.py` module is a pure function (or small dataclass pipeline) that takes process
conditions and returns a result dataclass; CoolProp supplies properties and the entry-point modules compose them.

| Stage | Module | Output |
|---|---|---|
| Properties | `properties.py` | `GasMixture` over CoolProp HEOS |
| Unit sizing | `precool.py`, `compressor.py`, `amine_absorber.py`, `molecular_sieve.py`, `vessels.py`, `exchangers.py`, `air_cooler.py`, `water_system.py` | Sized equipment results |
| Pinch / MCHE | `mche.py`, `cascade_loops.py`, `mche_tube_design.py`, `mche_vendor_selection.py` | MITA, pinch, rating |
| Terminals | `tank_bog.py`, `bog_compressor.py`, `regas_terminal.py`, `fractionation.py`, `lpg_terminal.py` | BOG, send-out, columns |
| Entry points | `liquefaction.py`, `regasification.py`, `lpg_terminal.py`, `refrigerant_supply.py` | One design object per plant |
| Presentation | `flowsheet.py`, `streamlit_app.py`, `ui/` | PFD, stream table, tabs |

Conditions needing an engineering decision (unsized subcooling loop, turndown below the compressor's
stable minimum, BOG the recondenser cannot absorb) come back in `.notes` rather than raising, so a design
that fails a check stays visible. The full module table is in [docs/MODULES.md](docs/MODULES.md);
worked examples (`examples/`) are described in [docs/EXAMPLES.md](docs/EXAMPLES.md).

## Repository layout
| Path | Purpose |
|---|---|
| `lng_design/` | Sizing modules (the library) |
| `lng_design/ui/` | Streamlit tab renderers, one `render_*` per tab, grouped by theme |
| `streamlit_app.py` | Page setup and tab wiring |
| `examples/` | Runnable worked examples (GEM project sizing, DMR vs C3MR, LPG terminal, regas + BOG, ...) |
| `tests/` | pytest suite, one file per module (279 tests, about 3 minutes because CoolProp is called heavily) |
| `docs/` | Methodology and citations, validation, EOS sensitivity, vendor reference, module/example reference |

## Data sources
| Source | What is taken | Access route | Licence / caveat |
|---|---|---|---|
| [Global Energy Monitor GGIT](https://globalenergymonitor.org/projects/global-gas-infrastructure-tracker/) | Published train capacities for seven projects in `examples/gem_upcoming_projects_sizing.py` | Transcribed into the script | Capacity and status only; feed composition is assumed, as the script states |
| GPSA Data Book, McCabe/Smith/Harriott, Linnhoff and others | Correlations and coefficients | Cited in each module docstring and [docs/METHODOLOGY.md](docs/METHODOLOGY.md) | Public-domain methods only |
| [CoolProp](http://www.coolprop.org/) | Fluid properties (HEOS) | Python dependency | Results can shift slightly between CoolProp versions |

## Configuration
No environment variables and no secrets. Runtime dependencies are in `requirements.txt` / `pyproject.toml`
(CoolProp, pymoo, scipy, numpy, streamlit, plotly, pandas). The optional `advanced` extra
(`pip install -e ".[advanced]"`) adds pyomo and idaes-pse; see [docs/EXTENDING.md](docs/EXTENDING.md).

## Testing
```bash
pip install -e ".[dev]"
pytest -q
ruff check .
```
Tests validate modules against external references (NIST constants, closed-form limits, a published GPSA
compressor worked example within 0.4% on head and 3.2 C on discharge temperature). Overview in
[docs/TESTS_AND_VALIDATION_OVERVIEW.md](docs/TESTS_AND_VALIDATION_OVERVIEW.md); cross-checks in
[docs/VALIDATION.md](docs/VALIDATION.md).

## Limitations and known issues
- Conceptual / screening level only; validate against a licensed rate-based simulator and vendor data before
  fixing equipment specifications.
- The liquefaction train uses a lumped heat capacity for the NG cooling duty; an independent Peng-Robinson
  check shows this understates the duty, and the corrected value would roughly double the pinned worked-example
  power. It is left unfixed pending an owner decision and recorded as a strict xfail on branch
  `sdlc/test-hardening-2026-10-25`.
- A CoolProp flash can fail at about 85 bar; see [docs/VALIDATION.md](docs/VALIDATION.md).
- The GEM example assumes a generic lean-gas feed because GGIT does not publish composition.

## Related repositories
None required. [docs/EOS_SENSITIVITY.md](docs/EOS_SENSITIVITY.md) compares HEOS, Peng-Robinson and SRK results.

## Licence
MIT, see [LICENSE](LICENSE).
