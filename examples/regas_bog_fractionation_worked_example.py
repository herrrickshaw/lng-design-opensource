"""Worked example: a 5 mtpa regas terminal (tanks -> BOG -> send-out) and an
NGL fractionation train that makes refrigerant-grade ethane and propane,
on one consistent basis.

Basis
-----
  LNG:        92/5/1.5/0.5/1 mol% CH4/C2H6/C3H8/nC4/N2, tank at 1.15 bara
  Send-out:   5 mtpa (158.5 kg/s) at 85 bara, 5 C
  Storage:    2 x 160,000 m3 full-containment tanks
  Unloading:  170,000 m3 cargo in ~14 h (12,000 m3/h), 40 % vapor return
  NGL feed:   the heavy ends of a rich feed gas, 920 kmol/h, C2-C6

Every number below is an OUTPUT of the modules - nothing is typed in from a
guarantee. Where a choice is a plain assumption (efficiencies, redundancy,
refrigerant specs, loss rate) it is marked ASSUMED, because those are the
inputs a real project replaces with vendor / licensor data.

Run: python examples/regas_bog_fractionation_worked_example.py
"""
from __future__ import annotations

from lng_design.bog_compressor import size_bog_compressor, turndown_check
from lng_design.fractionation import ColumnSpec, size_fractionation_train
from lng_design.refrigerant_generation import (
    ProductSpec, blend_mixed_refrigerant, check_product_spec, makeup_rate,
)
from lng_design.regas_terminal import size_recondenser, size_regas_train
from lng_design.tank_bog import compute_bog, size_tank_geometry

MTPA_TO_KG_S = 1.0e9 / (365.25 * 24 * 3600)
LNG = {"Methane": 0.92, "Ethane": 0.05, "Propane": 0.015, "n-Butane": 0.005, "Nitrogen": 0.01}
P_TANK = 1.15e5
SENDOUT_KG_S = 5.0 * MTPA_TO_KG_S


def hdr(t):
    print(f"\n{'=' * 72}\n{t}\n{'=' * 72}")


# ---------------------------------------------------------------- 1. tanks
hdr("1. Storage tanks and BOG")
geom = size_tank_geometry(160_000.0, height_to_diameter=0.40)
print(f"Tank: D = {geom.inner_diameter_m:.1f} m, liquid H = {geom.liquid_height_m:.1f} m, "
      f"wall {geom.wall_area_m2:,.0f} / roof {geom.roof_area_m2:,.0f} / floor {geom.floor_area_m2:,.0f} m2")

common = dict(n_tanks=2, fill_fraction=0.90, pump_heat_total_kW=250.0)   # ASSUMED recirculation pump heat
hold = compute_bog(LNG, P_TANK, geom, **common)
st = hold.liquid_state
print(f"Tank liquid: {st.temperature_K - 273.15:.1f} C, rho {st.liquid_density_kg_m3:.0f} kg/m3; "
      f"BOG latent heat {st.latent_heat_J_kg / 1e3:.0f} kJ/kg, BOG MW {st.bog_molecular_weight_g_mol:.1f}")
print(f"BOG composition (mol%): "
      + ", ".join(f"{k} {v * 100:.1f}" for k, v in st.bog_mole_fractions.items() if v > 5e-4)
      + f"   <- N2 is {st.bog_mole_fractions['Nitrogen'] / LNG['Nitrogen']:.0f}x its LNG level")
print(f"Static heat ingress (both tanks): {hold.heat_ingress_kW:,.0f} kW -> "
      f"static BOR {hold.boil_off_rate_static_percent_per_day:.3f} vol%/day  (commonly quoted vendor figure ~0.05)")

print("\nBarometric-pressure sensitivity (holding mode):")
for dp in (0.0, 50.0, 100.0, 300.0):
    r = compute_bog(LNG, P_TANK, geom, barometric_fall_Pa_per_h=dp, **common)
    print(f"  {dp:5.0f} Pa/h fall -> holding BOG {r.holding_bog_kg_s * 3.6:6.1f} t/h "
          f"({r.barometric_bog_kg_s / max(r.static_bog_kg_s, 1e-12):4.1f}x the static term)")

DESIGN_BARO = 100.0    # ASSUMED design allowance
design = compute_bog(
    LNG, P_TANK, geom, barometric_fall_Pa_per_h=DESIGN_BARO,
    unloading_rate_m3_h=12_000.0, vapor_return_fraction=0.40,
    arriving_T_K=st.temperature_K + 0.5, arriving_P_Pa=3.0e5, **common,
)
holding_design = compute_bog(LNG, P_TANK, geom, barometric_fall_Pa_per_h=DESIGN_BARO, **common)
print(f"\nDesign case (unloading, 40 % vapor return, {DESIGN_BARO:.0f} Pa/h barometric fall):")
for label, v in [("static heat ingress", design.static_bog_kg_s), ("pump heat", design.pump_bog_kg_s),
                 ("barometric", design.barometric_bog_kg_s), ("vapor displacement", design.displacement_bog_kg_s),
                 ("arrival flash", design.flash_bog_kg_s), ("TOTAL", design.unloading_bog_kg_s)]:
    print(f"  {label:20s} {v * 3.6:7.1f} t/h")

# ------------------------------------------------------- 2. BOG compressors
hdr("2. BOG compressors (to recondenser at 9 bara)")
comp = size_bog_compressor(
    design.bog_composition, design.design_bog_kg_s,
    suction_P_Pa=P_TANK - 0.05e5, discharge_P_Pa=9.0e5,
    n_operating=2, n_spare=1, margin=0.10,                       # ASSUMED 2 x 50 % + 1 spare
)
print(f"{comp.n_operating} + {comp.n_spare} machines, {comp.flow_per_machine_kg_s * 3.6:.1f} t/h each, "
      f"suction {comp.suction_T_K - 273.15:.0f} C ({comp.suction_density_kg_m3:.2f} kg/m3, "
      f"{comp.inlet_volume_flow_per_machine_m3_h:,.0f} m3/h)")
print(f"{comp.n_stages} stages at PR {comp.stage_pressure_ratio:.2f}; "
      f"{comp.shaft_power_kW_per_machine:,.0f} kW shaft each, discharge {comp.discharge_T_K - 273.15:.0f} C")
print(f"Frame: {comp.machine_note}")
warm = size_bog_compressor(design.bog_composition, design.design_bog_kg_s, P_TANK - 0.05e5, 9.0e5,
                           suction_T_K=298.15, n_operating=2, n_spare=1)
print(f"Same duty on warmed (+25 C) gas: {warm.shaft_power_kW_per_machine:,.0f} kW each "
      f"({warm.shaft_power_kW_per_machine / comp.shaft_power_kW_per_machine:.1f}x) - why BOG is compressed cold")
frac, ok = turndown_check(holding_design.holding_bog_kg_s, comp.flow_per_machine_kg_s, n_running=1)
print(f"Holding-mode BOG = {frac * 100:.0f} % of one machine's rating -> "
      f"{'within' if ok else 'BELOW'} an assumed 60 % stable turndown"
      + ("" if ok else ": needs recycle, or a reciprocating/step-unloaded unit for holding mode"))

# ---------------------------------------------------------------- 3. regas
hdr("3. Send-out train (5 mtpa, 85 bara, 5 C)")
train = size_regas_train(
    LNG, SENDOUT_KG_S, P_TANK, st.temperature_K, lp_discharge_Pa=10.0e5,
    sendout_pressure_Pa=85.0e5, sendout_T_K=278.15, seawater_in_C=20.0,
)
print(f"LP pump {train.lp_pump.shaft_kW:,.0f} kW ({train.lp_pump.volumetric_flow_m3_h:,.0f} m3/h, "
      f"{train.lp_pump.differential_head_m:,.0f} m), HP pump {train.hp_pump.shaft_kW:,.0f} kW "
      f"(+{train.hp_pump.temperature_rise_K:.1f} K)  [ASSUMED eta 0.70 / 0.75]")
print(f"Vaporizer duty {train.duty_kW / 1000:,.1f} MW = {train.duty_kJ_per_kg:,.0f} kJ/kg")
o = train.orv
print(f"ORV: {o.n_operating} + {o.n_spare} units, seawater {o.seawater_flow_t_h:,.0f} t/h "
      f"({o.seawater_flow_t_h / o.n_operating:,.0f} t/h/unit; published 5,000-10,000), "
      f"20 -> {o.seawater_outlet_C:.0f} C")
s = train.scv
print(f"SCV backup (cold seawater): {s.n_operating} + {s.n_spare} units burning "
      f"{s.fuel_gas_kg_s * 3.6:.1f} t/h fuel gas = {s.fuel_fraction_of_sendout * 100:.2f} % of send-out")
rc = size_recondenser(LNG, train.lp_pump.outlet_T_K, design.bog_composition,
                      comp.discharge_T_K, design.design_bog_kg_s, 9.0e5, SENDOUT_KG_S)
print(f"Recondenser @ 9 bara: {rc.lng_to_bog_mass_ratio:.1f} kg LNG per kg BOG; design BOG "
      f"{design.design_bog_kg_s * 3.6:.1f} t/h needs {rc.lng_required_kg_s * 3.6:.0f} t/h LNG "
      f"({rc.lng_required_kg_s / SENDOUT_KG_S * 100:.0f} % of send-out); "
      f"max recondensable {rc.max_recondensable_bog_kg_s * 3.6:.0f} t/h, excess {rc.excess_bog_kg_s * 3.6:.1f} t/h")
low = size_regas_train(LNG, 0.25 * SENDOUT_KG_S, P_TANK, st.temperature_K, 10.0e5, 85.0e5)
rc_low = size_recondenser(LNG, low.lp_pump.outlet_T_K, design.bog_composition, comp.discharge_T_K,
                          design.design_bog_kg_s, 9.0e5, 0.25 * SENDOUT_KG_S)
print(f"At 25 % send-out turndown the recondenser can take {rc_low.max_recondensable_bog_kg_s * 3.6:.0f} t/h; "
      f"excess {rc_low.excess_bog_kg_s * 3.6:.1f} t/h must go to a direct-to-pipeline (HP BOG) compressor")
hp = size_bog_compressor(design.bog_composition, max(rc_low.excess_bog_kg_s, 0.5), P_TANK - 0.05e5, 85.0e5)
print(f"  HP BOG route for that excess: {hp.n_stages} stages, {hp.gas_power_kW_per_machine:,.0f} kW, "
      f"discharge {hp.discharge_T_K - 273.15:.0f} C without intercooling")

# ------------------------------------------------------- 4. fractionation
hdr("4. NGL fractionation: distillates and refrigerant-grade cuts")
NGL = {"Ethane": 320, "Propane": 300, "Isobutane": 60, "n-Butane": 100,
       "Isopentane": 50, "Pentane": 50, "Hexane": 40}                 # kmol/h
specs = [
    ColumnSpec("deethanizer", "Ethane", "Propane", 26e5, 0.98, 0.995),
    ColumnSpec("depropanizer", "Propane", "Isobutane", 17e5, 0.985, 0.98),
    ColumnSpec("debutanizer", "n-Butane", "Isopentane", 6e5, 0.98, 0.98),
]
ngl = size_fractionation_train(NGL, specs)
print(f"Feed {sum(NGL.values()):,.0f} kmol/h; train mole balance error {ngl.mass_balance_error:.1e}\n")
print(f"{'column':13s}{'Nmin':>6s}{'Rmin':>6s}{'R':>6s}{'Nth':>6s}{'trays':>6s}{'Eo':>6s}"
      f"{'D m':>6s}{'H m':>6s}{'Tc K':>7s}{'Qc kW':>8s}{'Qr kW':>8s}  condenser")
for c in ngl.columns:
    print(f"{c.name:13s}{c.N_min:6.1f}{c.R_min:6.2f}{c.R:6.2f}{c.N_theoretical:6.1f}{c.N_real:6d}"
          f"{c.tray_efficiency:6.2f}{c.diameter_m:6.2f}{c.height_m:6.1f}{c.T_top_K:7.1f}"
          f"{c.condenser_duty_kW:8,.0f}{c.reboiler_duty_kW:8,.0f}  {c.condenser_service}")
    for n in c.notes:
        print(f"    note: {n}")
dp_col = ngl.columns[1]
if dp_col.min_pressure_for_cooling_water_Pa:
    print(f"\nDepropanizer needs >= {dp_col.min_pressure_for_cooling_water_Pa / 1e5:.1f} bar top pressure "
          f"for an air/water-cooled condenser (set at {dp_col.P_top_Pa / 1e5:.0f} bar)")

# ----------------------------------------------- 5. refrigerant generation
hdr("5. Refrigerant generation")
ETHANE_SPEC = ProductSpec("ethane refrigerant", min_mole_frac={"Ethane": 0.97},
                          max_mole_frac={"Propane": 0.03})            # ASSUMED - use licensor's spec
PROPANE_SPEC = ProductSpec("propane refrigerant", min_mole_frac={"Propane": 0.95},
                           max_mole_frac={"Ethane": 0.02, "n-Butane": 0.02, "Isobutane": 0.03})  # ASSUMED
c2 = check_product_spec(ngl.columns[0].distillate_mole_fractions, ETHANE_SPEC)
c3 = check_product_spec(ngl.columns[1].distillate_mole_fractions, PROPANE_SPEC)
for chk, col in ((c2, ngl.columns[0]), (c3, ngl.columns[1])):
    print(f"{chk.name}: {'PASS' if chk.passed else 'FAIL'}  "
          + ", ".join(f"{k} {v * 100:.2f}%" for k, v in col.distillate_mole_fractions.items() if v > 5e-4))
    for v in chk.violations:
        print(f"    violation: {v}")

MR_TARGET = {"Nitrogen": 0.05, "Methane": 0.40, "Ethane": 0.45, "Propane": 0.10}   # ASSUMED MR composition
sources = {
    "nitrogen": {"Nitrogen": 1.0},
    "methane (fuel gas)": {"Methane": 1.0},
    "ethane (deethanizer distillate)": ngl.columns[0].distillate_mole_fractions,
    "propane (depropanizer distillate)": ngl.columns[1].distillate_mole_fractions,
}
blend = blend_mixed_refrigerant(MR_TARGET, sources)
print(f"\nMR blend to N2/C1/C2/C3 = 5/40/45/10 mol%: max composition error {blend.max_abs_error:.4f} "
      f"({'reachable' if blend.reachable else 'NOT reachable'})")
for k, v in blend.source_kmol_per_kmol_mr.items():
    print(f"  {k:36s} {v:.4f} kmol / kmol MR")
mw_mr = sum(blend.achieved[c] * m for c, m in
            {"Nitrogen": 28.013, "Methane": 16.043, "Ethane": 30.070, "Propane": 44.097,
             "Isobutane": 58.123, "n-Butane": 58.123}.items() if c in blend.achieved)
CHARGE_KMOL = 8_000.0                                                  # ASSUMED MR inventory
mk = makeup_rate(CHARGE_KMOL, 0.10, blend, mw_mr)                      # ASSUMED 10 %/yr loss
d_ethane = sum(ngl.columns[0].distillate_kmol_h.values())
print(f"Make-up for {CHARGE_KMOL:,.0f} kmol charge at 10 %/yr: {mk.makeup_kmol_h:.3f} kmol/h "
      f"({mk.makeup_kg_h:.1f} kg/h); ethane share {mk.by_source_kmol_h['ethane (deethanizer distillate)']:.3f} "
      f"kmol/h vs {d_ethane:,.0f} kmol/h deethanizer distillate "
      f"= {mk.by_source_kmol_h['ethane (deethanizer distillate)'] / d_ethane * 100:.3f} % of that column's output")
print("-> the columns are sized for product recovery; refrigerant make-up is a tiny side draw.")
