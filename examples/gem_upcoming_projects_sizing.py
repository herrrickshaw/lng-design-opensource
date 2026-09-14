"""Size key equipment for a sample of major upcoming (proposed / under-
construction) global LNG liquefaction trains, using published capacity
data from the Global Energy Monitor Global Gas Infrastructure Tracker
(GGIT) - https://globalenergymonitor.org/projects/global-gas-infrastructure-tracker/,
individual project pages at gem.wiki (accessed 2026-09-14).

GGIT publishes train capacity (mtpa) and status but not feed-gas
composition, train-level P&IDs, or thermodynamic conditions - those are
proprietary to each project. This script therefore makes the same
conceptual-design assumption used throughout this package: a generic
lean natural gas feed (85% methane / 8% ethane / 4% propane / 3%
nitrogen), ambient conditions typical of each project's climate, and a
feed-to-LNG mass ratio of ~1.0 (i.e. treats each train's *annual LNG
capacity* as approximately equal to its feed gas rate for sizing
purposes - a reasonable first-pass approximation since NGL/impurity
removal is a small fraction of total mass for a lean feed).

Run: python examples/gem_upcoming_projects_sizing.py
"""
from __future__ import annotations

from dataclasses import dataclass

from lng_design.compressor import size_multistage
from lng_design.precool import optimal_evap_temperature
from lng_design.properties import GasMixture

MTPA_TO_KG_S = 1.0e9 / (365.25 * 24 * 3600)  # 1 million tonnes/yr -> kg/s


@dataclass
class Project:
    name: str
    country: str
    train: str
    capacity_mtpa: float
    status: str
    ambient_T_C: float  # typical high ambient for the project's climate
    source: str


PROJECTS = [
    Project("Qatar North Field East", "Qatar", "T1-4 (avg/train)", 8.0,
            "construction", 35.0,
            "gem.wiki/Qatar_North_Field_LNG_Terminal"),
    Project("Plaquemines LNG Expansion", "USA", "T37-60 (avg/train)", 24.8 / 24,
            "proposed", 32.0,
            "gem.wiki/Plaquemines_LNG_Terminal"),
    Project("Rio Grande LNG Phase 2", "USA", "T4", 6.0,
            "construction", 33.0,
            "gem.wiki/Rio_Grande_LNG_Terminal"),
    Project("LNG Canada Phase 2", "Canada", "T3-4 (avg/train)", 7.0,
            "proposed", 25.0,
            "gem.wiki/LNG_Canada_Terminal"),
    Project("Golden Pass LNG", "USA", "T1", 5.2,
            "construction", 33.0,
            "gem.wiki/Golden_Pass_LNG_Terminal"),
    Project("Papua LNG", "Papua New Guinea", "T1", 1.4,
            "proposed", 30.0,
            "gem.wiki/Papua_LNG_Terminal"),
    Project("Arctic LNG 2", "Russia", "T3", 6.6,
            "construction", 15.0,
            "gem.wiki/Arctic_LNG_2_Terminal"),
]

GAS = GasMixture({"Methane": 0.85, "Ethane": 0.08, "Propane": 0.04, "Nitrogen": 0.03})


def main() -> None:
    header = (
        f"{'Project':30s} {'Train':16s} {'mtpa/train':>10s} "
        f"{'Feed kg/s':>10s} {'Precool kW':>11s} {'Comp. kW':>10s}"
    )
    print(header)
    print("-" * len(header))

    for p in PROJECTS:
        feed_kg_s = p.capacity_mtpa * MTPA_TO_KG_S
        # Precool duty: cool feed from ambient to a representative -30 C
        # ahead of the cryogenic section (typical C3-stage exit target for
        # a C3MR-style process); NG cp ~2.3 kJ/kg-K.
        T_in = p.ambient_T_C + 273.15
        T_out = -30.0 + 273.15
        duty_kW = feed_kg_s * 2.3 * (T_in - T_out)

        precool = optimal_evap_temperature(
            duty_kW, T_cold_end_target_K=T_out, T_cond_K=p.ambient_T_C + 15 + 273.15,
        )

        # Illustrative boil-off / recompression style train: compress the
        # feed-equivalent flow from 5 -> 45 bara across 3 stages, purely to
        # show the sizing pattern at each project's actual scale.
        stages = size_multistage(
            GAS, T_in, 5e5, 45e5, feed_kg_s, n_stages=3, interstage_cooling_to_K=T_in,
        )
        total_comp_kW = sum(s.gas_power_kW for s in stages)

        print(
            f"{p.name:30s} {p.train:16s} {p.capacity_mtpa:10.2f} "
            f"{feed_kg_s:10.1f} {precool.compressor_power_kW:11,.0f} {total_comp_kW:10,.0f}"
        )

    print()
    print("Sources (accessed 2026-09-14):")
    for p in PROJECTS:
        print(f"  - {p.name}: https://www.{p.source}  (status: {p.status})")
    print()
    print(
        "Note: train capacities are published; feed composition, ambient "
        "design conditions, and process configuration are NOT published by "
        "GGIT and are assumed generically here for illustration. Do not use "
        "these numbers for actual project engineering."
    )


if __name__ == "__main__":
    main()
