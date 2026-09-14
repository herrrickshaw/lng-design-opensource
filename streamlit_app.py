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

from lng_design.amine_absorber import size_packed_absorber
from lng_design.compressor import size_multistage
from lng_design.mche import StreamSegment, analyze_composite_curves
from lng_design.precool import optimal_evap_temperature, propane_cycle_power
from lng_design.properties import GasMixture

st.set_page_config(page_title="LNG Train Conceptual Sizing", layout="wide")
st.title("LNG Train Conceptual Sizing (open-source)")
st.caption(
    "Independent open-source reimplementation using public-domain correlations "
    "(GPSA Engineering Data Book, Kremser equation, pinch/composite-curve analysis) "
    "and CoolProp thermodynamics. Not derived from, and does not reproduce, any "
    "proprietary vendor or client simulation data. See README.md for methodology "
    "and citations, and the disclaimer at the bottom of this page."
)

tab_precool, tab_compressor, tab_absorber, tab_mche = st.tabs(
    ["C3 Pre-cool Loop", "Compressor Train", "Amine Absorber", "MCHE / Pinch Check"]
)

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
        except ValueError as e:
            st.error(str(e))

st.divider()
st.caption(
    "**Disclaimer**: this tool implements textbook/public-domain conceptual sizing "
    "methods for early-stage screening only. It is not a substitute for a rigorous "
    "process simulator (rate-based absorber models, full multistream exchanger "
    "rating, vendor-certified compressor curves) for detailed design. Always "
    "validate against a licensed simulator and vendor data before committing to "
    "equipment specifications."
)
