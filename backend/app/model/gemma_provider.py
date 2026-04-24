from __future__ import annotations

import json
from textwrap import shorten

from app.model.embeddings import lexical_similarity


class DemoGemmaProvider:
    async def generate_json(self, prompt: str, schema: dict, mode: str) -> dict:
        payload = json.loads(prompt)
        if mode == "intent":
            return self._intent(payload["message"])
        if mode == "planner":
            return self._reason(payload)
        if mode == "critic":
            return self._critic(payload)
        return {}

    async def generate_text(self, prompt: str, mode: str) -> str:
        return prompt

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text))] for text in texts]

    def _intent(self, message: str) -> dict:
        lowered = message.lower()
        if any(word in lowered for word in ["ingest", "import", "index"]):
            intent = "ingest_request"
        elif any(word in lowered for word in ["draft", "rewrite", "tighten", "follow-up", "email"]):
            intent = "draft_text"
        elif any(word in lowered for word in ["remind", "schedule", "create event", "add reminder"]):
            intent = "propose_action"
        elif any(word in lowered for word in ["waiting", "what am i waiting on", "summarize", "recall", "context"]):
            intent = "memory_lookup"
        else:
            intent = "chat_answer"
        return {"intent": intent}

    def _reason(self, payload: dict) -> dict:
        message = payload["message"]
        lowered = message.lower()
        bundle = payload["bundle"]
        evidence = bundle.get("evidence_snippets", [])
        citations = bundle.get("citations", [])
        focus_entities = [entity["name"] for entity in bundle.get("entities", [])]
        focus_label = focus_entities[0] if focus_entities else "current context"

        if "waiting" in lowered:
            open_loops = bundle.get("kg_facts", [])[:3]
            bullets = []
            for item in open_loops:
                label = item.get("predicate_label") or item.get("predicate")
                target = item.get("target_label") or item.get("object") or item.get("target")
                bullets.append(f"- {label}: {target}")
            if not bullets:
                bullets.append("- No hard blockers found in current memory bundle.")
            message_text = (
                f"Biggest open loops around {focus_label} right now:\n"
                + "\n".join(bullets)
                + "\n\nBest next move: either send follow-up draft or set reminder before context goes stale."
            )
            return {
                "assistant_message": message_text,
                "artifact": None,
                "action_proposal": None,
                "citations": [citation["id"] for citation in citations[:3]],
            }

        if any(word in lowered for word in ["draft", "rewrite", "tighten", "follow-up", "email"]):
            quote = evidence[0]["text"] if evidence else "Thanks again for the update. I am still very interested."
            opener = "Hope your week is going smoothly."
            body = (
                f"{opener}\n\n"
                f"I wanted to follow up on {focus_label}. I'm still very interested and would love any update on timing or next steps.\n\n"
                "If helpful, I can also send over anything else you need from me.\n\n"
                "Best,\nAvi"
            )
            summary = shorten(quote.replace("\n", " "), width=120, placeholder="...")
            assistant = (
                f"Tightened opener. Kept tone warm-formal. Moved timing ask into sentence two.\n\n"
                f"Anchor from memory: {summary}"
            )
            action = None
            if any(word in lowered for word in ["remind", "later", "tomorrow"]):
                action = {
                    "tool_name": "reminders.create",
                    "arguments": {
                        "title": f"Follow up on {focus_label}",
                        "due_at": "Tomorrow 10:00 AM",
                        "notes": "Resurface draft if no reply lands first.",
                    },
                    "reason": "Keep recruiter loop warm without relying on memory.",
                    "expected_effect": "Reminder appears in act lane and timeline.",
                    "citations": [citation["id"] for citation in citations[:2]],
                }
            return {
                "assistant_message": assistant,
                "artifact": {
                    "type": "email_draft",
                    "title": f"Draft for {focus_label}",
                    "subject": f"Following up on {focus_label}",
                    "body": body,
                    "content": {"relationship": focus_label},
                },
                "action_proposal": action,
                "citations": [citation["id"] for citation in citations[:4]],
            }

        if "summarize" in lowered and "spec" in lowered:
            ranked = sorted(
                evidence,
                key=lambda item: lexical_similarity(message, item["text"]),
                reverse=True,
            )[:4]
            bullets = [
                f"- {shorten(item['text'].replace(chr(10), ' '), width=150, placeholder='...')}" for item in ranked
            ]
            assistant = "Fast synthesis from indexed spec:\n" + "\n".join(bullets)
            return {
                "assistant_message": assistant,
                "artifact": None,
                "action_proposal": None,
                "citations": [citation["id"] for citation in citations[:4]],
            }

        assistant = (
            f"I pulled context around {focus_label} and can keep going from here. "
            "Best path now is either draft, summarize, or stage an approval-safe action."
        )
        return {
            "assistant_message": assistant,
            "artifact": None,
            "action_proposal": None,
            "citations": [citation["id"] for citation in citations[:2]],
        }

    def _critic(self, payload: dict) -> dict:
        reasoner_output = payload["reasoner_output"]
        citations = reasoner_output.get("citations", [])
        if not citations and payload.get("bundle", {}).get("citations"):
            citations = [payload["bundle"]["citations"][0]["id"]]
        return {
            "assistant_message": reasoner_output["assistant_message"],
            "artifact": reasoner_output.get("artifact"),
            "action_proposal": reasoner_output.get("action_proposal"),
            "citations": citations,
        }
