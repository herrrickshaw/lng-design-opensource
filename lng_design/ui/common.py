"""Widgets shared by several tabs."""
from __future__ import annotations

import streamlit as st


def comp_editor(defaults: dict[str, float], key: str) -> dict[str, float]:
    """Row of mole-fraction inputs (0-1, one per species); warns if they do not sum to 1."""
    cols = st.columns(len(defaults))
    vals = {n: c.number_input(f"{n}", 0.0, 1.0, v, 0.005, key=f"{key}_{n}", format="%.3f")
            for (n, v), c in zip(defaults.items(), cols)}
    tot = sum(vals.values())
    if abs(tot - 1.0) > 1e-6:
        st.warning(f"Mole fractions sum to {tot:.4f}; they must sum to 1.")
    return vals
