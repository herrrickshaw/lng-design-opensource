"""LNG storage tank geometry and boil-off gas (BOG) generation.

Two parts:

1. **Tank geometry** - a full-containment cylindrical tank sized from net
   working volume at a chosen liquid-height-to-diameter ratio. Gives the
   wall/roof/floor areas that drive heat ingress.

2. **BOG generation** - the four independent sources of vapor a terminal's
   BOG system must handle, each computed from an energy or mass balance
   with CoolProp's HEOS mixture equation of state (not a fixed "0.05 %/day"
   rule of thumb - that figure (0.05 % per day is the commonly quoted vendor
   value) is reported as an OUTPUT to compare against,
   see `boil_off_rate_percent_per_day`):

   * **Static heat ingress** through wall, roof and floor,
     Q = sum(U_i * A_i * dT_i), with each U built from explicit insulation
     layers (`InsulationLayer`: thickness / conductivity).
   * **Pump / recirculation heat** - every watt a submerged pump draws and
     does not convert into useful hydraulic work ends up in the LNG.
   * **Unloading**: (a) vapor *displaced* by rising liquid (mass =
     rho_vapor x volumetric receipt rate, less whatever is returned to the
     ship's vapor header) and (b) *flash* of the arriving cargo as it lets
     down to tank pressure (reuses `end_flash.flash_end_gas`, an isenthalpic
     CoolProp flash).
   * **Barometric pressure fall** - if atmospheric pressure drops by dP/dt
     the tank's saturation temperature drops with it, and the sensible heat
     the LNG inventory gives up flashes off vapor:
     m_flash = m_liq * cp * (dT_sat/dP) * dP / h_fg, plus the small
     vapor-space expansion term.

**Latent heat is that of the boil-off, not of the bulk liquid.** LNG boils
off preferentially light: a 1 mol% nitrogen LNG at 1.1 bar has an
equilibrium vapor that is ~25 mol% nitrogen (CoolProp; see
docs/VALIDATION.md). The energy needed per kg of BOG is therefore
h_V(y) - h_L(x) using the equilibrium vapor composition y, and the BOG
composition is returned so the BOG compressor module can size on the real
(nitrogen-rich) gas rather than on LNG composition.

Approximation: for a differential amount evaporating, the enthalpy change
of the composition drift of the remaining liquid is neglected (second
order for the small fractions boiled per day). Heat conduction is 1-D
steady state through the layers; solar loading, thermal bridging at
penetrations and the annular-space convection of a real double-wall tank
are NOT modeled - they are why real guaranteed BOR figures carry a margin
over a bare U*A*dT estimate.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import CoolProp.CoolProp as CP

from .end_flash import flash_end_gas


# ---------------------------------------------------------------------
# Equilibrium helpers
# ---------------------------------------------------------------------

def _state(names: list[str], fracs: list[float]) -> "CP.AbstractState":
    s = CP.AbstractState("HEOS", "&".join(names))
    s.set_mole_fractions(fracs)
    return s


@dataclass
class TankLiquidState:
    """Saturated LNG at tank pressure and the vapor in equilibrium with it."""

    pressure_Pa: float
    temperature_K: float
    liquid_density_kg_m3: float
    vapor_density_kg_m3: float
    liquid_cp_J_kg_K: float
    latent_heat_J_kg: float          # h_V(y) - h_L(x), per kg of BOG
    dTsat_dP_K_per_Pa: float
    bog_mole_fractions: dict[str, float]
    bog_molecular_weight_g_mol: float


def tank_liquid_state(composition: dict[str, float], pressure_Pa: float) -> TankLiquidState:
    """Bubble-point LNG at `pressure_Pa` and its equilibrium boil-off vapor."""
    names = list(composition.keys())
    x = list(composition.values())
    if abs(sum(x) - 1.0) > 1e-6:
        raise ValueError(f"Mole fractions must sum to 1.0, got {sum(x)}")

    liq = _state(names, x)
    liq.update(CP.PQ_INPUTS, pressure_Pa, 0.0)
    T = liq.T()
    h_L = liq.hmass()
    rho_L = liq.rhomass()
    cp_L = liq.cpmass()
    y = list(liq.mole_fractions_vapor())

    # Equilibrium vapor: dew-point state of composition y at the same P.
    vap = _state(names, y)
    vap.update(CP.PQ_INPUTS, pressure_Pa, 1.0)
    h_V = vap.hmass()
    rho_V = vap.rhomass()
    MW_bog = vap.molar_mass() * 1000.0

    # dT_sat/dP by central difference on the bubble-point curve.
    dP = 0.01 * pressure_Pa
    lo = _state(names, x); lo.update(CP.PQ_INPUTS, pressure_Pa - dP, 0.0)
    hi = _state(names, x); hi.update(CP.PQ_INPUTS, pressure_Pa + dP, 0.0)
    dTdP = (hi.T() - lo.T()) / (2.0 * dP)

    return TankLiquidState(
        pressure_Pa=pressure_Pa, temperature_K=T,
        liquid_density_kg_m3=rho_L, vapor_density_kg_m3=rho_V,
        liquid_cp_J_kg_K=cp_L, latent_heat_J_kg=h_V - h_L,
        dTsat_dP_K_per_Pa=dTdP,
        bog_mole_fractions=dict(zip(names, y)),
        bog_molecular_weight_g_mol=MW_bog,
    )


# ---------------------------------------------------------------------
# Geometry and heat ingress
# ---------------------------------------------------------------------

@dataclass
class InsulationLayer:
    name: str
    thickness_m: float
    conductivity_W_mK: float


@dataclass
class TankGeometry:
    net_volume_m3: float
    inner_diameter_m: float
    liquid_height_m: float          # at full net volume
    wall_area_m2: float             # wetted + vapor-space wall, up to roof
    roof_area_m2: float
    floor_area_m2: float
    gross_volume_m3: float


def size_tank_geometry(
    net_volume_m3: float,
    height_to_diameter: float = 0.40,
    vapor_space_height_m: float = 2.0,
) -> TankGeometry:
    """Cylindrical inner tank sized so the liquid column at full net volume
    has H_liquid / D = `height_to_diameter`.

    Large full-containment LNG tanks are squat (H/D well below 1); 0.40
    is an assumed typical aspect for a 100,000-200,000 m3 tank, not taken
    from a specific project - override it with the contractor's geometry.
    Wall height is liquid height plus `vapor_space_height_m` (max liquid level to roof
    knuckle; an assumption - EN 14620 fixes it per design case).
    """
    if net_volume_m3 <= 0 or height_to_diameter <= 0:
        raise ValueError("net_volume_m3 and height_to_diameter must be positive")
    # V = (pi/4) D^2 * (H/D * D) = (pi/4) (H/D) D^3
    D = (net_volume_m3 / (math.pi / 4.0 * height_to_diameter)) ** (1.0 / 3.0)
    H = height_to_diameter * D
    wall_h = H + vapor_space_height_m
    return TankGeometry(
        net_volume_m3=net_volume_m3, inner_diameter_m=D, liquid_height_m=H,
        wall_area_m2=math.pi * D * wall_h,
        roof_area_m2=math.pi / 4.0 * D ** 2,
        floor_area_m2=math.pi / 4.0 * D ** 2,
        gross_volume_m3=math.pi / 4.0 * D ** 2 * wall_h,
    )


def layer_U_W_m2K(layers: list[InsulationLayer], outer_film_W_m2K: float = 10.0) -> float:
    """Overall U from series conduction layers plus an outer film.

    outer_film_W_m2K = 10 W/m2K is an assumed still-to-light-wind outside
    film; insulation dominates, so the exact value barely matters (10 vs
    34 W/m2K moves U by well under 1 %, checked in tests). The cold-side film is neglected
    (liquid/vapor film coefficients are orders of magnitude larger than
    the insulation's conductance).
    """
    if not layers:
        raise ValueError("At least one insulation layer is required")
    R = 1.0 / outer_film_W_m2K + sum(l.thickness_m / l.conductivity_W_mK for l in layers)
    return 1.0 / R


# Default layer stacks. Conductivities are mean-temperature values for
# cryogenic service from public manufacturer/handbook data ranges
# (expanded perlite ~0.04-0.05 W/mK, foam glass ~0.04-0.05, glass wool
# ~0.035-0.045, all at cryogenic mean temperature). Thicknesses are
# illustrative screening values, NOT a vendor design - replace them with
# your tank contractor's actual build-up.
DEFAULT_WALL_LAYERS = [InsulationLayer("expanded perlite (annular)", 1.00, 0.045)]
DEFAULT_ROOF_LAYERS = [InsulationLayer("glass wool on suspended deck", 0.60, 0.040)]
DEFAULT_FLOOR_LAYERS = [InsulationLayer("foam glass base insulation", 0.50, 0.045)]


@dataclass
class HeatIngressResult:
    wall_kW: float
    roof_kW: float
    floor_kW: float
    total_kW: float
    U_wall: float
    U_roof: float
    U_floor: float


def heat_ingress(
    geometry: TankGeometry,
    T_liquid_K: float,
    T_ambient_K: float = 308.15,
    T_ground_K: float = 288.15,
    wall_layers: list[InsulationLayer] | None = None,
    roof_layers: list[InsulationLayer] | None = None,
    floor_layers: list[InsulationLayer] | None = None,
    penetration_allowance_fraction: float = 0.10,
) -> HeatIngressResult:
    """Steady 1-D conduction heat leak into the tank.

    The floor sees ground temperature, wall and roof see ambient.
    `penetration_allowance_fraction` adds a uniform percentage for thermal
    bridges (nozzles, pump columns, roof supports) that the 1-D model
    omits; 10 % is an assumption, not a cited figure.
    """
    Uw = layer_U_W_m2K(wall_layers or DEFAULT_WALL_LAYERS)
    Ur = layer_U_W_m2K(roof_layers or DEFAULT_ROOF_LAYERS)
    Uf = layer_U_W_m2K(floor_layers or DEFAULT_FLOOR_LAYERS)
    k = 1.0 + penetration_allowance_fraction
    wall = Uw * geometry.wall_area_m2 * (T_ambient_K - T_liquid_K) * k / 1000.0
    roof = Ur * geometry.roof_area_m2 * (T_ambient_K - T_liquid_K) * k / 1000.0
    floor = Uf * geometry.floor_area_m2 * (T_ground_K - T_liquid_K) * k / 1000.0
    return HeatIngressResult(wall, roof, floor, wall + roof + floor, Uw, Ur, Uf)


# ---------------------------------------------------------------------
# BOG sources
# ---------------------------------------------------------------------

def pump_heat_kW(
    electrical_input_kW: float,
    hydraulic_power_kW: float,
) -> float:
    """Heat released into the LNG by submerged pumps: everything drawn
    from the supply that does not leave as useful hydraulic (pressure x
    flow) work. Motor and hydraulic losses are both inside the LNG for an
    in-tank pump, so both count."""
    if hydraulic_power_kW > electrical_input_kW:
        raise ValueError("hydraulic power cannot exceed electrical input")
    return electrical_input_kW - hydraulic_power_kW


def barometric_bog_kg_s(
    liquid_state: TankLiquidState,
    liquid_inventory_kg: float,
    vapor_space_volume_m3: float,
    pressure_fall_Pa_per_h: float,
) -> float:
    """BOG from a falling atmospheric (and hence tank) pressure.

    (1) Sensible heat released by cooling the inventory to the lower
        saturation temperature, flashed at the boil-off latent heat.
    (2) Expansion of the vapor space at constant mass.
    A rising pressure gives zero (the tank recondenses; no BOG).
    """
    if pressure_fall_Pa_per_h <= 0:
        return 0.0
    dPdt = pressure_fall_Pa_per_h / 3600.0  # Pa/s
    flash = (liquid_inventory_kg * liquid_state.liquid_cp_J_kg_K
             * liquid_state.dTsat_dP_K_per_Pa * dPdt / liquid_state.latent_heat_J_kg)
    expansion = (vapor_space_volume_m3 * liquid_state.vapor_density_kg_m3
                 * dPdt / liquid_state.pressure_Pa)
    return flash + expansion


@dataclass
class BOGResult:
    """BOG mass flows [kg/s] by source and operating mode."""

    liquid_state: TankLiquidState
    inventory_kg: float
    heat_ingress_kW: float
    pump_heat_kW: float
    static_bog_kg_s: float
    pump_bog_kg_s: float
    barometric_bog_kg_s: float
    displacement_bog_kg_s: float
    flash_bog_kg_s: float
    holding_bog_kg_s: float
    unloading_bog_kg_s: float
    design_bog_kg_s: float
    design_mode: str
    boil_off_rate_percent_per_day: float
    boil_off_rate_static_percent_per_day: float
    bog_composition: dict[str, float] = field(default_factory=dict)

    def as_t_per_day(self, kg_s: float) -> float:
        return kg_s * 86.4


def compute_bog(
    composition: dict[str, float],
    tank_pressure_Pa: float,
    geometry: TankGeometry,
    fill_fraction: float = 0.90,
    n_tanks: int = 1,
    pump_heat_total_kW: float = 0.0,
    barometric_fall_Pa_per_h: float = 0.0,
    unloading_rate_m3_h: float = 0.0,
    vapor_return_fraction: float = 0.0,
    arriving_T_K: float | None = None,
    arriving_P_Pa: float | None = None,
    **heat_kwargs,
) -> BOGResult:
    """Total BOG for `n_tanks` identical tanks, holding and unloading.

    fill_fraction: liquid inventory as a fraction of net volume, used for
    the inventory mass and the vapor-space volume.

    barometric_fall_Pa_per_h: design rate of atmospheric pressure fall.
    Default 0 (excluded) because it is a site/design-basis input - but do
    not leave it at 0 for a real design: at 100 Pa/h (1 mbar/h) the
    barometric term for a 160,000 m3 tank is ~3x the static heat-leak BOG
    (see examples/regas_bog_fractionation_worked_example.py).

    unloading_rate_m3_h: total volumetric LNG receipt across the terminal
    (m3/h). 0 means no ship on berth (holding mode only).

    vapor_return_fraction: fraction of the displaced vapor sent back to the
    ship to replace the liquid it discharges. It leaves the shore BOG
    system, so it reduces what the compressors must take. 0 is the
    conservative (max compressor duty) bound.

    arriving_T_K / arriving_P_Pa: state of LNG at the tank inlet valve,
    upstream of the let-down (P must exceed tank pressure). If given
    and the liquid is warmer than the saturation temperature at tank
    pressure it flashes isenthalpically to tank pressure (CoolProp). If
    None, no flash is assumed (subcooled or exactly saturated receipt).

    heat_kwargs: passed to `heat_ingress` (ambient/ground temperatures,
    insulation layers, penetration allowance).
    """
    if not (0.0 < fill_fraction <= 1.0):
        raise ValueError("fill_fraction must be in (0, 1]")
    if not (0.0 <= vapor_return_fraction <= 1.0):
        raise ValueError("vapor_return_fraction must be in [0, 1]")

    st = tank_liquid_state(composition, tank_pressure_Pa)
    ingress = heat_ingress(geometry, st.temperature_K, **heat_kwargs)

    inv_kg_each = geometry.net_volume_m3 * fill_fraction * st.liquid_density_kg_m3
    inv_kg = inv_kg_each * n_tanks
    vapor_vol = (geometry.gross_volume_m3 - geometry.net_volume_m3 * fill_fraction) * n_tanks

    static = n_tanks * ingress.total_kW * 1000.0 / st.latent_heat_J_kg
    pump = pump_heat_total_kW * 1000.0 / st.latent_heat_J_kg
    baro = barometric_bog_kg_s(st, inv_kg, vapor_vol, barometric_fall_Pa_per_h)
    holding = static + pump + baro

    displaced = 0.0
    flash = 0.0
    if unloading_rate_m3_h > 0:
        displaced = (unloading_rate_m3_h / 3600.0) * st.vapor_density_kg_m3 * (1.0 - vapor_return_fraction)
        if arriving_T_K is not None:
            if arriving_P_Pa is None:
                raise ValueError("arriving_P_Pa is required when arriving_T_K is given")
            if arriving_P_Pa <= tank_pressure_Pa:
                raise ValueError(
                    "arriving_P_Pa must exceed tank pressure: receipt is a let-down "
                    "through the fill valve/nozzle (use the line pressure at the tank inlet)")
            mdot_in = (unloading_rate_m3_h / 3600.0) * st.liquid_density_kg_m3
            fr = flash_end_gas(composition, arriving_T_K, arriving_P_Pa, tank_pressure_Pa, mdot_in)
            flash = fr.vapor_mass_flow_kg_s
    unloading = holding + displaced + flash

    if unloading_rate_m3_h > 0:
        design, mode = unloading, "unloading"
    else:
        design, mode = holding, "holding"

    def bor(kg_s: float) -> float:
        return kg_s * 86400.0 / inv_kg * 100.0

    # Conventional BOR is quoted at FULL tank, static conditions.
    full_mass = geometry.net_volume_m3 * st.liquid_density_kg_m3 * n_tanks
    bor_static_full = static * 86400.0 / full_mass * 100.0

    return BOGResult(
        liquid_state=st, inventory_kg=inv_kg,
        heat_ingress_kW=ingress.total_kW * n_tanks, pump_heat_kW=pump_heat_total_kW,
        static_bog_kg_s=static, pump_bog_kg_s=pump, barometric_bog_kg_s=baro,
        displacement_bog_kg_s=displaced, flash_bog_kg_s=flash,
        holding_bog_kg_s=holding, unloading_bog_kg_s=unloading,
        design_bog_kg_s=design, design_mode=mode,
        boil_off_rate_percent_per_day=bor(holding),
        boil_off_rate_static_percent_per_day=bor_static_full,
        bog_composition=st.bog_mole_fractions,
    )
