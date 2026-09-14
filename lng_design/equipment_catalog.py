"""Standard/commercially-available equipment variant catalogs, and a
generic "round up to the next real size" matcher.

Every conceptual sizing calculation in this package produces a continuous
number (a diameter, an area, a bay width). In practice a design engineer
then picks the smallest commercially standard item that covers it - a
vessel shell comes in defined diameter increments, a shell-and-tube
exchanger in TEMA standard shell sizes, an air cooler bay in standard
widths, a compressor in a manufacturer's defined frame sizes. This module
holds those standard series (each cited to its source) and one shared
`match_standard_size` helper used by every equipment module.
"""
from __future__ import annotations

from dataclasses import dataclass

# Common process vessel shell diameters, mm - GPSA Engineering Data Book
# Ch. 7 ("Separators") and Campbell, "Gas Conditioning and Processing"
# Vol. 2, both list vessel diameters in these standard increments (roughly
# 6-inch steps for smaller vessels, coarser for larger ones - driven by
# standard head-forming tooling).
STANDARD_VESSEL_DIAMETERS_MM = [
    457, 610, 762, 914, 1067, 1219, 1372, 1524, 1676, 1829, 1981, 2134,
    2286, 2438, 2591, 2743, 2896, 3048, 3200, 3353, 3658, 3962, 4267,
]

# TEMA standard shell outside diameters, mm (converted from the standard
# inch series published by the Tubular Exchanger Manufacturers
# Association and reproduced in every major heat-transfer text, e.g.
# Kern, "Process Heat Transfer"; Sinnott & Towler, "Chemical Engineering
# Design").
STANDARD_TEMA_SHELL_OD_MM = [
    203, 254, 305, 337, 387, 438, 489, 540, 591, 635, 686, 737, 787,
    838, 889, 940, 991, 1067, 1143, 1219, 1372, 1524, 1676, 1829,
]

# API 661 standard air-cooler bay widths, m (API 661 permits 8-16 ft bay
# widths; these are the widths actually offered by fabricators in
# practice - GPSA Engineering Data Book Ch. 9 reproduces the same series).
STANDARD_AIR_COOLER_BAY_WIDTHS_M = [2.4, 3.0, 3.7, 4.3, 4.9]  # 8,10,12,14,16 ft

# Standard air-cooler bay (tube) lengths, m - common fabricator increments.
STANDARD_AIR_COOLER_BAY_LENGTHS_M = [3.0, 4.6, 6.1, 7.6, 9.1, 10.7, 12.2]


@dataclass
class CompressorFrame:
    name: str
    inlet_volume_flow_m3_h_min: float
    inlet_volume_flow_m3_h_max: float
    nominal_polytropic_head_N_m_kg: float
    nominal_polytropic_efficiency: float
    nominal_speed_rpm: float
    nominal_impeller_diameter_mm: float


# Typical centrifugal compressor frame data, reproduced from "Pipeline
# Rules of Thumb Handbook" by E.W. McAllister, 3rd Ed., Gulf Publishing
# Company - the same public source used for this package's compressor
# validation case (see docs/VALIDATION.md). Real vendor frames vary, but
# these are representative, published values for a first-pass frame
# selection at the conceptual stage.
COMPRESSOR_FRAMES = [
    CompressorFrame("A", 1700, 12000, 30000, 0.76, 11000, 406),
    CompressorFrame("B", 10000, 31000, 30000, 0.76, 7700, 584),
    CompressorFrame("C", 22000, 53000, 30000, 0.77, 5900, 762),
    CompressorFrame("D", 39000, 75000, 30000, 0.77, 4900, 914),
    CompressorFrame("E", 55000, 110000, 30000, 0.78, 4000, 1120),
    CompressorFrame("F", 82000, 170000, 30000, 0.78, 3300, 1370),
]


def match_standard_size(required: float, standard_series: list[float]) -> float:
    """Return the smallest value in `standard_series` that is >= required.

    Raises ValueError if `required` exceeds the largest standard size (the
    caller needs a custom/non-standard item or multiple parallel units).
    """
    for size in sorted(standard_series):
        if size >= required:
            return size
    raise ValueError(
        f"Required size {required:.3g} exceeds the largest standard size "
        f"{max(standard_series):.3g} - consider multiple parallel units."
    )


def select_compressor_frame(inlet_volume_flow_m3_h: float) -> CompressorFrame:
    """Pick the smallest standard frame whose inlet volume flow range
    covers the required flow (GPSA-style frame selection - see
    docs/VALIDATION.md for the worked example this table is validated
    against)."""
    for frame in COMPRESSOR_FRAMES:
        if frame.inlet_volume_flow_m3_h_min <= inlet_volume_flow_m3_h <= frame.inlet_volume_flow_m3_h_max:
            return frame
    if inlet_volume_flow_m3_h < COMPRESSOR_FRAMES[0].inlet_volume_flow_m3_h_min:
        return COMPRESSOR_FRAMES[0]
    if inlet_volume_flow_m3_h > COMPRESSOR_FRAMES[-1].inlet_volume_flow_m3_h_max:
        raise ValueError(
            f"Inlet volume flow {inlet_volume_flow_m3_h:,.0f} m3/h exceeds "
            f"the largest standard frame ({COMPRESSOR_FRAMES[-1].name}, up to "
            f"{COMPRESSOR_FRAMES[-1].inlet_volume_flow_m3_h_max:,.0f} m3/h) - "
            "multiple parallel trains are needed."
        )
    raise AssertionError("unreachable")
