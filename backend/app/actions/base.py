from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ActionAdapter(ABC):
    name: str
    risk_class: int

    @abstractmethod
    async def validate(self, args: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    async def rollback(self, result: dict[str, Any]) -> dict[str, Any] | None:
        return None
