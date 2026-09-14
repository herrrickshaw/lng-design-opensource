"""LNG carrier berth (jetty) offtake and storage tank sizing.

Two independent, standard public-domain methods:

1. **Berth occupancy / waiting time** - the Erlang C (M/M/c) queueing
   formula (Erlang, 1917; standard in any operations-research text, e.g.
   Hillier & Lieberman, "Introduction to Operations Research" - the same
   mathematics used for call-center/service-counter capacity planning,
   applied here to ship arrivals and berth service). Given a ship arrival
   rate and mean berth service (turnaround) time, it gives the
   probability an arriving ship has to wait and the expected wait.

2. **Storage tank sizing** - a mass-balance approach: continuous
   liquefaction production must be buffered in a storage tank against
   discrete (periodic) ship departures. Required storage bridges the
   average interval between departures plus a contingency allowance for
   weather/queueing delays (both are plant-specific inputs here, not
   assumed) - this is the same reasoning behind the commonly cited
   industry rule of thumb of roughly 1.5-2x a single cargo size for
   terminal storage (see e.g. GIIGNL LNG terminal design guidance), which
   this function's default inputs reproduce as a sanity check rather than
   using as the sizing basis itself.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class BerthQueueingResult:
    offered_load_erlangs: float
    utilization: float
    probability_of_waiting: float
    expected_wait_hours: float
    expected_ships_in_queue: float


def _erlang_c_probability_wait(offered_load_erlangs: float, n_berths: int) -> float:
    """Erlang C formula: probability an arriving ship must wait for a
    berth, given offered load `a` (Erlangs) and `n_berths` servers."""
    a = offered_load_erlangs
    rho = a / n_berths
    if rho >= 1.0:
        raise ValueError(
            f"System is unstable (utilization {rho:.2f} >= 1.0): arrival "
            "rate exceeds total berth service capacity. Add berths or "
            "reduce turnaround time."
        )

    # sum_{k=0}^{n-1} a^k / k!
    partial_sum = sum(a ** k / math.factorial(k) for k in range(n_berths))
    last_term = (a ** n_berths) / (math.factorial(n_berths) * (1.0 - rho))
    return last_term / (partial_sum + last_term)


def berth_queueing_analysis(
    annual_offtake_mtpa: float,
    cargo_size_m3: float,
    lng_density_kg_m3: float,
    berth_service_time_h: float,
    n_berths: int = 1,
) -> BerthQueueingResult:
    """berth_service_time_h: total time a ship occupies the berth,
    including mooring, loading, cooldown/purging, and unmooring - not
    just the loading duration itself.
    """
    cargo_mass_kg = cargo_size_m3 * lng_density_kg_m3
    ships_per_year = (annual_offtake_mtpa * 1e9) / cargo_mass_kg
    arrival_rate_per_h = ships_per_year / (365.25 * 24.0)
    service_rate_per_h = 1.0 / berth_service_time_h

    offered_load = arrival_rate_per_h / service_rate_per_h  # Erlangs
    rho = offered_load / n_berths

    p_wait = _erlang_c_probability_wait(offered_load, n_berths)
    # Standard Erlang-C expected wait: Wq = P(wait) / (c*mu - lambda)
    expected_wait_h = p_wait / (n_berths * service_rate_per_h - arrival_rate_per_h)
    expected_queue_length = arrival_rate_per_h * expected_wait_h  # Little's Law

    return BerthQueueingResult(
        offered_load_erlangs=offered_load,
        utilization=rho,
        probability_of_waiting=p_wait,
        expected_wait_hours=expected_wait_h,
        expected_ships_in_queue=expected_queue_length,
    )


@dataclass
class StorageTankSizingResult:
    required_volume_m3: float
    cargo_equivalent: float


def size_storage_tank(
    production_rate_kg_s: float,
    lng_density_kg_m3: float,
    average_shipping_interval_days: float,
    contingency_days: float = 1.5,
    cargo_size_m3: float | None = None,
) -> StorageTankSizingResult:
    """Required LNG storage volume to bridge continuous production against
    periodic ship departures, plus a contingency allowance for
    weather/queueing delays (feed `contingency_days` from
    `berth_queueing_analysis`'s expected wait, converted to days, plus
    your own weather-downtime allowance).

    cargo_size_m3, if given, is used only to report the result as a
    multiple of a single cargo (a standard cross-check figure) - it does
    not change the sizing itself.
    """
    total_days = average_shipping_interval_days + contingency_days
    volume_m3 = (production_rate_kg_s * 86400.0 * total_days) / lng_density_kg_m3

    return StorageTankSizingResult(
        required_volume_m3=volume_m3,
        cargo_equivalent=(volume_m3 / cargo_size_m3) if cargo_size_m3 else float("nan"),
    )
