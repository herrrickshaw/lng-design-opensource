"""Interactive LNG train conceptual sizing tool.

Run with:  streamlit run streamlit_app.py

Engineers enter feed/process conditions in the sidebar; the app sizes the
propane pre-cool loop, a multistage compressor, and an amine absorber, and
runs the MITA/composite-curve pinch check on a simplified precool duty.
All methods are cited public-domain correlations - see README.md and each
module's docstring for sources.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lng_design.air_cooler import size_air_cooler
from lng_design.air_supply import size_instrument_air_system
from lng_design.amine_absorber import size_packed_absorber
from lng_design.berth import berth_queueing_analysis, size_storage_tank
from lng_design.compressor import match_frame_for_stage, size_centrifugal_stage, size_multistage
from lng_design.end_flash import flash_end_gas
from lng_design.exchangers import size_shell_and_tube
from lng_design.flowsheet import FlowsheetState, build_diagram, build_stream_table
from lng_design.mche import StreamSegment, analyze_composite_curves, classify_mche_type
from lng_design.nitrogen_system import size_nitrogen_supply, size_purge
from lng_design.precool import optimal_evap_temperature, propane_cycle_power
from lng_design.process_selection import compare_liquefaction_cycles
from lng_design.properties import GasMixture
from lng_design.refrigerant_makeup import size_refrigerant_storage
from lng_design.vessels import size_vertical_separator
from lng_design.water_system import cooling_water_demand, service_water_demand

st.set_page_config(page_title="LNG Train Conceptual Sizing", layout="wide")
st.title("LNG Train Conceptual Sizing (open-source)")
st.caption(
    "Independent open-source reimplementation using public-domain correlations "
    "(GPSA Engineering Data Book, Kremser equation, pinch/composite-curve analysis) "
    "and CoolProp thermodynamics. Not derived from, and does not reproduce, any "
    "proprietary vendor or client simulation data. See README.md for methodology "
    "and citations, and the disclaimer at the bottom of this page."
)

if "flowsheet" not in st.session_state:
    st.session_state.flowsheet = FlowsheetState()
flowsheet: FlowsheetState = st.session_state.flowsheet

(tab_flow, tab_precool, tab_compressor, tab_absorber, tab_mche, tab_vessel,
 tab_exchanger, tab_aircooler, tab_water, tab_endflash, tab_refrigmu,
 tab_berth, tab_utilities) = st.tabs([
    "Process Flow Diagram", "C3 Pre-cool Loop", "Compressor Train", "Amine Absorber",
    "MCHE / Pinch Check", "Separator Vessel", "Shell & Tube Exchanger", "Air Cooler",
    "Cooling Water", "End Flash", "Refrigerant Makeup", "Storage & Berth", "Utilities",
])

# ---------------------------------------------------------------------
with tab_precool:
    st.header("Propane pre-cool refrigeration cycle")
    c1, c2, c3 = st.columns(3)
    with c1:
        duty_kW = st.number_input("Pre-cool duty (kW)", min_value=1.0, value=5000.0, step=100.0)
        T_cold_target_C = st.number_input("Process cold-end target temp (°C)", value=-20.0)
    with c2:
        T_cond_C = st.number_input("Propane condensing temp (°C, ambient-set)", value=40.0)
        mita_K = st.number_input("MITA / pinch (K)", min_value=0.5, value=3.0, step=0.5)
    with c3:
        eta_isen = st.slider("Compressor isentropic efficiency", 0.5, 0.9, 0.75, 0.01)

    if st.button("Size pre-cool loop", type="primary"):
        try:
            result = optimal_evap_temperature(
                duty_kW, T_cold_target_C + 273.15, T_cond_C + 273.15,
                mita_K=mita_K, isentropic_efficiency=eta_isen,
            )
            base = propane_cycle_power(
                duty_kW, T_cold_target_C + 273.15 - mita_K, T_cond_C + 273.15, eta_isen
            )
            colA, colB, colC, colD = st.columns(4)
            colA.metric("Optimal T_evap", f"{result.T_evap_K - 273.15:.1f} °C")
            colB.metric("Compressor power", f"{result.compressor_power_kW:,.0f} kW")
            colC.metric("Refrigerant flow", f"{result.refrigerant_mass_flow_kg_s:,.1f} kg/s")
            colD.metric("COP", f"{result.cop:.2f}")
            flowsheet.set("precool", {
                "Duty": f"{duty_kW:,.0f} kW",
                "T_evap": f"{result.T_evap_K - 273.15:.1f} C",
                "Power": f"{result.compressor_power_kW:,.0f} kW",
                "COP": f"{result.cop:.2f}",
            })
            st.caption(
                "For a single evaporation level, the MITA-limited boundary is the "
                "power-optimal point (see lng_design/precool.py docstring) - the "
                "'Optimal T_evap' above should sit at cold-end target minus MITA."
            )
        except ValueError as e:
            st.error(str(e))

# ---------------------------------------------------------------------
with tab_compressor:
    st.header("Multistage centrifugal compressor sizing")
    st.caption("Method: polytropic head / efficiency approach, GPSA Engineering Data Book Ch. 13.")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Gas composition (mole fraction)")
        ch4 = st.slider("Methane", 0.0, 1.0, 0.85, 0.01)
        c2h6 = st.slider("Ethane", 0.0, 1.0 - ch4, 0.08, 0.01)
        c3h8 = st.slider("Propane", 0.0, 1.0 - ch4 - c2h6, 0.04, 0.01)
        n2_frac = max(0.0, 1.0 - ch4 - c2h6 - c3h8)
        st.write(f"Nitrogen (balance): {n2_frac:.2f}")
    with c2:
        T_in_C = st.number_input("Suction temperature (°C)", value=30.0)
        P_in_bar = st.number_input("Suction pressure (bara)", min_value=0.1, value=5.0)
        P_out_bar = st.number_input("Discharge pressure (bara)", min_value=0.2, value=45.0)
        mdot = st.number_input("Mass flow (kg/s)", min_value=0.01, value=50.0)
        n_stages = st.number_input("Number of stages", min_value=1, max_value=8, value=3)
        eta_p = st.slider("Polytropic efficiency", 0.6, 0.9, 0.78, 0.01)
        T_interstage_C = st.number_input("Interstage cooling target (°C)", value=40.0)

    if st.button("Size compressor train", type="primary"):
        comp = {"Methane": ch4, "Ethane": c2h6, "Propane": c3h8, "Nitrogen": n2_frac}
        comp = {k: v for k, v in comp.items() if v > 1e-6}
        total = sum(comp.values())
        comp = {k: v / total for k, v in comp.items()}
        gas = GasMixture(comp)
        stages = size_multistage(
            gas, T_in_C + 273.15, P_in_bar * 1e5, P_out_bar * 1e5, mdot,
            n_stages=int(n_stages), polytropic_efficiency=eta_p,
            interstage_cooling_to_K=T_interstage_C + 273.15,
        )
        df = pd.DataFrame([
            {
                "Stage": i + 1,
                "P_in (bara)": s.P_in / 1e5,
                "T_in (°C)": s.T_in - 273.15,
                "Pressure ratio": s.pressure_ratio,
                "T_out (°C)": s.T_out_ideal - 273.15,
                "Head (kJ/kg)": s.polytropic_head_J_per_kg / 1000.0,
                "Power (kW)": s.gas_power_kW,
            }
            for i, s in enumerate(stages)
        ])
        st.dataframe(df, use_container_width=True)
        st.metric("Total compressor power", f"{sum(s.gas_power_kW for s in stages):,.0f} kW")

        st.subheader("Matched to standard compressor frame")
        st.caption(
            "Frame table: 'Pipeline Rules of Thumb Handbook', E.W. McAllister, "
            "3rd Ed., Gulf Publishing - the same public source this package's "
            "compressor module is validated against (see docs/VALIDATION.md)."
        )
        frame_rows = []
        for i, s in enumerate(stages):
            frame, vol_flow = match_frame_for_stage(gas, s.T_in, s.P_in, mdot)
            frame_rows.append({
                "Stage": i + 1, "Inlet vol. flow (m3/h)": f"{vol_flow:,.0f}",
                "Matched frame": frame.name,
                "Nominal speed (rpm)": f"{frame.nominal_speed_rpm:,.0f}",
                "Nominal impeller dia. (mm)": f"{frame.nominal_impeller_diameter_mm:,.0f}",
            })
        st.dataframe(pd.DataFrame(frame_rows), use_container_width=True)

# ---------------------------------------------------------------------
with tab_absorber:
    st.header("Amine acid-gas absorber (packed column)")
    st.caption(
        "Diameter: Souders-Brown flooding correlation. Height: Kremser equation "
        "theoretical stages x HETP. Both per GPSA Engineering Data Book Ch. 19 / "
        "Kohl & Nielsen, 'Gas Purification'."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        q_gas = st.number_input("Gas volumetric flow (m3/s, actual)", min_value=0.01, value=5.0)
        rho_gas = st.number_input("Gas density (kg/m3)", min_value=0.1, value=25.0)
        rho_liq = st.number_input("Amine solution density (kg/m3)", min_value=500.0, value=1010.0)
    with c2:
        y_in = st.number_input("Feed acid-gas mole fraction (y_in)", min_value=0.0, value=0.03, format="%.4f")
        y_out = st.number_input("Target outlet mole fraction (y_out)", min_value=0.0, value=0.0005, format="%.5f")
        x_in = st.number_input("Lean amine acid-gas loading (x_in)", min_value=0.0, value=0.001, format="%.4f")
    with c3:
        m_slope = st.number_input("Equilibrium slope m (system-specific)", min_value=0.01, value=0.4)
        LV_ratio = st.number_input("L/V molar ratio", min_value=0.1, value=25.0)
        K_SB = st.number_input("Souders-Brown K factor (m/s)", min_value=0.01, value=0.04, format="%.3f")
        hetp = st.number_input("HETP (m)", min_value=0.1, value=0.5)

    if st.button("Size absorber", type="primary"):
        try:
            result = size_packed_absorber(
                q_gas, rho_gas, rho_liq, y_in, y_out, x_in, m_slope, LV_ratio,
                K_SB=K_SB, hetp_m=hetp,
            )
            colA, colB, colC, colD = st.columns(4)
            colA.metric("Column diameter", f"{result.diameter_m:.2f} m")
            colB.metric("Theoretical stages", f"{result.n_theoretical_stages:.1f}")
            colC.metric("Packed height", f"{result.packed_height_m:.1f} m")
            colD.metric("% of flood", f"{100*result.superficial_gas_velocity_m_s/result.flooding_velocity_m_s:.0f}%")
            flowsheet.set("absorber", {
                "Diameter": f"{result.diameter_m:.2f} m",
                "Stages": f"{result.n_theoretical_stages:.1f}",
                "Height": f"{result.packed_height_m:.1f} m",
            })
        except ValueError as e:
            st.error(str(e))

# ---------------------------------------------------------------------
with tab_mche:
    st.header("MCHE composite-curve / MITA pinch check")
    st.caption(
        "Simplified 2-composite pinch analysis (Linnhoff pinch technology). "
        "Checks the minimum approach across the WHOLE curve, not just terminal "
        "temperatures - an internal pinch can hide even when terminals look fine."
    )
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Hot stream (gas being cooled)")
        hot_T_in = st.number_input("Hot T_in (°C)", value=25.0)
        hot_T_out = st.number_input("Hot T_out (°C)", value=-35.0)
        hot_duty = st.number_input("Hot duty (kW)", min_value=1.0, value=8000.0)
    with c2:
        st.subheader("Cold stream (refrigerant evaporating)")
        cold_T_in = st.number_input("Cold T_in (°C)", value=-38.0)
        cold_T_out = st.number_input("Cold T_out (°C)", value=22.0)
        cold_duty = st.number_input("Cold duty (kW)", min_value=1.0, value=8000.0)
    U_value = st.number_input("Overall U (W/m2-K)", min_value=100.0, value=2000.0)
    mita_input = st.number_input("Required MITA (K)", min_value=0.5, value=3.0)

    if st.button("Run pinch check", type="primary"):
        hot = [StreamSegment(hot_T_in + 273.15, hot_T_out + 273.15, hot_duty)]
        cold = [StreamSegment(cold_T_in + 273.15, cold_T_out + 273.15, cold_duty)]
        try:
            result = analyze_composite_curves(hot, cold, mita_input, overall_U_W_m2K=U_value)
            colA, colB, colC = st.columns(3)
            colA.metric("Min approach achieved", f"{result.min_approach_K:.2f} K")
            colB.metric("Estimated UA", f"{result.ua_estimate_kW_per_K:.1f} kW/K")
            colC.metric("Estimated area", f"{result.area_estimate_m2:,.0f} m2")
            st.success("MITA constraint satisfied.")
            flowsheet.set("mche", {
                "Duty": f"{result.total_duty_kW:,.0f} kW",
                "Min approach": f"{result.min_approach_K:.2f} K",
                "Area": f"{result.area_estimate_m2:,.0f} m2",
            })

            st.subheader("Typical commercial MCHE technology at this scale")
            lng_capacity_guess = st.number_input(
                "Approx. train LNG capacity for technology classification (mtpa)",
                min_value=0.05, value=2.0, step=0.1, key="mche_capacity",
            )
            tech = classify_mche_type(lng_capacity_guess)
            st.info(f"**{tech['typical_technology']}** — {tech['note']}")

            st.subheader("Liquefaction cycle screening: C3MR vs. DMR vs. AP-X")
            st.caption(
                "Illustrative screening heuristic from published comparative studies "
                "(see lng_design/process_selection.py docstring for citations) - not a "
                "techno-economic optimization."
            )
            cc1, cc2 = st.columns(2)
            with cc1:
                cycle_capacity = st.number_input(
                    "Target train capacity (mtpa)", min_value=0.5, value=lng_capacity_guess,
                    step=0.5, key="cycle_capacity",
                )
            with cc2:
                ambient_swing = st.number_input(
                    "Site ambient temperature swing, summer-winter (K)",
                    min_value=0.0, value=15.0, step=1.0, key="ambient_swing",
                )
            cycle_result = compare_liquefaction_cycles(cycle_capacity, ambient_swing)
            st.success(f"**Recommended: {cycle_result.recommended}**")
            st.write(cycle_result.rationale)
            st.caption(f"Alternatives considered: {', '.join(cycle_result.alternatives_considered)}")
        except ValueError as e:
            st.error(str(e))

# ---------------------------------------------------------------------
with tab_vessel:
    st.header("Vertical separator vessel sizing")
    st.caption(
        "Diameter: Souders-Brown gas-capacity correlation. Height: liquid "
        "residence time. GPSA Engineering Data Book Ch. 7 / Campbell, "
        "'Gas Conditioning and Processing' Vol. 2."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        v_qgas = st.number_input("Gas volumetric flow (m3/s, actual)", min_value=0.01, value=2.0, key="v_qgas")
        v_rho_gas = st.number_input("Gas density (kg/m3)", min_value=0.1, value=20.0, key="v_rhog")
    with c2:
        v_rho_liq = st.number_input("Liquid density (kg/m3)", min_value=100.0, value=650.0, key="v_rhol")
        v_qliq = st.number_input("Liquid volumetric flow (m3/s)", min_value=0.0001, value=0.02, key="v_qliq", format="%.4f")
    with c3:
        v_res_time = st.number_input("Liquid residence time (min)", min_value=1.0, value=5.0, key="v_res")
        v_ksb = st.number_input("Souders-Brown K factor (m/s)", min_value=0.01, value=0.107, format="%.3f", key="v_ksb")

    if st.button("Size separator", type="primary"):
        result = size_vertical_separator(
            v_qgas, v_rho_gas, v_rho_liq, v_qliq, liquid_residence_time_min=v_res_time, K_SB=v_ksb,
        )
        colA, colB, colC, colD = st.columns(4)
        colA.metric("Standard diameter", f"{result.standard_diameter_mm:,.0f} mm")
        colB.metric("Seam-to-seam height", f"{result.seam_to_seam_height_m:.2f} m")
        colC.metric("Design velocity", f"{result.vapor_velocity_design_m_s:.3f} m/s")
        colD.metric("Liquid holdup", f"{result.liquid_holdup_volume_m3:.1f} m3")
        flowsheet.set("vessel", {
            "Diameter": f"{result.standard_diameter_mm:,.0f} mm",
            "Height": f"{result.seam_to_seam_height_m:.2f} m",
        })

# ---------------------------------------------------------------------
with tab_exchanger:
    st.header("Shell & tube exchanger sizing")
    st.caption(
        "LMTD/U-area method (Kern, 'Process Heat Transfer'; Sinnott & Towler, "
        "'Chemical Engineering Design'), matched to standard TEMA shell sizes. "
        "See lng_design/exchangers.py docstring for the shell-diameter estimate's "
        "assumptions."
    )
    c1, c2 = st.columns(2)
    with c1:
        e_duty = st.number_input("Duty (kW)", min_value=1.0, value=2000.0, key="e_duty")
        e_hot_in = st.number_input("Hot fluid T_in (°C)", value=120.0, key="e_hin")
        e_hot_out = st.number_input("Hot fluid T_out (°C)", value=60.0, key="e_hout")
        e_cold_in = st.number_input("Cold fluid T_in (°C)", value=30.0, key="e_cin")
        e_cold_out = st.number_input("Cold fluid T_out (°C)", value=50.0, key="e_cout")
    with c2:
        e_U = st.number_input("Overall U (W/m2-K)", min_value=50.0, value=600.0, key="e_U")
        e_F = st.slider("LMTD correction factor F", 0.7, 1.0, 0.9, 0.01, key="e_F")
        e_tube_od_mm = st.number_input("Tube OD (mm)", min_value=10.0, value=19.05, key="e_tod")
        e_tube_len = st.number_input("Tube length (m)", min_value=1.0, value=6.1, key="e_tlen")

    if st.button("Size exchanger", type="primary"):
        try:
            result = size_shell_and_tube(
                e_duty, e_hot_in + 273.15, e_hot_out + 273.15, e_cold_in + 273.15, e_cold_out + 273.15,
                overall_U_W_m2K=e_U, lmtd_correction_factor_F=e_F,
                tube_od_m=e_tube_od_mm / 1000.0, tube_length_m=e_tube_len,
            )
            colA, colB, colC, colD = st.columns(4)
            colA.metric("LMTD", f"{result.lmtd_K:.1f} K")
            colB.metric("Required area", f"{result.required_area_m2:,.0f} m2")
            colC.metric("Standard shell OD", f"{result.standard_shell_od_mm:,.0f} mm")
            colD.metric("Est. tube count", f"{result.n_tubes_estimate:,}")
        except ValueError as e:
            st.error(str(e))

# ---------------------------------------------------------------------
with tab_aircooler:
    st.header("Air-cooled exchanger (fin-fan) sizing")
    st.caption("GPSA Engineering Data Book Ch. 9 / API 661 conventions.")
    c1, c2 = st.columns(2)
    with c1:
        a_duty = st.number_input("Duty (kW)", min_value=1.0, value=3000.0, key="a_duty")
        a_ambient = st.number_input("Design ambient temperature (°C)", value=35.0, key="a_amb")
        a_rise = st.number_input("Air temperature rise (K)", min_value=2.0, value=14.0, key="a_rise")
    with c2:
        a_facevel = st.number_input("Design face velocity (m/s)", min_value=1.0, value=3.0, key="a_fv")
        a_dP = st.number_input("Air-side static pressure drop (Pa)", min_value=20.0, value=180.0, key="a_dp")
        a_eta = st.slider("Fan static efficiency", 0.4, 0.8, 0.65, 0.01, key="a_eta")

    if st.button("Size air cooler", type="primary"):
        result = size_air_cooler(
            a_duty, a_ambient, air_temperature_rise_K=a_rise, face_velocity_m_s=a_facevel,
            static_pressure_drop_Pa=a_dP, fan_static_efficiency=a_eta,
        )
        colA, colB, colC, colD = st.columns(4)
        colA.metric("Bays needed", f"{result.n_bays}")
        colB.metric("Bay size", f"{result.bay_width_m:.1f} x {result.bay_length_m:.1f} m")
        colC.metric("Air flow", f"{result.air_volumetric_flow_m3_s:,.1f} m3/s")
        colD.metric("Total fan power", f"{result.total_fan_power_kW:,.0f} kW")
        flowsheet.set("air_cooler", {
            "Bays": f"{result.n_bays} x {result.bay_width_m:.1f}x{result.bay_length_m:.1f} m",
            "Fan power": f"{result.total_fan_power_kW:,.0f} kW",
        })

# ---------------------------------------------------------------------
with tab_water:
    st.header("Cooling water system demand")
    st.caption(
        "Cooling Tower Institute practice, reproduced in GPSA Engineering Data "
        "Book Ch. 9: evaporation = 0.00085 x circulation x range(°F)."
    )
    c1, c2 = st.columns(2)
    with c1:
        w_duty = st.number_input("Total cooling water duty (kW)", min_value=1.0, value=10000.0, key="w_duty")
        w_supply = st.number_input("Supply (cold) temperature (°C)", value=30.0, key="w_sup")
        w_return = st.number_input("Return (warm) temperature (°C)", value=40.0, key="w_ret")
    with c2:
        w_coc = st.number_input("Cycles of concentration", min_value=1.5, value=4.0, key="w_coc")
        w_drift = st.number_input("Drift loss fraction", min_value=0.0, value=0.0005, format="%.4f", key="w_drift")

    if st.button("Compute water demand", type="primary"):
        try:
            result = cooling_water_demand(w_duty, w_supply, w_return, cycles_of_concentration=w_coc, drift_fraction=w_drift)
            colA, colB, colC, colD = st.columns(4)
            colA.metric("Circulation rate", f"{result.circulation_rate_m3_h:,.0f} m3/h")
            colB.metric("Evaporation", f"{result.evaporation_m3_h:,.1f} m3/h")
            colC.metric("Blowdown", f"{result.blowdown_m3_h:,.1f} m3/h")
            colD.metric("Total makeup", f"{result.total_makeup_m3_h:,.1f} m3/h")
        except ValueError as e:
            st.error(str(e))

# ---------------------------------------------------------------------
with tab_endflash:
    st.header("Post-MCHE end-flash system")
    st.caption(
        "Rigorous isenthalpic (JT-valve) two-phase flash of subcooled LNG down to "
        "storage tank pressure, via CoolProp's mixture equation of state - not a "
        "shortcut correlation. See lng_design/end_flash.py docstring for the "
        "molar-vs-mass vapor-fraction detail this module handles explicitly."
    )
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("LNG composition (mole fraction)")
        ef_ch4 = st.slider("Methane", 0.0, 1.0, 0.90, 0.01, key="ef_ch4")
        ef_c2h6 = st.slider("Ethane", 0.0, 1.0 - ef_ch4, 0.06, 0.01, key="ef_c2h6")
        ef_c3h8 = st.slider("Propane", 0.0, 1.0 - ef_ch4 - ef_c2h6, 0.02, 0.01, key="ef_c3h8")
        ef_n2 = max(0.0, 1.0 - ef_ch4 - ef_c2h6 - ef_c3h8)
        st.write(f"Nitrogen (balance): {ef_n2:.2f}")
    with c2:
        ef_T = st.number_input("MCHE outlet temperature (°C)", value=-158.0, key="ef_T")
        ef_Pin = st.number_input("MCHE outlet pressure (bara)", min_value=1.1, value=4.5, key="ef_Pin")
        ef_Pout = st.number_input("Storage tank pressure (bara)", min_value=1.01, value=1.10, key="ef_Pout")
        ef_mdot = st.number_input("LNG mass flow (kg/s)", min_value=0.1, value=50.0, key="ef_mdot")

    if st.button("Flash end gas", type="primary"):
        comp = {"Methane": ef_ch4, "Ethane": ef_c2h6, "Propane": ef_c3h8, "Nitrogen": ef_n2}
        comp = {k: v for k, v in comp.items() if v > 1e-6}
        total = sum(comp.values())
        comp = {k: v / total for k, v in comp.items()}
        try:
            result = flash_end_gas(comp, ef_T + 273.15, ef_Pin * 1e5, ef_Pout * 1e5, ef_mdot)
            colA, colB, colC, colD = st.columns(4)
            colA.metric("Vapor mass fraction", f"{result.vapor_mass_fraction*100:.2f}%")
            colB.metric("Flash gas flow", f"{result.vapor_mass_flow_kg_s:,.2f} kg/s")
            colC.metric("LNG product flow", f"{result.liquid_mass_flow_kg_s:,.2f} kg/s")
            colD.metric("Flash temperature", f"{result.flash_temperature_K - 273.15:.2f} °C")

            flowsheet.set("end_flash", {
                "Flash gas": f"{result.vapor_mass_flow_kg_s:.2f} kg/s",
                "LNG out": f"{result.liquid_mass_flow_kg_s:.1f} kg/s",
            })

            if result.vapor_mass_flow_kg_s > 0:
                st.subheader("Flash gas compressor (fuel gas / BOG duty)")
                flash_gas = GasMixture(result.vapor_composition_mole_frac)
                comp_result = size_centrifugal_stage(
                    flash_gas, result.flash_temperature_K, ef_Pout * 1e5, 5e5,
                    result.vapor_mass_flow_kg_s,
                )
                st.metric("Flash gas compressor power", f"{comp_result.gas_power_kW:,.1f} kW")
                flowsheet.set("flash_compressor", {"Power": f"{comp_result.gas_power_kW:.1f} kW"})
        except ValueError as e:
            st.error(str(e))

# ---------------------------------------------------------------------
with tab_refrigmu:
    st.header("Refrigerant storage / makeup vessel")
    st.caption(
        "Sized to hold at least one full system charge plus a reserve for "
        "top-up losses, at a standard maximum liquid fill fraction "
        "(thermal-expansion vapor space) - see lng_design/refrigerant_makeup.py."
    )
    c1, c2 = st.columns(2)
    with c1:
        rm_charge = st.number_input("System refrigerant charge (kg)", min_value=100.0, value=30000.0, key="rm_charge")
        rm_density = st.number_input("Refrigerant liquid density (kg/m3)", min_value=100.0, value=500.0, key="rm_density")
    with c2:
        rm_reserve = st.slider("Reserve fraction", 0.0, 0.5, 0.20, 0.01, key="rm_reserve")
        rm_fill = st.slider("Max fill fraction", 0.5, 0.95, 0.85, 0.01, key="rm_fill")

    if st.button("Size refrigerant storage", type="primary"):
        try:
            result = size_refrigerant_storage(rm_charge, rm_density, reserve_fraction=rm_reserve, max_fill_fraction=rm_fill)
            colA, colB, colC = st.columns(3)
            colA.metric("Standard diameter", f"{result.standard_diameter_mm:,.0f} mm")
            colB.metric("Vessel length", f"{result.vessel_length_m:.1f} m")
            colC.metric("Vessel volume", f"{result.vessel_volume_m3:,.1f} m3")
            flowsheet.set("refrigerant_makeup", {
                "Diameter": f"{result.standard_diameter_mm:,.0f} mm",
                "Length": f"{result.vessel_length_m:.1f} m",
            })
        except ValueError as e:
            st.error(str(e))

# ---------------------------------------------------------------------
with tab_berth:
    st.header("LNG storage tank and loading berth")
    st.caption(
        "Storage: mass-balance buffer between continuous production and periodic "
        "ship departures. Berth: Erlang-C (M/M/c) queueing for waiting time - "
        "standard operations-research mathematics. See lng_design/berth.py."
    )
    st.subheader("Storage tank")
    c1, c2 = st.columns(2)
    with c1:
        st_prod = st.number_input("LNG production rate (kg/s)", min_value=0.1, value=60.0, key="st_prod")
        st_density = st.number_input("LNG density (kg/m3)", min_value=300.0, value=450.0, key="st_density")
    with c2:
        st_interval = st.number_input("Average shipping interval (days)", min_value=0.5, value=4.0, key="st_interval")
        st_contingency = st.number_input("Contingency allowance (days)", min_value=0.0, value=1.5, key="st_contingency")
    st_cargo = st.number_input("Reference cargo size (m3)", min_value=1000.0, value=170000.0, key="st_cargo")

    if st.button("Size storage tank", type="primary"):
        tank = size_storage_tank(st_prod, st_density, st_interval, st_contingency, cargo_size_m3=st_cargo)
        colA, colB = st.columns(2)
        colA.metric("Required storage volume", f"{tank.required_volume_m3:,.0f} m3")
        colB.metric("Equivalent cargoes", f"{tank.cargo_equivalent:.2f}x")
        flowsheet.set("storage_tank", {"Volume": f"{tank.required_volume_m3:,.0f} m3"})

    st.divider()
    st.subheader("Loading berth")
    c1, c2 = st.columns(2)
    with c1:
        b_offtake = st.number_input("Annual offtake (mtpa)", min_value=0.1, value=5.0, key="b_offtake")
        b_cargo = st.number_input("Cargo size (m3)", min_value=1000.0, value=170000.0, key="b_cargo")
    with c2:
        b_service = st.number_input("Berth service time per ship (h)", min_value=1.0, value=30.0, key="b_service")
        b_berths = st.number_input("Number of berths", min_value=1, max_value=6, value=1, key="b_berths")

    if st.button("Analyze berth queueing", type="primary"):
        try:
            berth_result = berth_queueing_analysis(
                b_offtake, b_cargo, st_density, b_service, n_berths=int(b_berths),
            )
            colA, colB, colC, colD = st.columns(4)
            colA.metric("Utilization", f"{berth_result.utilization*100:.0f}%")
            colB.metric("P(ship must wait)", f"{berth_result.probability_of_waiting*100:.0f}%")
            colC.metric("Expected wait", f"{berth_result.expected_wait_hours:.1f} h")
            colD.metric("Ships queued (avg)", f"{berth_result.expected_ships_in_queue:.2f}")
            flowsheet.set("berth", {
                "Berths": f"{int(b_berths)}",
                "Utilization": f"{berth_result.utilization*100:.0f}%",
                "Avg wait": f"{berth_result.expected_wait_hours:.1f} h",
            })
        except ValueError as e:
            st.error(str(e))

# ---------------------------------------------------------------------
with tab_utilities:
    st.header("Plant utility systems")
    u_air, u_n2, u_water = st.tabs(["Instrument/Plant Air", "Nitrogen", "Service Water"])

    with u_air:
        st.caption("Aggregated pneumatic-instrument demand, GPSA/ISA-style conceptual sizing.")
        c1, c2 = st.columns(2)
        with c1:
            a_n_inst = st.number_input("Number of pneumatic instruments", min_value=1, value=400, key="a_n_inst")
            a_consump = st.number_input("Avg. consumption per instrument (Nm3/h)", min_value=0.01, value=0.85, key="a_consump")
        with c2:
            a_div = st.slider("Diversity factor", 0.1, 1.0, 0.6, 0.05, key="a_div")
            a_margin = st.slider("Design margin", 0.0, 0.5, 0.25, 0.05, key="a_margin")
        if st.button("Size air system", type="primary"):
            result = size_instrument_air_system(int(a_n_inst), a_consump, a_div, a_margin)
            colA, colB, colC = st.columns(3)
            colA.metric("Average demand", f"{result.average_demand_Nm3_h:,.0f} Nm3/h")
            colB.metric("Compressor capacity", f"{result.compressor_capacity_Nm3_h:,.0f} Nm3/h")
            colC.metric("Receiver volume", f"{result.receiver_volume_m3:,.1f} m3")
            flowsheet.set("air_supply", {"Capacity": f"{result.compressor_capacity_Nm3_h:,.0f} Nm3/h"})

    with u_n2:
        st.caption("Purge (vessel volume exchange) + continuous blanketing demand.")
        c1, c2 = st.columns(2)
        with c1:
            n_free_vol = st.number_input("Vessel free volume per purge (m3)", min_value=1.0, value=50.0, key="n_free_vol")
            n_exchanges = st.number_input("Volume exchanges per purge", min_value=1.0, value=4.0, key="n_exchanges")
            n_events = st.number_input("Purge events per day", min_value=0.0, value=2.0, key="n_events")
        with c2:
            n_blanket = st.number_input("Continuous blanketing flow (Nm3/h)", min_value=0.0, value=20.0, key="n_blanket")
            n_margin = st.slider("Design margin", 0.0, 0.5, 0.25, 0.05, key="n_margin")
        if st.button("Size nitrogen system", type="primary"):
            purge = size_purge(n_free_vol, n_exchanges)
            supply = size_nitrogen_supply(n_blanket, n_events, purge.purge_volume_Nm3, n_margin)
            colA, colB, colC = st.columns(3)
            colA.metric("Purge volume/event", f"{purge.purge_volume_Nm3:,.0f} Nm3")
            colB.metric("Total demand", f"{supply.total_demand_Nm3_h:,.1f} Nm3/h")
            colC.metric("Generator capacity", f"{supply.generator_capacity_Nm3_h:,.1f} Nm3/h")
            flowsheet.set("nitrogen", {"Capacity": f"{supply.generator_capacity_Nm3_h:,.1f} Nm3/h"})

    with u_water:
        st.caption("Potable + general service water, standard peaking-factor design flow.")
        c1, c2 = st.columns(2)
        with c1:
            sw_people = st.number_input("Site personnel", min_value=1, value=150, key="sw_people")
            sw_rate = st.number_input("Potable use (L/person/day)", min_value=50.0, value=130.0, key="sw_rate")
        with c2:
            sw_general = st.number_input("General service water (m3/day)", min_value=0.0, value=20.0, key="sw_general")
            sw_peak = st.slider("Peak hour factor", 1.0, 5.0, 3.0, 0.5, key="sw_peak")
        if st.button("Size service water", type="primary"):
            result = service_water_demand(int(sw_people), sw_rate, sw_general, sw_peak)
            colA, colB, colC = st.columns(3)
            colA.metric("Total daily demand", f"{result.total_m3_day:,.1f} m3/day")
            colB.metric("Peak flow", f"{result.peak_flow_m3_h:,.1f} m3/h")
            colC.metric("Potable share", f"{result.potable_m3_day:,.1f} m3/day")
            flowsheet.set("service_water", {"Peak flow": f"{result.peak_flow_m3_h:,.1f} m3/h"})

# ---------------------------------------------------------------------
# tab_flow is rendered LAST (though it's the leftmost/first tab visually -
# st.tabs() controls visual order independently of code order) so it
# always reflects this run's fully up-to-date flowsheet state. Streamlit
# reruns the whole script top-to-bottom on every interaction; rendering
# it earlier would show state from before the triggering tab's own
# updates ran in the same pass.
with tab_flow:
    st.header("Process flow diagram")
    st.caption(
        "A schematic, illustrative LNG train topology - NOT a drafting-standard "
        "P&ID/PFD. Each box fills in with your latest sizing result from the "
        "other tabs as you use them; the stream table below follows the same "
        "structure as a process simulator's heat-and-material-balance (HMB) "
        "stream report."
    )
    st.graphviz_chart(build_diagram(flowsheet), use_container_width=True)
    st.subheader("Stream table (HMB-style)")
    st.dataframe(pd.DataFrame(build_stream_table(flowsheet)), use_container_width=True, hide_index=True)
    if st.button("Reset flow diagram"):
        st.session_state.flowsheet = FlowsheetState()
        st.rerun()

st.divider()
st.caption(
    "**Disclaimer**: this tool implements textbook/public-domain conceptual sizing "
    "methods for early-stage screening only. It is not a substitute for a rigorous "
    "process simulator (rate-based absorber models, full multistream exchanger "
    "rating, vendor-certified compressor curves) for detailed design. Always "
    "validate against a licensed simulator and vendor data before committing to "
    "equipment specifications."
)
