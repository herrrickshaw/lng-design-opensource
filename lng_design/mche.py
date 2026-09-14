"""Simplified main cryogenic heat exchanger (MCHE) sizing via composite
curves / pinch analysis.

Method: classic Linnhoff pinch technology (Linnhoff & Hindmarsh, 1983;
standard treatment in Smith, "Chemical Process Design and Integration").
Both streams are represented as piecewise-linear composite curves on a
*shared cumulative-duty axis* (the standard pinch-analysis "problem
table" construction), which lets us:

1. Check the minimum internal temperature approach (MITA) at every point
   along the curve, not just at the terminal temperatures - the classic
   trap in multi-stream cryogenic exchanger design, since an internal
   pinch can hide even when both terminals look fine (this is exactly
   what happens when streams with very different local slopes, e.g. a
   refrigerant changing phase against a single-phase gas, cross the
   exchanger at different rates).
2. Estimate UA by numerically integrating dQ / (T_hot(Q) - T_cold(Q))
   along that same duty axis - the same "problem table" idea used for
   MITA, rather than a coarse single LMTD, so the estimate reflects the
   *local* approach at every point, not just the interval width.

A user-supplied overall U converts UA to area (published brazed-aluminum
plate-fin exchanger U-values for LNG service are commonly cited in the
1500-3500 W/m2-K range depending on stream side and fouling allowance;
override with vendor/literature data for your specific service).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class StreamSegment:
    """A linear T-H segment of a composite stream, already broken into a
    piecewise-linear representation (constant CP within the segment)."""
    T_start_K: float   # temperature at the start of the segment
    T_end_K: float      # temperature at the end of the segment (T_end < T_start for hot streams)
    duty_kW: float       # positive magnitude of heat released (hot) / absorbed (cold)


@dataclass
class CompositeCurveResult:
    min_approach_K: float
    pinch_temperature_K: float
    total_duty_kW: float
    ua_estimate_kW_per_K: float
    area_estimate_m2: float
    interval_report: list[dict] = field(default_factory=list)


def _temperature_at_duty(segments: list[StreamSegment], q_from_hot_start: float):
    """Temperature on a composite curve at cumulative duty q, measured from
    the hottest end of that composite (q=0 at its hottest point). Both hot
    and cold composites are queried at the same q so they can be compared
    directly - the shared duty axis is what makes the MITA/UA calculations
    below correct for streams with different local slopes."""
    running = 0.0
    ordered = sorted(segments, key=lambda s: max(s.T_start_K, s.T_end_K), reverse=True)
    for seg in ordered:
        if running + seg.duty_kW >= q_from_hot_start - 1e-9:
            frac = (q_from_hot_start - running) / seg.duty_kW if seg.duty_kW > 0 else 0.0
            frac = min(max(frac, 0.0), 1.0)
            t_hi, t_lo = sorted([seg.T_start_K, seg.T_end_K], reverse=True)
            return t_hi - frac * (t_hi - t_lo)
        running += seg.duty_kW
    return None


def analyze_composite_curves(
    hot_segments: list[StreamSegment],
    cold_segments: list[StreamSegment],
    min_approach_K: float,
    overall_U_W_m2K: float = 2000.0,
    n_samples: int = 400,
) -> CompositeCurveResult:
    """Build hot/cold composite curves on a shared duty axis, check the
    MITA constraint everywhere along it, and estimate UA/area by
    numerically integrating dQ / local-approach over that same axis.

    Raises ValueError if the MITA constraint is violated anywhere, or if
    the two composites don't span the same total duty (unbalanced heat
    exchanger spec - a modeling error, not a sizing result).
    """
    total_hot_duty = sum(s.duty_kW for s in hot_segments)
    total_cold_duty = sum(s.duty_kW for s in cold_segments)
    if abs(total_hot_duty - total_cold_duty) > 1e-6 * max(total_hot_duty, 1.0):
        raise ValueError(
            f"Unbalanced duty: hot streams total {total_hot_duty:.1f} kW, "
            f"cold streams total {total_cold_duty:.1f} kW. Composite curves "
            "must span equal total duty."
        )

    worst_approach = math.inf
    pinch_T = None
    ua_total = 0.0  # kW/K
    interval_report = []

    prev_q = 0.0
    prev_T_hot = _temperature_at_duty(hot_segments, 0.0)
    prev_T_cold = _temperature_at_duty(cold_segments, 0.0)
    prev_approach = prev_T_hot - prev_T_cold
    worst_approach, pinch_T = prev_approach, prev_T_hot

    for i in range(1, n_samples + 1):
        q = total_hot_duty * i / n_samples
        T_hot = _temperature_at_duty(hot_segments, q)
        T_cold = _temperature_at_duty(cold_segments, q)
        approach = T_hot - T_cold

        if approach < worst_approach:
            worst_approach, pinch_T = approach, T_hot

        dQ = q - prev_q
        mean_approach = 0.5 * (approach + prev_approach)
        if mean_approach > 1e-6 and dQ > 0:
            ua_slice = dQ / mean_approach
            ua_total += ua_slice
            interval_report.append({
                "Q_kW": q, "T_hot_K": T_hot, "T_cold_K": T_cold,
                "local_approach_K": approach, "ua_slice_kW_per_K": ua_slice,
            })

        prev_q, prev_T_hot, prev_T_cold, prev_approach = q, T_hot, T_cold, approach

    if worst_approach < min_approach_K - 1e-6:
        raise ValueError(
            f"MITA violated: minimum approach in the network is "
            f"{worst_approach:.2f} K at T~{pinch_T:.1f} K, below the "
            f"required {min_approach_K:.2f} K. Increase refrigerant flow, "
            f"add a refrigeration level, or relax the target duty/temperature."
        )

    return CompositeCurveResult(
        min_approach_K=worst_approach,
        pinch_temperature_K=pinch_T,
        total_duty_kW=total_hot_duty,
        ua_estimate_kW_per_K=ua_total,
        area_estimate_m2=(ua_total * 1000.0) / overall_U_W_m2K,
        interval_report=interval_report,
    )


def classify_mche_type(lng_capacity_mtpa_equivalent: float) -> dict:
    """Rough, illustrative classification of which commercially available
    MCHE technology family a given train scale is typically built with.

    This reflects widely published, general LNG technology comparisons
    (not proprietary vendor data): coil-wound (spiral-wound) exchangers
    dominate large base-load trains, since a single core can be fabricated
    at very large scale; brazed-aluminum plate-fin cores are common for
    smaller/mid-scale and peak-shaving/FLNG service, since core
    fabrication size is more constrained, and multiple cores in parallel
    are used to reach base-load scale. The ~1.5 mtpa/train threshold below
    is an approximate, illustrative dividing line for conceptual screening
    only - actual technology choice depends on licensor, site, and
    commercial factors well beyond capacity alone.
    """
    if lng_capacity_mtpa_equivalent < 1.5:
        return {
            "typical_technology": "brazed-aluminum plate-fin (parallel cores)",
            "note": (
                "Small/mid-scale and peak-shaving/FLNG trains commonly use "
                "multiple parallel brazed-aluminum plate-fin cores rather "
                "than a single large coil-wound unit."
            ),
        }
    return {
        "typical_technology": "coil-wound (spiral-wound)",
        "note": (
            "Large base-load trains commonly use a single coil-wound "
            "(spiral-wound) main cryogenic heat exchanger, which scales to "
            "much larger single-core duties than plate-fin technology."
        ),
    }
