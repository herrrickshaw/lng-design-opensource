"""Regasification terminal: one entry point that sizes tanks, BOG handling
and the send-out train on one basis.

`size_regasification_terminal(RegasificationBasis)` runs, in order:

    tanks (`tank_bog`)  ->  BOG by source, holding and unloading
      -> BOG compressors (`bog_compressor`) on the design BOG and its
         real (nitrogen-rich) composition, with a holding-mode turndown check
      -> send-out train (`regas_terminal`): LP/HP pumps, vaporizer duty,
         ORV bank, SCV backup
      -> BOG recondenser at full send-out AND at a turndown send-out, and,
         if the recondenser cannot absorb all the BOG at turndown, the
         direct-to-pipeline (HP) BOG compressor for the excess

The turndown case is the one that usually decides the BOG system: the
recondenser can only condense as much BOG as the LNG passing it can absorb,
so a terminal that is comfortable at full send-out can be BOG-limited at low
send-out. It is computed by default rather than left to the reader.

Liquefaction (feed gas to LNG) is the separate entry point in
`liquefaction.py`. Everything here inherits the scope limits of the modules
it calls; conditions that need a human decision are returned in
`RegasificationDesign.notes`, not raised, so a design that fails a check is
still visible in full.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .bog_compressor import BOGCompressorResult, size_bog_compressor, turndown_check
from .regas_terminal import RecondenserResult, RegasTrainResult, size_recondenser, size_regas_train
from .tank_bog import BOGResult, TankGeometry, compute_bog, size_tank_geometry, tank_liquid_state

MTPA_TO_KG_S = 1.0e9 / (365.25 * 24 * 3600)


@dataclass
class RegasificationBasis:
    """Every input. Defaults = the 5 mtpa, 2 x 160,000 m3 worked example;
    entries marked ASSUMED are screening values to replace with project data."""

    lng_composition: dict[str, float] = field(default_factory=lambda: {
        "Methane": 0.92, "Ethane": 0.05, "Propane": 0.015, "n-Butane": 0.005, "Nitrogen": 0.01})
    sendout_mtpa: float = 5.0
    sendout_pressure_Pa: float = 85e5
    sendout_T_K: float = 278.15
    seawater_in_C: float = 20.0
    seawater_dT_K: float = 5.0

    # Tanks
    tank_net_volume_m3: float = 160_000.0
    n_tanks: int = 2
    tank_pressure_Pa: float = 1.15e5
    fill_fraction: float = 0.90
    height_to_diameter: float = 0.40
    pump_heat_total_kW: float = 250.0            # ASSUMED in-tank pump heat
    barometric_fall_Pa_per_h: float = 100.0      # ASSUMED design allowance
    unloading_rate_m3_h: float = 12_000.0
    vapor_return_fraction: float = 0.40
    arriving_superheat_K: float = 0.5            # arriving LNG above tank saturation
    arriving_P_Pa: float = 3.0e5                 # at the tank inlet valve

    # BOG compressors
    recondenser_P_Pa: float = 9.0e5
    bog_suction_dP_Pa: float = 0.05e5            # header + K.O. drum loss
    bog_suction_T_K: float = 143.15
    n_operating: int = 2                         # ASSUMED 2 x 50 % + 1 spare
    n_spare: int = 1
    bog_margin: float = 0.10
    min_stable_fraction: float = 0.60            # ASSUMED centrifugal turndown

    # Send-out
    lp_discharge_Pa: float = 10e5
    lp_efficiency: float = 0.70                  # ASSUMED
    hp_efficiency: float = 0.75                  # ASSUMED
    turndown_sendout_fraction: float = 0.25


@dataclass
class RegasificationDesign:
    basis: RegasificationBasis
    sendout_kg_s: float
    tank: TankGeometry
    bog_holding: BOGResult
    bog_design: BOGResult
    bog_compressor: BOGCompressorResult
    holding_fraction_of_machine: float
    holding_within_turndown: bool
    train: RegasTrainResult
    recondenser: RecondenserResult
    recondenser_turndown: RecondenserResult
    hp_bog_compressor: BOGCompressorResult | None
    notes: list[str] = field(default_factory=list)

    @property
    def installed_power_kW(self) -> float:
        """Pump shafts + installed BOG compressor shafts (+ HP BOG unit if any)."""
        hp = self.hp_bog_compressor.installed_shaft_power_kW if self.hp_bog_compressor else 0.0
        return self.train.total_pump_shaft_kW + self.bog_compressor.installed_shaft_power_kW + hp

    @property
    def excess_bog_at_turndown_kg_s(self) -> float:
        return self.recondenser_turndown.excess_bog_kg_s


def size_regasification_terminal(basis: RegasificationBasis | None = None) -> RegasificationDesign:
    b = basis or RegasificationBasis()
    if not (0.0 < b.turndown_sendout_fraction <= 1.0):
        raise ValueError("turndown_sendout_fraction must be in (0, 1]")
    notes: list[str] = []
    m = b.sendout_mtpa * MTPA_TO_KG_S

    st = tank_liquid_state(b.lng_composition, b.tank_pressure_Pa)
    geom = size_tank_geometry(b.tank_net_volume_m3, b.height_to_diameter)
    common = dict(n_tanks=b.n_tanks, fill_fraction=b.fill_fraction,
                  pump_heat_total_kW=b.pump_heat_total_kW,
                  barometric_fall_Pa_per_h=b.barometric_fall_Pa_per_h)
    holding = compute_bog(b.lng_composition, b.tank_pressure_Pa, geom, **common)
    design = compute_bog(
        b.lng_composition, b.tank_pressure_Pa, geom,
        unloading_rate_m3_h=b.unloading_rate_m3_h,
        vapor_return_fraction=b.vapor_return_fraction,
        arriving_T_K=st.temperature_K + b.arriving_superheat_K if b.arriving_superheat_K > 0 else None,
        arriving_P_Pa=b.arriving_P_Pa if b.arriving_superheat_K > 0 else None,
        **common)

    comp = size_bog_compressor(
        design.bog_composition, design.design_bog_kg_s,
        suction_P_Pa=b.tank_pressure_Pa - b.bog_suction_dP_Pa, discharge_P_Pa=b.recondenser_P_Pa,
        suction_T_K=b.bog_suction_T_K, margin=b.bog_margin,
        n_operating=b.n_operating, n_spare=b.n_spare)
    frac, ok = turndown_check(holding.holding_bog_kg_s, comp.flow_per_machine_kg_s,
                              n_running=1, min_stable_fraction=b.min_stable_fraction)
    if not ok:
        notes.append(
            f"Holding-mode BOG is {frac * 100:.0f}% of one machine's rating, below the "
            f"{b.min_stable_fraction * 100:.0f}% stable minimum: needs recycle, or a "
            "reciprocating/step-unloaded machine for holding mode.")
    if not comp.frame:
        notes.append(comp.machine_note)

    train = size_regas_train(
        b.lng_composition, m, b.tank_pressure_Pa, st.temperature_K,
        lp_discharge_Pa=b.lp_discharge_Pa, sendout_pressure_Pa=b.sendout_pressure_Pa,
        sendout_T_K=b.sendout_T_K, seawater_in_C=b.seawater_in_C,
        lp_efficiency=b.lp_efficiency, hp_efficiency=b.hp_efficiency,
        seawater_dT_K=b.seawater_dT_K)
    if not train.orv.usable:
        notes.append(train.orv.note)

    # The LP pump outlet temperature does not depend on flow, so one train
    # sizing serves both send-out cases.
    lng_T = train.lp_pump.outlet_T_K
    rc = size_recondenser(b.lng_composition, lng_T, design.bog_composition, comp.discharge_T_K,
                          design.design_bog_kg_s, b.recondenser_P_Pa, m)
    rc_low = size_recondenser(b.lng_composition, lng_T, design.bog_composition, comp.discharge_T_K,
                              design.design_bog_kg_s, b.recondenser_P_Pa,
                              b.turndown_sendout_fraction * m)
    if rc.excess_bog_kg_s > 0:
        notes.append(f"At full send-out the recondenser cannot absorb all BOG "
                     f"(excess {rc.excess_bog_kg_s * 3.6:.1f} t/h).")

    hp = None
    if rc_low.excess_bog_kg_s > 0:
        hp = size_bog_compressor(
            design.bog_composition, rc_low.excess_bog_kg_s,
            suction_P_Pa=b.tank_pressure_Pa - b.bog_suction_dP_Pa,
            discharge_P_Pa=b.sendout_pressure_Pa, suction_T_K=b.bog_suction_T_K,
            margin=b.bog_margin)
        notes.append(
            f"At {b.turndown_sendout_fraction * 100:.0f}% send-out the recondenser absorbs "
            f"{rc_low.max_recondensable_bog_kg_s * 3.6:.0f} t/h of the {design.design_bog_kg_s * 3.6:.0f} "
            f"t/h design BOG: {rc_low.excess_bog_kg_s * 3.6:.1f} t/h goes to a direct-to-pipeline "
            f"HP BOG compressor ({hp.n_stages} stages, discharge {hp.discharge_T_K - 273.15:.0f} C "
            "without intercooling).")

    return RegasificationDesign(
        basis=b, sendout_kg_s=m, tank=geom, bog_holding=holding, bog_design=design,
        bog_compressor=comp, holding_fraction_of_machine=frac, holding_within_turndown=ok,
        train=train, recondenser=rc, recondenser_turndown=rc_low, hp_bog_compressor=hp,
        notes=notes)
