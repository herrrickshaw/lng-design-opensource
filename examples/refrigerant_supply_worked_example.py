"""Worked example: refrigerant storage at 2.5-3x total demand, and the
fractionation train that makes ethane, propane and butane to fill it.

Basis: C3 precool charge 16,765 kg propane; mixed refrigerant 8,000 kmol of
N2/C1/C2/C3/nC4 = 5/38/44/10/3 mol% (the 3 % butane is an ASSUMED illustrative
heavy component); 10 %/yr losses; 60-day fill; 920 kmol/h of NGL available.

Run: python examples/refrigerant_supply_worked_example.py
"""
from lng_design.refrigerant_supply import RefrigerantLoop, RefrigerantSupplyBasis, size_refrigerant_supply

loops = [RefrigerantLoop("C3 precool", {"Propane": 1.0}, charge_kg=16765.0),
         RefrigerantLoop("Mixed refrigerant",
                         {"Nitrogen": 0.05, "Methane": 0.38, "Ethane": 0.44, "Propane": 0.10, "n-Butane": 0.03},
                         charge_kmol=8000.0)]
d = size_refrigerant_supply(RefrigerantSupplyBasis(loops=loops, ngl_available_kmol_h=920.0))

print(f"Total refrigerant demand (charge + 1 yr make-up): {d.demand.total_kg / 1000:,.0f} t\n")
print(f"{'component':10s}{'demand t':>10s}{'x2.5 t':>9s}{'x2.75 t':>9s}{'x3.0 t':>9s}  storage")
for comp, kg in d.demand.by_component_kg.items():
    s = d.storage.get(comp)
    if s is None:
        print(f"{comp:10s}{kg / 1000:10.1f}   not stored (fuel gas / nitrogen system)")
        continue
    print(f"{comp:10s}{kg / 1000:10.1f}{s.capacity_range_kg[0] / 1000:9.1f}{s.capacity_kg / 1000:9.1f}"
          f"{s.capacity_range_kg[1] / 1000:9.1f}  {s.n_vessels} x {s.vessel.standard_diameter_mm:,.0f} mm x "
          f"{s.vessel.vessel_length_m:.1f} m, {s.design_pressure_Pa / 1e5:.1f} bar design at {s.design_T_K - 273.15:.0f} C"
          + (" (REFRIGERATED)" if s.needs_refrigeration else ""))
print(f"Total storage: {d.total_storage_m3:,.0f} m3, {d.total_capacity_kg / 1000:,.0f} t")

print(f"\nFractionation train feed: {sum(d.scaled_feed_kmol_h.values()):,.1f} kmol/h (x{d.feed_scale:.4f} of the reference NGL)")
print(f"{'product':9s}{'made kg/h':>11s}{'need kg/h':>11s}{'cover':>7s}{'fill d':>8s}  spec")
for k, p in d.production.items():
    print(f"{k:9s}{p.component_kg_h:11.1f}{p.required_kg_h:11.1f}{p.coverage:6.2f}x{d.fill_days_achieved[k]:8.1f}  "
          f"{'PASS' if p.spec.passed else 'FAIL ' + '; '.join(p.spec.violations)}")
print(f"\n{'column':13s}{'trays':>6s}{'D m':>6s}{'H m':>6s}{'Qc kW':>8s}{'Qr kW':>8s}  condenser")
for c in d.train.columns:
    print(f"{c.name:13s}{c.N_real:6d}{c.diameter_m:6.2f}{c.height_m:6.1f}{c.condenser_duty_kW:8,.0f}"
          f"{c.reboiler_duty_kW:8,.0f}  {c.condenser_service}")
print("\nNotes:")
for n in d.notes:
    print(" -", n)
