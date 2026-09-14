"""Builds a simplified process flow diagram (Graphviz DOT source) and an
accompanying HMB-style stream table from whatever equipment has been sized
so far in an interactive session.

This is a schematic aid for understanding how the pieces fit together -
NOT a drafting-standard P&ID or PFD. Node/stream topology is a generic,
illustrative LNG train (inlet separation -> amine sweetening -> trim
cooling -> C3 precool -> MCHE liquefaction -> end-flash -> storage ->
berth), matching the equipment modules in this package; a real project's
actual configuration will differ.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# (from_node, to_node, default_stream_label) - the main process train.
TOPOLOGY = [
    ("FEED", "V101", "Feed gas"),
    ("V101", "T301", "Wet sour gas"),
    ("T301", "V201", "Sweet wet gas"),
    ("V201", "AC101", "Dry gas"),
    ("AC101", "C3LOOP", "Cooled gas"),
    ("C3LOOP", "MCHE", "Precooled gas"),
    ("MCHE", "ENDFLASH", "Subcooled LNG"),
    ("ENDFLASH", "TANK", "LNG to storage"),
    ("TANK", "BERTH", "LNG send-out"),
    ("BERTH", "SHIP", "LNG cargo"),
]

# Side branches: (from_node, to_node, label) - not part of the main flow
# path, rendered with a dashed edge.
SIDE_TOPOLOGY = [
    ("C3LOOP", "REFRIGMU", "Makeup/topping"),
    ("ENDFLASH", "FUELGAS", "Flash/BOG gas"),
]

# Standalone plant utility systems - not connected to the process stream
# topology at all, rendered in their own cluster.
UTILITY_NODES = ["AIRSYS", "N2SYS", "WATERSYS"]

NODE_TITLES = {
    "FEED": "Feed Gas",
    "V101": "V-101\nInlet Separator",
    "T301": "T-301\nAmine Absorber",
    "V201": "V-201\nMolecular Sieve",
    "AC101": "A-101\nAir Cooler",
    "C3LOOP": "C3-100\nPrecool Loop",
    "MCHE": "E-201\nMCHE",
    "ENDFLASH": "V-401\nEnd-Flash Drum",
    "TANK": "TK-501\nLNG Storage Tank",
    "BERTH": "J-601\nLoading Berth",
    "SHIP": "LNG Carrier",
    "REFRIGMU": "V-102\nRefrigerant Makeup",
    "FUELGAS": "K-401\nFlash Gas Compressor",
    "AIRSYS": "Instrument/Plant\nAir System",
    "N2SYS": "Nitrogen\nSupply System",
    "WATERSYS": "Service/Potable\nWater System",
}

NODE_STATE_KEYS = {
    "V101": "vessel",
    "T301": "absorber",
    "V201": "molecular_sieve",
    "AC101": "air_cooler",
    "C3LOOP": "precool",
    "MCHE": "mche",
    "ENDFLASH": "end_flash",
    "TANK": "storage_tank",
    "BERTH": "berth",
    "REFRIGMU": "refrigerant_makeup",
    "FUELGAS": "flash_compressor",
    "AIRSYS": "air_supply",
    "N2SYS": "nitrogen",
    "WATERSYS": "service_water",
}

_ALL_EDGES = TOPOLOGY + SIDE_TOPOLOGY


@dataclass
class FlowsheetState:
    """Holds the latest sizing result (as a plain dict of display strings)
    for each node, keyed the same as NODE_STATE_KEYS values. Populated
    incrementally as the user sizes each piece of equipment in the app."""
    node_data: dict[str, dict[str, str]] = field(default_factory=dict)

    def set(self, key: str, data: dict[str, str]) -> None:
        self.node_data[key] = data

    def get(self, key: str) -> dict[str, str] | None:
        return self.node_data.get(key)


def _node_label(node_id: str, state: FlowsheetState) -> str:
    title = NODE_TITLES[node_id]
    state_key = NODE_STATE_KEYS.get(node_id)
    if state_key is None:
        # Boundary stream node (feed / product), not a piece of equipment -
        # there's nothing to "size" here, so no status line.
        return title
    data = state.get(state_key)
    if not data:
        return f"{title}\n(not yet sized)"
    detail = "\n".join(f"{k}: {v}" for k, v in data.items())
    return f"{title}\n{detail}"


def _node_fill(node_id: str, state: FlowsheetState) -> str:
    sized = NODE_STATE_KEYS.get(node_id) and state.get(NODE_STATE_KEYS[node_id])
    return "#d7f0d7" if sized else "#f0f0f0"


def build_diagram(state: FlowsheetState) -> str:
    """Return Graphviz DOT source for the current flowsheet state."""
    lines = [
        "digraph Flowsheet {",
        '  rankdir=LR;',
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", '
        'fontsize=11, margin=0.15];',
        '  edge [fontname="Helvetica", fontsize=9, color="#666666"];',
    ]

    process_nodes = {n for edge in TOPOLOGY for n in (edge[0], edge[1])}
    side_only_nodes = {n for edge in SIDE_TOPOLOGY for n in (edge[0], edge[1])} - process_nodes

    for node_id in list(process_nodes) + list(side_only_nodes):
        label = _node_label(node_id, state).replace('"', "'")
        lines.append(f'  {node_id} [label="{label}", fillcolor="{_node_fill(node_id, state)}"];')

    for src, dst, stream_label in TOPOLOGY:
        lines.append(f'  {src} -> {dst} [label="{stream_label}"];')
    for src, dst, stream_label in SIDE_TOPOLOGY:
        lines.append(f'  {src} -> {dst} [label="{stream_label}", style=dashed];')

    lines.append('  subgraph cluster_utilities {')
    lines.append('    label="Plant Utilities"; style=dashed; fontname="Helvetica"; fontsize=10;')
    for node_id in UTILITY_NODES:
        label = _node_label(node_id, state).replace('"', "'")
        lines.append(f'    {node_id} [label="{label}", fillcolor="{_node_fill(node_id, state)}"];')
    lines.append("  }")

    lines.append("}")
    return "\n".join(lines)


def build_stream_table(state: FlowsheetState) -> list[dict]:
    """Return an HMB-style stream table (one row per process/side edge)
    with whatever data is available from the sized equipment on either
    side. Utility systems have no connecting stream, so they aren't
    included here - see their own tabs/nodes for their sizing results."""
    rows = []
    for i, (src, dst, label) in enumerate(_ALL_EDGES, start=1):
        src_data = state.get(NODE_STATE_KEYS.get(src, "")) or {}
        dst_data = state.get(NODE_STATE_KEYS.get(dst, "")) or {}
        rows.append({
            "Stream": f"S-{100+i}",
            "Description": label,
            "From": NODE_TITLES[src].split("\n")[0],
            "To": NODE_TITLES[dst].split("\n")[0],
            "Upstream equipment data": "; ".join(f"{k}={v}" for k, v in src_data.items()) or "-",
            "Downstream equipment data": "; ".join(f"{k}={v}" for k, v in dst_data.items()) or "-",
        })
    return rows
