"""Smoke test: the Streamlit page renders every tab with default inputs and raises nothing."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "streamlit_app.py")


def test_app_renders_all_tabs_without_exception():
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    assert len(at.tabs) >= 23  # 23 top-level tabs plus nested ones
    assert at.title[0].value == "LNG Train Conceptual Sizing (open-source)"


def test_precool_button_reports_metrics():
    at = AppTest.from_file(APP, default_timeout=120).run()
    next(b for b in at.button if b.label == "Size pre-cool loop").click().run()
    assert not at.exception
    labels = {m.label for m in at.metric}
    assert {"Optimal T_evap", "Compressor power", "Refrigerant flow", "COP"} <= labels
