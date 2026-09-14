"""Plant-wide heating/cooling load summary - the utility-side companion to
a process heat and material balance (HMB).

A standard HMB stream table (the format used in every commercial process
simulator's stream report, and every process design textbook) lists, per
stream: stream number, phase, temperature, pressure, mass/molar flow, and
composition. `HMBStream` captures that same structure so equipment duties
computed elsewhere in this package can be tied back to named process
streams. `DutyItem` + `summarize_loads` then roll individual equipment
duties up into plant-wide heating load, cooling load, and utility (cooling
water / air) demand totals - the numbers that size the utility systems
(`water_system.py`, `air_cooler.py`) rather than the process equipment
itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DutyType(str, Enum):
    HEATING = "heating"
    COOLING = "cooling"


class UtilityMedium(str, Enum):
    COOLING_WATER = "cooling_water"
    AIR = "air"
    HOT_OIL = "hot_oil"
    STEAM = "steam"
    REFRIGERANT = "refrigerant"
    ELECTRIC = "electric"


@dataclass
class HMBStream:
    """One row of a standard heat-and-material-balance stream table."""
    stream_id: str
    description: str
    phase: str            # "V", "L", "VL", "LL", etc. (standard HMB phase code)
    temperature_K: float
    pressure_Pa: float
    mass_flow_kg_s: float
    composition_mass_frac: dict[str, float] = field(default_factory=dict)


@dataclass
class DutyItem:
    equipment_tag: str
    duty_kW: float
    duty_type: DutyType
    medium: UtilityMedium
    stream_in: HMBStream | None = None
    stream_out: HMBStream | None = None


@dataclass
class LoadSummary:
    total_heating_kW: float
    total_cooling_kW: float
    by_medium_kW: dict[str, float]
    items: list[DutyItem]


def summarize_loads(items: list[DutyItem]) -> LoadSummary:
    total_heating = sum(i.duty_kW for i in items if i.duty_type == DutyType.HEATING)
    total_cooling = sum(i.duty_kW for i in items if i.duty_type == DutyType.COOLING)

    by_medium: dict[str, float] = {}
    for i in items:
        by_medium[i.medium.value] = by_medium.get(i.medium.value, 0.0) + i.duty_kW

    return LoadSummary(
        total_heating_kW=total_heating,
        total_cooling_kW=total_cooling,
        by_medium_kW=by_medium,
        items=list(items),
    )
