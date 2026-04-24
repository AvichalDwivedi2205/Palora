from __future__ import annotations

from dataclasses import dataclass


RISK_BY_TOOL = {
    "mail.create_draft": 1,
    "calendar.create_event": 2,
    "reminders.create": 2,
    "browser.read": 0,
    "browser.act": 3,
    "shell.exec": 3,
}


@dataclass(slots=True)
class PolicyDecision:
    status: str
    risk_class: int
    requires_approval: bool
    block_reason: str | None = None


class PolicyEngine:
    def decide(self, tool_name: str | None) -> PolicyDecision:
        if not tool_name:
            return PolicyDecision(status="answer-only", risk_class=0, requires_approval=False)

        risk_class = RISK_BY_TOOL.get(tool_name, 3)
        if tool_name in {"shell.exec", "browser.act"}:
            return PolicyDecision(
                status="blocked",
                risk_class=risk_class,
                requires_approval=True,
                block_reason="Tool disabled in MVP allowlist.",
            )

        requires_approval = risk_class >= 2
        status = "pending-approval" if requires_approval else "ready"
        return PolicyDecision(status=status, risk_class=risk_class, requires_approval=requires_approval)
