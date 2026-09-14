"""Amine acid-gas absorber conceptual sizing (packed column).

Two independent, textbook-standard methods, kept deliberately simple and
auditable rather than a full rate-based simulation:

1. Diameter - Souders-Brown flooding velocity correlation, the same
   approach GPSA Engineering Data Book Ch. 19 ("Hydrocarbon Treating") and
   Kohl & Nielsen ("Gas Purification", Ch. 2) use for a first-pass column
   diameter:
       v_flood = K_SB * sqrt((rho_L - rho_V) / rho_V)
   with K_SB a packing-factor-dependent constant (typical structured
   packing: 0.03-0.05 m/s at the F-factor basis used here); operate at a
   fraction of flood (typically 70-80%) for design margin.

2. Height - Kremser equation for the number of theoretical stages needed
   for a target removal efficiency, converted to packed height via an
   HETP (height equivalent to a theoretical plate) typical of structured
   packing in amine service (Kohl & Nielsen quote 0.4-0.6 m for common
   structured packings in amine treating; user-overridable).

The Kremser equation (McCabe, Smith & Harriott, "Unit Operations of
Chemical Engineering", absorption chapter) for absorption of a dilute
solute with a linear equilibrium line y* = m*x and absorption factor
A = L/(m*V):

    (y_in - y_out) / (y_in - m*x_in) = (A**(N+1) - A) / (A**(N+1) - 1)   [A != 1]

solved here for N given a target fractional removal.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class AbsorberSizingResult:
    diameter_m: float
    cross_section_area_m2: float
    superficial_gas_velocity_m_s: float
    flooding_velocity_m_s: float
    n_theoretical_stages: float
    packed_height_m: float
    absorption_factor: float


def _kremser_stages(
    y_in: float, y_out_target: float, m: float, x_in: float, absorption_factor: float
) -> float:
    """Number of theoretical equilibrium stages for a target outlet
    composition, absorption factor A = L/(m*V). Standard Kremser form."""
    A = absorption_factor
    if A <= 0:
        raise ValueError("absorption_factor (L / (m*V)) must be positive")

    numerator = y_in - m * x_in
    denominator = y_out_target - m * x_in
    if denominator <= 0:
        raise ValueError(
            "y_out_target must be achievable above the equilibrium floor "
            "m*x_in - i.e. y_out_target > m*x_in"
        )
    fraction_remaining = denominator / numerator  # (y_out - m x_in)/(y_in - m x_in)

    if abs(A - 1.0) < 1e-9:
        # Kremser's A -> 1 limit: N = (y_in - y_out)/(y_out - m*x_in)
        return (y_in - y_out_target) / denominator

    # Solve fraction_remaining = (A - 1) / (A**(N+1) - 1) for N
    # => A**(N+1) = 1 + (A - 1) / fraction_remaining
    rhs = 1.0 + (A - 1.0) / fraction_remaining
    if rhs <= 0:
        raise ValueError("Infeasible specification: no finite stage count satisfies it")
    N_plus_1 = math.log(rhs) / math.log(A)
    return N_plus_1 - 1.0


def size_packed_absorber(
    gas_volumetric_flow_m3_s: float,
    gas_density_kg_m3: float,
    liquid_density_kg_m3: float,
    y_in_mole_frac: float,
    y_out_target_mole_frac: float,
    x_in_mole_frac: float,
    equilibrium_slope_m: float,
    liquid_to_gas_molar_ratio: float,
    K_SB: float = 0.04,
    design_fraction_of_flood: float = 0.75,
    hetp_m: float = 0.5,
) -> AbsorberSizingResult:
    """Size a packed amine absorption column.

    Parameters
    ----------
    gas_volumetric_flow_m3_s : actual gas flow at column conditions
    gas_density_kg_m3, liquid_density_kg_m3 : at column conditions
    y_in_mole_frac, y_out_target_mole_frac : acid-gas mole fraction in,
        target out (e.g. CO2 or H2S)
    x_in_mole_frac : acid-gas loading mole fraction in lean amine feed
    equilibrium_slope_m : local slope of the y* = m*x equilibrium line for
        the amine/acid-gas system at absorber conditions (system- and
        loading-dependent; obtain from published VLE data, e.g. Kohl &
        Nielsen appendix correlations, for the specific amine/concentration)
    liquid_to_gas_molar_ratio : L/V used to form absorption factor A = L/(m*V)
    K_SB : Souders-Brown flooding constant (m/s basis), packing-dependent
    design_fraction_of_flood : operate below flood for margin (0-1)
    hetp_m : height equivalent to a theoretical stage for the chosen packing
    """
    v_flood = K_SB * math.sqrt(
        (liquid_density_kg_m3 - gas_density_kg_m3) / gas_density_kg_m3
    )
    v_design = design_fraction_of_flood * v_flood
    area = gas_volumetric_flow_m3_s / v_design
    diameter = math.sqrt(4.0 * area / math.pi)
    v_actual = gas_volumetric_flow_m3_s / area

    A = liquid_to_gas_molar_ratio / equilibrium_slope_m
    N = _kremser_stages(
        y_in_mole_frac, y_out_target_mole_frac, equilibrium_slope_m,
        x_in_mole_frac, A,
    )
    height = N * hetp_m

    return AbsorberSizingResult(
        diameter_m=diameter,
        cross_section_area_m2=area,
        superficial_gas_velocity_m_s=v_actual,
        flooding_velocity_m_s=v_flood,
        n_theoretical_stages=N,
        packed_height_m=height,
        absorption_factor=A,
    )
