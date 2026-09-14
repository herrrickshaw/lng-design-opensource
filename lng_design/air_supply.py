"""Instrument / plant air system sizing.

Method: aggregate demand from a pneumatic instrument count and an
average per-instrument consumption (a widely used conceptual-design
approach for utility air systems, e.g. as described in ISA and GPSA
utility-system guidance - continuous positioner bleed plus intermittent
valve-stroking demand, both captured in the average-consumption figure
rather than modeled separately at conceptual stage), with a diversity
factor (not every instrument strokes simultaneously) and a design margin
for compressor sizing. Receiver volume is sized to a target number of
minutes of average demand - a common utility-system design heuristic to
limit compressor start/stop cycling, applied here as a simple,
transparent default (`receiver_minutes`) rather than a specific numeric
code citation, since exact multipliers vary by compressor type and
control philosophy; override it with your project's own practice.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AirSupplyResult:
    average_demand_Nm3_h: float
    compressor_capacity_Nm3_h: float
    receiver_volume_m3: float


def size_instrument_air_system(
    n_pneumatic_instruments: int,
    avg_consumption_Nm3_h_per_instrument: float = 0.85,
    diversity_factor: float = 0.6,
    design_margin: float = 0.25,
    receiver_minutes: float = 8.0,
) -> AirSupplyResult:
    """avg_consumption_Nm3_h_per_instrument default (~0.5 SCFM) is a
    typical order-of-magnitude per-instrument figure for a mixed
    population of control valves and positioners; refine with an actual
    instrument count/type breakdown for anything beyond a first pass.
    """
    average_demand = n_pneumatic_instruments * avg_consumption_Nm3_h_per_instrument * diversity_factor
    compressor_capacity = average_demand * (1.0 + design_margin)
    receiver_volume_m3 = (average_demand / 60.0) * receiver_minutes

    return AirSupplyResult(
        average_demand_Nm3_h=average_demand,
        compressor_capacity_Nm3_h=compressor_capacity,
        receiver_volume_m3=receiver_volume_m3,
    )
