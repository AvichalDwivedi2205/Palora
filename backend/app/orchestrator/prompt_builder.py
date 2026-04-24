from __future__ import annotations

import json
from typing import Any


def build_intent_prompt(message: str) -> str:
    return json.dumps({"message": message}, ensure_ascii=True)


def build_reasoner_prompt(message: str, plan: dict[str, Any], bundle: dict[str, Any]) -> str:
    return json.dumps(
        {
            "message": message,
            "plan": plan,
            "bundle": bundle,
        },
        ensure_ascii=True,
    )


def build_critic_prompt(reasoner_output: dict[str, Any], bundle: dict[str, Any]) -> str:
    return json.dumps(
        {
            "reasoner_output": reasoner_output,
            "bundle": bundle,
        },
        ensure_ascii=True,
    )
