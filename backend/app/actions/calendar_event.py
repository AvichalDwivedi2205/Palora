from __future__ import annotations

from typing import Any

from app.actions.base import ActionAdapter


class CalendarEventAdapter(ActionAdapter):
    name = "calendar.create_event"
    risk_class = 2

    async def validate(self, args: dict[str, Any]) -> None:
        if not args.get("title") or not args.get("starts_at"):
            raise ValueError("calendar event requires title and starts_at")

    async def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "adapter": self.name,
            "status": "created",
            "title": args["title"],
            "starts_at": args["starts_at"],
            "ends_at": args.get("ends_at"),
            "calendar": args.get("calendar", "Default"),
            "dry_run": True,
        }
