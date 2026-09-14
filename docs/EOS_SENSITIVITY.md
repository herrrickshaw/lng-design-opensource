# Equation-of-state sensitivity: HEOS vs. Peng-Robinson vs. SRK

This package uses CoolProp's **HEOS** backend throughout - a
multi-parameter reference equation of state (Helmholtz-energy
formulation), not a cubic EOS. This page answers a natural question: how
would results change if the tool instead used **Peng-Robinson (PR)** or
**Soave-Redlich-Kwong (SRK)** - the two cubic equations of state most
commonly offered as defaults in commercial process simulators? Both PR
and SRK are available as alternative CoolProp backends, which made a
direct, reproducible comparison possible rather than a qualitative
guess.

## Warm gas compression (the GPSA validation case)

Reusing the exact published worked example from
[docs/VALIDATION.md](VALIDATION.md) (5/80/15 mol% ethane/propane/
n-butane, 40°C, 2.068→6.89 bara):

| Backend | Z_avg | Polytropic head | Power | T_out |
|---|---:|---:|---:|---:|
| Published (GPSA) | 0.956 | 71,971 J/kg | 3,533.1 kW | 99.9°C |
| **HEOS** (this package) | 0.956 | 72,232 J/kg | 3,545.9 kW | 102.9°C |
| PR | 0.952 | 71,877 J/kg | 3,528.4 kW | 102.3°C |
| SRK | 0.956 | 72,198 J/kg | 3,544.2 kW | 102.4°C |

**PR vs. HEOS: head/power differ by only 0.49%; SRK vs. HEOS: 0.05%.**
For warm, moderate-pressure gas compression - the regime the GPSA method
itself was built for - all three equations of state agree closely with
each other and with the published reference. Switching to PR or SRK here
would not meaningfully change a compressor sizing result.

## Cryogenic two-phase flash (the end-flash case)

Reusing `end_flash.py`'s worked example (90/6/2/2 mol% methane/ethane/
propane/nitrogen, 115 K / 4.5 bara letting down to 1.10 bara):

| Backend | Molar vapor fraction | Flash temperature |
|---|---:|---:|
| **HEOS** (this package) | 4.03% | 110.09 K |
| PR | 3.39% | 110.63 K |
| SRK | 3.34% | 110.89 K |

**PR vs. HEOS: -16% relative; SRK vs. HEOS: -17% relative.** This is a
meaningfully different design number: a flash-gas/BOG compressor sized
from the PR or SRK result would come out roughly one-sixth smaller than
one sized from HEOS. Cryogenic vapor-liquid equilibrium involving light
components (nitrogen) partitioning against a heavy hydrocarbon-dominated
liquid is exactly the regime where cubic equations of state are known to
be less accurate than a multi-parameter reference EOS - this empirical
gap is consistent with that general pattern, not a surprise specific to
this tool.

## A practical software limitation, not just accuracy

CoolProp's PR/SRK backends only support a narrower set of input-pair
combinations than HEOS. In particular, a pressure-entropy flash
(`PSmass_INPUTS`) - needed for the isentropic-compression step in
`precool.py`'s propane refrigeration cycle - raised `ValueError: type not
set` on both the PR and SRK backends in the CoolProp version used here,
while working directly on HEOS. This means switching this package's
refrigeration-cycle module to a cubic-EOS backend isn't just a smaller
accuracy question - it would require reworking that calculation to avoid
the unsupported input pair entirely.

## Conclusion

HEOS was already the right choice on accuracy grounds for a package whose
core value is the cryogenic sections (end-flash, MCHE, precool cycle) -
exactly where this comparison shows cubic EOS diverge the most from a
reference-quality model. It's also more capable in practice (broader
input-pair support). There's no accuracy or capability case for switching
to PR or Redlich-Kwong-family models in this package; if you need to
cross-check a specific case against a cubic EOS your own project uses
(e.g. to match an existing PRO/II or HYSYS model's property package), the
`AbstractState("PR", ...)` / `AbstractState("SRK", ...)` pattern used to
produce the tables above is the way to do it - see
`lng_design/compressor.py` and `lng_design/end_flash.py` for where the
HEOS calls would need to be swapped.
