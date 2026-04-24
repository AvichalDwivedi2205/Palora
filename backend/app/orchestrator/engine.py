from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any, AsyncIterator

from app.model.gemma_provider import DemoGemmaProvider
from app.orchestrator.intents import ensure_intent
from app.orchestrator.prompt_builder import build_critic_prompt, build_intent_prompt, build_reasoner_prompt
from app.orchestrator.schemas import Artifact, ChatTurnRequest, ChatTurnResponse, PendingAction, TurnEvent
from app.services import AppServices, isoformat, utcnow


class OrchestratorEngine:
    def __init__(self, services: AppServices) -> None:
        self.services = services
        self.provider = DemoGemmaProvider()

    async def run_turn(self, turn: ChatTurnRequest) -> ChatTurnResponse:
        final_payload: ChatTurnResponse | None = None
        async for event in self.stream_turn(turn):
            if event.event == "final":
                final_payload = ChatTurnResponse.model_validate(event.data)
        if final_payload is None:
            raise RuntimeError("missing final payload")
        return final_payload

    async def stream_turn(self, turn: ChatTurnRequest) -> AsyncIterator[TurnEvent]:
        trace_id = self.services.db.make_id("tr")
        self.services.db.create_message(turn.session_id, "user", turn.message, None, trace_id=trace_id)
        yield TurnEvent(event="status", data={"step": "intent", "label": "Classifying request"})
        intent_payload = await self.provider.generate_json(build_intent_prompt(turn.message), {}, "intent")
        intent = ensure_intent(intent_payload["intent"])

        plan = self.services.memory.build_retrieval_plan(turn.message, intent)
        if plan.target_entities:
            self.services.db.execute(
                "UPDATE sessions SET active_entity_id = ?, updated_at = ? WHERE id = ?",
                (plan.target_entities[0], isoformat(utcnow()), turn.session_id),
            )
        yield TurnEvent(
            event="retrieval_plan",
            data={"intent": plan.intent, "target_entities": plan.target_entities, "needs": plan.needs},
        )

        yield TurnEvent(event="status", data={"step": "retrieve", "label": "Retrieving memory bundle"})
        bundle = self.services.memory.build_bundle(plan)
        emitted_nodes: set[str] = set()
        for node in bundle["graph_nodes"][:10]:
            if node["id"] in emitted_nodes:
                continue
            emitted_nodes.add(node["id"])
            yield TurnEvent(event="graph_delta", data={"kind": "node", "node": node})
            await asyncio.sleep(0.035)
        for edge in bundle["graph_edges"][:12]:
            yield TurnEvent(event="graph_delta", data={"kind": "edge", "edge": edge})
            await asyncio.sleep(0.02)

        yield TurnEvent(event="status", data={"step": "reason", "label": "Drafting response"})
        reasoner_output = await self.provider.generate_json(
            build_reasoner_prompt(turn.message, plan.model_dump(), bundle),
            {},
            "planner",
        )
        critic_output = await self.provider.generate_json(
            build_critic_prompt(reasoner_output, bundle),
            {},
            "critic",
        )

        artifact: Artifact | None = None
        if critic_output.get("artifact"):
            artifact = Artifact.model_validate(critic_output["artifact"])

        pending_action: PendingAction | None = None
        action_proposal = critic_output.get("action_proposal")
        if action_proposal:
            decision = self.services.policy.decide(action_proposal["tool_name"])
            if decision.status == "blocked":
                critic_output["assistant_message"] += f"\n\nBlocked by policy: {decision.block_reason}"
            else:
                plan_row = self.services.db.create_action_plan(
                    session_id=turn.session_id,
                    tool_name=action_proposal["tool_name"],
                    intent=intent,
                    risk_class=decision.risk_class,
                    prepared_args=action_proposal["arguments"],
                    memory_refs=action_proposal.get("citations", []),
                    reason=action_proposal["reason"],
                    status="pending-approval" if decision.requires_approval else "ready",
                    expires_at=utcnow() + timedelta(minutes=30),
                )
                pending_action = self.services.memory._plan_to_pending_action(plan_row)
                yield TurnEvent(
                    event="pending_action",
                    data=pending_action.model_dump(mode="json"),
                )

        if artifact:
            draft_id = self.services.db.create_draft(
                turn.session_id,
                "ready now",
                artifact.subject or artifact.title or "Draft",
                "Draft created from current memory bundle.",
                artifact.body or "",
                "needs approval" if pending_action and pending_action.requires_approval else "draft",
                critic_output.get("citations", []),
            )
            yield TurnEvent(
                event="draft_created",
                data={"draft_id": draft_id, "title": artifact.subject or artifact.title or "Draft"},
            )

        assistant_message = critic_output["assistant_message"]
        self.services.db.create_message(
            turn.session_id,
            "assistant",
            assistant_message,
            {
                "artifact": artifact.model_dump() if artifact else None,
                "pending_action": pending_action.model_dump(mode="json") if pending_action else None,
                "citations": critic_output.get("citations", []),
            },
            trace_id=trace_id,
        )

        for token in assistant_message.split():
            yield TurnEvent(event="token", data={"text": token + " "})
            await asyncio.sleep(0.01)

        self.services.writer.record_turn(
            trace_id=trace_id,
            event_type="turn_completed",
            subject_id=plan.target_entities[0] if plan.target_entities else "ent_user",
            payload={"summary": assistant_message[:180]},
        )

        final = ChatTurnResponse(
            trace_id=trace_id,
            status="ok",
            assistant_message=assistant_message,
            artifact=artifact,
            pending_action=pending_action,
            citations=[
                {
                    "id": citation["id"],
                    "label": citation["label"],
                    "kind": citation["kind"],
                    "source_id": citation.get("source_id"),
                }
                for citation in bundle["citations"]
                if citation["id"] in critic_output.get("citations", [])
            ],
        )
        yield TurnEvent(event="final", data=json.loads(final.model_dump_json()))
