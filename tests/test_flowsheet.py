from lng_design.flowsheet import (
    FlowsheetState, build_diagram, build_stream_table, TOPOLOGY,
    SIDE_TOPOLOGY, UTILITY_NODES, NODE_TITLES, NODE_STATE_KEYS, CLUSTERS,
)


def test_empty_state_produces_valid_dot_with_all_nodes_and_edges():
    state = FlowsheetState()
    dot = build_diagram(state)
    assert dot.startswith("digraph Flowsheet {")
    assert dot.rstrip().endswith("}")
    for node_id in NODE_TITLES:
        assert node_id in dot
    for src, dst, _ in TOPOLOGY:
        assert f"{src} -> {dst}" in dot
    for src, dst, _ in SIDE_TOPOLOGY:
        assert f"{src} -> {dst}" in dot


def test_utility_nodes_rendered_in_their_own_cluster():
    state = FlowsheetState()
    dot = build_diagram(state)
    assert "cluster_utilities" in dot
    assert "Plant Utilities" in dot
    for node_id in UTILITY_NODES:
        assert node_id in dot


def test_unsized_equipment_nodes_show_not_yet_sized():
    state = FlowsheetState()
    dot = build_diagram(state)
    # Every node with a NODE_STATE_KEYS entry is "equipment" and should
    # show the not-yet-sized status when the state is empty; boundary
    # nodes (FEED, SHIP) have no state key and show no status line.
    assert dot.count("not yet sized") == len(NODE_STATE_KEYS)


def test_sized_node_shows_its_data_and_different_fill():
    state = FlowsheetState()
    state.set("vessel", {"Diameter": "914 mm"})
    dot = build_diagram(state)
    assert "Diameter: 914 mm" in dot
    assert "#d7f0d7" in dot  # sized-node fill color present
    assert "not yet sized" not in dot.split("V101")[1].split("];")[0]


def test_stream_table_has_one_row_per_process_and_side_edge():
    state = FlowsheetState()
    rows = build_stream_table(state)
    assert len(rows) == len(TOPOLOGY) + len(SIDE_TOPOLOGY)
    assert all("Stream" in r and "From" in r and "To" in r for r in rows)


def test_stream_table_reflects_sized_equipment():
    state = FlowsheetState()
    state.set("vessel", {"Diameter": "914 mm"})
    rows = build_stream_table(state)
    v101_row = next(r for r in rows if "V-101" in r["From"] or "V-101" in r["To"])
    combined = v101_row["Upstream equipment data"] + v101_row["Downstream equipment data"]
    assert "Diameter=914 mm" in combined


def test_side_branch_reflects_sized_refrigerant_makeup():
    state = FlowsheetState()
    state.set("refrigerant_makeup", {"Diameter": "1219 mm"})
    rows = build_stream_table(state)
    refrig_row = next(r for r in rows if "V-102" in r["To"])  # first line of the REFRIGMU title
    assert "Diameter=1219 mm" in refrig_row["Downstream equipment data"]


def test_regas_and_fractionation_groups_are_wired_in_and_clustered():
    dot = build_diagram(FlowsheetState())
    for edge in [("TANK", "BOGGEN"), ("BOGGEN", "BOGCOMP"), ("BOGCOMP", "RECOND"),
                 ("RECOND", "REGAS"), ("REGAS", "PIPELINE"), ("V101", "DEETH"),
                 ("DEETH", "DEPROP"), ("DEPROP", "DEBUT"), ("DEETH", "MRBLEND"),
                 ("DEPROP", "MRBLEND"), ("MRBLEND", "REFRIGMU")]:
        assert f"{edge[0]} -> {edge[1]}" in dot
    for cid, (label, members) in CLUSTERS.items():
        assert f"subgraph {cid}" in dot and label in dot
        block = dot.split(f"subgraph {cid}")[1].split("  }")[0]
        for m in members:
            assert m in block                     # declared inside its cluster
    # every node is declared exactly once
    for node_id in NODE_TITLES:
        assert dot.count(f"  {node_id} [label=") == 1


def test_new_equipment_nodes_reflect_sizing_and_stream_table_rows():
    state = FlowsheetState()
    state.set("deethanizer", {"Trays": "35"})
    state.set("bog_compressor", {"Power": "2,097 kW"})
    dot = build_diagram(state)
    assert "Trays: 35" in dot and "Power: 2,097 kW" in dot
    rows = build_stream_table(state)
    assert len(rows) == len(TOPOLOGY) + len(SIDE_TOPOLOGY)
    r = next(r for r in rows if r["Description"] == "C3+ bottoms")
    assert "Trays=35" in r["Upstream equipment data"]
    r = next(r for r in rows if r["Description"] == "Compressed BOG")
    assert "Power=2,097 kW" in r["Upstream equipment data"]


def test_stream_ids_stay_unique():
    ids = [r["Stream"] for r in build_stream_table(FlowsheetState())]
    assert len(ids) == len(set(ids))


def test_lpg_terminal_is_wired_in_with_its_return_loop_and_cluster():
    dot = build_diagram(FlowsheetState())
    for edge in [("LPGSHIP", "LPGTANK"), ("LPGTANK", "LPGCOMP"), ("LPGCOMP", "LPGCOND"),
                 ("LPGCOND", "LPGTANK"), ("LPGTANK", "LPGPUMP"), ("LPGPUMP", "LPGHEAT"),
                 ("LPGHEAT", "LPGDELIV")]:
        assert f"{edge[0]} -> {edge[1]}" in dot
    assert "subgraph cluster_lpg" in dot and "LPG Import Terminal" in dot
    block = dot.split("subgraph cluster_lpg")[1].split("  }")[0]
    for m in CLUSTERS["cluster_lpg"][1]:
        assert m in block


def test_lpg_nodes_show_sizing_and_boundaries_have_none():
    state = FlowsheetState()
    state.set("lpg_tank", {"Volume": "59,747 m3 x 2"})
    state.set("lpg_heater", {"Duty": "3,218 kW"})
    dot = build_diagram(state)
    assert "Volume: 59,747 m3 x 2" in dot and "Duty: 3,218 kW" in dot
    assert "LPGSHIP" not in NODE_STATE_KEYS and "LPGDELIV" not in NODE_STATE_KEYS
    rows = build_stream_table(state)
    r = next(r for r in rows if r["Description"] == "Pressurized LPG")
    assert "Duty=3,218 kW" in r["Downstream equipment data"]
