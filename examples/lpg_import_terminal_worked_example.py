"""Worked example: a 1 mtpa fully-refrigerated LPG import terminal
(95/5 mol% propane/n-butane, 84,000 m3 carriers, 2 atmospheric tanks).

Shows the three things that make LPG different from LNG regasification:
the BOG re-liquefaction loop and its flash penalty (and what sub-cooling
buys), liquid send-out through a heater, and a much smaller tank heat leak.
Entries marked ASSUMED are screening values in LPGTerminalBasis.

Run: python examples/lpg_import_terminal_worked_example.py
"""
from lng_design.lpg_terminal import LPGTerminalBasis, size_lpg_import_terminal

d = size_lpg_import_terminal()
st, bd, rl = d.tank_state, d.bog_design, d.reliquefaction
print(f"Storage {st.temperature_K - 273.15:.1f} C at 1.10 bara, {st.liquid_density_kg_m3:.0f} kg/m3; "
      f"vapor pressure at 40 C = {d.vapor_pressure_at_ambient_Pa / 1e5:.1f} bar")
s = d.storage
print(f"{s.n_tanks} x {s.per_tank_m3:,.0f} m3 ({s.cargoes_equivalent:.2f} cargoes; cargo {s.cargo_m3:,.0f} + "
      f"contingency {s.contingency_m3:,.0f} + heel {s.heel_m3:,.0f}); D {d.tank.inner_diameter_m:.1f} m, "
      f"H {d.tank.liquid_height_m:.1f} m")
print(f"Static BOR {d.bog_holding.boil_off_rate_static_percent_per_day:.3f} %/d "
      f"(heat ingress {d.bog_holding.heat_ingress_kW:,.0f} kW for both tanks)")
print("\nBOG, design case (unloading), t/h:")
for k, v in [("static", bd.static_bog_kg_s), ("pump heat", bd.pump_bog_kg_s), ("barometric", bd.barometric_bog_kg_s),
             ("displacement", bd.displacement_bog_kg_s), ("arrival flash", bd.flash_bog_kg_s),
             ("TOTAL", bd.design_bog_kg_s)]:
    print(f"  {k:14s}{v * 3.6:7.1f}")

print(f"\nRe-liquefaction at {rl.condensing_T_K - 273.15:.0f} C = {rl.condensing_P_Pa / 1e5:.1f} bar:")
print(f"  flash on let-down to the tank: {rl.flash_fraction * 100:.0f} % -> compressors handle "
      f"{rl.recycle_factor:.2f}x the BOG ({rl.compressed_flow_kg_s * 3.6:.1f} t/h)")
print(f"  {rl.compressor.n_stages} stages, {rl.compressor.shaft_power_kW_per_machine:,.0f} kW shaft each, "
      f"discharge {rl.compressor.discharge_T_K - 273.15:.0f} C; {rl.specific_power_kWh_per_t:.0f} kWh/t BOG; "
      f"{rl.compressor.machine_note}")
sub = size_lpg_import_terminal(LPGTerminalBasis(subcool_to_K=283.15)).reliquefaction
print(f"  sub-cool to 10 C: flash {sub.flash_fraction * 100:.0f} %, {sub.compressor.shaft_power_kW_per_machine:,.0f} kW "
      f"each ({(1 - sub.compressor.shaft_power_kW_per_machine / rl.compressor.shaft_power_kW_per_machine) * 100:.0f} % less) "
      f"for a {sub.subcooler_duty_kW:,.0f} kW sub-cooler on the refrigeration side")

b = d.berth
print(f"\nBerth: {b.utilization * 100:.0f} % utilized, expected wait {b.expected_wait_hours:.1f} h")
print(f"Send-out: pump {d.pump.shaft_kW:,.0f} kW ({d.pump.volumetric_flow_m3_h:,.0f} m3/h) to "
      f"{d.basis.delivery_pressure_Pa / 1e5:.0f} bar; heater {d.heater.duty_kW:,.0f} kW "
      f"({d.heater.inlet_T_K - 273.15:.0f} -> {d.heater.outlet_T_K - 273.15:.0f} C)")
print("\nNotes:")
for n in d.notes:
    print("  -", n)
