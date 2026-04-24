from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


IntentKind = Literal[
    "chat_answer",
    "memory_lookup",
    "draft_text",
    "propose_action",
    "execute_approved_action",
    "ingest_request",
    "clarification_needed",
]


class Attachment(BaseModel):
    name: str
    path: str | None = None
    media_type: str | None = None


class ChatTurnRequest(BaseModel):
    session_id: str
    message: str
    attachments: list[Attachment] = Field(default_factory=list)
    mode: str = "default"


class Citation(BaseModel):
    id: str
    label: str
    kind: str
    source_id: str | None = None


class Artifact(BaseModel):
    type: str
    title: str | None = None
    subject: str | None = None
    body: str | None = None
    content: dict[str, Any] | None = None


class PendingAction(BaseModel):
    id: str
    tool_name: str
    intent: str
    risk_class: int
    status: str
    reason: str
    prepared_hash: str
    prepared_args: dict[str, Any]
    requires_approval: bool
    expires_at: datetime | None = None


class ChatTurnResponse(BaseModel):
    trace_id: str
    status: str
    assistant_message: str
    artifact: Artifact | None = None
    pending_action: PendingAction | None = None
    citations: list[Citation] = Field(default_factory=list)


class GraphNode(BaseModel):
    id: str
    kind: str
    label: str
    summary: str
    status: str = "active"
    confidence: float = 0.8
    cluster_id: str | None = None
    cluster_label: str | None = None
    cluster_kind: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    timestamps: dict[str, str | None] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    kind: str
    source: str
    target: str
    weight: float = 0.6
    status: str = "active"
    evidence_ids: list[str] = Field(default_factory=list)
    last_updated_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphOverlay(BaseModel):
    node_id: str
    overlay_kind: str
    label: str
    severity: str


class GraphResponse(BaseModel):
    graph_id: str
    mode: Literal["macro", "cluster", "local"]
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    clusters: list[dict[str, Any]] = Field(default_factory=list)
    overlays: dict[str, Any] = Field(default_factory=dict)


class InspectorPayload(BaseModel):
    node: GraphNode
    summary: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    related_nodes: list[GraphNode] = Field(default_factory=list)
    related_edges: list[GraphEdge] = Field(default_factory=list)
    actions: list[PendingAction] = Field(default_factory=list)
    drafts: list[dict[str, Any]] = Field(default_factory=list)
    rules: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)


class QueueItem(BaseModel):
    id: str
    kind: str
    time: str
    title: str
    summary: str
    tags: list[str] = Field(default_factory=list)
    prompt: str
    entity_id: str
    context: dict[str, Any] = Field(default_factory=dict)


class TimelineItem(BaseModel):
    time: str
    text: str


class ChatMessage(BaseModel):
    id: str
    role: str
    label: str
    body: str
    created_at: str
    tool: dict[str, Any] | None = None


class DraftItem(BaseModel):
    id: str
    kind: str
    title: str
    summary: str
    body: str
    status: str
    tags: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class SessionSnapshot(BaseModel):
    session_id: str
    active_focus_id: str
    queue: list[QueueItem] = Field(default_factory=list)
    timeline: list[TimelineItem] = Field(default_factory=list)
    chat_messages: list[ChatMessage] = Field(default_factory=list)
    drafts: list[DraftItem] = Field(default_factory=list)
    actions: list[PendingAction] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
    graph: GraphResponse


class IngestSourceRequest(BaseModel):
    source_type: str
    source_ref: str
    title: str
    text: str
    timestamp: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestJobResponse(BaseModel):
    job_id: str
    status: str
    source_event_id: str
    chunks_written: int
    entities_written: int
    facts_written: int


class ApproveActionRequest(BaseModel):
    prepared_hash: str


class ActionExecutionResponse(BaseModel):
    status: str
    result: dict[str, Any]


class TurnEvent(BaseModel):
    event: str
    data: dict[str, Any]


class RetrievalPlan(BaseModel):
    intent: IntentKind
    target_entities: list[str] = Field(default_factory=list)
    needs: list[str] = Field(default_factory=list)
    deep_search: bool = False
    query: str


class MemoryBundle(BaseModel):
    bundle_id: str
    intent: str
    entities: list[dict[str, Any]] = Field(default_factory=list)
    profile_memories: list[dict[str, Any]] = Field(default_factory=list)
    procedural_rules: list[dict[str, Any]] = Field(default_factory=list)
    style_examples: list[dict[str, Any]] = Field(default_factory=list)
    kg_facts: list[dict[str, Any]] = Field(default_factory=list)
    episodic_memories: list[dict[str, Any]] = Field(default_factory=list)
    evidence_snippets: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    graph_nodes: list[GraphNode] = Field(default_factory=list)
    graph_edges: list[GraphEdge] = Field(default_factory=list)


class ActionProposal(BaseModel):
    tool_name: str
    arguments: dict[str, Any]
    reason: str
    expected_effect: str
    citations: list[str] = Field(default_factory=list)


class ReasonerOutput(BaseModel):
    assistant_message: str
    artifact: Artifact | None = None
    action_proposal: ActionProposal | None = None
    citations: list[str] = Field(default_factory=list)
