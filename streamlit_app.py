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
from lng_design.bog_compressor import size_bog_compressor, turndown_check
from lng_design.cascade_loops import three_loop_cascade
from lng_design.compressor import match_frame_for_stage, size_centrifugal_stage, size_multistage
from lng_design.end_flash import flash_end_gas
from lng_design.exchangers import size_shell_and_tube
from lng_design.fractionation import ColumnSpec, size_fractionation_train
from lng_design.liquefaction import LiquefactionBasis, size_liquefaction_train
from lng_design.lpg_terminal import LPGTerminalBasis, size_lpg_import_terminal
from lng_design.flowsheet import FlowsheetState, build_diagram, build_stream_table
from lng_design.mche import StreamSegment, analyze_composite_curves, classify_mche_type
from lng_design.mche_tube_design import TubeBundleGeometry, rate_mche_bundle
from lng_design.mche_vendor_selection import compare_mche_vendors
from lng_design.molecular_sieve import size_molecular_sieve_bed
from lng_design.nitrogen_system import size_nitrogen_supply, size_purge
from lng_design.precool import optimal_evap_temperature, propane_cycle_power
from lng_design.process_selection import compare_liquefaction_cycles
from lng_design.properties import GasMixture
from lng_design.refrigerant_generation import ProductSpec, blend_mixed_refrigerant, check_product_spec
from lng_design.refrigerant_makeup import size_refrigerant_storage
from lng_design.refrigerant_supply import RefrigerantLoop, RefrigerantSupplyBasis, size_refrigerant_supply
from lng_design.regasification import RegasificationBasis, size_regasification_terminal
from lng_design.regas_terminal import heating_curve, size_recondenser, size_regas_train
from lng_design.tank_bog import compute_bog, size_tank_geometry
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

(tab_flow, tab_precool, tab_compressor, tab_absorber, tab_molsieve, tab_mche,
 tab_vessel, tab_exchanger, tab_aircooler, tab_water, tab_endflash, tab_refrigmu,
 tab_berth, tab_utilities, tab_cascade, tab_debottleneck, tab_mche_rating,
 tab_regas, tab_frac, tab_liq, tab_regasif, tab_lpg, tab_refsup) = st.tabs([
    "Process Flow Diagram", "C3 Pre-cool Loop", "Compressor Train", "Amine Absorber",
    "Molecular Sieve", "MCHE / Pinch Check", "Separator Vessel", "Shell & Tube Exchanger",
    "Air Cooler", "Cooling Water", "End Flash", "Refrigerant Makeup", "Storage & Berth",
    "Utilities", "3-Loop Cascade", "MCHE Debottleneck", "MCHE Rating",
    "Regas & BOG", "Fractionation", "Liquefaction", "Regasification", "LPG Import", "Refrigerant Supply",
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
with tab_molsieve:
    st.header("Molecular sieve dehydration (post-amine, pre-cryogenic)")
    st.caption(
        "Amine removes acid gases but not water; LNG needs water down to well "
        "under 1 ppmv before the cryogenic section, or ice/hydrates plug the MCHE. "
        "4A molecular sieve, GPSA Engineering Data Book Ch. 20 - see "
        "lng_design/molecular_sieve.py."
    )
    c1, c2 = st.columns(2)
    with c1:
        ms_flow = st.number_input("Gas mass flow (kg/s)", min_value=1.0, value=20.0, key="ms_flow")
        ms_density = st.number_input("Gas density at bed conditions (kg/m3)", min_value=1.0, value=25.0, key="ms_density")
        ms_water = st.number_input("Inlet water content (ppm wt)", min_value=1.0, value=800.0, key="ms_water")
    with c2:
        ms_ads_time = st.number_input("Adsorption time (h)", min_value=1.0, value=8.0, key="ms_ads")
        ms_regen_time = st.number_input("Regeneration time (h)", min_value=0.5, value=4.0, key="ms_regen")
        ms_cool_time = st.number_input("Cooldown time (h)", min_value=0.1, value=1.5, key="ms_cool")
    ms_velocity = st.slider("Design velocity (m/s)", 0.10, 0.35, 0.20, 0.01, key="ms_vel")
    ms_capacity = st.slider("Working capacity (wt%)", 5.0, 15.0, 11.0, 0.5, key="ms_cap")

    if st.button("Size molecular sieve bed", type="primary"):
        try:
            result = size_molecular_sieve_bed(
                ms_flow, ms_density, ms_water, adsorption_time_h=ms_ads_time,
                regen_time_h=ms_regen_time, cooldown_time_h=ms_cool_time,
                design_velocity_m_s=ms_velocity, working_capacity_wt_pct=ms_capacity,
            )
            colA, colB, colC, colD = st.columns(4)
            colA.metric("Standard diameter", f"{result.standard_diameter_mm:,.0f} mm")
            colB.metric("Bed height", f"{result.bed_height_m:.1f} m")
            colC.metric("Number of beds", f"{result.n_beds}")
            colD.metric("Regen heater duty", f"{result.regen_heater_duty_kW:,.0f} kW")
            flowsheet.set("molecular_sieve", {
                "Diameter": f"{result.standard_diameter_mm:,.0f} mm",
                "Beds": f"{result.n_beds}",
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

    st.divider()
    st.subheader("MCHE vendor comparison: APCI vs. Linde")
    st.caption(
        "Structured factor-by-factor comparison, not a forced single answer - the "
        "literature doesn't reduce this to one clean threshold. See "
        "lng_design/mche_vendor_selection.py for citations."
    )
    vc1, vc2 = st.columns(2)
    with vc1:
        vendor_capacity = st.number_input(
            "Target train capacity for context (mtpa, optional)", min_value=0.0,
            value=2.0, step=0.5, key="vendor_capacity",
        )
    with vc2:
        vendor_modularity = st.selectbox(
            "Preference", ["No preference", "Value modularity/flexibility", "Prefer simplicity"],
            key="vendor_modularity",
        )
    modularity_arg = {"Value modularity/flexibility": True, "Prefer simplicity": False}.get(vendor_modularity)
    vendor_result = compare_mche_vendors(
        target_train_capacity_mtpa=vendor_capacity if vendor_capacity > 0 else None,
        values_modularity=modularity_arg,
    )
    vcol1, vcol2 = st.columns(2)
    for col, profile in [(vcol1, vendor_result.apci), (vcol2, vendor_result.linde)]:
        with col:
            st.markdown(f"**{profile.vendor}**")
            st.write(f"Process: {profile.process}")
            st.write(f"Exchanger: {profile.exchanger_technology}")
            st.write(f"Refrigeration cycles: {profile.n_refrigeration_cycles}")
            st.write(f"Proven capacity: {profile.proven_train_capacity_mtpa}")
            st.caption(profile.notes)
    for note in vendor_result.screening_notes:
        st.info(note)

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
with tab_cascade:
    st.header("Three-loop cascade (NG / Refrigerant-LRC / PMR)")
    st.caption(
        "Models the Linde MFC-style cascade structure: PMR condenses at ambient and "
        "absorbs both the NG precool duty AND the LRC loop's condensing heat - the "
        "defining cascade link. Real gas/thermodynamic properties throughout via "
        "CoolProp mixture flashes. See lng_design/cascade_loops.py for the physics "
        "and the empirical validation behind the temperature ranges below."
    )
    st.subheader("NG duties")
    c1, c2 = st.columns(2)
    with c1:
        cs_precool_duty = st.number_input("NG precool duty (kW)", min_value=1.0, value=3000.0, key="cs_precool_duty")
    with c2:
        cs_liq_duty = st.number_input("NG liquefaction duty (kW)", min_value=1.0, value=5000.0, key="cs_liq_duty")

    st.subheader("PMR loop (condenses at ambient)")
    c1, c2, c3 = st.columns(3)
    with c1:
        cs_pmr_evap_C = st.number_input("PMR T_evap (°C)", value=-40.0, key="cs_pmr_evap")
    with c2:
        cs_pmr_cond_C = st.number_input("PMR T_cond (°C, ambient)", value=40.0, key="cs_pmr_cond")
    with c3:
        cs_dmr_style = st.checkbox("DMR-style blend (colder than propane's ~-42°C floor)", key="cs_dmr")

    st.subheader("Refrigerant (LRC) loop (condenses against PMR's cold duty)")
    c1, c2, c3 = st.columns(3)
    with c1:
        cs_lrc_evap_C = st.number_input("LRC T_evap (°C)", value=-100.0, key="cs_lrc_evap")
    with c2:
        cs_mita = st.number_input("MITA between loops (K)", min_value=0.5, value=3.0, key="cs_mita")
    with c3:
        st.metric("LRC T_cond (°C)", f"{cs_pmr_evap_C + cs_mita:.1f}")

    if st.button("Solve cascade", type="primary"):
        lrc_blend = GasMixture({"Nitrogen": 0.05, "Methane": 0.30, "Ethane": 0.35, "Propane": 0.30})
        dmr_blend = GasMixture({"Ethane": 0.30, "Propane": 0.70})
        try:
            result = three_loop_cascade(
                cs_precool_duty, cs_liq_duty,
                cs_pmr_evap_C + 273.15, cs_pmr_cond_C + 273.15,
                lrc_blend, cs_lrc_evap_C + 273.15,
                lrc_T_cond_K=cs_pmr_evap_C + 273.15 + cs_mita,
                mita_K=cs_mita,
                pmr_refrigerant=dmr_blend if cs_dmr_style else None,
            )
            colA, colB, colC = st.columns(3)
            colA.metric("PMR power", f"{result.pmr.compressor_power_kW:,.0f} kW")
            colB.metric("LRC power", f"{result.lrc.compressor_power_kW:,.0f} kW")
            colC.metric("Total power", f"{result.total_compressor_power_kW:,.0f} kW")
            st.caption(
                f"PMR total duty (NG precool + LRC condensing): {result.pmr_total_duty_kW:,.0f} kW "
                f"| LRC condensing duty: {result.lrc.condensing_duty_kW:,.0f} kW"
            )
            if cs_dmr_style:
                st.info(
                    f"DMR-style PMR evaporating at {cs_pmr_evap_C:.0f}°C - below pure propane's "
                    "~-42°C atmospheric floor - using a heavier ethane/propane blend instead of "
                    "pure propane."
                )
        except ValueError as e:
            st.error(str(e))

# ---------------------------------------------------------------------
with tab_debottleneck:
    st.header("MCHE NG-throughput ceiling: C3MR vs. DMR")
    st.caption(
        "Quantifies WHY a colder DMR precool floor raises the MCHE's NG throughput "
        "ceiling vs. C3MR's - process_selection.py cites a published ~5 mtpa/train "
        "(C3MR) vs. ~8 mtpa/train (DMR) capacity ceiling from MCHE/compressor size "
        "limits; this breaks that down into two physical mechanisms. See "
        "examples/mche_debottleneck_dmr_vs_c3mr.py and docs/VALIDATION.md."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        db_c3mr_floor_C = st.number_input("C3MR precool floor (°C)", value=-40.0, key="db_c3mr_floor")
    with c2:
        db_dmr_floor_C = st.number_input("DMR precool floor (°C)", value=-50.0, key="db_dmr_floor")
    with c3:
        db_rundown_C = st.number_input("LNG rundown target (°C)", value=-159.0, key="db_rundown")
    c1, c2, c3 = st.columns(3)
    with c1:
        db_c3mr_ceiling = st.number_input("Published C3MR ceiling (mtpa)", min_value=0.1, value=5.0, key="db_c3mr_ceiling")
    with c2:
        db_dmr_ceiling = st.number_input("Published DMR ceiling (mtpa)", min_value=0.1, value=8.0, key="db_dmr_ceiling")
    with c3:
        db_P_bara = st.number_input("MCHE inlet pressure (bara)", min_value=1.0, value=50.0, key="db_P")

    if st.button("Run comparison", type="primary"):
        ng = GasMixture({"Methane": 0.85, "Ethane": 0.08, "Propane": 0.04, "Nitrogen": 0.03})
        c3mr_floor_K, dmr_floor_K, rundown_K = db_c3mr_floor_C + 273.15, db_dmr_floor_C + 273.15, db_rundown_C + 273.15
        c3mr_span_K, dmr_span_K = c3mr_floor_K - rundown_K, dmr_floor_K - rundown_K

        c3mr_mdot_ceiling = db_c3mr_ceiling * (1.0e9 / (365.25 * 24 * 3600))
        cp_avg = 2.9  # same illustrative average used throughout the full-train worked examples
        mche_duty_ceiling_kW = c3mr_mdot_ceiling * cp_avg * c3mr_span_K
        dmr_mtpa_max_duty = (mche_duty_ceiling_kW / (cp_avg * dmr_span_K)) / (1.0e9 / (365.25 * 24 * 3600))
        duty_pct = 100.0 * (dmr_mtpa_max_duty / db_c3mr_ceiling - 1.0)

        c3mr_rho = ng.density(c3mr_floor_K, db_P_bara * 1e5)
        dmr_rho = ng.density(dmr_floor_K, db_P_bara * 1e5)
        c3mr_vol_ceiling = c3mr_mdot_ceiling / c3mr_rho
        dmr_mtpa_max_vol = (c3mr_vol_ceiling * dmr_rho) / (1.0e9 / (365.25 * 24 * 3600))
        vol_pct = 100.0 * (dmr_mtpa_max_vol / db_c3mr_ceiling - 1.0)

        published_pct = 100.0 * (db_dmr_ceiling / db_c3mr_ceiling - 1.0)
        combined_pct = 100.0 * ((1 + duty_pct / 100.0) * (1 + vol_pct / 100.0) - 1.0)

        colA, colB = st.columns(2)
        colA.metric("Duty mechanism alone", f"{duty_pct:+.1f}%", help="Smaller precool-to-rundown span, fixed MCHE duty ceiling")
        colB.metric("Density/velocity mechanism alone", f"{vol_pct:+.1f}%", help="Denser MCHE inlet, fixed volumetric/tube-velocity ceiling")
        colA.metric("Combined (compounded)", f"{combined_pct:+.1f}%")
        colB.metric("Published ceiling uplift", f"{published_pct:+.0f}%")
        st.info(
            f"NG density at MCHE inlet: {c3mr_rho:.2f} kg/m3 (C3MR) vs. {dmr_rho:.2f} kg/m3 (DMR) - "
            f"a {100.0*(dmr_rho/c3mr_rho-1.0):.1f}% density increase."
        )
        if combined_pct < published_pct - 5.0:
            st.warning(
                f"Both mechanisms combined ({combined_pct:+.1f}%) fall short of the published "
                f"ceiling uplift ({published_pct:+.0f}%) - the gap is honestly attributed to "
                "unmodeled compressor casing/impeller limits and real core-fabrication limits, "
                "not smoothed over. See examples/mche_debottleneck_dmr_vs_c3mr.py."
            )

# ---------------------------------------------------------------------
with tab_mche_rating:
    st.header("MCHE rating: achievable rundown for a real tube bundle")
    st.caption(
        "SIZING (mche.py's MCHE / Pinch Check tab) assumes a target rundown and one "
        "constant overall U, then checks if the area works out. This is the inverse "
        "RATING calculation (Kern, 'Process Heat Transfer'): given a FIXED tube "
        "bundle and known flows, what rundown can it actually deliver - using local "
        "tube-side (Dittus-Boelter / Shah condensation) and shell-side (falling-film) "
        "heat transfer coefficients computed from real CoolProp properties at many "
        "points along the exchanger, not one assumed number. See "
        "lng_design/mche_tube_design.py and docs/VALIDATION.md for the correlations, "
        "citations, and a documented finding on why this can disagree with the "
        "simple constant-U estimate. **This takes 20-60 seconds to run** - it does "
        "real property lookups at many points, not a lookup table."
    )
    st.subheader("Process (NG) stream")
    c1, c2, c3 = st.columns(3)
    with c1:
        mr_mass_flow = st.number_input("NG mass flow (kg/s)", min_value=0.1, value=63.4, key="mr_mass_flow")
    with c2:
        mr_P_bara = st.number_input("Pressure (bara)", min_value=1.0, value=50.0, key="mr_P")
    with c3:
        mr_T_hot_C = st.number_input("Hot-end temperature (°C)", value=-40.0, key="mr_T_hot")

    st.subheader("Refrigerant loop (evaporating)")
    c1, c2, c3 = st.columns(3)
    with c1:
        mr_refrig_mass_flow = st.number_input("Refrigerant mass flow (kg/s)", min_value=0.1, value=37.6, key="mr_refrig_flow")
    with c2:
        mr_T_evap_C = st.number_input("Refrigerant T_evap (°C)", value=-100.0, key="mr_T_evap")
    with c3:
        mr_mita = st.number_input("Required MITA (K)", min_value=0.5, value=3.0, key="mr_mita")

    st.subheader("Tube bundle geometry")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        mr_n_tubes = st.number_input("Number of tubes", min_value=10, value=3000, step=100, key="mr_n_tubes")
    with c2:
        mr_od_mm = st.number_input("Tube OD (mm)", min_value=5.0, value=19.05, key="mr_od")
    with c3:
        mr_wall_mm = st.number_input("Wall thickness (mm)", min_value=0.5, value=1.6, key="mr_wall")
    with c4:
        mr_length_m = st.number_input("Tube length (m)", min_value=1.0, value=6.1, key="mr_length")
    mr_n_zones = st.slider(
        "Duty-axis resolution (zones)", min_value=5, max_value=20, value=8,
        help="More zones = more accurate, but roughly linearly slower.",
    )

    if st.button("Rate this bundle", type="primary"):
        geometry = TubeBundleGeometry(
            n_tubes=int(mr_n_tubes), tube_od_m=mr_od_mm / 1000.0,
            tube_wall_m=mr_wall_mm / 1000.0, tube_length_m=mr_length_m,
        )
        ng = GasMixture({"Methane": 0.85, "Ethane": 0.08, "Propane": 0.04, "Nitrogen": 0.03})
        refrigerant = GasMixture({"Nitrogen": 0.05, "Methane": 0.30, "Ethane": 0.35, "Propane": 0.30})
        try:
            with st.spinner("Rating the bundle (real CoolProp property lookups, ~20-60s)..."):
                result = rate_mche_bundle(
                    geometry, ng, mr_mass_flow, mr_P_bara * 1e5, mr_T_hot_C + 273.15,
                    refrigerant, mr_refrig_mass_flow, mr_T_evap_C + 273.15,
                    min_approach_K=mr_mita, n_zones=int(mr_n_zones),
                )
            colA, colB, colC = st.columns(3)
            colA.metric("Achievable rundown", f"{result.achievable_rundown_T_K-273.15:.1f} °C")
            colB.metric("Binding constraint", result.binding_constraint)
            colC.metric("Local U range", f"{result.min_local_U_W_m2K:.0f}-{result.max_local_U_W_m2K:.0f} W/m2K")
            st.caption(
                f"Bundle: {geometry.outer_area_m2:,.0f} m2 outer area | "
                f"Area used: {result.total_area_used_m2:,.0f} m2"
            )
            if result.binding_constraint == "MITA":
                st.success(
                    "This bundle has more area than needed - the pinch (MITA) constraint "
                    "caps the achievable rundown, not the bundle size."
                )
            else:
                st.info(
                    "This bundle runs out of area before reaching the MITA limit - a larger "
                    "bundle (more/longer tubes) could reach a colder rundown."
                )
        except ValueError as e:
            st.error(str(e))

# ---------------------------------------------------------------------
def _comp_editor(defaults: dict[str, float], key: str) -> dict[str, float]:
    cols = st.columns(len(defaults))
    vals = {n: c.number_input(f"{n}", 0.0, 1.0, v, 0.005, key=f"{key}_{n}", format="%.3f")
            for (n, v), c in zip(defaults.items(), cols)}
    tot = sum(vals.values())
    if abs(tot - 1.0) > 1e-6:
        st.warning(f"Mole fractions sum to {tot:.4f}; they must sum to 1.")
    return vals


with tab_regas:
    st.header("Regasification terminal: tank BOG, BOG compressor, send-out train")
    st.caption(
        "CoolProp mixture thermodynamics throughout. BOG is computed by source "
        "(heat ingress, pump heat, unloading displacement + flash, barometric fall) "
        "on the equilibrium vapor composition. See lng_design/tank_bog.py, "
        "bog_compressor.py, regas_terminal.py."
    )
    lng_x = _comp_editor({"Methane": 0.92, "Ethane": 0.05, "Propane": 0.015,
                          "n-Butane": 0.005, "Nitrogen": 0.01}, "rg")
    r_tank, r_comp, r_send = st.tabs(["Tank & BOG", "BOG Compressor", "Send-out Train"])

    with r_tank:
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

    with r_comp:
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

    with r_send:
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

# ---------------------------------------------------------------------
with tab_frac:
    st.header("NGL fractionation: distillate columns and refrigerant generation")
    st.caption(
        "Fenske-Underwood-Gilliland shortcut with CoolProp K-values (lng_design/fractionation.py). "
        "Stage counts are +/-10-15% - confirm in a rigorous simulator."
    )
    f_col, f_ref = st.tabs(["Column train", "Refrigerant blend"])
    with f_col:
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

    with f_ref:
        tr = st.session_state.get("frac_train")
        if tr is None:
            st.info("Size the column train first - its ethane and propane distillates are the blend sources.")
        else:
            st.subheader("Target mixed refrigerant (mole fraction)")
            mr = _comp_editor({"Nitrogen": 0.05, "Methane": 0.40, "Ethane": 0.45, "Propane": 0.10}, "mr")
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

# ---------------------------------------------------------------------
with tab_liq:
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
    lq_feed = _comp_editor({"Methane": 0.85, "Ethane": 0.08, "Propane": 0.04, "Nitrogen": 0.03}, "lq_feed")
    lq_frac = st.checkbox(
        "Also fractionate the NGL (deethanizer / depropanizer) and blend make-up mixed refrigerant",
        value=False, key="lq_frac")

    lq_sup = st.checkbox(
        "Also size refrigerant storage (2.75x demand) and the ethane/propane/butane supply train",
        value=False, key="lq_sup")

    if st.button("Size liquefaction train", type="primary", key="lq_go"):
        try:
            kw = {}
            if lq_frac:
                kw = dict(
                    ngl_feed_kmol_h={"Ethane": 320.0, "Propane": 300.0, "Isobutane": 60.0,
                                     "n-Butane": 100.0, "Isopentane": 50.0, "Pentane": 50.0, "Hexane": 40.0},
                    fractionation_specs=[ColumnSpec("deethanizer", "Ethane", "Propane", 26e5, 0.98, 0.995),
                                         ColumnSpec("depropanizer", "Propane", "Isobutane", 17e5, 0.985, 0.98),
                                         ColumnSpec("debutanizer", "n-Butane", "Isopentane", 6e5, 0.98, 0.98)],
                    mr_target={"Nitrogen": 0.05, "Methane": 0.40, "Ethane": 0.45, "Propane": 0.10})
            d = size_liquefaction_train(LiquefactionBasis(
                capacity_mtpa=lq_mtpa, feed_composition=lq_feed, feed_T_K=lq_T + 273.15,
                feed_P_Pa=lq_P * 1e5, ambient_T_K=lq_amb + 273.15,
                inlet_water_ppm_wt=lq_water,
                include_refrigerant_supply=lq_sup, **kw))
            st.session_state["liq_design"] = d

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
        except Exception as e:
            st.error(str(e))

    d = st.session_state.get("liq_design")
    if d is not None:
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

# ---------------------------------------------------------------------
with tab_regasif:
    st.header("Regasification terminal: tanks, BOG and send-out")
    st.caption(
        "One entry point (lng_design/regasification.py) runs tank BOG (holding and unloading), the BOG "
        "compressors with a turndown check, the send-out pumps/ORV/SCV, and the recondenser at full AND "
        "turndown send-out, adding the direct-to-pipeline HP BOG compressor for whatever the recondenser "
        "cannot absorb. Takes ~15-30 s (real CoolProp mixture flashes)."
    )
    st.subheader("LNG composition (mole fraction)")
    rs_lng = _comp_editor({"Methane": 0.92, "Ethane": 0.05, "Propane": 0.015,
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

# ---------------------------------------------------------------------
with tab_lpg:
    st.header("LPG import terminal: refrigerated storage, BOG re-liquefaction, send-out")
    st.caption(
        "Fully-refrigerated propane/butane import (lng_design/lpg_terminal.py). Differences from LNG that drive "
        "the design: BOG is compressed and CONDENSED (the flash on let-down to the cold tank multiplies the "
        "compressor flow by 1/(1-f)), send-out is a liquid pumped and heated (no vaporization), and tank heat "
        "ingress is small. Insulation, unloading rate, contingency and efficiencies are assumptions."
    )
    st.subheader("LPG composition (mole fraction)")
    lp_comp = _comp_editor({"Propane": 0.95, "n-Butane": 0.05, "Isobutane": 0.0, "Ethane": 0.0}, "lp_comp")
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

# ---------------------------------------------------------------------
with tab_refsup:
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
    rf_comp = _comp_editor({"Nitrogen": 0.05, "Methane": 0.38, "Ethane": 0.44, "Propane": 0.10, "n-Butane": 0.03}, "rf_comp")

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
        "stream report. The regas terminal, NGL fractionation / refrigerant "
        "generation and LPG import groups sit in dashed clusters; the diagram is wide, so hover "
        "it and use the fullscreen button to read the boxes."
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
