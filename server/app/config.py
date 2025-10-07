"""Конфигурация приложения через pydantic settings."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Рабочие параметры сервера."""

    data_dir: Path = Path(__file__).resolve().parent.parent / "data"
    static_sender_path: Path = Path(__file__).resolve().parent / "static_sender"
    static_dashboard_path: Path = Path(__file__).resolve().parent / "static_dashboard"
    metrics_window_seconds: int = 60
    sse_queue_size: int = 100
    max_chunk_size: int = 256 * 1024
    default_rs_n: int = 120
    default_rs_k: int = 100

    class Config:
        env_prefix = "IMAGE_LAB_"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
