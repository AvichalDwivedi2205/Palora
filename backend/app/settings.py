from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    app_name: str = "Palora"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default_factory=lambda: int(os.environ.get("PALORA_PORT", "8787")))
    api_token: str = Field(default_factory=lambda: os.environ.get("PALORA_TOKEN", "palora-dev-token"))
    repo_root: Path = Field(
        default_factory=lambda: Path(os.environ.get("PALORA_REPO_ROOT", Path(__file__).resolve().parents[2]))
    )
    data_dir: Path = Field(
        default_factory=lambda: Path(os.environ.get("PALORA_DATA_DIR", Path.home() / ".palora"))
    )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def blob_dir(self) -> Path:
        return self.data_dir / "blobs"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.blob_dir / "sources").mkdir(parents=True, exist_ok=True)
        (self.blob_dir / "attachments").mkdir(parents=True, exist_ok=True)
        (self.blob_dir / "screenshots").mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
