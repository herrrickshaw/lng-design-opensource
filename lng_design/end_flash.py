"""Post-MCHE end-flash system sizing.

Subcooled LNG leaving the MCHE is typically let down across a Joule-
Thomson valve (or a hydraulic turbine on larger trains) from the high
liquefaction pressure to the near-atmospheric storage tank pressure. That
pressure drop is isenthalpic (a JT valve does no work; a turbine recovers
some, which is neglected here for a conceptual-design first pass - see
note below), and because the storage pressure sits below the mixture's
bubble point at the upstream temperature, a small vapor fraction flashes
off ("end-flash gas" or "flash gas"). That vapor is normally recompressed
and used as fuel gas, sent to the boil-off gas (BOG) compression system,
or reliquefied - it is not simply vented.

Method: a rigorous isenthalpic (constant-H) two-phase flash using
CoolProp's HEOS mixture equation of state via the low-level
`AbstractState` interface - not a shortcut correlation. This is the same
level of rigor a process simulator's flash unit operation uses.

**Important CoolProp detail** (verified empirically for this module -
see docs/VALIDATION.md): `AbstractState.Q()` for a mixture is a MOLAR
vapor fraction, not a mass fraction. This module always converts to a
mass basis explicitly, using the flashed liquid/vapor mole fractions and
each component's molecular weight - conflating the two is a common and
easy-to-miss error.

**Turbine note**: a hydraulic/cryogenic expander recovers work instead of
destroying it across the pressure drop, which lowers the outlet enthalpy
relative to a JT valve at the same inlet/outlet pressure and therefore
produces LESS flash vapor. This module models the JT-valve (isenthalpic)
case, which is the conservative (higher flash gas) bound; if your train
uses an expander, the real flash fraction will be somewhat lower.
"""
from __future__ import annotations

from dataclasses import dataclass

import CoolProp.CoolProp as CP

# Standard atomic/molecular weights, g/mol - used to convert CoolProp's
# molar vapor quality to a mass basis.
_MW_G_MOL = {
    "Methane": 16.043, "Ethane": 30.070, "Propane": 44.097,
    "n-Butane": 58.123, "i-Butane": 58.123, "Isobutane": 58.123, "Nitrogen": 28.013,
}


@dataclass
class EndFlashResult:
    vapor_mass_flow_kg_s: float
    liquid_mass_flow_kg_s: float
    vapor_mass_fraction: float
    vapor_mole_fraction: float
    flash_temperature_K: float
    vapor_composition_mole_frac: dict[str, float]
    liquid_composition_mole_frac: dict[str, float]


def flash_end_gas(
    composition_mole_frac: dict[str, float],
    inlet_T_K: float,
    inlet_P_Pa: float,
    outlet_P_Pa: float,
    total_mass_flow_kg_s: float,
) -> EndFlashResult:
    """Isenthalpic (JT-valve) flash of LNG from MCHE outlet conditions to
    storage tank pressure."""
    names = list(composition_mole_frac.keys())
    fracs = list(composition_mole_frac.values())
    if abs(sum(fracs) - 1.0) > 1e-6:
        raise ValueError(f"Mole fractions must sum to 1.0, got {sum(fracs)}")
    if outlet_P_Pa >= inlet_P_Pa:
        raise ValueError("outlet_P_Pa must be less than inlet_P_Pa (this is a let-down)")

    fluid_string = "&".join(names)

    upstream = CP.AbstractState("HEOS", fluid_string)
    upstream.set_mole_fractions(fracs)
    upstream.update(CP.PT_INPUTS, inlet_P_Pa, inlet_T_K)
    h_in = upstream.hmass()

    downstream = CP.AbstractState("HEOS", fluid_string)
    downstream.set_mole_fractions(fracs)
    downstream.update(CP.HmassP_INPUTS, h_in, outlet_P_Pa)

    if downstream.phase() not in (CP.iphase_twophase,):
        # Fully liquid (no flash) or fully vapor - report the degenerate
        # case rather than pretending a two-phase split exists.
        is_liquid = downstream.phase() == CP.iphase_liquid
        return EndFlashResult(
            vapor_mass_flow_kg_s=0.0 if is_liquid else total_mass_flow_kg_s,
            liquid_mass_flow_kg_s=total_mass_flow_kg_s if is_liquid else 0.0,
            vapor_mass_fraction=0.0 if is_liquid else 1.0,
            vapor_mole_fraction=0.0 if is_liquid else 1.0,
            flash_temperature_K=downstream.T(),
            vapor_composition_mole_frac={} if is_liquid else dict(zip(names, fracs)),
            liquid_composition_mole_frac=dict(zip(names, fracs)) if is_liquid else {},
        )

    Q_molar = downstream.Q()
    x_liq = downstream.mole_fractions_liquid()
    y_vap = downstream.mole_fractions_vapor()

    try:
        MW_liq = sum(x * _MW_G_MOL[n] for x, n in zip(x_liq, names))
        MW_vap = sum(y * _MW_G_MOL[n] for y, n in zip(y_vap, names))
    except KeyError as e:
        raise ValueError(
            f"Component {e} has no molecular weight on file - add it to "
            "_MW_G_MOL in end_flash.py"
        ) from e

    vapor_mass_fraction = (Q_molar * MW_vap) / (Q_molar * MW_vap + (1.0 - Q_molar) * MW_liq)

    return EndFlashResult(
        vapor_mass_flow_kg_s=vapor_mass_fraction * total_mass_flow_kg_s,
        liquid_mass_flow_kg_s=(1.0 - vapor_mass_fraction) * total_mass_flow_kg_s,
        vapor_mass_fraction=vapor_mass_fraction,
        vapor_mole_fraction=Q_molar,
        flash_temperature_K=downstream.T(),
        vapor_composition_mole_frac=dict(zip(names, y_vap)),
        liquid_composition_mole_frac=dict(zip(names, x_liq)),
    )
