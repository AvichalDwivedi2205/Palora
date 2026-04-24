from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_services, require_token
from app.orchestrator.schemas import ActionExecutionResponse, ApproveActionRequest, PendingAction
from app.services import AppServices


router = APIRouter(prefix="/v1/actions", tags=["actions"], dependencies=[Depends(require_token)])


@router.get("/pending", response_model=list[PendingAction])
def list_pending_actions(session_id: str = "sess_demo", services: AppServices = Depends(get_services)):
    return services.actions.list_actions(session_id)


@router.post("/{action_id}/approve", response_model=ActionExecutionResponse)
async def approve_action(
    action_id: str,
    request: ApproveActionRequest,
    services: AppServices = Depends(get_services),
) -> ActionExecutionResponse:
    try:
        result = await services.actions.approve(action_id, request.prepared_hash)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown action") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ActionExecutionResponse(status="executed", result=result)


@router.post("/{action_id}/reject")
def reject_action(action_id: str, services: AppServices = Depends(get_services)):
    services.actions.reject(action_id)
    return {"status": "rejected"}
