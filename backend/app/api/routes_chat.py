from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_services, require_token
from app.orchestrator.engine import OrchestratorEngine
from app.orchestrator.schemas import ChatTurnRequest, ChatTurnResponse, TurnEvent
from app.services import AppServices


router = APIRouter(prefix="/v1", tags=["chat"], dependencies=[Depends(require_token)])


def _to_sse(event: TurnEvent) -> bytes:
    payload = json.dumps(event.data, ensure_ascii=True)
    return f"event: {event.event}\ndata: {payload}\n\n".encode("utf-8")


@router.get("/sessions/{session_id}/snapshot")
def get_snapshot(session_id: str, services: AppServices = Depends(get_services)):
    return services.memory.snapshot(session_id)


@router.post("/chat/turn", response_model=ChatTurnResponse)
async def post_chat_turn(turn: ChatTurnRequest, services: AppServices = Depends(get_services)) -> ChatTurnResponse:
    engine = OrchestratorEngine(services)
    return await engine.run_turn(turn)


@router.post("/chat/turn/stream")
async def stream_chat_turn(turn: ChatTurnRequest, services: AppServices = Depends(get_services)) -> StreamingResponse:
    engine = OrchestratorEngine(services)

    async def event_stream():
        async for event in engine.stream_turn(turn):
            yield _to_sse(event)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
