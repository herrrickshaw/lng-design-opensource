# Test suite and validation overview

Moved verbatim from the README; see also VALIDATION.md.

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
  [docs/VALIDATION.md](VALIDATION.md) for the exact inputs, outputs,
  and why the small remaining gap exists.

No proprietary or client-specific validation data is used anywhere in this
repository or its history — see [docs/METHODOLOGY.md](METHODOLOGY.md)
for the full citation list and [docs/VALIDATION.md](VALIDATION.md)
for external cross-checks against published sources.

[docs/VENDOR_REFERENCE.md](VENDOR_REFERENCE.md) goes one step
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
