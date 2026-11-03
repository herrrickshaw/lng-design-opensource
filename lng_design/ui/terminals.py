"""Terminal-scale tabs: regas and BOG, fractionation, liquefaction, regasification, LPG import, refrigerant supply.

Mechanically split out of streamlit_app.py; behaviour unchanged.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lng_design.bog_compressor import size_bog_compressor, turndown_check
from lng_design.flowsheet import FlowsheetState
from lng_design.fractionation import ColumnSpec, size_fractionation_train
from lng_design.liquefaction import LiquefactionBasis, size_liquefaction_train
from lng_design.refrigerant_generation import ProductSpec, blend_mixed_refrigerant, check_product_spec
from lng_design.regas_terminal import heating_curve, size_recondenser, size_regas_train
from lng_design.tank_bog import compute_bog, size_tank_geometry
from lng_design.ui.common import comp_editor
from lng_design.ui.import_terminals import render_lpg, render_refsup, render_regasif


def _regas_tank_tab(flowsheet: FlowsheetState, lng_x: dict) -> None:
    """Tank & BOG sub-tab of the regas tab."""
    c1, c2, c3 = st.columns(3)
    with c1:
        t_vol = st.number_input("Net volume per tank (m3)", 10000.0, 300000.0, 160000.0, 10000.0, key="rg_vol")
        t_n = st.number_input("Number of tanks", 1, 8, 2, key="rg_n")
        t_hd = st.number_input("Liquid height / diameter", 0.2, 1.0, 0.40, 0.05, key="rg_hd")
    with c2:
        t_p = st.number_input("Tank pressure (bara)", 1.02, 1.5, 1.15, 0.01, key="rg_p")
        t_fill = st.number_input("Fill fraction", 0.1, 1.0, 0.90, 0.05, key="rg_fill")
        t_pump = st.number_input("Pump heat into LNG, total (kW)", 0.0, 2000.0, 250.0, 25.0, key="rg_pump")
    with c3:
        t_baro = st.number_input("Barometric fall (Pa/h)", 0.0, 1000.0, 100.0, 25.0, key="rg_baro")
        t_unl = st.number_input("Unloading rate (m3/h, 0 = holding)", 0.0, 20000.0, 12000.0, 1000.0, key="rg_unl")
        t_ret = st.number_input("Vapor return to ship (fraction)", 0.0, 1.0, 0.40, 0.05, key="rg_ret")
    t_warm = st.number_input("Arriving LNG warmer than tank saturation (K, 0 = no flash)", 0.0, 5.0, 0.5, 0.1, key="rg_warm")
    if st.button("Compute BOG", type="primary", key="rg_go"):
        try:
            geom = size_tank_geometry(t_vol, t_hd)
            from lng_design.tank_bog import tank_liquid_state
            st0 = tank_liquid_state(lng_x, t_p * 1e5)
            kw = dict(n_tanks=int(t_n), fill_fraction=t_fill, pump_heat_total_kW=t_pump,
                      barometric_fall_Pa_per_h=t_baro, unloading_rate_m3_h=t_unl,
                      vapor_return_fraction=t_ret)
            if t_warm > 0 and t_unl > 0:
                kw.update(arriving_T_K=st0.temperature_K + t_warm, arriving_P_Pa=3.0e5)
            res = compute_bog(lng_x, t_p * 1e5, geom, **kw)
            st.session_state["rg_bog"] = res
            flowsheet.set("tank_bog", {
                "Design BOG": f"{res.design_bog_kg_s * 3.6:.1f} t/h ({res.design_mode})",
                "Static BOR": f"{res.boil_off_rate_static_percent_per_day:.3f} %/d",
            })
            a, b, c, d = st.columns(4)
            a.metric("Tank D x liquid H", f"{geom.inner_diameter_m:.1f} x {geom.liquid_height_m:.1f} m")
            b.metric("Static BOR", f"{res.boil_off_rate_static_percent_per_day:.3f} %/d")
            c.metric(f"Design BOG ({res.design_mode})", f"{res.design_bog_kg_s * 3.6:.1f} t/h")
            d.metric("BOG nitrogen", f"{res.bog_composition.get('Nitrogen', 0) * 100:.1f} mol%")
            df = pd.DataFrame({
                "Source": ["Static heat ingress", "Pump heat", "Barometric fall",
                           "Vapor displacement", "Arrival flash"],
                "BOG (t/h)": [res.static_bog_kg_s * 3.6, res.pump_bog_kg_s * 3.6,
                              res.barometric_bog_kg_s * 3.6, res.displacement_bog_kg_s * 3.6,
                              res.flash_bog_kg_s * 3.6]})
            st.plotly_chart(go.Figure(go.Bar(x=df["Source"], y=df["BOG (t/h)"])).update_layout(
                yaxis_title="BOG (t/h)", height=300, margin=dict(t=20)), use_container_width=True)
            st.caption(f"Latent heat of the boil-off {res.liquid_state.latent_heat_J_kg/1e3:.0f} kJ/kg, "
                       f"BOG MW {res.liquid_state.bog_molecular_weight_g_mol:.1f} g/mol; "
                       "the ~0.05 %/d vendor figure is an output to compare against, not an input.")
        except Exception as e:
            st.error(str(e))


def _regas_compressor_tab(flowsheet: FlowsheetState) -> None:
    """BOG compressor sub-tab of the regas tab."""
    bog = st.session_state.get("rg_bog")
    if bog is None:
        st.info("Compute BOG on the Tank & BOG tab first - the compressor is sized on its design flow and composition.")
    else:
        c1, c2, c3 = st.columns(3)
        with c1:
            cp_suc = st.number_input("Suction pressure (bara)", 1.0, 1.5, 1.10, 0.01, key="bc_ps")
            cp_dis = st.number_input("Discharge pressure (bara)", 2.0, 100.0, 9.0, 0.5, key="bc_pd")
        with c2:
            cp_T = st.number_input("Suction temperature (K)", 120.0, 320.0, 143.15, 5.0, key="bc_T")
            cp_marg = st.number_input("Capacity margin", 0.0, 0.5, 0.10, 0.05, key="bc_m")
        with c3:
            cp_op = st.number_input("Operating machines", 1, 4, 2, key="bc_op")
            cp_sp = st.number_input("Spare machines", 0, 2, 1, key="bc_sp")
        if st.button("Size BOG compressors", type="primary", key="bc_go"):
            try:
                r = size_bog_compressor(bog.bog_composition, bog.design_bog_kg_s, cp_suc * 1e5,
                                        cp_dis * 1e5, cp_T, cp_marg, int(cp_op), int(cp_sp))
                a, b, c, d = st.columns(4)
                a.metric("Stages", f"{r.n_stages} @ PR {r.stage_pressure_ratio:.2f}")
                b.metric("Shaft power / machine", f"{r.shaft_power_kW_per_machine:,.0f} kW")
                c.metric("Discharge T", f"{r.discharge_T_K - 273.15:.0f} C")
                d.metric("Inlet flow / machine", f"{r.inlet_volume_flow_per_machine_m3_h:,.0f} m3/h")
                st.write(r.machine_note)
                flowsheet.set("bog_compressor", {
                    "Machines": f"{r.n_operating}+{r.n_spare}",
                    "Power": f"{r.shaft_power_kW_per_machine:,.0f} kW each",
                    "Stages": f"{r.n_stages}",
                })
                frac, ok = turndown_check(bog.holding_bog_kg_s, r.flow_per_machine_kg_s)
                (st.success if ok else st.warning)(
                    f"Holding-mode BOG is {frac*100:.0f}% of one machine's rating "
                    f"({'within' if ok else 'BELOW'} an assumed 60% stable turndown).")
            except ValueError as e:
                st.error(str(e))


def _regas_sendout_tab(flowsheet: FlowsheetState, lng_x: dict) -> None:
    """Send-out train sub-tab of the regas tab."""
    c1, c2, c3 = st.columns(3)
    with c1:
        so_mtpa = st.number_input("Send-out (mtpa)", 0.5, 30.0, 5.0, 0.5, key="so_m")
        so_p = st.number_input("Send-out pressure (bara)", 10.0, 150.0, 85.0, 5.0, key="so_p")
    with c2:
        so_T = st.number_input("Send-out temperature (C)", -10.0, 30.0, 5.0, 1.0, key="so_T")
        so_sw = st.number_input("Seawater inlet (C)", 0.0, 35.0, 20.0, 1.0, key="so_sw")
    with c3:
        so_lp = st.number_input("LP pump discharge (bara)", 5.0, 20.0, 10.0, 1.0, key="so_lp")
        so_dT = st.number_input("Allowed seawater drop (K)", 1.0, 10.0, 5.0, 0.5, key="so_dT")
    if st.button("Size send-out train", type="primary", key="so_go"):
        try:
            with st.spinner("Solving pump, vaporizer and recondenser states..."):
                from lng_design.tank_bog import tank_liquid_state
                st0 = tank_liquid_state(lng_x, 1.15e5)
                m = so_mtpa * 1e9 / (365.25 * 24 * 3600)
                r = size_regas_train(lng_x, m, 1.15e5, st0.temperature_K, so_lp * 1e5, so_p * 1e5,
                                     so_T + 273.15, so_sw, seawater_dT_K=so_dT)
                a, b, c, d = st.columns(4)
                a.metric("Pump shaft (LP+HP)", f"{r.total_pump_shaft_kW:,.0f} kW")
                b.metric("Vaporizer duty", f"{r.duty_kW/1000:,.1f} MW ({r.duty_kJ_per_kg:,.0f} kJ/kg)")
                c.metric("ORV units", f"{r.orv.n_operating} + {r.orv.n_spare}")
                d.metric("SCV fuel gas", f"{r.scv.fuel_fraction_of_sendout*100:.2f}% of send-out")
                flowsheet.set("regas_train", {
                    "Duty": f"{r.duty_kW / 1000:,.1f} MW",
                    "Pumps": f"{r.total_pump_shaft_kW:,.0f} kW",
                    "ORV": f"{r.orv.n_operating}+{r.orv.n_spare}",
                })
                st.write(f"Seawater {r.orv.seawater_flow_t_h:,.0f} t/h, {so_sw:.0f} -> {r.orv.seawater_outlet_C:.0f} C. "
                     + r.orv.note)
                T, Q = heating_curve(lng_x, so_p * 1e5, r.hp_pump.outlet_T_K, so_T + 273.15, m, n_points=60)
                st.plotly_chart(go.Figure(go.Scatter(x=Q / 1000.0, y=T - 273.15)).update_layout(
                    xaxis_title="Cumulative duty (MW)", yaxis_title="LNG/gas temperature (C)",
                    height=300, margin=dict(t=20)), use_container_width=True)
                bg = st.session_state.get("rg_bog")
                if bg is not None:
                    rc = size_recondenser(lng_x, r.lp_pump.outlet_T_K, bg.bog_composition, 240.0,
                                          bg.design_bog_kg_s, so_lp * 1e5 - 1e5, m)
                    flowsheet.set("recondenser", {
                        "LNG/BOG": f"{rc.lng_to_bog_mass_ratio:.1f} kg/kg",
                        "Max BOG": f"{rc.max_recondensable_bog_kg_s * 3.6:,.0f} t/h",
                    })
                    st.write(f"Recondenser: {rc.lng_to_bog_mass_ratio:.1f} kg LNG per kg BOG; can absorb "
                         f"{rc.max_recondensable_bog_kg_s*3.6:,.0f} t/h vs design BOG "
                         f"{bg.design_bog_kg_s*3.6:.1f} t/h; excess {rc.excess_bog_kg_s*3.6:.1f} t/h.")
        except Exception as e:
            st.error(str(e))


def render_regas(flowsheet: FlowsheetState) -> None:
    """Render the 'regas' tab."""
    st.header("Regasification terminal: tank BOG, BOG compressor, send-out train")
    st.caption(
        "CoolProp mixture thermodynamics throughout. BOG is computed by source "
        "(heat ingress, pump heat, unloading displacement + flash, barometric fall) "
        "on the equilibrium vapor composition. See lng_design/tank_bog.py, "
        "bog_compressor.py, regas_terminal.py."
    )
    lng_x = comp_editor({"Methane": 0.92, "Ethane": 0.05, "Propane": 0.015,
                          "n-Butane": 0.005, "Nitrogen": 0.01}, "rg")
    r_tank, r_comp, r_send = st.tabs(["Tank & BOG", "BOG Compressor", "Send-out Train"])

    with r_tank:
        _regas_tank_tab(flowsheet, lng_x)
    with r_comp:
        _regas_compressor_tab(flowsheet)
    with r_send:
        _regas_sendout_tab(flowsheet, lng_x)


def _frac_column_tab(flowsheet: FlowsheetState) -> None:
    """Column train sub-tab of the frac tab."""
    st.subheader("NGL feed (kmol/h)")
    ngl_defaults = {"Ethane": 320.0, "Propane": 300.0, "Isobutane": 60.0, "n-Butane": 100.0,
                    "Isopentane": 50.0, "Pentane": 50.0, "Hexane": 40.0}
    cols = st.columns(len(ngl_defaults))
    ngl_feed = {n: c.number_input(n, 0.0, 5000.0, v, 10.0, key=f"fr_{n}")
                for (n, v), c in zip(ngl_defaults.items(), cols)}
    st.subheader("Columns (top pressure bara, key recoveries)")
    defaults = [("deethanizer", "Ethane", "Propane", 26.0, 0.98, 0.995),
                ("depropanizer", "Propane", "Isobutane", 17.0, 0.985, 0.98),
                ("debutanizer", "n-Butane", "Isopentane", 6.0, 0.98, 0.98)]
    specs = []
    for i, (nm, lk, hk, p, rl, rh) in enumerate(defaults):
        a, b, c, d, e = st.columns([2, 1, 1, 1, 1])
        a.markdown(f"**{nm}**  ({lk} / {hk})")
        pp = b.number_input("P top", 1.0, 40.0, p, 0.5, key=f"fp_{i}")
        r1 = c.number_input("LK rec.", 0.6, 0.999, rl, 0.005, key=f"fl_{i}", format="%.3f")
        r2 = d.number_input("HK rec.", 0.6, 0.999, rh, 0.005, key=f"fh_{i}", format="%.3f")
        rf = e.number_input("R/Rmin", 1.05, 2.0, 1.2, 0.05, key=f"fr_rf_{i}")
        specs.append(ColumnSpec(nm, lk, hk, pp * 1e5, r1, r2, reflux_factor=rf))
    if st.button("Size fractionation train", type="primary", key="fr_go"):
        try:
            tr = size_fractionation_train({k: v for k, v in ngl_feed.items() if v > 0}, specs)
            st.session_state["frac_train"] = tr
            for key, c in zip(("deethanizer", "depropanizer", "debutanizer"), tr.columns):
                flowsheet.set(key, {
                    "Trays": f"{c.N_real}",
                    "D x H": f"{c.diameter_m:.2f} x {c.height_m:.1f} m",
                    "Qc/Qr": f"{c.condenser_duty_kW:,.0f}/{c.reboiler_duty_kW:,.0f} kW",
                })
            st.dataframe(pd.DataFrame([{
                "Column": c.name, "N min": round(c.N_min, 1), "R min": round(c.R_min, 2),
                "R": round(c.R, 2), "Theor. stages": round(c.N_theoretical, 1),
                "Trays": c.N_real, "Feed tray": c.feed_tray_from_top,
                "Eo": round(c.tray_efficiency, 2), "D (m)": round(c.diameter_m, 2),
                "H (m)": round(c.height_m, 1), "T top (K)": round(c.T_top_K, 1),
                "Qc (kW)": round(c.condenser_duty_kW), "Qr (kW)": round(c.reboiler_duty_kW),
                "Condenser": c.condenser_service} for c in tr.columns]),
                use_container_width=True, hide_index=True)
            for c in tr.columns:
                for n in c.notes:
                    st.info(f"{c.name}: {n}")
            st.caption(f"Train mole balance error {tr.mass_balance_error:.1e}")
            for c in tr.columns:
                st.write(f"**{c.name} distillate:** " + ", ".join(
                    f"{k} {v*100:.2f}%" for k, v in c.distillate_mole_fractions.items() if v > 5e-4))
        except Exception as e:
            st.error(str(e))


def _frac_blend_tab(flowsheet: FlowsheetState) -> None:
    """Refrigerant blend sub-tab of the frac tab."""
    tr = st.session_state.get("frac_train")
    if tr is None:
        st.info("Size the column train first - its ethane and propane distillates are the blend sources.")
    else:
        st.subheader("Target mixed refrigerant (mole fraction)")
        mr = comp_editor({"Nitrogen": 0.05, "Methane": 0.40, "Ethane": 0.45, "Propane": 0.10}, "mr")
        st.subheader("Propane-refrigerant spec (assumed - use your licensor's)")
        a, b = st.columns(2)
        s_c3 = a.number_input("Min propane", 0.5, 1.0, 0.95, 0.01, key="sp_c3")
        s_c2 = b.number_input("Max ethane", 0.0, 0.2, 0.02, 0.005, key="sp_c2", format="%.3f")
        if st.button("Check specs and blend", type="primary", key="mr_go"):
            try:
                dp = tr.columns[1].distillate_mole_fractions
                chk = check_product_spec(dp, ProductSpec(
                    "propane refrigerant", {"Propane": s_c3}, {"Ethane": s_c2}))
                (st.success if chk.passed else st.error)(
                    f"Propane distillate: {'PASS' if chk.passed else 'FAIL'}. " + "; ".join(chk.violations))
                src = {"nitrogen": {"Nitrogen": 1.0}, "methane": {"Methane": 1.0},
                       "ethane distillate": tr.columns[0].distillate_mole_fractions,
                       "propane distillate": dp}
                bl = blend_mixed_refrigerant(mr, src)
                st.dataframe(pd.DataFrame({"Source": list(bl.source_kmol_per_kmol_mr),
                                           "kmol / kmol MR": [round(v, 4) for v in bl.source_kmol_per_kmol_mr.values()]}),
                             hide_index=True)
                flowsheet.set("mr_blend", {
                    "Propane spec": "PASS" if chk.passed else "FAIL",
                    "Blend error": f"{bl.max_abs_error:.4f}",
                })
                (st.success if bl.reachable else st.warning)(
                    f"Max composition error {bl.max_abs_error:.4f} "
                    f"({'reachable' if bl.reachable else 'target NOT reachable from these sources'})")
            except Exception as e:
                st.error(str(e))


def render_frac(flowsheet: FlowsheetState) -> None:
    """Render the 'frac' tab."""
    st.header("NGL fractionation: distillate columns and refrigerant generation")
    st.caption(
        "Fenske-Underwood-Gilliland shortcut with CoolProp K-values (lng_design/fractionation.py). "
        "Stage counts are +/-10-15% - confirm in a rigorous simulator."
    )
    f_col, f_ref = st.tabs(["Column train", "Refrigerant blend"])
    with f_col:
        _frac_column_tab(flowsheet)
    with f_ref:
        _frac_blend_tab(flowsheet)


def _liq_ngl_options() -> dict:
    """Fractionation + MR-blend options added to the liquefaction basis when the NGL box is ticked."""
    return dict(
        ngl_feed_kmol_h={"Ethane": 320.0, "Propane": 300.0, "Isobutane": 60.0,
                         "n-Butane": 100.0, "Isopentane": 50.0, "Pentane": 50.0, "Hexane": 40.0},
        fractionation_specs=[ColumnSpec("deethanizer", "Ethane", "Propane", 26e5, 0.98, 0.995),
                             ColumnSpec("depropanizer", "Propane", "Isobutane", 17e5, 0.985, 0.98),
                             ColumnSpec("debutanizer", "n-Butane", "Isopentane", 6e5, 0.98, 0.98)],
        mr_target={"Nitrogen": 0.05, "Methane": 0.40, "Ethane": 0.45, "Propane": 0.10})


def _liq_update_flowsheet(flowsheet: FlowsheetState, d) -> None:
    """Push the liquefaction-train results into the process flow diagram."""
    fs = flowsheet.set
    fs("vessel", {"Diameter": f"{d.inlet_separator.standard_diameter_mm:,.0f} mm"})
    fs("absorber", {"Diameter": f"{d.absorber.diameter_m:.2f} m",
                    "Packed height": f"{d.absorber.packed_height_m:.1f} m"})
    fs("molecular_sieve", {"Bed": f"{d.molecular_sieve.standard_diameter_mm:,.0f} mm x {d.molecular_sieve.bed_height_m:.1f} m",
                           "Beds": f"{d.molecular_sieve.n_beds}"})
    fs("air_cooler", {"Bays": f"{d.trim_cooler.n_bays}", "Fans": f"{d.trim_cooler.total_fan_power_kW:.0f} kW"})
    fs("precool", {"T evap": f"{d.precool.T_evap_K - 273.15:.1f} C",
                   "Power": f"{d.precool.compressor_power_kW:,.0f} kW"})
    fs("mche", {"LRC power": f"{d.cascade.lrc.compressor_power_kW:,.0f} kW",
                "MITA": f"{d.mche_pinch.min_approach_K:.1f} K"})
    fs("end_flash", {"Flash": f"{d.end_flash.vapor_mass_fraction * 100:.2f} %"})
    if d.flash_gas_compressor:
        fs("flash_compressor", {"Power": f"{d.flash_gas_compressor.gas_power_kW:,.0f} kW"})
    fs("storage_tank", {"Volume": f"{d.storage_tank.required_volume_m3:,.0f} m3"})
    fs("refrigerant_makeup", {"Vessel": f"{d.refrigerant_storage.standard_diameter_mm:,.0f} mm x "
                                        f"{d.refrigerant_storage.vessel_length_m:.1f} m"})
    if d.refrigerant_supply:
        for key, data in d.refrigerant_supply.flowsheet_state().items():
            fs(key, data)
    if d.fractionation:
        for key, c in zip(("deethanizer", "depropanizer", "debutanizer"), d.fractionation.columns):
            fs(key, {"Trays": f"{c.N_real}", "D x H": f"{c.diameter_m:.2f} x {c.height_m:.1f} m",
                     "Qc/Qr": f"{c.condenser_duty_kW:,.0f}/{c.reboiler_duty_kW:,.0f} kW"})
    if d.mr_blend:
        fs("mr_blend", {"Blend error": f"{d.mr_blend.max_abs_error:.4f}",
                        "Make-up": f"{d.mr_makeup.makeup_kmol_h:.3f} kmol/h"})


def _liq_show_results(d) -> None:
    """Metrics, equipment table and notes for a sized liquefaction train."""
    a, b, c, e = st.columns(4)
    a.metric("Feed", f"{d.feed_mass_flow_kg_s:.1f} kg/s")
    b.metric("Precool + LRC power", f"{d.refrigeration_power_kW / 1000:,.1f} MW")
    c.metric("Total compression", f"{d.total_compression_power_kW / 1000:,.1f} MW")
    e.metric("LNG to storage", f"{d.lng_out_kg_s:.1f} kg/s")
    rows = [
        ("V-101 inlet separator", f"{d.inlet_separator.standard_diameter_mm:,.0f} mm x {d.inlet_separator.seam_to_seam_height_m:.1f} m S/S"),
        ("T-301 amine absorber", f"{d.absorber.diameter_m:.2f} m x {d.absorber.packed_height_m:.1f} m packed ({d.absorber.n_theoretical_stages:.1f} stages)"),
        ("V-201 molecular sieve", f"{d.molecular_sieve.standard_diameter_mm:,.0f} mm x {d.molecular_sieve.bed_height_m:.1f} m, {d.molecular_sieve.n_beds} beds, {d.molecular_sieve.regen_heater_duty_kW:,.0f} kW regen"),
        ("A-101 trim air cooler", f"{d.trim_cooler.n_bays} bays {d.trim_cooler.bay_width_m:.1f} x {d.trim_cooler.bay_length_m:.1f} m, {d.trim_cooler_duty_kW:,.0f} kW duty"),
        ("C3-100 precool", f"duty {d.precool_duty_kW:,.0f} kW, T evap {d.precool.T_evap_K - 273.15:.1f} C, {d.precool.compressor_power_kW:,.0f} kW; "
                           + (f"frame {d.precool_frame.name}" if d.precool_frame else "no single frame")),
        ("E-201 MCHE liquefaction", f"duty {d.lrc_duty_kW:,.0f} kW, LRC {d.cascade.lrc.compressor_power_kW:,.0f} kW, MITA {d.mche_pinch.min_approach_K:.1f} K, {d.mche_technology['typical_technology']}"),
        ("Subcooling (not sized)", f"{d.subcooling_duty_kW:,.0f} kW"),
        ("V-401 end flash", f"{d.end_flash.vapor_mass_fraction * 100:.2f} % flash ({d.end_flash.vapor_mass_flow_kg_s:.2f} kg/s)"),
        ("K-401 flash gas compressor", f"{d.flash_gas_compressor.gas_power_kW:,.0f} kW" if d.flash_gas_compressor else "-"),
        ("TK-501 storage", f"{d.storage_tank.required_volume_m3:,.0f} m3 ({d.storage_tank.cargo_equivalent:.2f}x a cargo)"),
        ("V-102 refrigerant storage", f"{d.refrigerant_storage.standard_diameter_mm:,.0f} mm x {d.refrigerant_storage.vessel_length_m:.1f} m ({d.c3_charge_kg:,.0f} kg)"),
    ]
    if d.fractionation:
        for col in d.fractionation.columns:
            rows.append((f"{col.name}", f"{col.N_real} trays, {col.diameter_m:.2f} m x {col.height_m:.1f} m, Qc {col.condenser_duty_kW:,.0f} / Qr {col.reboiler_duty_kW:,.0f} kW, {col.condenser_service}"))
    if d.mr_blend:
        rows.append(("MR blend / make-up", f"max error {d.mr_blend.max_abs_error:.4f}, make-up {d.mr_makeup.makeup_kmol_h:.3f} kmol/h ({d.mr_makeup.makeup_kg_h:.1f} kg/h)"))
    st.dataframe(pd.DataFrame(rows, columns=["Equipment", "Result"]), use_container_width=True, hide_index=True)
    for n in d.notes:
        st.warning(n)
    st.caption("The Process Flow Diagram tab now shows these results.")


def render_liq(flowsheet: FlowsheetState) -> None:
    """Render the 'liq' tab."""
    st.header("Liquefaction train: feed gas to LNG storage")
    st.caption(
        "One entry point (lng_design/liquefaction.py) chains the inlet separator, amine absorber, "
        "molecular sieve, trim cooler, C3 precool, LRC/MCHE pinch check, end-flash, storage and "
        "refrigerant storage on ONE feed basis, and fills in the flow diagram. Duties use "
        "illustrative average specific heats (inputs of LiquefactionBasis), not a heat-and-material balance."
    )
    c1, c2, c3 = st.columns(3)
    lq_mtpa = c1.number_input("Train capacity (mtpa)", 0.5, 8.0, 2.0, 0.5, key="lq_mtpa")
    lq_T = c2.number_input("Feed temperature (C)", 0.0, 60.0, 25.0, 1.0, key="lq_T")
    lq_P = c3.number_input("Feed pressure (bara)", 20.0, 90.0, 50.0, 5.0, key="lq_P")
    c1, c2 = st.columns(2)
    lq_amb = c1.number_input("Design ambient (C)", 20.0, 50.0, 40.0, 1.0, key="lq_amb")
    lq_water = c2.number_input("Inlet water content (ppmw)", 100.0, 3000.0, 700.0, 100.0, key="lq_water")
    st.subheader("Feed gas (mole fraction)")
    lq_feed = comp_editor({"Methane": 0.85, "Ethane": 0.08, "Propane": 0.04, "Nitrogen": 0.03}, "lq_feed")
    lq_frac = st.checkbox(
        "Also fractionate the NGL (deethanizer / depropanizer) and blend make-up mixed refrigerant",
        value=False, key="lq_frac")

    lq_sup = st.checkbox(
        "Also size refrigerant storage (2.75x demand) and the ethane/propane/butane supply train",
        value=False, key="lq_sup")

    if st.button("Size liquefaction train", type="primary", key="lq_go"):
        try:
            kw = _liq_ngl_options() if lq_frac else {}
            d = size_liquefaction_train(LiquefactionBasis(
                capacity_mtpa=lq_mtpa, feed_composition=lq_feed, feed_T_K=lq_T + 273.15,
                feed_P_Pa=lq_P * 1e5, ambient_T_K=lq_amb + 273.15,
                inlet_water_ppm_wt=lq_water,
                include_refrigerant_supply=lq_sup, **kw))
            st.session_state["liq_design"] = d

            _liq_update_flowsheet(flowsheet, d)
        except Exception as e:
            st.error(str(e))

    d = st.session_state.get("liq_design")
    if d is not None:
        _liq_show_results(d)


__all__ = ["render_regas", "render_frac", "render_liq", "render_regasif", "render_lpg", "render_refsup"]
