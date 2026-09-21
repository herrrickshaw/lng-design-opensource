"""LPG import terminal: refrigerated storage, BOG re-liquefaction, unloading
berth, send-out pumps and heaters, on one basis.

A fully-refrigerated LPG import terminal receives propane / butane (or a
mix) from a gas carrier at close to atmospheric pressure and low
temperature (propane about -42 C, n-butane about -0.5 C), stores it in
atmospheric-pressure tanks, and delivers it warm and pressurized (bullets,
pipeline, truck/rail) through pumps and heaters. Structurally it is the LNG
regasification terminal with three differences that drive the design, and
each is handled explicitly here rather than by reusing LNG numbers:

* **The boil-off is condensed, not burned or exported.** LPG BOG has a
  dew point high enough to condense against cooling water once compressed
  (propane: ~14.7 bar at 45 C), so the standard answer is a
  compress-condense-return loop (`size_bog_reliquefaction`). The catch it
  quantifies: liquid condensed at 45 C and let down to the -40 C tank
  flashes a large fraction (cp x dT / h_fg, roughly half for propane), and
  that flash vapor must be recompressed. Net liquid recovery per pass is
  (1 - f), so the compressors handle BOG / (1 - f), not BOG. Optional
  refrigerated sub-cooling before let-down (`subcool_to_K`) cuts f and the
  compressor load at the price of a sub-cooler duty. It is the same
  thermodynamics as a propane refrigeration cycle whose evaporator is the
  tank (`precool.py`), and the energy balance is reported so that can be
  checked.
* **Send-out is a liquid.** Pumps lift the cold liquid to the delivery
  pressure and a heater brings it to delivery temperature - there is no
  vaporization duty. The heater duty is sensible heat from CoolProp
  enthalpies. Warming -40 C LPG against seawater risks ice on the water
  side, so a glycol-water intermediate loop is flagged when the product
  is colder than 0 C.
* **The tank is much less insulated.** The ambient-to-liquid temperature
  difference is ~80 K instead of ~195 K, so tank heat ingress, boil-off
  rate and insulation thickness are all much smaller than for LNG; the
  default insulation stacks here are correspondingly thinner (assumptions,
  not vendor build-ups).

Reused, not re-derived: tank geometry, layered-insulation heat ingress and
the BOG-by-source accounting (`tank_bog.py`), the polytropic compressor
(`bog_compressor.py`), the cryogenic pump and CoolProp enthalpy guards
(`regas_terminal.py`), the isenthalpic flash (`end_flash.py`), and the
Erlang-C berth model (`berth.py`). Storage volume is a simple mass balance
(`size_import_storage`): one full cargo plus a contingency stock and a
heel, an assumption-driven sizing, not a code-based tank design.

Limits: pure/mixed LPG in CoolProp's HEOS (ethane, propane, isobutane,
n-butane); no propylene, no odorant, no pressure-relief/flare sizing, no
jetty hydraulics, and no economic comparison of fully-refrigerated versus
semi-refrigerated or pressurized storage - although `vapor_pressure_Pa` at
the design ambient temperature gives the number that decides it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import CoolProp.CoolProp as CP
import numpy as np

from .berth import BerthQueueingResult, berth_queueing_analysis
from .bog_compressor import BOGCompressorResult, size_bog_compressor, turndown_check
from .end_flash import flash_end_gas
from .regas_terminal import CP_SEAWATER_J_KG_K, PumpResult, size_lng_pump, vaporizer_duty
from .tank_bog import (
    BOGResult, InsulationLayer, TankGeometry, TankLiquidState, compute_bog,
    size_tank_geometry, tank_liquid_state,
)

# Thinner stacks than the LNG defaults (illustrative screening values).
LPG_WALL_LAYERS = [InsulationLayer("polyurethane/perlite (wall)", 0.30, 0.040)]
LPG_ROOF_LAYERS = [InsulationLayer("glass wool (roof)", 0.30, 0.040)]
LPG_FLOOR_LAYERS = [InsulationLayer("foam glass (floor)", 0.30, 0.045)]


def _lpg_state(comp: dict[str, float]) -> "CP.AbstractState":
    names = [n for n, x in comp.items() if x > 1e-12]
    v = np.array([comp[n] for n in names])
    s = CP.AbstractState("HEOS", "&".join(names))
    s.set_mole_fractions(list(v / v.sum()))
    return s


def vapor_pressure_Pa(composition: dict[str, float], T_K: float) -> float:
    """Bubble-point pressure of the LPG at T_K (its vapor pressure)."""
    s = _lpg_state(composition)
    s.update(CP.QT_INPUTS, 0.0, T_K)
    return s.p()


# ---------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------

@dataclass
class ImportStorageResult:
    net_volume_m3: float
    per_tank_m3: float
    n_tanks: int
    cargo_m3: float
    contingency_m3: float
    heel_m3: float
    cargoes_equivalent: float


def size_import_storage(
    throughput_kg_s: float,
    liquid_density_kg_m3: float,
    cargo_m3: float,
    contingency_days: float = 5.0,
    heel_fraction: float = 0.10,
    n_tanks: int = 2,
) -> ImportStorageResult:
    """Net storage = one cargo + contingency stock (send-out for
    `contingency_days` if the next ship is late) + a heel.

    The tank must be able to take a full cargo while still holding the
    contingency stock, so the two add rather than overlap; the heel
    (`heel_fraction` of the total) is the unusable low-level inventory that
    keeps pumps submerged. contingency_days = 5 and heel 10 % are
    assumptions - weather delay statistics for the actual route replace them.
    """
    if n_tanks < 1:
        raise ValueError("n_tanks must be >= 1")
    if not (0.0 <= heel_fraction < 0.5):
        raise ValueError("heel_fraction must be in [0, 0.5)")
    daily_m3 = throughput_kg_s * 86400.0 / liquid_density_kg_m3
    contingency = daily_m3 * contingency_days
    working = cargo_m3 + contingency
    total = working / (1.0 - heel_fraction)
    return ImportStorageResult(
        net_volume_m3=total, per_tank_m3=total / n_tanks, n_tanks=n_tanks,
        cargo_m3=cargo_m3, contingency_m3=contingency, heel_m3=total - working,
        cargoes_equivalent=total / cargo_m3,
    )


# ---------------------------------------------------------------------
# BOG re-liquefaction
# ---------------------------------------------------------------------

@dataclass
class ReliquefactionResult:
    bog_kg_s: float
    condensing_T_K: float
    condensing_P_Pa: float
    flash_fraction: float
    recycle_factor: float
    compressed_flow_kg_s: float
    compressor: BOGCompressorResult
    heat_load_removed_kW: float
    total_heat_rejection_kW: float
    subcooler_duty_kW: float
    specific_power_kWh_per_t: float
    notes: list[str] = field(default_factory=list)


def size_bog_reliquefaction(
    tank: TankLiquidState,
    bog_kg_s: float,
    condensing_T_K: float = 318.15,
    subcool_to_K: float | None = None,
    suction_superheat_K: float = 10.0,
    interstage_cooling_to_K: float | None = 318.15,
    n_operating: int = 1,
    n_spare: int = 1,
    margin: float = 0.10,
    max_condensing_P_Pa: float = 25e5,
) -> ReliquefactionResult:
    """Compress-condense-return loop for the tank BOG.

    condensing_T_K: 318 K (45 C) = ~35 C cooling water/air plus ~10 K
    approach, an assumption. The condensing pressure is the bubble-point
    pressure of the BOG's own composition at that temperature (CoolProp).

    Liquid leaving the condenser (optionally sub-cooled to `subcool_to_K`
    by refrigeration) is let down isenthalpically to tank pressure; the
    flash fraction f comes from `end_flash.flash_end_gas`. The flash vapor
    rejoins the BOG, so in steady state the compressors handle
    bog / (1 - f). Heat balance: rejected heat = compressor gas power + the
    tank heat load removed (bog x latent heat) [+ sub-cooler duty is on the
    refrigeration side and not counted here].
    """
    bog = {k: v for k, v in tank.bog_mole_fractions.items() if v > 1e-6}
    tot = sum(bog.values())
    bog = {k: v / tot for k, v in bog.items()}

    s = _lpg_state(bog)
    try:
        s.update(CP.QT_INPUTS, 0.0, condensing_T_K)
    except ValueError as e:
        raise ValueError(
            f"BOG cannot be condensed at {condensing_T_K:.1f} K (above its critical "
            "temperature or outside the EOS range)") from e
    p_cond = s.p()
    notes: list[str] = []
    if p_cond > max_condensing_P_Pa:
        notes.append(f"Condensing pressure {p_cond / 1e5:.1f} bar exceeds {max_condensing_P_Pa / 1e5:.0f} bar: "
                     "consider refrigerated condensing or a colder cooling medium.")

    if subcool_to_K is None:
        T_liq = condensing_T_K - 1e-3            # just below the bubble point, compressed liquid
    else:
        if subcool_to_K >= condensing_T_K:
            raise ValueError("subcool_to_K must be below condensing_T_K")
        T_liq = subcool_to_K
    ef = flash_end_gas(bog, T_liq, p_cond, tank.pressure_Pa, 1.0)
    f = ef.vapor_mass_fraction
    if f >= 0.95:
        raise ValueError(f"Flash fraction {f:.2f} - loop cannot recover liquid; sub-cool more")
    recycle = 1.0 / (1.0 - f)
    m_c = bog_kg_s * recycle

    sub_duty = 0.0
    if subcool_to_K is not None:
        h_sat = _lpg_state(bog); h_sat.update(CP.QT_INPUTS, 0.0, condensing_T_K)
        hs = h_sat.hmass()
        h_sub = _lpg_state(bog); h_sub.update(CP.PT_INPUTS, p_cond, subcool_to_K)
        sub_duty = m_c * (hs - h_sub.hmass()) / 1000.0

    comp = size_bog_compressor(
        bog, m_c, suction_P_Pa=tank.pressure_Pa, discharge_P_Pa=p_cond,
        suction_T_K=tank.temperature_K + suction_superheat_K, margin=margin,
        n_operating=n_operating, n_spare=n_spare,
        interstage_cooling_to_K=interstage_cooling_to_K)

    load = bog_kg_s * tank.latent_heat_J_kg / 1000.0                # kW removed at the tank
    # The margin is spare capacity, not duty: divide it out for real power.
    gas_kW = comp.gas_power_kW_per_machine * n_operating / (1.0 + margin)
    shaft_kW = comp.shaft_power_kW_per_machine * n_operating / (1.0 + margin)
    rejection = gas_kW + load
    return ReliquefactionResult(
        bog_kg_s=bog_kg_s, condensing_T_K=condensing_T_K, condensing_P_Pa=p_cond,
        flash_fraction=f, recycle_factor=recycle, compressed_flow_kg_s=m_c, compressor=comp,
        heat_load_removed_kW=load, total_heat_rejection_kW=rejection, subcooler_duty_kW=sub_duty,
        specific_power_kWh_per_t=shaft_kW / (bog_kg_s * 3.6),
        notes=notes,
    )


# ---------------------------------------------------------------------
# Send-out heater
# ---------------------------------------------------------------------

@dataclass
class HeaterResult:
    duty_kW: float
    inlet_T_K: float
    outlet_T_K: float
    medium_flow_t_h: float
    medium_dT_K: float
    note: str


def size_lpg_heater(
    composition: dict[str, float], P_Pa: float, T_in_K: float, T_out_K: float,
    mass_flow_kg_s: float, medium_dT_K: float = 5.0,
    medium_cp_J_kg_K: float = CP_SEAWATER_J_KG_K,
) -> HeaterResult:
    """Sensible-heat duty from CoolProp enthalpies and a warm-water
    flow at `medium_dT_K` temperature drop (seawater cp by default)."""
    duty = vaporizer_duty(composition, P_Pa, T_in_K, T_out_K, mass_flow_kg_s)
    m_med = duty * 1000.0 / (medium_cp_J_kg_K * medium_dT_K)
    note = "OK"
    if T_in_K < 273.15:
        note = (f"Product enters at {T_in_K - 273.15:.0f} C: direct seawater heating risks ice on "
                "the water side - use a glycol-water intermediate loop or a steam/hot-water heater.")
    return HeaterResult(duty_kW=duty, inlet_T_K=T_in_K, outlet_T_K=T_out_K,
                        medium_flow_t_h=m_med * 3.6, medium_dT_K=medium_dT_K, note=note)


# ---------------------------------------------------------------------
# Whole terminal
# ---------------------------------------------------------------------

@dataclass
class LPGTerminalBasis:
    """Defaults: a 1 mtpa commercial-propane terminal (95/5 mol% C3/nC4),
    fed by 84,000 m3 gas carriers. ASSUMED entries are screening values."""

    composition: dict[str, float] = field(default_factory=lambda: {"Propane": 0.95, "n-Butane": 0.05})
    throughput_mtpa: float = 1.0
    cargo_m3: float = 84_000.0
    n_tanks: int = 2
    tank_pressure_Pa: float = 1.10e5
    height_to_diameter: float = 0.50             # ASSUMED
    fill_fraction: float = 0.85
    ambient_T_K: float = 313.15
    ground_T_K: float = 293.15
    contingency_days: float = 5.0                # ASSUMED
    heel_fraction: float = 0.10                  # ASSUMED

    # Unloading / berth
    unloading_rate_m3_h: float = 3000.0          # ASSUMED ship-pump rate
    vapor_return_fraction: float = 0.50          # ASSUMED
    arriving_superheat_K: float = 1.0            # cargo warmer than tank saturation
    arriving_P_Pa: float = 5e5
    berth_overhead_h: float = 12.0               # mooring, arms, documents; ASSUMED
    n_berths: int = 1
    pump_heat_total_kW: float = 60.0             # ASSUMED in-tank pump heat
    barometric_fall_Pa_per_h: float = 100.0      # ASSUMED

    # BOG re-liquefaction
    condensing_T_K: float = 318.15
    subcool_to_K: float | None = None
    n_operating: int = 1
    n_spare: int = 1

    # Send-out
    delivery_pressure_Pa: float = 20e5
    delivery_T_K: float = 278.15
    pump_efficiency: float = 0.70                # ASSUMED
    tank_liquid_head_Pa: float = 1.5e5
    heater_medium_dT_K: float = 5.0


@dataclass
class LPGTerminalDesign:
    basis: LPGTerminalBasis
    throughput_kg_s: float
    tank_state: TankLiquidState
    vapor_pressure_at_ambient_Pa: float
    storage: ImportStorageResult
    tank: TankGeometry
    bog_holding: BOGResult
    bog_design: BOGResult
    reliquefaction: ReliquefactionResult
    holding_fraction_of_machine: float
    berth: BerthQueueingResult
    pump: PumpResult
    heater: HeaterResult
    notes: list[str] = field(default_factory=list)

    @property
    def installed_power_kW(self) -> float:
        return self.pump.shaft_kW + self.reliquefaction.compressor.installed_shaft_power_kW


def size_lpg_import_terminal(basis: LPGTerminalBasis | None = None) -> LPGTerminalDesign:
    b = basis or LPGTerminalBasis()
    notes: list[str] = []
    m = b.throughput_mtpa * 1e9 / (365.25 * 24 * 3600)

    st = tank_liquid_state(b.composition, b.tank_pressure_Pa)
    p_amb = vapor_pressure_Pa(b.composition, b.ambient_T_K)
    storage = size_import_storage(m, st.liquid_density_kg_m3, b.cargo_m3, b.contingency_days,
                                  b.heel_fraction, b.n_tanks)
    geom = size_tank_geometry(storage.per_tank_m3, b.height_to_diameter)

    heat = dict(T_ambient_K=b.ambient_T_K, T_ground_K=b.ground_T_K, wall_layers=LPG_WALL_LAYERS,
                roof_layers=LPG_ROOF_LAYERS, floor_layers=LPG_FLOOR_LAYERS)
    common = dict(n_tanks=b.n_tanks, fill_fraction=b.fill_fraction,
                  pump_heat_total_kW=b.pump_heat_total_kW,
                  barometric_fall_Pa_per_h=b.barometric_fall_Pa_per_h, **heat)
    holding = compute_bog(b.composition, b.tank_pressure_Pa, geom, **common)
    warm = b.arriving_superheat_K > 0
    design = compute_bog(
        b.composition, b.tank_pressure_Pa, geom, unloading_rate_m3_h=b.unloading_rate_m3_h,
        vapor_return_fraction=b.vapor_return_fraction,
        arriving_T_K=st.temperature_K + b.arriving_superheat_K if warm else None,
        arriving_P_Pa=b.arriving_P_Pa if warm else None, **common)

    rl = size_bog_reliquefaction(
        st, design.design_bog_kg_s, condensing_T_K=b.condensing_T_K, subcool_to_K=b.subcool_to_K,
        n_operating=b.n_operating, n_spare=b.n_spare)
    notes.extend(rl.notes)
    # Holding-mode load on the re-liquefaction loop (compressed flow scales with recycle)
    frac, ok = turndown_check(holding.holding_bog_kg_s * rl.recycle_factor,
                              rl.compressor.flow_per_machine_kg_s, n_running=b.n_operating)
    if not ok:
        notes.append(f"Holding-mode BOG is {frac * 100:.0f}% of the re-liquefaction machine rating "
                     "(below the assumed 60% stable minimum): a smaller holding machine or recycle is needed.")
    if rl.compressor.frame is None:
        notes.append(rl.compressor.machine_note)

    service_h = b.cargo_m3 / b.unloading_rate_m3_h + b.berth_overhead_h
    berth = berth_queueing_analysis(b.throughput_mtpa, b.cargo_m3, st.liquid_density_kg_m3,
                                    service_h, n_berths=b.n_berths)

    pump = size_lng_pump(b.composition, st.temperature_K, b.tank_pressure_Pa + b.tank_liquid_head_Pa,
                         b.delivery_pressure_Pa, m, b.pump_efficiency)
    heater = size_lpg_heater(b.composition, b.delivery_pressure_Pa, pump.outlet_T_K,
                             b.delivery_T_K, m, b.heater_medium_dT_K)
    if heater.note != "OK":
        notes.append(heater.note)

    return LPGTerminalDesign(
        basis=b, throughput_kg_s=m, tank_state=st, vapor_pressure_at_ambient_Pa=p_amb,
        storage=storage, tank=geom, bog_holding=holding, bog_design=design, reliquefaction=rl,
        holding_fraction_of_machine=frac, berth=berth, pump=pump, heater=heater, notes=notes)
