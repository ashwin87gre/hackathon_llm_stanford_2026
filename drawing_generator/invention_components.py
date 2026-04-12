"""
Read invention JSON, generate a rich description with an LLM, extract canonical
components via register_component (canonical -> int id), then emit a JSON graph whose
node ids come from that registry; visible labels are `<canonical>-<id>` (canonical from LLM, id from code); layout LLM proposes connectivity; draw.io positions are computed in code (no overlap).

LLM wording lives in PROMPT_* and USER_* constants near the top of this file.
A verify node refines the graph; draw.io XML uses deterministic positions; a final LLM node writes the Brief Description of the Drawings; output includes that text and the diagrams.net URL.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.parse
from collections import defaultdict, deque
from typing import Literal, TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# JSON shapes (documentation + strings embedded in LLM prompts)
# =============================================================================

# Final graph written to stdout / state (assembled in code from registry + LLM layout).
STRICT_GRAPH_JSON_SPEC = """{
  "nodes": [
    {
      "id": number,
      "label": "string",
      "x": number,
      "y": number
    }
  ],
  "edges": [
    {
      "source": number,
      "target": number,
      "label": "optional string"
    }
  ]
}"""

# Subset the LLM must return; labels come from register_component, not from the model.
LLM_LAYOUT_JSON_SPEC = """{
  "positions": [
    { "id": number, "x": number, "y": number }
  ],
  "edges": [
    { "source": number, "target": number, "label": "optional string" }
  ]
}"""


# =============================================================================
# LLM system prompts — edit wording here; nodes only substitute variables.
# =============================================================================

PROMPT_DESCRIPTION_GENERATION_SYSTEM = """\
You write a clear, technical paragraph describing the invention for engineers. \
Synthesize the name, existing description, and key innovation into one cohesive text."""


PROMPT_COMPONENT_EXTRACTION_SYSTEM = """\
You are writing a patent for this invention. You identify distinct HIGH LEVEL technical components suitable for inclusion in a high level patent system diagram (e.g., FIG. 1).

Identify major components for a patent system diagram, call register_component exactly once with a single canonical English name.

A valid component must be a concrete or well-defined functional element that would reasonably appear as a labeled box or element in a patent figure.

Include components such as:
- physical devices (e.g., sensors, servers, user devices)
- data sources or inputs (e.g., questionnaire responses, user input)
- processing modules (e.g., machine learning model, feature extraction module)
- intermediate data representations (e.g., verdict inclination, feature vectors)
- outputs (e.g., prediction output, ranking result)
- user-facing modules or interfaces

Prefer components that participate directly in:
- input
- processing
- transformation
- storage
- output
- communication

Map synonyms to one canonical form (e.g., "CPU" instead of "central processing unit").

Do NOT register:
- the invention as a whole
- abstract umbrella terms
- marketing or descriptive phrases

Avoid vague labels such as:
- system
- software system
- framework
- platform
- solution
- technology
- approach
- workflow
- pipeline

unless they are explicitly described as a distinct, bounded subsystem with a specific function.

Prefer specific, operational names over abstract summaries.

In figures, each box label is formed in code as: your canonical English name, then "-", then the integer id assigned in the registry (e.g. ML model-2). You only supply the short canonical name to register_component; do not append the id yourself.

After each batch of register_component results, you will receive a message listing ALL components registered so far (canonical_name -> id). That list is authoritative.

Before calling register_component again, compare your next candidate to that list. Do NOT register a new name if it is the same component, a synonym, or substantially similar in function or role to an entry already listed (e.g. "ML model" vs "machine learning model"). Only register genuinely distinct components that are not already covered by an existing canonical name."""


PROMPT_GRAPH_LAYOUT_SYSTEM = """\
You propose layout and connectivity for a component graph. \
Node identities are NOT yours to choose: they come only from register_component (canonical_name -> integer id). \
You MUST NOT invent or rename ids. Use ONLY these integer ids as `id`, edge `source`, and edge `target`:
{allowed_ids_json}

Output MUST follow this structure (no other top-level keys):

{layout_spec}

Rules for `positions`:
- Include exactly one position entry for every id in the allowed list (each with that id plus x and y). Spread x and y so nodes do not overlap.

Rules for `edges` (read carefully):
- Each edge must follow a forward pipeline direction: input → processing → model → output → interface (adapt this pattern to the actual registered components; preserve left-to-right or top-down flow of data and control).
- Do NOT connect components across unrelated workflows.
- Do NOT create cycles or feedback loops unless the invention text explicitly describes them.
- Do NOT connect UI or interface components back into data collection unless the description clearly supports that flow.
- Avoid edges that only indicate vague association.
- When you set an edge `label`, use a short phrase for what flows along that edge (e.g. response data, demographic data, feature vectors, prediction output, comparison results). Do not use the source or target node name alone as the label.
- If including an edge would break a clean pipeline structure, omit it.
- Use only allowed ids as source and target. If only one node, use an empty edge list.

The final artifact shown to the user will merge your positions with labels from:
{registered_json}
"""


PROMPT_GRAPH_VERIFY_SYSTEM = """\
You verify and correct a draft component graph so it matches the invention text (especially the generated technical description). \
Output a single JSON object with the same schema as the input graph: `nodes` (id, label, x, y) and `edges` (source, target, optional label).

Focus heavily on `edges`:
- Remove or reroute edges that contradict the high-level data/control flow described in the text.
- Remove edges that connect unrelated subsystems or imply cycles/feedback unless the description explicitly supports them.
- Ensure edge labels describe what flows (short phrases: e.g. feature vectors, prediction output); omit edge label if unnecessary.
- Prefer a clear forward pipeline consistent with the overview; drop edges that only suggest vague association.

Nodes:
- Keep the same set of node ids as in the draft (do not invent new components or ids). Node `label` values follow `<canonical>-<id>` matching the draft; downstream code may normalize labels to that pattern.
- You may adjust x and y slightly to reduce overlap or clarify flow after edge changes.

If the draft is already consistent, return an equivalent graph with only minor improvements. \
The output must be valid for the schema and use only integer ids present in the draft nodes."""


# =============================================================================
# LLM user-message templates — placeholders filled from graph state in node functions.
# =============================================================================

USER_DESCRIPTION_GENERATION = """\
Invention name: {invention_name}

Description: {description}

Key innovation: {key_innovation}"""


USER_COMPONENT_EXTRACTION = """\
Invention description to analyze:

{generated_description}"""


USER_COMPONENT_REGISTRY_SNAPSHOT = """\
Reminder — all components registered so far (canonical_name -> id). Review before any further register_component calls:
{registry_json}

Only register a new canonical name if it is not already represented above and is not a synonym or overlapping concept with an existing entry. If the next component is similar to one already listed, do not call register_component for it."""


USER_GRAPH_LAYOUT = """\
Invention name: {invention_name}

Original description: {description}

Key innovation: {key_innovation}

Generated technical description:
{generated_description}

Use only the registered component ids from the system message. Do not add nodes for components not in the registry."""


USER_GRAPH_VERIFY = """\
Invention name: {invention_name}

Original description: {description}

Key innovation: {key_innovation}

Generated technical description (use as primary overview for consistency checks):
{generated_description}

Draft component graph JSON:
{draft_graph_json}
"""


PROMPT_BRIEF_DESCRIPTION_DRAWINGS_SYSTEM = """\
You are a patent drafting assistant.

Your task is to write the **Brief Description of the Drawings** section of a patent application from the provided JSON.

Instructions:
- Use formal US patent style.
- Write a section titled exactly: **Brief Description of the Drawings**
- For each figure in the JSON, write one concise sentence beginning with "FIG. X".
- Describe what the figure illustrates in clear, neutral, technical language.
- Do not add interpretation, advantages, claim language, marketing language, or implementation details beyond what is needed to identify the figure.
- Do not invent figures or technical details not supported by the JSON.
- Keep the output concise and professional.
- Output only the final section text."""


USER_BRIEF_DESCRIPTION_DRAWINGS = """\
Invention name: {invention_name}

Component diagram JSON (the drawing content to describe):
{graph_json}
"""


# Shared registry: canonical_name -> unique integer id (assigned on first registration)
_COMPONENT_ID_MAP: dict[str, int] = {}
_NEXT_COMPONENT_ID: int = 0


def reset_component_registry() -> None:
    """Clear register_component state before a new pipeline run."""
    global _NEXT_COMPONENT_ID
    _COMPONENT_ID_MAP.clear()
    _NEXT_COMPONENT_ID = 0


def _new_component_id() -> int:
    global _NEXT_COMPONENT_ID
    cid = _NEXT_COMPONENT_ID
    _NEXT_COMPONENT_ID += 1
    return cid


def _graph_node_display_label(canonical_name: str, registry_id: int) -> str:
    """Visible node label: short name from LLM (register_component) + '-' + id assigned in code."""
    return f"{canonical_name}-{registry_id}"


@tool
def register_component(canonical_name: str) -> str:
    """Register one distinct technical component under its canonical English name.

    The model should check the latest registry snapshot in the conversation before calling:
    only register if this name is new and not similar to an already-listed component.
    Each new canonical name gets a unique integer id (canonical_name -> id in the shared map).
    """
    name = canonical_name.strip()
    if not name:
        return "ignored_empty"
    if name in _COMPONENT_ID_MAP:
        cid = _COMPONENT_ID_MAP[name]
        total = len(_COMPONENT_ID_MAP)
        print(
            f"[register_component] canonical '{name}' already mapped to id {cid} "
            f"→ distinct components = {total}"
        )
        return f"already_registered:{name}:id={cid}"
    cid = _new_component_id()
    _COMPONENT_ID_MAP[name] = cid
    total = len(_COMPONENT_ID_MAP)
    print(
        f"[register_component] mapped '{name}' -> id {cid} "
        f"→ distinct components = {total}"
    )
    return f"registered:{name}:id={cid}"


class GraphEdge(BaseModel):
    """Directed edge; source and target must be node ids from nodes[].id."""

    model_config = ConfigDict(extra="forbid")

    source: int = Field(description="Source node id (must match a nodes[].id)")
    target: int = Field(description="Target node id (must match a nodes[].id)")
    label: str | None = Field(
        default=None,
        description="Optional short label on the edge (e.g. data flow, power); omit if not needed",
    )


class NodePositionSpec(BaseModel):
    """x/y for one registered component id (id must come from register_component)."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(description="Must be one of the allowed registered node ids")
    x: float = Field(description="Horizontal position (unitless; spread roughly 0–800)")
    y: float = Field(description="Vertical position (unitless; spread roughly 0–600)")


class GraphLayoutLLMSchema(BaseModel):
    """LLM output: coordinates and edges only. Node ids are fixed by the tool registry."""

    model_config = ConfigDict(extra="forbid")

    positions: list[NodePositionSpec] = Field(
        description="One {id,x,y} per registered component id you were given; ids must match exactly."
    )
    edges: list[GraphEdge] = Field(
        description="Directed edges using only registered node ids as source/target; [] if single node"
    )


class FinalGraphNode(BaseModel):
    """One node in the verified graph (matches STRICT_GRAPH_JSON_SPEC node shape)."""

    model_config = ConfigDict(extra="forbid")

    id: int
    label: str
    x: float
    y: float


class VerifiedComponentGraphSchema(BaseModel):
    """Structured output for the graph verification node (full graph, same format as final artifact)."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[FinalGraphNode]
    edges: list[GraphEdge]


def _build_component_graph_from_registry(layout: GraphLayoutLLMSchema) -> dict:
    """Assemble final graph: labels and ids from _COMPONENT_ID_MAP only; x/y from LLM with fallbacks."""
    allowed_ids = set(_COMPONENT_ID_MAP.values())
    id_to_label = {vid: name for name, vid in _COMPONENT_ID_MAP.items()}
    pos_by_id: dict[int, tuple[float, float]] = {}
    for p in layout.positions:
        if p.id in allowed_ids:
            pos_by_id[p.id] = (float(p.x), float(p.y))

    sorted_ids = sorted(allowed_ids)
    nodes: list[dict] = []
    for i, nid in enumerate(sorted_ids):
        if nid in pos_by_id:
            x, y = pos_by_id[nid]
        else:
            x, y = float((i % 4) * 200), float((i // 4) * 150)
        nodes.append(
            {
                "id": nid,
                "label": _graph_node_display_label(id_to_label[nid], nid),
                "x": x,
                "y": y,
            }
        )

    edges_out: list[dict] = []
    for e in layout.edges:
        if e.source in allowed_ids and e.target in allowed_ids:
            edges_out.append(e.model_dump(mode="json", exclude_none=True))

    return {"nodes": nodes, "edges": edges_out}


def _reconcile_verified_graph(draft: dict, verified: VerifiedComponentGraphSchema) -> dict:
    """Force registry-true labels and valid ids; merge LLM positions with draft fallbacks."""
    allowed = set(_COMPONENT_ID_MAP.values())
    id_to_label = {vid: name for name, vid in _COMPONENT_ID_MAP.items()}
    draft_by_id = {n["id"]: n for n in draft.get("nodes", []) if isinstance(n, dict) and "id" in n}
    llm_by_id = {n.id: n for n in verified.nodes}

    nodes: list[dict] = []
    for i, nid in enumerate(sorted(allowed)):
        label = _graph_node_display_label(id_to_label[nid], nid)
        if nid in llm_by_id:
            n = llm_by_id[nid]
            nodes.append({"id": nid, "label": label, "x": float(n.x), "y": float(n.y)})
        elif nid in draft_by_id:
            d = draft_by_id[nid]
            nodes.append(
                {
                    "id": nid,
                    "label": label,
                    "x": float(d["x"]),
                    "y": float(d["y"]),
                }
            )
        else:
            nodes.append(
                {
                    "id": nid,
                    "label": label,
                    "x": float((i % 4) * 200),
                    "y": float((i // 4) * 150),
                }
            )

    edges_out: list[dict] = []
    seen: set[tuple[int, int, str | None]] = set()
    for e in verified.edges:
        if e.source not in allowed or e.target not in allowed or e.source == e.target:
            continue
        key = (e.source, e.target, e.label)
        if key in seen:
            continue
        seen.add(key)
        edges_out.append(e.model_dump(mode="json", exclude_none=True))

    return {"nodes": nodes, "edges": edges_out}


class InventionState(TypedDict):
    invention_name: str
    description: str
    key_innovation: str
    generated_description: str
    component_graph: dict
    drawio_xml: str
    brief_description_drawings: str


LLMProvider = Literal["openai", "claude"]
_LLM_PROVIDER: LLMProvider = "openai"

def set_llm_provider(provider: LLMProvider) -> None:
    global _LLM_PROVIDER
    _LLM_PROVIDER = provider


def _anthropic_api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")


def _require_llm() -> BaseChatModel:
    if _LLM_PROVIDER == "claude":
        key = _anthropic_api_key()
        if not key:
            print(
                "Error: for --provider claude set ANTHROPIC_API_KEY or CLAUDE_API_KEY.",
                file=sys.stderr,
            )
            sys.exit(1)
        model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")
        return ChatAnthropic(model=model, temperature=0.2, api_key=key)
    if not os.environ.get("OPENAI_API_KEY"):
        print("Error: for --provider openai set OPENAI_API_KEY in the environment.", file=sys.stderr)
        sys.exit(1)
    model = os.environ.get("OPENAI_MODEL", "gpt-5.4")
    return ChatOpenAI(model=model, temperature=0.2)


def load_invention(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for key in ("invention_name", "description", "key_innovation"):
        if key not in data:
            raise ValueError(f"JSON must include '{key}'")
    return data


def invoke_patent_drawing_pipeline(data: dict) -> InventionState:
    """Run the full LangGraph once. `data` must include invention_name, description, key_innovation."""
    reset_component_registry()
    initial: InventionState = {
        "invention_name": data["invention_name"],
        "description": data["description"],
        "key_innovation": data["key_innovation"],
        "generated_description": "",
        "component_graph": {},
        "drawio_xml": "",
        "brief_description_drawings": "",
    }
    graph = build_graph()
    return graph.invoke(initial)


def _component_registry_json_for_prompt() -> str:
    """Pretty-print current register_component map for injection into LLM messages."""
    if not _COMPONENT_ID_MAP:
        return "(none yet — no components registered)"
    return json.dumps(dict(sorted(_COMPONENT_ID_MAP.items())), indent=2)


_MINIMAL_MXGRAPH = (
    '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
    "</root></mxGraphModel>"
)

# Block diagram layout (deterministic): layered columns left→right, stacked vertically per layer.
_BLK_MARGIN = 96.0
_BLK_NODE_W = 220.0
_BLK_NODE_H_MIN = 56.0
_BLK_GAP_X = 96.0
_BLK_GAP_Y = 80.0
_BLK_LINE_HEIGHT_PX = 20.0
_BLK_PAD_Y = 18.0
_BLK_PAD_X = 18.0
_BLK_AVG_CHAR_PX = 7.0
_BLK_EDGE_LABEL_MAX = 42
_BLK_VERTEX_STYLE = (
    "rounded=0;whiteSpace=wrap;html=1;align=center;verticalAlign=middle;"
    "strokeWidth=2;fontSize=12;fontStyle=0;fillColor=#FFFFFF;strokeColor=#333333;"
)
_BLK_EDGE_BASE = (
    "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
    "endArrow=classic;endFill=1;strokeWidth=2;"
)
_BLK_EDGE_LABELED = (
    _BLK_EDGE_BASE
    + "fontSize=12;fontStyle=0;labelBackgroundColor=#FFFFFF;labelBorderColor=#B0BEC5;"
    "spacingTop=2;spacingBottom=2;spacingLeft=4;spacingRight=4;"
)
_BLK_EDGE_UNLABELED = _BLK_EDGE_BASE + "fontSize=12;"


def _blk_normalize_id(nid: object) -> int | str:
    if isinstance(nid, float) and nid == int(nid):
        return int(nid)
    if isinstance(nid, int) and type(nid) is not bool:
        return nid
    return nid


def _blk_truncated_edge_label(raw: object) -> str | None:
    s = str(raw).strip() if raw is not None else ""
    if not s:
        return None
    if len(s) > _BLK_EDGE_LABEL_MAX:
        s = s[: _BLK_EDGE_LABEL_MAX - 3].rstrip() + "..."
    return s


def _blk_box_dimensions(label: str) -> tuple[float, float]:
    w = _BLK_NODE_W
    inner = max(8.0, w - 2.0 * _BLK_PAD_X)
    cpl = max(12, int(inner / _BLK_AVG_CHAR_PX))
    n = len(label) if label else 0
    n_lines = max(1, (n + cpl - 1) // cpl)
    h = max(_BLK_NODE_H_MIN, float(n_lines) * _BLK_LINE_HEIGHT_PX + 2.0 * _BLK_PAD_Y)
    return (w, h)


def _blk_topological_order(ids: set[int | str], edges: list[dict]) -> list[int | str]:
    out_adj: dict[int | str, list[int | str]] = defaultdict(list)
    in_deg: dict[int | str, int] = {i: 0 for i in ids}
    for e in edges:
        if not isinstance(e, dict):
            continue
        s = _blk_normalize_id(e.get("source"))
        t = _blk_normalize_id(e.get("target"))
        if s not in ids or t not in ids or s == t:
            continue
        out_adj[s].append(t)
        in_deg[t] += 1
    for v in out_adj:
        out_adj[v].sort(key=lambda x: (str(type(x)), str(x)))
    q = deque(sorted([i for i in ids if in_deg[i] == 0], key=lambda x: (str(type(x)), str(x))))
    order: list[int | str] = []
    while q:
        u = q.popleft()
        order.append(u)
        for v in out_adj[u]:
            in_deg[v] -= 1
            if in_deg[v] == 0:
                q.append(v)
    seen = set(order)
    for i in sorted(ids, key=lambda x: (str(type(x)), str(x))):
        if i not in seen:
            order.append(i)
    return order


def _blk_compute_levels(ids: set[int | str], edges: list[dict], topo: list[int | str]) -> dict[int | str, int]:
    """DAG layer index along primary flow (left = earlier in pipeline). Cycles: best-effort."""
    out_adj: dict[int | str, list[int | str]] = defaultdict(list)
    for e in edges:
        if not isinstance(e, dict):
            continue
        s = _blk_normalize_id(e.get("source"))
        t = _blk_normalize_id(e.get("target"))
        if s not in ids or t not in ids or s == t:
            continue
        out_adj[s].append(t)
    level: dict[int | str, int] = {i: 0 for i in ids}
    for u in topo:
        for v in out_adj.get(u, []):
            level[v] = max(level[v], level[u] + 1)
    return level


def _render_block_diagram_mxgraph_xml(graph: dict) -> str:
    """draw.io block diagram: orthogonal edges, positions from layered layout (no LLM)."""
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    if not nodes:
        return _MINIMAL_MXGRAPH

    label_by_id: dict[int | str, str] = {}
    for n in nodes:
        if not isinstance(n, dict) or "id" not in n:
            continue
        nid = _blk_normalize_id(n["id"])
        label_by_id[nid] = str(n.get("label", ""))

    ids: set[int | str] = set(label_by_id.keys())
    edge_rows = [e for e in edges if isinstance(e, dict)]
    topo = _blk_topological_order(ids, edge_rows)
    level_of = _blk_compute_levels(ids, edge_rows, topo)

    by_level: dict[int, list[int | str]] = defaultdict(list)
    for nid in ids:
        by_level[level_of[nid]].append(nid)
    for lv in by_level:
        by_level[lv].sort(key=lambda x: (str(type(x)), str(x)))

    col_w = _BLK_NODE_W + _BLK_GAP_X
    pos: dict[int | str, tuple[float, float, float, float]] = {}
    max_x = _BLK_MARGIN
    max_y = _BLK_MARGIN

    for lv in sorted(by_level.keys()):
        x = _BLK_MARGIN + float(lv) * col_w
        y_cur = _BLK_MARGIN
        for nid in by_level[lv]:
            bw, bh = _blk_box_dimensions(label_by_id.get(nid, ""))
            pos[nid] = (x, y_cur, bw, bh)
            max_x = max(max_x, x + bw)
            max_y = max(max_y, y_cur + bh)
            y_cur += bh + _BLK_GAP_Y

    page_w_in = max(11.0, (max_x + _BLK_MARGIN) / 96.0)
    page_h_in = max(8.5, (max_y + _BLK_MARGIN) / 96.0)

    parts: list[str] = [
        f'<mxGraphModel dx="0" dy="0" grid="1" gridSize="10" page="1" pageScale="1" '
        f'pageWidth="{page_w_in:.2f}" pageHeight="{page_h_in:.2f}">',
        "<root>",
        '<mxCell id="0"/>',
        '<mxCell id="1" parent="0"/>',
    ]

    for nid in sorted(ids, key=lambda x: (str(type(x)), str(x))):
        cid = f"n{nid}"
        lab = html.escape(label_by_id.get(nid, ""), quote=True)
        x, y, bw, bh = pos[nid]
        parts.append(
            f'<mxCell id="{cid}" value="{lab}" style="{_BLK_VERTEX_STYLE}" '
            f'vertex="1" parent="1">'
            f'<mxGeometry x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" as="geometry"/>'
            f"</mxCell>"
        )

    ei = 0
    for e in edge_rows:
        s = _blk_normalize_id(e.get("source"))
        t = _blk_normalize_id(e.get("target"))
        if s not in label_by_id or t not in label_by_id or s == t:
            continue
        short = _blk_truncated_edge_label(e.get("label"))
        val_attr = ""
        estyle = _BLK_EDGE_UNLABELED
        if short is not None:
            val_attr = f' value="{html.escape(short, quote=True)}"'
            estyle = _BLK_EDGE_LABELED
        eid = f"e{ei}"
        ei += 1
        parts.append(
            f'<mxCell id="{eid}"{val_attr} style="{estyle}" edge="1" parent="1" '
            f'source="n{s}" target="n{t}">'
            '<mxGeometry relative="1" as="geometry"/>'
            "</mxCell>"
        )

    parts.append("</root></mxGraphModel>")
    return "".join(parts)


def _verified_graph_to_drawio_block_xml(graph: dict) -> str:
    """Emit block diagram XML with code-computed positions (ignores JSON x/y)."""
    if not graph.get("nodes"):
        return _MINIMAL_MXGRAPH
    return _render_block_diagram_mxgraph_xml(graph)


def diagrams_net_create_url(xml_content: str) -> str:
    """Build https://app.diagrams.net/#create=... URL from mxGraphModel XML."""
    config = {"type": "xml", "data": xml_content}
    encoded_json = urllib.parse.quote(json.dumps(config))
    return f"https://app.diagrams.net/#create={encoded_json}"


def node_description_generation(state: InventionState) -> dict[str, str]:
    llm = _require_llm()
    system_msg = SystemMessage(content=PROMPT_DESCRIPTION_GENERATION_SYSTEM)
    human_msg = HumanMessage(
        content=USER_DESCRIPTION_GENERATION.format(
            invention_name=state["invention_name"],
            description=state["description"],
            key_innovation=state["key_innovation"],
        )
    )
    out = llm.invoke([system_msg, human_msg])
    text = out.content if isinstance(out.content, str) else str(out.content)
    return {"generated_description": text}


def node_component_extraction(state: InventionState) -> dict:
    llm = _require_llm().bind_tools([register_component])
    system_msg = SystemMessage(content=PROMPT_COMPONENT_EXTRACTION_SYSTEM)
    human_msg = HumanMessage(
        content=USER_COMPONENT_EXTRACTION.format(
            generated_description=state["generated_description"],
        )
    )
    messages: list = [system_msg, human_msg]
    for _ in range(15):
        ai: AIMessage = llm.invoke(messages)
        messages.append(ai)
        calls = getattr(ai, "tool_calls", None) or []
        if not calls:
            break
        for tc in calls:
            name = tc.get("name")
            args = tc.get("args") or {}
            tid = tc.get("id") or ""
            if name == "register_component":
                cn = args.get("canonical_name", "")
                result = register_component.invoke({"canonical_name": cn})
                messages.append(
                    ToolMessage(content=str(result), tool_call_id=tid)
                )
        messages.append(
            HumanMessage(
                content=USER_COMPONENT_REGISTRY_SNAPSHOT.format(
                    registry_json=_component_registry_json_for_prompt(),
                )
            )
        )
    else:
        print(
            "[component_extraction] stopped after max tool rounds (15).",
            file=sys.stderr,
        )
    return {}


def node_component_graph_json(state: InventionState) -> dict[str, dict]:
    """Draft graph: layout LLM + registry merge; refined by `verify_component_graph`."""
    if not _COMPONENT_ID_MAP:
        return {"component_graph": {"nodes": [], "edges": []}}

    llm = _require_llm().with_structured_output(GraphLayoutLLMSchema)
    registered = dict(sorted(_COMPONENT_ID_MAP.items()))
    allowed_ids = sorted(_COMPONENT_ID_MAP.values())

    system_msg = SystemMessage(
        content=PROMPT_GRAPH_LAYOUT_SYSTEM.format(
            allowed_ids_json=json.dumps(allowed_ids),
            layout_spec=LLM_LAYOUT_JSON_SPEC,
            registered_json=json.dumps(registered),
        )
    )
    human_msg = HumanMessage(
        content=USER_GRAPH_LAYOUT.format(
            invention_name=state["invention_name"],
            description=state["description"],
            key_innovation=state["key_innovation"],
            generated_description=state["generated_description"],
        )
    )
    out: GraphLayoutLLMSchema = llm.invoke([system_msg, human_msg])
    graph = _build_component_graph_from_registry(out)
    return {"component_graph": graph}


def node_verify_component_graph(state: InventionState) -> dict[str, dict]:
    """Align draft graph with invention overview (edges-focused); output is the final `component_graph`."""
    draft = state["component_graph"]
    if not isinstance(draft, dict):
        return {"component_graph": {"nodes": [], "edges": []}}
    if not draft.get("nodes"):
        return {"component_graph": draft}

    llm = _require_llm().with_structured_output(VerifiedComponentGraphSchema)
    system_msg = SystemMessage(content=PROMPT_GRAPH_VERIFY_SYSTEM)
    human_msg = HumanMessage(
        content=USER_GRAPH_VERIFY.format(
            invention_name=state["invention_name"],
            description=state["description"],
            key_innovation=state["key_innovation"],
            generated_description=state["generated_description"],
            draft_graph_json=json.dumps(draft, indent=2),
        )
    )
    out: VerifiedComponentGraphSchema = llm.invoke([system_msg, human_msg])
    final_graph = _reconcile_verified_graph(draft, out)
    return {"component_graph": final_graph}


def node_drawio_block(state: InventionState) -> dict[str, str]:
    """Block diagram: draw.io XML with deterministic layered layout (no diagram LLM)."""
    graph = state["component_graph"]
    if not isinstance(graph, dict) or not graph.get("nodes"):
        return {"drawio_xml": _MINIMAL_MXGRAPH}
    return {"drawio_xml": _verified_graph_to_drawio_block_xml(graph)}


def node_brief_description_drawings(state: InventionState) -> dict[str, str]:
    """LLM: Brief Description of the Drawings from verified component graph JSON."""
    graph = state["component_graph"]
    if not isinstance(graph, dict) or not graph.get("nodes"):
        return {
            "brief_description_drawings": (
                "Brief Description of the Drawings\n\n"
                "No component diagram was generated; there are no figures to describe."
            )
        }

    llm = _require_llm()
    system_msg = SystemMessage(content=PROMPT_BRIEF_DESCRIPTION_DRAWINGS_SYSTEM)
    human_msg = HumanMessage(
        content=USER_BRIEF_DESCRIPTION_DRAWINGS.format(
            invention_name=state["invention_name"],
            graph_json=json.dumps(graph, indent=2),
        )
    )
    out = llm.invoke([system_msg, human_msg])
    text = out.content if isinstance(out.content, str) else str(out.content)
    return {"brief_description_drawings": text.strip()}


def build_graph():
    """Pipeline through description, components, graph, verify, draw.io export, then brief description of drawings."""
    g = StateGraph(InventionState)
    g.add_node("description_generation", node_description_generation)
    g.add_node("component_extraction", node_component_extraction)
    g.add_node("component_graph_json", node_component_graph_json)
    g.add_node("verify_component_graph", node_verify_component_graph)
    g.add_node("drawio_block", node_drawio_block)
    g.add_node("brief_description_drawings", node_brief_description_drawings)

    g.add_edge(START, "description_generation")
    g.add_edge("description_generation", "component_extraction")
    g.add_edge("component_extraction", "component_graph_json")
    g.add_edge("component_graph_json", "verify_component_graph")
    g.add_edge("verify_component_graph", "drawio_block")
    g.add_edge("drawio_block", "brief_description_drawings")
    g.add_edge("brief_description_drawings", END)

    return g.compile()


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract invention components via LangGraph + LLM tools")
    parser.add_argument("json_path", help="Path to JSON with invention_name, description, key_innovation")
    parser.add_argument(
        "--provider",
        choices=("openai", "claude"),
        default="openai",
        help="LLM backend: openai (OPENAI_API_KEY; optional OPENAI_MODEL) or "
        "claude (ANTHROPIC_API_KEY or CLAUDE_API_KEY; optional CLAUDE_MODEL)",
    )
    args = parser.parse_args()

    set_llm_provider(args.provider)

    data = load_invention(args.json_path)
    final = invoke_patent_drawing_pipeline(data)

    print("\n--- Generated description ---\n")
    print(final["generated_description"])
    print("\n--- Canonical components (name -> id) ---")
    for name, cid in sorted(_COMPONENT_ID_MAP.items()):
        print(f"  - {name!r} -> {cid}")
    print(f"\nTotal distinct components: {len(_COMPONENT_ID_MAP)}")
    print("\n--- Component graph (JSON, verified) ---\n")
    print(json.dumps(final["component_graph"], indent=2))
    print("\n--- Brief Description of the Drawings ---\n")
    print(final["brief_description_drawings"])
    print("\n--- draw.io (diagrams.net) ---\n")
    url = diagrams_net_create_url(final["drawio_xml"])
    print(url)


if __name__ == "__main__":
    main()
