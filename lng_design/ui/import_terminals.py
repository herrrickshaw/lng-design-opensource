"""Import-terminal tabs: regasification terminal, LPG import, refrigerant supply.

Split out of terminals.py; behaviour unchanged.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lng_design.flowsheet import FlowsheetState
from lng_design.lpg_terminal import LPGTerminalBasis, size_lpg_import_terminal
from lng_design.refrigerant_supply import RefrigerantLoop, RefrigerantSupplyBasis, size_refrigerant_supply
from lng_design.regasification import RegasificationBasis, size_regasification_terminal
from lng_design.ui.common import comp_editor


def render_regasif(flowsheet: FlowsheetState) -> None:
    """Render the 'regasif' tab."""
    st.header("Regasification terminal: tanks, BOG and send-out")
    st.caption(
        "One entry point (lng_design/regasification.py) runs tank BOG (holding and unloading), the BOG "
        "compressors with a turndown check, the send-out pumps/ORV/SCV, and the recondenser at full AND "
        "turndown send-out, adding the direct-to-pipeline HP BOG compressor for whatever the recondenser "
        "cannot absorb. Takes ~15-30 s (real CoolProp mixture flashes)."
    )
    st.subheader("LNG composition (mole fraction)")
    rs_lng = comp_editor({"Methane": 0.92, "Ethane": 0.05, "Propane": 0.015,
                           "n-Butane": 0.005, "Nitrogen": 0.01}, "rs_lng")
    c1, c2, c3 = st.columns(3)
    with c1:
        rs_mtpa = st.number_input("Send-out (mtpa)", 0.5, 30.0, 5.0, 0.5, key="rs_mtpa")
        rs_P = st.number_input("Send-out pressure (bara)", 10.0, 150.0, 85.0, 5.0, key="rs_P")
        rs_T = st.number_input("Send-out temperature (C)", -10.0, 30.0, 5.0, 1.0, key="rs_T")
        rs_sw = st.number_input("Seawater inlet (C)", 0.0, 35.0, 20.0, 1.0, key="rs_sw")
    with c2:
        rs_vol = st.number_input("Net volume per tank (m3)", 10000.0, 300000.0, 160000.0, 10000.0, key="rs_vol")
        rs_n = st.number_input("Number of tanks", 1, 8, 2, key="rs_n")
        rs_baro = st.number_input("Barometric fall (Pa/h)", 0.0, 1000.0, 100.0, 25.0, key="rs_baro")
        rs_unl = st.number_input("Unloading rate (m3/h)", 1000.0, 20000.0, 12000.0, 1000.0, key="rs_unl")
    with c3:
        rs_ret = st.number_input("Vapor return to ship (fraction)", 0.0, 1.0, 0.40, 0.05, key="rs_ret")
        rs_op = st.number_input("BOG compressors operating", 1, 4, 2, key="rs_op")
        rs_sp = st.number_input("BOG compressors spare", 0, 2, 1, key="rs_sp")
        rs_td = st.number_input("Turndown send-out (fraction)", 0.1, 1.0, 0.25, 0.05, key="rs_td")

    if st.button("Size regasification terminal", type="primary", key="rs_go"):
        try:
            with st.spinner("Solving tanks, BOG compressors, pumps, vaporizers and recondenser..."):
                r = size_regasification_terminal(RegasificationBasis(
                    lng_composition=rs_lng, sendout_mtpa=rs_mtpa, sendout_pressure_Pa=rs_P * 1e5,
                    sendout_T_K=rs_T + 273.15, seawater_in_C=rs_sw, tank_net_volume_m3=rs_vol,
                    n_tanks=int(rs_n), barometric_fall_Pa_per_h=rs_baro,
                    unloading_rate_m3_h=rs_unl, vapor_return_fraction=rs_ret,
                    n_operating=int(rs_op), n_spare=int(rs_sp), turndown_sendout_fraction=rs_td))
            st.session_state["regas_design"] = r
            fs = flowsheet.set
            fs("tank_bog", {"Design BOG": f"{r.bog_design.design_bog_kg_s * 3.6:.1f} t/h ({r.bog_design.design_mode})",
                            "Static BOR": f"{r.bog_design.boil_off_rate_static_percent_per_day:.3f} %/d"})
            fs("bog_compressor", {"Machines": f"{r.bog_compressor.n_operating}+{r.bog_compressor.n_spare}",
                                  "Power": f"{r.bog_compressor.shaft_power_kW_per_machine:,.0f} kW each",
                                  "Stages": f"{r.bog_compressor.n_stages}"})
            fs("regas_train", {"Duty": f"{r.train.duty_kW / 1000:,.1f} MW",
                               "Pumps": f"{r.train.total_pump_shaft_kW:,.0f} kW",
                               "ORV": f"{r.train.orv.n_operating}+{r.train.orv.n_spare}"})
            fs("recondenser", {"LNG/BOG": f"{r.recondenser.lng_to_bog_mass_ratio:.1f} kg/kg",
                               "Max BOG": f"{r.recondenser.max_recondensable_bog_kg_s * 3.6:,.0f} t/h"})
        except Exception as e:
            st.error(str(e))

    r = st.session_state.get("regas_design")
    if r is not None:
        bd, comp, tr = r.bog_design, r.bog_compressor, r.train
        a, b, c, e = st.columns(4)
        a.metric("Design BOG", f"{bd.design_bog_kg_s * 3.6:.1f} t/h")
        b.metric("Vaporizer duty", f"{tr.duty_kW / 1000:,.1f} MW")
        c.metric("Installed power", f"{r.installed_power_kW / 1000:,.1f} MW")
        e.metric("Excess BOG at turndown", f"{r.excess_bog_at_turndown_kg_s * 3.6:.1f} t/h")

        st.subheader("BOG by source (design case)")
        src = pd.DataFrame({
            "Source": ["Static heat ingress", "Pump heat", "Barometric fall", "Vapor displacement",
                       "Arrival flash"],
            "BOG (t/h)": [bd.static_bog_kg_s * 3.6, bd.pump_bog_kg_s * 3.6, bd.barometric_bog_kg_s * 3.6,
                          bd.displacement_bog_kg_s * 3.6, bd.flash_bog_kg_s * 3.6]})
        st.plotly_chart(go.Figure(go.Bar(x=src["Source"], y=src["BOG (t/h)"])).update_layout(
            yaxis_title="BOG (t/h)", height=280, margin=dict(t=20)), use_container_width=True)

        rows = [
            ("Tanks", f"{r.basis.n_tanks} x {r.basis.tank_net_volume_m3:,.0f} m3: D {r.tank.inner_diameter_m:.1f} m, liquid H {r.tank.liquid_height_m:.1f} m; static BOR {bd.boil_off_rate_static_percent_per_day:.3f} %/d"),
            ("BOG (holding / design)", f"{r.bog_holding.design_bog_kg_s * 3.6:.1f} / {bd.design_bog_kg_s * 3.6:.1f} t/h; N2 in BOG {bd.bog_composition.get('Nitrogen', 0) * 100:.1f} mol%"),
            ("BOG compressors", f"{comp.n_operating}+{comp.n_spare} x {comp.shaft_power_kW_per_machine:,.0f} kW, {comp.n_stages} stages, discharge {comp.discharge_T_K - 273.15:.0f} C; {comp.machine_note}"),
            ("Holding-mode turndown", f"{r.holding_fraction_of_machine * 100:.0f} % of one machine ({'ok' if r.holding_within_turndown else 'BELOW stable minimum'})"),
            ("LP / HP pumps", f"{tr.lp_pump.shaft_kW:,.0f} / {tr.hp_pump.shaft_kW:,.0f} kW (HP +{tr.hp_pump.temperature_rise_K:.1f} K)"),
            ("Vaporizer", f"{tr.duty_kW / 1000:,.1f} MW ({tr.duty_kJ_per_kg:,.0f} kJ/kg)"),
            ("ORV bank", f"{tr.orv.n_operating}+{tr.orv.n_spare} units, seawater {tr.orv.seawater_flow_t_h:,.0f} t/h; {tr.orv.note}"),
            ("SCV backup", f"{tr.scv.n_operating}+{tr.scv.n_spare} units, fuel {tr.scv.fuel_fraction_of_sendout * 100:.2f} % of send-out"),
            ("Recondenser (full send-out)", f"{r.recondenser.lng_to_bog_mass_ratio:.1f} kg LNG/kg BOG, absorbs up to {r.recondenser.max_recondensable_bog_kg_s * 3.6:,.0f} t/h"),
            (f"Recondenser ({r.basis.turndown_sendout_fraction * 100:.0f} % send-out)", f"absorbs up to {r.recondenser_turndown.max_recondensable_bog_kg_s * 3.6:,.0f} t/h; excess {r.excess_bog_at_turndown_kg_s * 3.6:.1f} t/h"),
        ]
        if r.hp_bog_compressor:
            hp = r.hp_bog_compressor
            rows.append(("HP BOG compressor (excess)", f"{hp.n_stages} stages, {hp.shaft_power_kW_per_machine:,.0f} kW, discharge {hp.discharge_T_K - 273.15:.0f} C w/o intercooling"))
        st.dataframe(pd.DataFrame(rows, columns=["Item", "Result"]), use_container_width=True, hide_index=True)
        for n in r.notes:
            st.warning(n)
        st.caption("The Process Flow Diagram tab now shows these results.")


def render_lpg(flowsheet: FlowsheetState) -> None:
    """Render the 'lpg' tab."""
    st.header("LPG import terminal: refrigerated storage, BOG re-liquefaction, send-out")
    st.caption(
        "Fully-refrigerated propane/butane import (lng_design/lpg_terminal.py). Differences from LNG that drive "
        "the design: BOG is compressed and CONDENSED (the flash on let-down to the cold tank multiplies the "
        "compressor flow by 1/(1-f)), send-out is a liquid pumped and heated (no vaporization), and tank heat "
        "ingress is small. Insulation, unloading rate, contingency and efficiencies are assumptions."
    )
    st.subheader("LPG composition (mole fraction)")
    lp_comp = comp_editor({"Propane": 0.95, "n-Butane": 0.05, "Isobutane": 0.0, "Ethane": 0.0}, "lp_comp")
    c1, c2, c3 = st.columns(3)
    with c1:
        lp_mtpa = st.number_input("Throughput (mtpa)", 0.1, 5.0, 1.0, 0.1, key="lp_mtpa")
        lp_cargo = st.number_input("Cargo size (m3)", 5000.0, 100000.0, 84000.0, 1000.0, key="lp_cargo")
        lp_n = st.number_input("Number of tanks", 1, 6, 2, key="lp_n")
    with c2:
        lp_unl = st.number_input("Unloading rate (m3/h)", 500.0, 6000.0, 3000.0, 250.0, key="lp_unl")
        lp_ret = st.number_input("Vapor return to ship (fraction)", 0.0, 1.0, 0.50, 0.05, key="lp_ret")
        lp_cond = st.number_input("BOG condensing temperature (C)", 30.0, 70.0, 45.0, 1.0, key="lp_cond")
    with c3:
        lp_sub = st.checkbox("Sub-cool condensed BOG by refrigeration", value=False, key="lp_sub")
        lp_subT = st.number_input("Sub-cool to (C)", -30.0, 40.0, 10.0, 5.0, key="lp_subT", disabled=not lp_sub)
        lp_dP = st.number_input("Delivery pressure (bara)", 5.0, 60.0, 20.0, 5.0, key="lp_dP")
        lp_dT = st.number_input("Delivery temperature (C)", -10.0, 40.0, 5.0, 1.0, key="lp_dT")

    if st.button("Size LPG import terminal", type="primary", key="lp_go"):
        try:
            lp = size_lpg_import_terminal(LPGTerminalBasis(
                composition={k: v for k, v in lp_comp.items() if v > 0}, throughput_mtpa=lp_mtpa,
                cargo_m3=lp_cargo, n_tanks=int(lp_n), unloading_rate_m3_h=lp_unl,
                vapor_return_fraction=lp_ret, condensing_T_K=lp_cond + 273.15,
                subcool_to_K=(lp_subT + 273.15) if lp_sub else None,
                delivery_pressure_Pa=lp_dP * 1e5, delivery_T_K=lp_dT + 273.15))
            st.session_state["lpg_design"] = lp
            rl0 = lp.reliquefaction
            fs = flowsheet.set
            fs("lpg_tank", {"Volume": f"{lp.storage.n_tanks} x {lp.storage.per_tank_m3:,.0f} m3",
                            "Temp": f"{lp.tank_state.temperature_K - 273.15:.1f} C",
                            "Design BOG": f"{lp.bog_design.design_bog_kg_s * 3.6:.1f} t/h"})
            fs("lpg_bog_compressor", {"Power": f"{rl0.compressor.shaft_power_kW_per_machine:,.0f} kW each",
                                      "Stages": f"{rl0.compressor.n_stages}",
                                      "Recycle": f"{rl0.recycle_factor:.2f}x"})
            fs("lpg_condenser", {"Condense": f"{rl0.condensing_T_K - 273.15:.0f} C / {rl0.condensing_P_Pa / 1e5:.1f} bar",
                                 "Rejection": f"{rl0.total_heat_rejection_kW:,.0f} kW"})
            fs("lpg_pump", {"Power": f"{lp.pump.shaft_kW:,.0f} kW"})
            fs("lpg_heater", {"Duty": f"{lp.heater.duty_kW:,.0f} kW",
                              "Out": f"{lp.heater.outlet_T_K - 273.15:.0f} C"})
        except Exception as e:
            st.error(str(e))

    lp = st.session_state.get("lpg_design")
    if lp is not None:
        rl, bd = lp.reliquefaction, lp.bog_design
        a, b, c, e = st.columns(4)
        a.metric("Storage temperature", f"{lp.tank_state.temperature_K - 273.15:.1f} C")
        b.metric("Design BOG", f"{bd.design_bog_kg_s * 3.6:.1f} t/h")
        c.metric("Re-liquefaction flash / recycle", f"{rl.flash_fraction * 100:.0f} % / {rl.recycle_factor:.2f}x")
        e.metric("Installed power", f"{lp.installed_power_kW / 1000:,.2f} MW")
        src = pd.DataFrame({
            "Source": ["Static heat ingress", "Pump heat", "Barometric fall", "Vapor displacement", "Arrival flash"],
            "BOG (t/h)": [bd.static_bog_kg_s * 3.6, bd.pump_bog_kg_s * 3.6, bd.barometric_bog_kg_s * 3.6,
                          bd.displacement_bog_kg_s * 3.6, bd.flash_bog_kg_s * 3.6]})
        st.plotly_chart(go.Figure(go.Bar(x=src["Source"], y=src["BOG (t/h)"])).update_layout(
            yaxis_title="BOG (t/h)", height=260, margin=dict(t=20)), use_container_width=True)
        rows = [
            ("Product", f"{lp.tank_state.temperature_K - 273.15:.1f} C at {lp.basis.tank_pressure_Pa / 1e5:.2f} bara, "
                        f"{lp.tank_state.liquid_density_kg_m3:.0f} kg/m3; vapor pressure {lp.vapor_pressure_at_ambient_Pa / 1e5:.1f} bar at "
                        f"{lp.basis.ambient_T_K - 273.15:.0f} C ambient"),
            ("Storage", f"{lp.storage.n_tanks} x {lp.storage.per_tank_m3:,.0f} m3 ({lp.storage.cargoes_equivalent:.2f} cargoes): "
                        f"cargo {lp.storage.cargo_m3:,.0f} + contingency {lp.storage.contingency_m3:,.0f} + heel {lp.storage.heel_m3:,.0f} m3"),
            ("Tank geometry", f"D {lp.tank.inner_diameter_m:.1f} m, liquid H {lp.tank.liquid_height_m:.1f} m; static BOR {lp.bog_holding.boil_off_rate_static_percent_per_day:.3f} %/d"),
            ("BOG (holding / design)", f"{lp.bog_holding.design_bog_kg_s * 3.6:.1f} / {bd.design_bog_kg_s * 3.6:.1f} t/h"),
            ("Re-liquefaction", f"condense at {rl.condensing_T_K - 273.15:.0f} C = {rl.condensing_P_Pa / 1e5:.1f} bar; compress {rl.compressed_flow_kg_s * 3.6:.1f} t/h "
                                f"in {rl.compressor.n_stages} stages, {rl.compressor.shaft_power_kW_per_machine:,.0f} kW each ({rl.compressor.n_operating}+{rl.compressor.n_spare}); "
                                f"{rl.compressor.machine_note}"),
            ("Heat rejection / specific power", f"{rl.total_heat_rejection_kW:,.0f} kW; {rl.specific_power_kWh_per_t:.0f} kWh per t BOG" +
                                                (f"; sub-cooler {rl.subcooler_duty_kW:,.0f} kW" if rl.subcooler_duty_kW else "")),
            ("Berth", f"utilization {lp.berth.utilization * 100:.0f} %, P(wait) {lp.berth.probability_of_waiting * 100:.0f} %, expected wait {lp.berth.expected_wait_hours:.1f} h"),
            ("Send-out pump", f"{lp.pump.shaft_kW:,.0f} kW, {lp.pump.volumetric_flow_m3_h:,.0f} m3/h, +{lp.pump.temperature_rise_K:.2f} K"),
            ("Send-out heater", f"{lp.heater.duty_kW:,.0f} kW ({lp.heater.inlet_T_K - 273.15:.0f} -> {lp.heater.outlet_T_K - 273.15:.0f} C), medium {lp.heater.medium_flow_t_h:,.0f} t/h"),
        ]
        st.dataframe(pd.DataFrame(rows, columns=["Item", "Result"]), use_container_width=True, hide_index=True)
        for n in lp.notes:
            st.warning(n)


def render_refsup(flowsheet: FlowsheetState) -> None:
    """Render the 'refsup' tab."""
    st.header("Refrigerant storage (2.5-3x demand) and ethane / propane / butane production")
    st.caption(
        "lng_design/refrigerant_supply.py. Demand = every loop's charge plus make-up; each liquid component is "
        "stored at the chosen multiple of demand as pressurized bullets, and a deethanizer / depropanizer / "
        "debutanizer train is scaled so the scarcest product fills its storage in the fill time. Ethane cannot "
        "be stored at ambient (critical temperature 32 C) so it is stored cold. Loss rate, fill time and the "
        "refrigerant-grade specs are assumptions."
    )
    c1, c2, c3 = st.columns(3)
    rf_c3 = c1.number_input("C3 precool charge (kg propane)", 1000.0, 500000.0, 16765.0, 1000.0, key="rf_c3")
    rf_mr = c2.number_input("Mixed-refrigerant charge (kmol)", 500.0, 100000.0, 8000.0, 500.0, key="rf_mr")
    rf_fac = c3.slider("Storage factor (x total demand)", 2.5, 3.0, 2.75, 0.05, key="rf_fac")
    c1, c2, c3 = st.columns(3)
    rf_loss = c1.number_input("Annual loss fraction", 0.0, 0.5, 0.10, 0.01, key="rf_loss")
    rf_fill = c2.number_input("Fill time (days)", 5.0, 365.0, 60.0, 5.0, key="rf_fill")
    rf_avail = c3.number_input("NGL available (kmol/h, 0 = unknown)", 0.0, 20000.0, 920.0, 10.0, key="rf_avail")
    st.subheader("Mixed-refrigerant composition (mole fraction)")
    rf_comp = comp_editor({"Nitrogen": 0.05, "Methane": 0.38, "Ethane": 0.44, "Propane": 0.10, "n-Butane": 0.03}, "rf_comp")

    if st.button("Size refrigerant storage and supply", type="primary", key="rf_go"):
        try:
            d = size_refrigerant_supply(RefrigerantSupplyBasis(
                loops=[RefrigerantLoop("C3 precool", {"Propane": 1.0}, charge_kg=rf_c3),
                       RefrigerantLoop("Mixed refrigerant", {k: v for k, v in rf_comp.items() if v > 0},
                                       charge_kmol=rf_mr)],
                storage_factor=rf_fac, annual_loss_fraction=rf_loss, fill_days=rf_fill,
                ngl_available_kmol_h=rf_avail if rf_avail > 0 else None))
            st.session_state["ref_supply"] = d
            for key, data in d.flowsheet_state().items():
                flowsheet.set(key, data)
            for key, col in zip(("deethanizer", "depropanizer", "debutanizer"), d.train.columns):
                flowsheet.set(key, {"Trays": f"{col.N_real}",
                                    "D x H": f"{col.diameter_m:.2f} x {col.height_m:.1f} m",
                                    "Qc/Qr": f"{col.condenser_duty_kW:,.0f}/{col.reboiler_duty_kW:,.0f} kW"})
        except Exception as e:
            st.error(str(e))

    d = st.session_state.get("ref_supply")
    if d is not None:
        a, b, c, e = st.columns(4)
        a.metric("Total refrigerant demand", f"{d.demand.total_kg / 1000:,.0f} t")
        b.metric("Storage capacity", f"{d.total_capacity_kg / 1000:,.0f} t")
        c.metric("Storage volume", f"{d.total_storage_m3:,.0f} m3")
        e.metric("Train feed", f"{sum(d.scaled_feed_kmol_h.values()):,.1f} kmol/h")
        st.subheader("Demand and storage by component")
        rows = []
        for comp, kg in d.demand.by_component_kg.items():
            s = d.storage.get(comp)
            rows.append({
                "Component": comp, "Demand (t)": round(kg / 1000, 1),
                "Capacity (t)": round(s.capacity_kg / 1000, 1) if s else "not stored",
                "2.5-3x range (t)": f"{s.capacity_range_kg[0] / 1000:,.0f}-{s.capacity_range_kg[1] / 1000:,.0f}" if s else "-",
                "Vessels": f"{s.n_vessels} x {s.vessel.standard_diameter_mm:,.0f} mm x {s.vessel.vessel_length_m:.1f} m" if s else "-",
                "Design": (f"{s.design_pressure_Pa / 1e5:.1f} bar at {s.design_T_K - 273.15:.0f} C"
                           + (" (refrigerated)" if s.needs_refrigeration else "")) if s else "-"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.subheader("Fractionation: products vs storage fill")
        st.dataframe(pd.DataFrame([{
            "Product": k, "Produced (kg/h)": round(p.component_kg_h, 1), "Required (kg/h)": round(p.required_kg_h, 1),
            "Coverage": f"{p.coverage:.2f}x", "Fill time (d)": round(d.fill_days_achieved[k], 1),
            "Spec": "PASS" if p.spec.passed else "FAIL: " + "; ".join(p.spec.violations)}
            for k, p in d.production.items()]), use_container_width=True, hide_index=True)
        st.dataframe(pd.DataFrame([{
            "Column": c.name, "Trays": c.N_real, "D (m)": round(c.diameter_m, 2), "H (m)": round(c.height_m, 1),
            "Qc (kW)": round(c.condenser_duty_kW), "Qr (kW)": round(c.reboiler_duty_kW),
            "Condenser": c.condenser_service} for c in d.train.columns]),
            use_container_width=True, hide_index=True)
        for n in d.notes:
            st.info(n)
