"""MCHE-centred tabs: 3-loop cascade, debottleneck comparison, bundle rating.

Mechanically split out of streamlit_app.py; behaviour unchanged.
"""
from __future__ import annotations

import streamlit as st

from lng_design.cascade_loops import three_loop_cascade
from lng_design.mche_tube_design import TubeBundleGeometry, rate_mche_bundle
from lng_design.properties import GasMixture


def render_cascade() -> None:
    """Render the 'cascade' tab."""
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


def render_debottleneck() -> None:
    """Render the 'debottleneck' tab."""
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


def render_mche_rating() -> None:
    """Render the 'mche_rating' tab."""
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
