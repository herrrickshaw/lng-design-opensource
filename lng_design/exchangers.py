"""Shell-and-tube heat exchanger conceptual sizing.

Method: standard LMTD/overall-U sizing for required area (any heat
transfer text, e.g. Kern, "Process Heat Transfer"; Sinnott & Towler,
"Chemical Engineering Design"):

    Q = U * A * F * LMTD_counter-current

then estimate the shell diameter needed to fit that area's worth of
tubes, and match to a standard TEMA shell size (see
`equipment_catalog.py`).

**On the shell-diameter estimate**: precise tube-count-per-shell tables
(the Kern/TEMA `Nt = K1*(Ds/do)^n1` correlations) are tabulated by number
of tube passes and layout, and different published sources give
meaningfully different constants depending on edition and layout
assumptions. Rather than reproduce a specific numeric table from memory
without being able to verify it against the exact published source, this
module uses a transparent, independently-checkable alternative: a typical
tube-bundle-to-shell area utilization fraction (0.55-0.65 is a commonly
cited range for a tube bundle within its shell, accounting for
pass-partition lanes, clearance, and baffle cuts - see Sinnott & Towler
for representative bundle layout diagrams). This is a coarser estimate
than a full tube-count table but avoids presenting borrowed numeric
constants as more precise than they can be verified to be. If you have a
specific TEMA tube-count table you trust, override
`bundle_area_utilization` accordingly or substitute your own function.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .equipment_catalog import STANDARD_TEMA_SHELL_OD_MM, match_standard_size


@dataclass
class ExchangerSizingResult:
    duty_kW: float
    lmtd_K: float
    required_area_m2: float
    n_tubes_estimate: int
    required_shell_diameter_m: float
    standard_shell_od_mm: float


def _lmtd_counter_current(T_hot_in: float, T_hot_out: float, T_cold_in: float, T_cold_out: float) -> float:
    dT1 = T_hot_in - T_cold_out
    dT2 = T_hot_out - T_cold_in
    if dT1 <= 0 or dT2 <= 0:
        raise ValueError(
            "Non-physical temperature crossing: both terminal approaches "
            "must be positive for counter-current exchange "
            f"(dT1={dT1:.2f} K, dT2={dT2:.2f} K)"
        )
    if abs(dT1 - dT2) < 1e-6:
        return dT1
    return (dT1 - dT2) / math.log(dT1 / dT2)


def size_shell_and_tube(
    duty_kW: float,
    T_hot_in_K: float,
    T_hot_out_K: float,
    T_cold_in_K: float,
    T_cold_out_K: float,
    overall_U_W_m2K: float,
    lmtd_correction_factor_F: float = 0.9,
    tube_od_m: float = 0.01905,  # 3/4 inch, the most common process tube OD
    tube_length_m: float = 6.1,   # 20 ft, a common standard tube length
    bundle_area_utilization: float = 0.60,
) -> ExchangerSizingResult:
    """Size a shell-and-tube exchanger for a given duty and terminal
    temperatures.

    lmtd_correction_factor_F: 1.0 for true counter-current (e.g. 1-1
    exchangers); 0.8-0.9 is a typical conceptual-design default for a
    1-shell / 2-or-more-tube-pass configuration (Sinnott & Towler, Ch.
    12) - override with an exact F-chart value once the configuration is
    fixed.
    """
    lmtd = _lmtd_counter_current(T_hot_in_K, T_hot_out_K, T_cold_in_K, T_cold_out_K)
    area = (duty_kW * 1000.0) / (overall_U_W_m2K * lmtd_correction_factor_F * lmtd)

    n_tubes = area / (math.pi * tube_od_m * tube_length_m)
    tube_pitch_area = (1.25 * tube_od_m) ** 2 * math.sin(math.radians(60))  # triangular pitch, 1.25x OD spacing
    bundle_area = n_tubes * tube_pitch_area / bundle_area_utilization
    shell_diameter = math.sqrt(4.0 * bundle_area / math.pi)

    standard_shell_od_mm = match_standard_size(shell_diameter * 1000.0, STANDARD_TEMA_SHELL_OD_MM)

    return ExchangerSizingResult(
        duty_kW=duty_kW,
        lmtd_K=lmtd,
        required_area_m2=area,
        n_tubes_estimate=math.ceil(n_tubes),
        required_shell_diameter_m=shell_diameter,
        standard_shell_od_mm=standard_shell_od_mm,
    )
