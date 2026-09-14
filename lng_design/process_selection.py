"""LNG liquefaction cycle screening: C3MR vs. DMR vs. AP-X.

A deliberately coarse, illustrative screening heuristic (same spirit as
`mche.classify_mche_type`) grounded in published comparative studies, not
a rigorous techno-economic optimization - real project selection also
weighs capital cost, driver/equipment availability, licensor terms, gas
reserves, and market demand well beyond the two factors modeled here.

**Key published findings this heuristic is built on** (accessed
2026-09-14):

- C3MR (propane-precooled mixed refrigerant, APCI) is capacity-limited to
  roughly 5 mtpa/train by propane compressor and main heat exchanger
  size limits (Technology Review of Natural Gas Liquefaction Processes,
  scialert.net); it is also widely reported as having the highest
  single-point thermodynamic efficiency of the three at its design
  ambient condition.
- DMR (dual mixed refrigerant) replaces the single-component propane
  precooling loop with a second mixed-refrigerant cycle specifically to
  keep compressors near their best efficiency point across a WIDE
  ambient temperature range - it is reported as advantageous both in
  very cold climates (its original design motivation) and, per Oil & Gas
  Journal ("Double mixed refrigerant LNG process provides viable
  alternative for tropical conditions"), in hot/tropical climates, where
  it can give 10-15% higher production capacity than C3MR for the same
  compressor drivers.
- AP-X adds a third (nitrogen-expander) subcooling cycle on top of a
  C3MR-style front end specifically to reach the highest per-train
  capacities (up to ~12 mtpa/train), at a reported thermodynamic
  efficiency penalty relative to C3MR and DMR (one comparative study
  found figure-of-merit values of roughly 50.8% for C3MR, 48.3% for DMR,
  and 42.6% for AP-X - useful as an indicative ordering, not a fixed
  constant across all designs/studies).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CycleSelectionGuidance:
    recommended: str
    rationale: str
    alternatives_considered: list[str]


def compare_liquefaction_cycles(
    target_train_capacity_mtpa: float,
    ambient_temp_swing_K: float,
    c3mr_capacity_ceiling_mtpa: float = 5.0,
    dmr_capacity_ceiling_mtpa: float = 8.0,
    wide_ambient_swing_threshold_K: float = 25.0,
) -> CycleSelectionGuidance:
    """Screening recommendation among C3MR / DMR / AP-X.

    target_train_capacity_mtpa: desired single-train nameplate capacity.
    ambient_temp_swing_K: difference between the site's summer and winter
        (or hot/cold extreme) design ambient temperatures - the wider
        this is, the more DMR's dual-cycle flexibility is worth its
        added complexity relative to C3MR's single-component precool.
    """
    if target_train_capacity_mtpa > dmr_capacity_ceiling_mtpa:
        return CycleSelectionGuidance(
            recommended="AP-X",
            rationale=(
                f"Target train capacity ({target_train_capacity_mtpa:.1f} mtpa) exceeds "
                f"typical C3MR ({c3mr_capacity_ceiling_mtpa:.0f} mtpa) and DMR "
                f"({dmr_capacity_ceiling_mtpa:.0f} mtpa) per-train ceilings; AP-X's third "
                "(nitrogen-expander) subcooling cycle is the technology reported to reach "
                "this scale, at a reported thermodynamic efficiency penalty vs. C3MR/DMR."
            ),
            alternatives_considered=["C3MR", "DMR"],
        )

    if target_train_capacity_mtpa > c3mr_capacity_ceiling_mtpa:
        return CycleSelectionGuidance(
            recommended="DMR",
            rationale=(
                f"Target train capacity ({target_train_capacity_mtpa:.1f} mtpa) exceeds C3MR's "
                f"typical per-train ceiling (~{c3mr_capacity_ceiling_mtpa:.0f} mtpa, propane "
                "compressor/MCHE size limits) but fits within DMR's reported range, without "
                "AP-X's added subcooling cycle and reported efficiency penalty."
            ),
            alternatives_considered=["C3MR", "AP-X"],
        )

    if ambient_temp_swing_K >= wide_ambient_swing_threshold_K:
        return CycleSelectionGuidance(
            recommended="DMR",
            rationale=(
                f"Target capacity fits within C3MR's range, but the site's ambient swing "
                f"({ambient_temp_swing_K:.0f} K) is wide enough that DMR's dual mixed-"
                "refrigerant precooling (replacing C3MR's single-component propane loop) is "
                "reported to keep compressors nearer their best efficiency point across the "
                "full seasonal range - the same reasoning behind DMR's reported use in both "
                "very cold and tropical/hot-climate LNG projects in the literature, rather "
                "than C3MR's single ambient-optimized design point."
            ),
            alternatives_considered=["C3MR"],
        )

    return CycleSelectionGuidance(
        recommended="C3MR",
        rationale=(
            f"Target capacity ({target_train_capacity_mtpa:.1f} mtpa) fits comfortably "
            f"within C3MR's typical range and the site's ambient swing "
            f"({ambient_temp_swing_K:.0f} K) is moderate - C3MR is the most proven, "
            "simplest, and (per comparative studies) generally highest single-point "
            "efficiency of the three at a stable design ambient condition."
        ),
        alternatives_considered=["DMR", "AP-X"],
    )
