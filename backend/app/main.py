from __future__ import annotations

import json
import os
import secrets
import socket

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.api.routes_actions import router as actions_router
from app.api.routes_chat import router as chat_router
from app.api.routes_ingest import router as ingest_router
from app.api.routes_memory import router as memory_router
from app.services import AppServices
from app.settings import load_settings


def create_app() -> FastAPI:
    settings = load_settings()
    services = AppServices(settings)
    app = FastAPI(title="Palora Backend", version="0.1.0")
    app.state.settings = settings
    app.state.services = services

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(chat_router)
    app.include_router(actions_router)
    app.include_router(memory_router)
    app.include_router(ingest_router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


def _pick_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


if __name__ == "__main__":
    os.environ.setdefault("PALORA_PORT", str(_pick_port()))
    os.environ.setdefault("PALORA_TOKEN", secrets.token_urlsafe(24))
    bootstrap = {"port": int(os.environ["PALORA_PORT"]), "token": os.environ["PALORA_TOKEN"]}
    print("PALORA_BOOTSTRAP " + json.dumps(bootstrap), flush=True)
    uvicorn.run("app.main:create_app", factory=True, host="127.0.0.1", port=bootstrap["port"], reload=False)
