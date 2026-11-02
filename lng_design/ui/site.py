"""Site-level tabs: water, end flash, refrigerant makeup, storage and berth, utilities.

Mechanically split out of streamlit_app.py; behaviour unchanged.
"""
from __future__ import annotations

import streamlit as st

from lng_design.air_supply import size_instrument_air_system
from lng_design.berth import berth_queueing_analysis, size_storage_tank
from lng_design.compressor import size_centrifugal_stage
from lng_design.end_flash import flash_end_gas
from lng_design.flowsheet import FlowsheetState
from lng_design.nitrogen_system import size_nitrogen_supply, size_purge
from lng_design.properties import GasMixture
from lng_design.refrigerant_makeup import size_refrigerant_storage
from lng_design.water_system import cooling_water_demand, service_water_demand


def render_water() -> None:
    """Render the 'water' tab."""
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


def render_endflash(flowsheet: FlowsheetState) -> None:
    """Render the 'endflash' tab."""
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


def render_refrigmu(flowsheet: FlowsheetState) -> None:
    """Render the 'refrigmu' tab."""
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


def render_berth(flowsheet: FlowsheetState) -> None:
    """Render the 'berth' tab."""
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


def render_utilities(flowsheet: FlowsheetState) -> None:
    """Render the 'utilities' tab."""
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
