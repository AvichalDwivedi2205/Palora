from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_services, require_token
from app.orchestrator.schemas import GraphResponse, InspectorPayload
from app.services import AppServices


router = APIRouter(prefix="/v1", tags=["memory"], dependencies=[Depends(require_token)])


class GraphExpandRequest(BaseModel):
    node_ids: list[str] = Field(default_factory=list)
    depth: int = 1
    include_kinds: list[str] = Field(default_factory=list)
    mode: str = "cluster"


class GraphPathRequest(BaseModel):
    from_id: str
    to_id: str
    path_mode: str = "strongest"


@router.get("/memory/search")
def search_memory(query: str, limit: int = 8, services: AppServices = Depends(get_services)):
    results = services.memory.search_evidence(query, limit=limit)
    return [
        {
            "id": result.id,
            "score": round(result.score, 3),
            "text": result.text,
            "title": result.title,
            "source_id": result.source_id,
            "kind": result.kind,
        }
        for result in results
    ]


@router.get("/graph/root", response_model=GraphResponse)
def graph_root(
    mode: str = "macro",
    session_id: str = "sess_demo",
    focus_entity_id: str | None = None,
    limit: int = 18,
    services: AppServices = Depends(get_services),
) -> GraphResponse:
    return services.memory.graph_root(mode, session_id, focus_entity_id, limit)


@router.get("/graph/node/{node_id}", response_model=InspectorPayload)
def graph_node(node_id: str, services: AppServices = Depends(get_services)) -> InspectorPayload:
    try:
        return services.memory.graph_node(node_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown node") from exc


@router.post("/graph/expand", response_model=GraphResponse)
def graph_expand(request: GraphExpandRequest, services: AppServices = Depends(get_services)) -> GraphResponse:
    return services.memory.graph_expand(request.node_ids, request.depth, request.include_kinds, request.mode)


@router.post("/graph/path")
def graph_path(request: GraphPathRequest, services: AppServices = Depends(get_services)) -> dict[str, Any]:
    return services.memory.graph_path(request.from_id, request.to_id)


@router.get("/graph/timeline-overlay")
def graph_timeline_overlay(services: AppServices = Depends(get_services)):
    return services.memory.timeline_overlay()


@router.get("/graph/open-loops")
def graph_open_loops(services: AppServices = Depends(get_services)):
    return services.memory.open_loops()
