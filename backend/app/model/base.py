from __future__ import annotations

from typing import Protocol


class ModelProvider(Protocol):
    async def generate_json(self, prompt: str, schema: dict, mode: str) -> dict: ...

    async def generate_text(self, prompt: str, mode: str) -> str: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
