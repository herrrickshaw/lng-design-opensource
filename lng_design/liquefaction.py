"""Liquefaction train: one entry point that sizes feed gas to LNG storage.

`size_liquefaction_train(LiquefactionBasis)` chains the package's
equipment modules on ONE consistent feed basis, in process order, the way
`examples/full_train_worked_example.py` does by hand:

    feed -> V-101 inlet separator -> T-301 amine absorber -> V-201
    molecular sieve -> A-101 trim cooler -> C3-100 precool -> E-201 MCHE
    (LRC loop + pinch check) -> V-401 end-flash + K-401 flash-gas
    compressor -> TK-501 storage -> V-102 refrigerant storage

and, optionally, the NGL fractionation train (`fractionation.py`) whose
ethane and propane distillates are blended into make-up mixed refrigerant
(`refrigerant_generation.py`) - the plant making its own refrigerant.

Regasification (the reverse direction: tanks, BOG, send-out) is a separate
entry point in `regasification.py`; the two share tanks/BOG physics only
through `tank_bog.py`.

Scope limits, inherited from the modules it calls (all surfaced in
`LiquefactionDesign.notes` rather than hidden):

* The MCHE liquefaction section is sized for -40 C to -100 C, the range a
  single mixed-refrigerant compression stage validly spans
  (`cascade_loops.py`); the -100 C to -159 C subcooling duty is REPORTED but
  its dedicated loop is not sized.
* Duties come from `cp x dT` with illustrative average specific heats
  (`LiquefactionBasis.cp_*`), not from a heat-and-material balance. They
  are inputs precisely so you can replace them.
* Defaults reproduce the 2 mtpa example, whose numbers are conceptual
  (see docs/VALIDATION.md), not a licensor's design.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import CoolProp.CoolProp as CP

from .air_cooler import AirCoolerSizingResult, size_air_cooler
from .amine_absorber import AbsorberSizingResult, size_packed_absorber
from .berth import StorageTankSizingResult, size_storage_tank
from .cascade_loops import CascadeResult, three_loop_cascade
from .compressor import CompressorStageResult, size_centrifugal_stage
from .end_flash import EndFlashResult, flash_end_gas
from .equipment_catalog import CompressorFrame, select_compressor_frame
from .fractionation import ColumnSpec, TrainResult, size_fractionation_train
from .mche import CompositeCurveResult, StreamSegment, analyze_composite_curves, classify_mche_type
from .molecular_sieve import MolecularSieveBedResult, size_molecular_sieve_bed
from .precool import PrecoolCycleResult, optimal_evap_temperature
from .properties import GasMixture
from .refrigerant_generation import BlendResult, MakeupResult, blend_mixed_refrigerant, makeup_rate
from .refrigerant_makeup import RefrigerantStorageResult, size_refrigerant_storage
from .refrigerant_supply import (
    RefrigerantLoop, RefrigerantSupplyBasis, RefrigerantSupplyDesign, size_refrigerant_supply,
)
from .vessels import SeparatorSizingResult, size_vertical_separator

MTPA_TO_KG_S = 1.0e9 / (365.25 * 24 * 3600)
_MW = {"Nitrogen": 28.013, "Methane": 16.043, "Ethane": 30.070, "Propane": 44.097,
       "Isobutane": 58.123, "n-Butane": 58.123}


@dataclass
class LiquefactionBasis:
    """Every input of the train. Defaults = the 2 mtpa worked example."""

    capacity_mtpa: float = 2.0
    feed_composition: dict[str, float] = field(default_factory=lambda: {
        "Methane": 0.85, "Ethane": 0.08, "Propane": 0.04, "Nitrogen": 0.03})
    feed_T_K: float = 298.15
    feed_P_Pa: float = 50e5
    ambient_T_K: float = 313.15            # design ambient for condensing/cooling

    # V-101 (condensate is an illustrative allowance, not derived)
    condensate_density_kg_m3: float = 550.0
    condensate_flow_m3_s: float = 0.015

    # T-301 acid-gas removal (L/V chosen for absorption factor ~1.4-2.0)
    co2_in_mole_frac: float = 0.02
    co2_out_mole_frac: float = 0.0005
    amine_density_kg_m3: float = 1010.0
    amine_equilibrium_slope: float = 0.4
    amine_liquid_to_gas: float = 0.8

    # V-201
    inlet_water_ppm_wt: float = 700.0

    # Duties: illustrative average cp (kJ/kg-K) x dT, all overridable
    trim_cooler_cp_kJ_kg_K: float = 2.3
    trim_cooler_dT_K: float = 20.0         # ~60 C post-sieve -> 40 C
    design_ambient_C_air_cooler: float = 35.0
    precool_cp_kJ_kg_K: float = 2.4
    precool_from_C: float = 40.0
    precool_to_C: float = -40.0
    liquefaction_cp_kJ_kg_K: float = 2.9   # average over the full -40 to -159 C span
    lrc_floor_C: float = -100.0            # single-stage LRC validated floor
    end_C: float = -159.0

    # LRC mixed refrigerant loop
    lrc_blend: dict[str, float] = field(default_factory=lambda: {
        "Nitrogen": 0.05, "Methane": 0.30, "Ethane": 0.35, "Propane": 0.30})
    lrc_T_evap_K: float = 173.15
    lrc_T_cond_K: float = 236.15
    mche_min_approach_K: float = 3.0
    mche_U_W_m2K: float = 2500.0

    # V-401 end flash
    lng_composition: dict[str, float] | None = None   # None -> feed composition
    end_flash_inlet_T_K: float = 113.15
    end_flash_inlet_P_Pa: float = 4.5e5
    storage_P_Pa: float = 1.10e5
    flash_gas_discharge_P_Pa: float = 5e5

    # TK-501 / V-102
    lng_density_kg_m3: float = 450.0
    shipping_interval_days: float = 4.0
    contingency_days: float = 1.5
    cargo_size_m3: float = 170000.0
    c3_holdup_s: float = 300.0             # ~5 min system holdup, illustrative
    c3_liquid_density_kg_m3: float = 500.0

    # Optional NGL fractionation + refrigerant generation
    ngl_feed_kmol_h: dict[str, float] | None = None
    fractionation_specs: list[ColumnSpec] | None = None
    mr_target: dict[str, float] | None = None
    mr_charge_kmol: float = 8000.0
    mr_annual_loss_fraction: float = 0.10

    # Optional refrigerant storage (2.5-3x total demand) + a train that makes
    # ethane, propane and butane to fill it (refrigerant_supply.py). The C3
    # precool charge and the LRC charge (lrc_blend x mr_charge_kmol) are the loops.
    include_refrigerant_supply: bool = False
    refrigerant_storage_factor: float = 2.75
    refrigerant_fill_days: float = 60.0


@dataclass
class LiquefactionDesign:
    basis: LiquefactionBasis
    feed_mass_flow_kg_s: float
    feed_density_kg_m3: float
    inlet_separator: SeparatorSizingResult
    absorber: AbsorberSizingResult
    molecular_sieve: MolecularSieveBedResult
    trim_cooler_duty_kW: float
    trim_cooler: AirCoolerSizingResult
    precool_duty_kW: float
    precool: PrecoolCycleResult
    precool_frame: CompressorFrame
    precool_inlet_m3_h: float
    lrc_duty_kW: float
    subcooling_duty_kW: float
    cascade: CascadeResult
    mche_pinch: CompositeCurveResult
    mche_technology: dict
    end_flash: EndFlashResult
    flash_gas_compressor: CompressorStageResult | None
    storage_tank: StorageTankSizingResult
    c3_charge_kg: float
    refrigerant_storage: RefrigerantStorageResult
    fractionation: TrainResult | None = None
    mr_blend: BlendResult | None = None
    mr_makeup: MakeupResult | None = None
    refrigerant_supply: RefrigerantSupplyDesign | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def refrigeration_power_kW(self) -> float:
        """Precool + LRC compressor power (the two loops sized here)."""
        return self.precool.compressor_power_kW + self.cascade.lrc.compressor_power_kW

    @property
    def total_compression_power_kW(self) -> float:
        fg = self.flash_gas_compressor.gas_power_kW if self.flash_gas_compressor else 0.0
        return self.refrigeration_power_kW + fg

    @property
    def lng_out_kg_s(self) -> float:
        return self.end_flash.liquid_mass_flow_kg_s


def size_liquefaction_train(basis: LiquefactionBasis | None = None) -> LiquefactionDesign:
    b = basis or LiquefactionBasis()
    notes: list[str] = []

    feed = GasMixture(b.feed_composition)
    m = b.capacity_mtpa * MTPA_TO_KG_S
    rho = feed.density(b.feed_T_K, b.feed_P_Pa)
    q = m / rho

    v101 = size_vertical_separator(q, rho, b.condensate_density_kg_m3, b.condensate_flow_m3_s)
    t301 = size_packed_absorber(
        gas_volumetric_flow_m3_s=q, gas_density_kg_m3=rho,
        liquid_density_kg_m3=b.amine_density_kg_m3,
        y_in_mole_frac=b.co2_in_mole_frac, y_out_target_mole_frac=b.co2_out_mole_frac,
        x_in_mole_frac=0.001, equilibrium_slope_m=b.amine_equilibrium_slope,
        liquid_to_gas_molar_ratio=b.amine_liquid_to_gas)
    v201 = size_molecular_sieve_bed(gas_mass_flow_kg_s=m, gas_density_kg_m3=rho,
                                    inlet_water_content_ppm_wt=b.inlet_water_ppm_wt)

    trim_duty = m * b.trim_cooler_cp_kJ_kg_K * b.trim_cooler_dT_K
    a101 = size_air_cooler(trim_duty, design_ambient_T_C=b.design_ambient_C_air_cooler)

    precool_duty = m * b.precool_cp_kJ_kg_K * (b.precool_from_C - b.precool_to_C)
    precool = optimal_evap_temperature(
        precool_duty, T_cold_end_target_K=b.precool_to_C + 273.15, T_cond_K=b.ambient_T_K)
    # Propane at (T_evap, P_evap) is exactly saturated: read vapor density via Q=1,
    # a (T, P) lookup is ambiguous there (see compressor.match_frame_for_stage).
    rho_suc = CP.PropsSI("D", "T", precool.T_evap_K, "Q", 1, "Propane")
    suction_m3_h = precool.refrigerant_mass_flow_kg_s / rho_suc * 3600.0
    try:
        frame = select_compressor_frame(suction_m3_h)
    except ValueError as e:
        notes.append(f"C3 compressor: {e}")
        frame = None

    total_span = abs(b.end_C - b.precool_to_C)
    lrc_span = abs(b.lrc_floor_C - b.precool_to_C)
    src_span = total_span - lrc_span
    total_duty = m * b.liquefaction_cp_kJ_kg_K * total_span
    lrc_duty = total_duty * lrc_span / total_span
    src_duty = total_duty * src_span / total_span
    notes.append(
        f"Subcooling {b.lrc_floor_C:.0f} C to {b.end_C:.0f} C ({src_duty:,.0f} kW) needs a "
        "dedicated subcooling loop that this package does not size.")

    cascade = three_loop_cascade(
        ng_precool_duty_kW=0.0, ng_liquefaction_duty_kW=lrc_duty,
        pmr_T_evap_K=b.precool_to_C + 273.15, pmr_T_cond_K=b.ambient_T_K,
        lrc_refrigerant=GasMixture(b.lrc_blend),
        lrc_T_evap_K=b.lrc_T_evap_K, lrc_T_cond_K=b.lrc_T_cond_K)

    hot = [StreamSegment(b.precool_to_C + 273.15, b.lrc_T_evap_K, lrc_duty)]
    cold = [StreamSegment(b.lrc_T_evap_K - 5.0, b.precool_to_C + 273.15 - 5.0, lrc_duty)]
    pinch = analyze_composite_curves(hot, cold, min_approach_K=b.mche_min_approach_K,
                                     overall_U_W_m2K=b.mche_U_W_m2K)
    tech = classify_mche_type(b.capacity_mtpa)

    lng_comp = b.lng_composition or b.feed_composition
    ef = flash_end_gas(lng_comp, b.end_flash_inlet_T_K, b.end_flash_inlet_P_Pa, b.storage_P_Pa, m)
    fgc = None
    if ef.vapor_mass_flow_kg_s > 0:
        fgc = size_centrifugal_stage(GasMixture(ef.vapor_composition_mole_frac),
                                     ef.flash_temperature_K, b.storage_P_Pa,
                                     b.flash_gas_discharge_P_Pa, ef.vapor_mass_flow_kg_s)

    tank = size_storage_tank(ef.liquid_mass_flow_kg_s, b.lng_density_kg_m3,
                             b.shipping_interval_days, b.contingency_days,
                             cargo_size_m3=b.cargo_size_m3)
    c3_charge = precool.refrigerant_mass_flow_kg_s * b.c3_holdup_s
    # Raises if the charge needs more than one standard vessel (the
    # catalog refuses rather than return an undersized match).
    v102 = size_refrigerant_storage(c3_charge, b.c3_liquid_density_kg_m3)

    frac = blend = mk = None
    if b.ngl_feed_kmol_h is not None:
        if not b.fractionation_specs:
            raise ValueError("ngl_feed_kmol_h given but fractionation_specs is empty")
        frac = size_fractionation_train(b.ngl_feed_kmol_h, b.fractionation_specs)
        if b.mr_target is not None:
            if len(frac.columns) < 2:
                raise ValueError("MR blending needs a deethanizer and depropanizer column (>= 2 columns)")
            sources = {
                "nitrogen": {"Nitrogen": 1.0}, "methane": {"Methane": 1.0},
                "ethane distillate": frac.columns[0].distillate_mole_fractions,
                "propane distillate": frac.columns[1].distillate_mole_fractions,
            }
            blend = blend_mixed_refrigerant(b.mr_target, sources)
            mw = sum(blend.achieved[c] * _MW[c] for c in blend.achieved if c in _MW)
            mk = makeup_rate(b.mr_charge_kmol, b.mr_annual_loss_fraction, blend, mw)
            if not blend.reachable:
                notes.append(f"MR target not reachable from the available sources "
                             f"(max error {blend.max_abs_error:.3f}).")

    supply = None
    if b.include_refrigerant_supply:
        supply = size_refrigerant_supply(RefrigerantSupplyBasis(
            loops=[RefrigerantLoop("C3 precool", {"Propane": 1.0}, charge_kg=c3_charge),
                   RefrigerantLoop("LRC mixed refrigerant", dict(b.lrc_blend), charge_kmol=b.mr_charge_kmol)],
            storage_factor=b.refrigerant_storage_factor, fill_days=b.refrigerant_fill_days,
            annual_loss_fraction=b.mr_annual_loss_fraction,
            **({"ngl_feed_kmol_h": b.ngl_feed_kmol_h} if b.ngl_feed_kmol_h else {})))
        notes.extend(supply.notes)

    return LiquefactionDesign(
        basis=b, feed_mass_flow_kg_s=m, feed_density_kg_m3=rho,
        inlet_separator=v101, absorber=t301, molecular_sieve=v201,
        trim_cooler_duty_kW=trim_duty, trim_cooler=a101,
        precool_duty_kW=precool_duty, precool=precool, precool_frame=frame,
        precool_inlet_m3_h=suction_m3_h, lrc_duty_kW=lrc_duty, subcooling_duty_kW=src_duty,
        cascade=cascade, mche_pinch=pinch, mche_technology=tech, end_flash=ef,
        flash_gas_compressor=fgc, storage_tank=tank, c3_charge_kg=c3_charge,
        refrigerant_storage=v102, fractionation=frac, mr_blend=blend, mr_makeup=mk,
        refrigerant_supply=supply,
        notes=notes,
    )
