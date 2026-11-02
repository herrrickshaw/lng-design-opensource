"""Process flow diagram tab (rendered last so it reflects this run's state).

Mechanically split out of streamlit_app.py; behaviour unchanged.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lng_design.flowsheet import FlowsheetState, build_diagram, build_stream_table


def render_flow(flowsheet: FlowsheetState) -> None:
    """Render the 'flow' tab."""
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
