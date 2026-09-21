"""Builds a simplified process flow diagram (Graphviz DOT source) and an
accompanying HMB-style stream table from whatever equipment has been sized
so far in an interactive session.

This is a schematic aid for understanding how the pieces fit together -
NOT a drafting-standard P&ID or PFD. Node/stream topology is a generic,
illustrative LNG train (inlet separation -> amine sweetening -> trim
cooling -> C3 precool -> MCHE liquefaction -> end-flash -> storage ->
berth), matching the equipment modules in this package; a real project's
actual configuration will differ.

Two further groups hang off that train, each in its own dashed cluster:
the regasification terminal (tank BOG generation -> BOG compressor ->
recondenser -> send-out pumps/vaporizers -> pipeline) and NGL
fractionation with refrigerant generation (deethanizer -> depropanizer
-> debutanizer, their ethane/propane distillates blended into make-up
mixed refrigerant that feeds the refrigerant storage vessel).
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
    # Regasification terminal: tank BOG -> compressor -> recondenser, and
    # LP-pumped LNG -> recondenser -> send-out pumps + vaporizers -> pipeline.
    ("TANK", "BOGGEN", "Heat leak / displacement"),
    ("BOGGEN", "BOGCOMP", "Boil-off gas"),
    ("BOGCOMP", "RECOND", "Compressed BOG"),
    ("TANK", "RECOND", "LP-pumped LNG"),
    ("RECOND", "REGAS", "Send-out LNG"),
    ("REGAS", "PIPELINE", "Send-out gas"),
    # NGL fractionation and refrigerant generation.
    ("V101", "DEETH", "NGL liquids"),
    ("DEETH", "DEPROP", "C3+ bottoms"),
    ("DEPROP", "DEBUT", "C4+ bottoms"),
    ("DEBUT", "CONDENSATE", "C5+ bottoms"),
    ("DEBUT", "LPG", "Butane distillate"),
    ("DEETH", "MRBLEND", "Ethane distillate"),
    ("DEPROP", "MRBLEND", "Propane distillate"),
    ("MRBLEND", "REFRIGMU", "Make-up MR"),
]

# Standalone plant utility systems - not connected to the process stream
# topology at all, rendered in their own cluster.
UTILITY_NODES = ["AIRSYS", "N2SYS", "WATERSYS"]

# Dashed clusters for the two groups added around the main train:
# cluster id -> (label, member nodes). Utilities keep their own cluster.
CLUSTERS = {
    "cluster_regas": ("Regas Terminal", ["BOGGEN", "BOGCOMP", "RECOND", "REGAS", "PIPELINE"]),
    "cluster_frac": ("NGL Fractionation & Refrigerant Generation",
                     ["DEETH", "DEPROP", "DEBUT", "MRBLEND", "CONDENSATE", "LPG"]),
}

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
    "BOGGEN": "TK-501\nBOG Generation",
    "BOGCOMP": "K-502\nBOG Compressor",
    "RECOND": "V-503\nBOG Recondenser",
    "REGAS": "P-601 / E-601\nSend-out Pumps + Vaporizers",
    "PIPELINE": "Sales Gas\nPipeline",
    "DEETH": "C-701\nDeethanizer",
    "DEPROP": "C-702\nDepropanizer",
    "DEBUT": "C-703\nDebutanizer",
    "MRBLEND": "M-704\nMR Blend / Make-up",
    "CONDENSATE": "C5+ Condensate",
    "LPG": "Butane LPG",
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
    "BOGGEN": "tank_bog",
    "BOGCOMP": "bog_compressor",
    "RECOND": "recondenser",
    "REGAS": "regas_train",
    "DEETH": "deethanizer",
    "DEPROP": "depropanizer",
    "DEBUT": "debutanizer",
    "MRBLEND": "mr_blend",
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

    clustered = {n for _, members in CLUSTERS.values() for n in members}

    def _decl(node_id: str, indent: str) -> str:
        label = _node_label(node_id, state).replace('"', "'")
        return f'{indent}{node_id} [label="{label}", fillcolor="{_node_fill(node_id, state)}"];'

    for node_id in list(process_nodes) + list(side_only_nodes):
        if node_id not in clustered:
            lines.append(_decl(node_id, "  "))

    for src, dst, stream_label in TOPOLOGY:
        lines.append(f'  {src} -> {dst} [label="{stream_label}"];')
    for src, dst, stream_label in SIDE_TOPOLOGY:
        lines.append(f'  {src} -> {dst} [label="{stream_label}", style=dashed];')

    for cid, (clabel, members) in CLUSTERS.items():
        lines.append(f'  subgraph {cid} {{')
        lines.append(f'    label="{clabel}"; style=dashed; fontname="Helvetica"; fontsize=10;')
        for node_id in members:
            lines.append(_decl(node_id, "    "))
        lines.append("  }")

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
