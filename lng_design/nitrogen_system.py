"""Nitrogen supply system sizing: purge demand and continuous blanketing,
matched against a generator capacity (or a liquid-nitrogen vaporizer
duty if the plant is supplied by cryogenic liquid N2 rather than an
on-site PSA/membrane generator).

Method:
- **Purge volume**: the standard "vessel volume exchange" approach used
  throughout process-safety/inerting practice (e.g. NFPA 69 inerting
  guidance) - a vessel is purged with roughly 3-5 exchanges of its free
  volume to bring oxygen concentration down to a safe level before
  hydrocarbon introduction or after maintenance opening. This module
  defaults to 4 exchanges (mid-range) and is fully user-overridable,
  since the exact number depends on target O2 concentration, purge gas
  distribution, and vessel geometry.
- **Blanketing flow**: driven by tank breathing (thermal/pump-out
  in-breathing) - a site- and tank-specific quantity, taken as a direct
  input here (`blanketing_flow_Nm3_h`) rather than derived from an API
  2000-style breathing-rate correlation, since those correlations are
  tank-geometry- and climate-specific enough that reproducing a generic
  numeric version risks being misleadingly precise.
- **Vaporizer duty** (if liquid N2 supply): mass flow x latent heat of
  vaporization, computed rigorously via CoolProp's nitrogen equation of
  state rather than a table lookup.
"""
from __future__ import annotations

from dataclasses import dataclass

import CoolProp.CoolProp as CP


@dataclass
class NitrogenPurgeResult:
    purge_volume_Nm3: float


@dataclass
class NitrogenSupplyResult:
    total_demand_Nm3_h: float
    generator_capacity_Nm3_h: float


@dataclass
class LN2VaporizerResult:
    mass_flow_kg_s: float
    latent_heat_J_kg: float
    vaporizer_duty_kW: float


def size_purge(vessel_free_volume_m3: float, n_volume_exchanges: float = 4.0) -> NitrogenPurgeResult:
    return NitrogenPurgeResult(purge_volume_Nm3=vessel_free_volume_m3 * n_volume_exchanges)


def size_nitrogen_supply(
    blanketing_flow_Nm3_h: float,
    purge_events_per_day: float,
    purge_volume_per_event_Nm3: float,
    design_margin: float = 0.25,
) -> NitrogenSupplyResult:
    purge_demand_Nm3_h = (purge_events_per_day * purge_volume_per_event_Nm3) / 24.0
    total_demand = blanketing_flow_Nm3_h + purge_demand_Nm3_h
    return NitrogenSupplyResult(
        total_demand_Nm3_h=total_demand,
        generator_capacity_Nm3_h=total_demand * (1.0 + design_margin),
    )


def size_ln2_vaporizer(mass_flow_kg_s: float, supply_pressure_Pa: float = 5e5) -> LN2VaporizerResult:
    """Duty to vaporize a liquid-nitrogen supply at the given delivery
    pressure. Uses CoolProp's nitrogen EOS for the latent heat, not a
    fixed table value, so it is consistent across supply pressures."""
    h_liquid = CP.PropsSI("H", "P", supply_pressure_Pa, "Q", 0, "Nitrogen")
    h_vapor = CP.PropsSI("H", "P", supply_pressure_Pa, "Q", 1, "Nitrogen")
    latent_heat = h_vapor - h_liquid
    duty_kW = mass_flow_kg_s * latent_heat / 1000.0
    return LN2VaporizerResult(
        mass_flow_kg_s=mass_flow_kg_s, latent_heat_J_kg=latent_heat, vaporizer_duty_kW=duty_kW,
    )
