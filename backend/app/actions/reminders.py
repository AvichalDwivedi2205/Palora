from __future__ import annotations

from typing import Any

from app.actions.base import ActionAdapter


class RemindersAdapter(ActionAdapter):
    name = "reminders.create"
    risk_class = 2

    async def validate(self, args: dict[str, Any]) -> None:
        if not args.get("title"):
            raise ValueError("reminder requires title")

    async def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "adapter": self.name,
            "status": "created",
            "title": args["title"],
            "due_at": args.get("due_at"),
            "notes": args.get("notes"),
            "dry_run": True,
        }
