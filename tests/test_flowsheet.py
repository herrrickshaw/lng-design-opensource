from lng_design.flowsheet import FlowsheetState, build_diagram, build_stream_table, TOPOLOGY, NODE_TITLES


def test_empty_state_produces_valid_dot_with_all_nodes_and_edges():
    state = FlowsheetState()
    dot = build_diagram(state)
    assert dot.startswith("digraph Flowsheet {")
    assert dot.rstrip().endswith("}")
    for node_id in NODE_TITLES:
        assert node_id in dot
    for src, dst, _ in TOPOLOGY:
        assert f"{src} -> {dst}" in dot


def test_unsized_nodes_show_not_yet_sized():
    state = FlowsheetState()
    dot = build_diagram(state)
    assert dot.count("not yet sized") == len([k for k in NODE_TITLES if k in
                                               {"V101", "T301", "AC101", "C3LOOP", "MCHE"}])


def test_sized_node_shows_its_data_and_different_fill():
    state = FlowsheetState()
    state.set("vessel", {"Diameter": "914 mm"})
    dot = build_diagram(state)
    assert "Diameter: 914 mm" in dot
    assert "#d7f0d7" in dot  # sized-node fill color present
    assert "not yet sized" not in dot.split("V101")[1].split("];")[0]


def test_stream_table_has_one_row_per_topology_edge():
    state = FlowsheetState()
    rows = build_stream_table(state)
    assert len(rows) == len(TOPOLOGY)
    assert all("Stream" in r and "From" in r and "To" in r for r in rows)


def test_stream_table_reflects_sized_equipment():
    state = FlowsheetState()
    state.set("vessel", {"Diameter": "914 mm"})
    rows = build_stream_table(state)
    v101_row = next(r for r in rows if "V-101" in r["From"] or "V-101" in r["To"])
    combined = v101_row["Upstream equipment data"] + v101_row["Downstream equipment data"]
    assert "Diameter=914 mm" in combined
