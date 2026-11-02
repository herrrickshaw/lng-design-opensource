"""Interactive LNG train conceptual sizing tool.

Run with:  streamlit run streamlit_app.py

Engineers enter feed/process conditions in the sidebar; the app sizes the
propane pre-cool loop, a multistage compressor, and an amine absorber, and
runs the MITA/composite-curve pinch check on a simplified precool duty.
All methods are cited public-domain correlations - see README.md and each
module's docstring for sources.
"""
from __future__ import annotations

import streamlit as st

from lng_design.flowsheet import FlowsheetState
from lng_design.ui.sizing import (
    render_precool,
    render_compressor,
    render_absorber,
    render_molsieve,
    render_mche,
    render_vessel,
    render_exchanger,
    render_aircooler,
)
from lng_design.ui.site import (
    render_water,
    render_endflash,
    render_refrigmu,
    render_berth,
    render_utilities,
)
from lng_design.ui.mche_tools import render_cascade, render_debottleneck, render_mche_rating
from lng_design.ui.terminals import (
    render_regas,
    render_frac,
    render_liq,
    render_regasif,
    render_lpg,
    render_refsup,
)
from lng_design.ui.flowsheet_tab import render_flow

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

with tab_precool:
    render_precool(flowsheet)

with tab_compressor:
    render_compressor()

with tab_absorber:
    render_absorber(flowsheet)

with tab_molsieve:
    render_molsieve(flowsheet)

with tab_mche:
    render_mche(flowsheet)

with tab_vessel:
    render_vessel(flowsheet)

with tab_exchanger:
    render_exchanger()

with tab_aircooler:
    render_aircooler(flowsheet)

with tab_water:
    render_water()

with tab_endflash:
    render_endflash(flowsheet)

with tab_refrigmu:
    render_refrigmu(flowsheet)

with tab_berth:
    render_berth(flowsheet)

with tab_utilities:
    render_utilities(flowsheet)

with tab_cascade:
    render_cascade()

with tab_debottleneck:
    render_debottleneck()

with tab_mche_rating:
    render_mche_rating()

with tab_regas:
    render_regas(flowsheet)

with tab_frac:
    render_frac(flowsheet)

with tab_liq:
    render_liq(flowsheet)

with tab_regasif:
    render_regasif(flowsheet)

with tab_lpg:
    render_lpg(flowsheet)

with tab_refsup:
    render_refsup(flowsheet)

# tab_flow is rendered LAST (though it's the leftmost/first tab visually -
# st.tabs() controls visual order independently of code order) so it
# always reflects this run's fully up-to-date flowsheet state. Streamlit
# reruns the whole script top-to-bottom on every interaction; rendering
# it earlier would show state from before the triggering tab's own
# updates ran in the same pass.
with tab_flow:
    render_flow(flowsheet)

st.divider()
st.caption(
    "**Disclaimer**: this tool implements textbook/public-domain conceptual sizing "
    "methods for early-stage screening only. It is not a substitute for a rigorous "
    "process simulator (rate-based absorber models, full multistream exchanger "
    "rating, vendor-certified compressor curves) for detailed design. Always "
    "validate against a licensed simulator and vendor data before committing to "
    "equipment specifications."
)
