"""Builds a simplified process flow diagram (Graphviz DOT source) and an
accompanying HMB-style stream table from whatever equipment has been sized
so far in an interactive session.

This is a schematic aid for understanding how the pieces fit together -
NOT a drafting-standard P&ID or PFD. Node/stream topology is a generic,
illustrative LNG train (inlet separation -> amine sweetening -> trim
cooling -> C3 precool -> MCHE liquefaction), matching the equipment
modules in this package; a real project's actual configuration will
differ.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# (from_node, to_node, default_stream_label) - the generic train topology.
TOPOLOGY = [
    ("FEED", "V101", "Feed gas"),
    ("V101", "T301", "Wet sour gas"),
    ("T301", "AC101", "Sweet gas"),
    ("AC101", "C3LOOP", "Cooled gas"),
    ("C3LOOP", "MCHE", "Precooled gas"),
    ("MCHE", "LNG", "LNG product"),
]

NODE_TITLES = {
    "FEED": "Feed Gas",
    "V101": "V-101\nInlet Separator",
    "T301": "T-301\nAmine Absorber",
    "AC101": "A-101\nAir Cooler",
    "C3LOOP": "C3-100\nPrecool Loop",
    "MCHE": "E-201\nMCHE",
    "LNG": "LNG Product",
}

NODE_STATE_KEYS = {
    "V101": "vessel",
    "T301": "absorber",
    "AC101": "air_cooler",
    "C3LOOP": "precool",
    "MCHE": "mche",
}


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


def build_diagram(state: FlowsheetState) -> str:
    """Return Graphviz DOT source for the current flowsheet state."""
    lines = [
        "digraph Flowsheet {",
        '  rankdir=LR;',
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", '
        'fontsize=11, margin=0.15];',
        '  edge [fontname="Helvetica", fontsize=9, color="#666666"];',
    ]
    for node_id in NODE_TITLES:
        sized = NODE_STATE_KEYS.get(node_id) and state.get(NODE_STATE_KEYS[node_id])
        fill = "#d7f0d7" if sized else "#f0f0f0"
        label = _node_label(node_id, state).replace('"', "'")
        lines.append(f'  {node_id} [label="{label}", fillcolor="{fill}"];')
    for src, dst, stream_label in TOPOLOGY:
        lines.append(f'  {src} -> {dst} [label="{stream_label}"];')
    lines.append("}")
    return "\n".join(lines)


def build_stream_table(state: FlowsheetState) -> list[dict]:
    """Return an HMB-style stream table (one row per topology edge) with
    whatever data is available from the sized equipment on either side."""
    rows = []
    for i, (src, dst, label) in enumerate(TOPOLOGY, start=1):
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
