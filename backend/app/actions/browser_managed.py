from __future__ import annotations

from typing import Any

from app.actions.base import ActionAdapter


class BrowserManagedAdapter(ActionAdapter):
    name = "browser.read"
    risk_class = 0

    async def validate(self, args: dict[str, Any]) -> None:
        if not args.get("url"):
            raise ValueError("browser.read requires url")

    async def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "adapter": self.name,
            "status": "captured",
            "url": args["url"],
            "summary": "Managed browser surface not wired to Playwright yet. Dry-run response only.",
            "dry_run": True,
        }
