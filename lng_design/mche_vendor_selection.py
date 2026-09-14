"""APCI vs. Linde MCHE technology comparison.

Unlike `process_selection.compare_liquefaction_cycles` (where the
literature supports a fairly crisp capacity/climate-based decision rule),
the published comparisons between APCI's and Linde's main cryogenic heat
exchanger technology don't reduce to one clean threshold - they differ
across several independent design dimensions. This module therefore
returns a structured, factor-by-factor comparison rather than forcing a
single recommendation the evidence doesn't actually support; treat it as
an informational screening aid; a real vendor selection also weighs
commercial terms, licensor bundling, fabrication schedule, and site-
specific factors this module doesn't model at all.

**Published basis** (accessed 2026-09-14):

- **APCI** (Air Products & Chemicals Inc.): the C3MR/AP-X processes use a
  single large proprietary spiral-wound heat exchanger (SWHE) per
  refrigeration duty, historically dominating roughly 75% of the global
  natural gas liquefaction market since the late 1970s (multiple
  comparative LNG technology reviews). Proven single-train capacity
  ranges from ~5 mtpa (C3MR) up to ~12 mtpa (AP-X, with a third
  nitrogen-expander subcooling cycle) - see
  `process_selection.compare_liquefaction_cycles`.
- **Linde**: its Mixed Fluid Cascade (MFC) process uses plate-fin heat
  exchangers (PFHE) for natural gas precooling and coil-wound heat
  exchangers (CWHE) for liquefaction/subcooling, across THREE separate
  mixed-refrigerant cycles (vs. APCI's two: precool + one MR liquefaction
  cycle) - reported to improve thermodynamic efficiency and operational
  flexibility via better-matched compressor operating ranges at each
  stage (Linde technical literature; Mixed Fluid Cascade process
  overviews). Linde's LNG track record was historically concentrated in
  small-to-medium scale plants (e.g. Statoil Hammerfest, ~4.3 mtpa), but
  it has since been awarded large-scale projects including a train
  configuration in the same capacity class as this package's own
  published-data example for Arctic LNG 2 (~6.6 mtpa/train - see
  `examples/gem_upcoming_projects_sizing.py`, independently sourced from
  the Global Energy Monitor tracker, not from Linde's own literature).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VendorProfile:
    vendor: str
    process: str
    exchanger_technology: str
    n_refrigeration_cycles: int
    proven_train_capacity_mtpa: str
    notes: str


@dataclass
class MCHEVendorComparison:
    apci: VendorProfile
    linde: VendorProfile
    screening_notes: list[str] = field(default_factory=list)


def compare_mche_vendors(
    target_train_capacity_mtpa: float | None = None,
    values_modularity: bool | None = None,
) -> MCHEVendorComparison:
    """Return a structured APCI-vs-Linde comparison. Optional inputs add a
    couple of contextual screening notes; they don't change the factual
    profiles themselves.
    """
    apci = VendorProfile(
        vendor="APCI (Air Products)",
        process="C3MR / AP-X",
        exchanger_technology="Single large spiral-wound heat exchanger (SWHE) per duty",
        n_refrigeration_cycles=2,
        proven_train_capacity_mtpa="~5 (C3MR) to ~12 (AP-X, 3rd N2-expander cycle)",
        notes=(
            "Historically the dominant licensor (~75% of global liquefaction "
            "capacity since the late 1970s per multiple comparative reviews); "
            "the largest, most-referenced installed base of any MCHE technology."
        ),
    )
    linde = VendorProfile(
        vendor="Linde",
        process="MFC (Mixed Fluid Cascade)",
        exchanger_technology="Plate-fin (precool) + coil-wound heat exchangers (liquefaction/subcooling)",
        n_refrigeration_cycles=3,
        proven_train_capacity_mtpa="Small-to-mid scale historically (e.g. ~4.3 at Hammerfest), now scaling to large trains",
        notes=(
            "Three separate mixed-refrigerant cycles (vs. APCI's two) reported to "
            "better match compressor operating ranges at each temperature level, "
            "improving thermodynamic efficiency and flexibility, at the cost of "
            "more rotating/heat-transfer equipment per train."
        ),
    )

    notes = []
    if target_train_capacity_mtpa is not None:
        if target_train_capacity_mtpa <= 5.0:
            notes.append(
                f"At {target_train_capacity_mtpa:.1f} mtpa, both vendors have proven "
                "references at this scale - technology choice here is likely driven "
                "more by commercial/licensing terms than by a capacity constraint."
            )
        else:
            notes.append(
                f"At {target_train_capacity_mtpa:.1f} mtpa, APCI's AP-X has the longer "
                "proven track record at this scale; confirm Linde's large-train "
                "references are current and applicable before treating it as "
                "equally proven at this capacity."
            )
    if values_modularity is True:
        notes.append(
            "Linde's 3-cycle, multi-exchanger MFC configuration offers more "
            "granular turndown/redundancy options than APCI's 2-cycle design, "
            "at the cost of more equipment to operate and maintain."
        )
    elif values_modularity is False:
        notes.append(
            "APCI's simpler 2-cycle configuration (fewer rotating machines, one "
            "large SWHE) reduces equipment count and interfaces relative to "
            "Linde's 3-cycle MFC, at the cost of the efficiency/flexibility "
            "benefit Linde's extra cycle is reported to provide."
        )

    return MCHEVendorComparison(apci=apci, linde=linde, screening_notes=notes)
