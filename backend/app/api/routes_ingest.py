from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_services, require_token
from app.orchestrator.schemas import IngestJobResponse, IngestSourceRequest
from app.services import AppServices


router = APIRouter(prefix="/v1/ingest", tags=["ingest"], dependencies=[Depends(require_token)])


@router.post("/source", response_model=IngestJobResponse)
def ingest_source(request: IngestSourceRequest, services: AppServices = Depends(get_services)) -> IngestJobResponse:
    response = services.ingest.ingest_source(request)
    services.writer.record_turn(
        trace_id=response.job_id,
        event_type="source_ingested",
        subject_id=response.source_event_id,
        payload={"summary": f"{request.title} indexed with {response.chunks_written} chunks."},
    )
    return response
