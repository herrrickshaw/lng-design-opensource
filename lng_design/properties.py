"""Thermophysical property helpers built on CoolProp.

CoolProp's HEOS backend supports arbitrary mixtures via a
"Component1[molefrac1]&Component2[molefrac2]&..." string. We use that
directly instead of hand-rolled correlations wherever CoolProp covers the
component, so results are traceable to a peer-reviewed equation of state
rather than to a fitted shortcut.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import CoolProp.CoolProp as CP

R_UNIVERSAL = 8.314462618  # J/mol-K


@dataclass
class GasMixture:
    """A CoolProp HEOS mixture, keyed by CAS-friendly CoolProp fluid names.

    Example
    -------
    >>> ng = GasMixture({"Methane": 0.88, "Ethane": 0.06, "Propane": 0.03,
    ...                   "n-Butane": 0.01, "Nitrogen": 0.02})
    >>> ng.molecular_weight()  # g/mol
    """

    composition: dict[str, float]  # component -> mole fraction (sums to 1)

    def __post_init__(self) -> None:
        total = sum(self.composition.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Mole fractions must sum to 1.0, got {total}")

    def _heos_string(self) -> str:
        parts = [f"{name}[{frac}]" for name, frac in self.composition.items()]
        return "&".join(parts)

    def molecular_weight(self) -> float:
        """g/mol"""
        names = "&".join(self.composition.keys())
        fracs = list(self.composition.values())
        return CP.PropsSI("M", self._heos_string()) * 1000.0

    def prop(self, output: str, T: float, P: float) -> float:
        """Generic CoolProp state lookup at (T [K], P [Pa]) for the mixture.

        output: any CoolProp output key, e.g. 'H' (J/kg), 'S' (J/kg-K),
        'D' (kg/m3), 'Z' (compressibility factor), 'Cpmass', 'Cvmass'.
        """
        if output == "Q" or P < self._dense_pressure_Pa():
            return CP.PropsSI(output, "T", T, "P", P, self._heos_string())
        # Above every component's critical pressure (x1.3, the same rule
        # regas_terminal._dense_pressure_Pa validates) the mixture is a single
        # dense phase. CoolProp's unconstrained HEOS (T, P) mixture flash can
        # silently return a spurious root there (e.g. 152 kg/m3 instead of
        # ~426 for LNG at 90 bar / 150 K), so impose the phase.
        AS = CP.AbstractState("HEOS", "&".join(self.composition))
        AS.set_mole_fractions(list(self.composition.values()))
        AS.specify_phase(CP.iphase_supercritical)
        AS.update(CP.PT_INPUTS, P, T)
        value = AS.keyed_output(CP.get_parameter_index(output))
        if value != value:  # NaN: some transport models do not evaluate in imposed-phase mode
            return CP.PropsSI(output, "T", T, "P", P, self._heos_string())
        return value

    def _dense_pressure_Pa(self) -> float:
        return 1.3 * max(CP.PropsSI("Pcrit", name) for name in self.composition)

    def cp_over_cv(self, T: float, P: float) -> float:
        cp = self.prop("Cpmass", T, P)
        cv = self.prop("Cvmass", T, P)
        return cp / cv

    def compressibility(self, T: float, P: float) -> float:
        return self.prop("Z", T, P)

    def density(self, T: float, P: float) -> float:
        return self.prop("Dmass", T, P)

    def enthalpy(self, T: float, P: float) -> float:
        return self.prop("Hmass", T, P)

    def viscosity(self, T: float, P: float) -> float:
        """Dynamic viscosity, Pa-s."""
        return self.prop("V", T, P)

    def thermal_conductivity(self, T: float, P: float) -> float:
        """Thermal conductivity, W/m-K."""
        return self.prop("L", T, P)

    def specific_heat(self, T: float, P: float) -> float:
        """Isobaric specific heat, J/kg-K."""
        return self.prop("Cpmass", T, P)

    def vapor_quality_molar(self, T: float, P: float) -> float | None:
        """Molar vapor fraction (CoolProp's mixture Q is MOLAR, not mass -
        see docs/VALIDATION.md / end_flash.py for why that distinction
        matters). Returns None if the state is single-phase at (T, P)
        rather than raising, since callers scanning across a phase
        transition need to detect "not in the two-phase region" as a
        normal outcome, not an error."""
        try:
            return self.prop("Q", T, P)
        except ValueError:
            return None


def pure_fluid_prop(fluid: str, output: str, **state) -> float:
    """Thin wrapper for CP.PropsSI on a pure fluid, keyword state pairs.

    e.g. pure_fluid_prop('Propane', 'T', P=101325, Q=0)
    """
    (k1, v1), (k2, v2) = list(state.items())
    return CP.PropsSI(output, k1, v1, k2, v2, fluid)
