from __future__ import annotations

from app.orchestrator.schemas import IntentKind


def ensure_intent(value: str) -> IntentKind:
    allowed: set[str] = {
        "chat_answer",
        "memory_lookup",
        "draft_text",
        "propose_action",
        "execute_approved_action",
        "ingest_request",
        "clarification_needed",
    }
    if value not in allowed:
        return "chat_answer"
    return value  # type: ignore[return-value]
