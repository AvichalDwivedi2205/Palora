from __future__ import annotations

from typing import Any

from app.actions.base import ActionAdapter


class MailDraftAdapter(ActionAdapter):
    name = "mail.create_draft"
    risk_class = 1

    async def validate(self, args: dict[str, Any]) -> None:
        if not args.get("subject") or not args.get("body"):
            raise ValueError("mail draft requires subject and body")

    async def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "adapter": self.name,
            "status": "drafted",
            "subject": args["subject"],
            "body": args["body"],
            "to": args.get("to", []),
            "dry_run": True,
        }
