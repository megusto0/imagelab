"""Точка входа FastAPI-приложения."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .http import routes_query, routes_upload
from .http.sse import SSEManager
from .noise import engine as noise_engine
from .pipelines.metrics import MetricAggregator


def create_app() -> FastAPI:
    app = FastAPI(
        title="Лаборатории по передаче изображений",
        description="HTTP-конвейер: сжатие → шифрование → FEC.",
        version="0.1.0",
        default_response_class=ORJSONResponse,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.metrics = MetricAggregator(settings.metrics_window_seconds)
    app.state.noise = noise_engine
    app.state.sse = SSEManager(settings.sse_queue_size)

    app.include_router(routes_upload.router, prefix="/api")
    app.include_router(routes_query.router, prefix="/api")

    app.mount(
        "/sender",
        StaticFiles(directory=settings.static_sender_path, html=True),
        name="sender",
    )
    app.mount(
        "/dashboard",
        StaticFiles(directory=settings.static_dashboard_path, html=True),
        name="dashboard",
    )

    @app.get("/")
    async def root():
        return {"сообщение": "Добро пожаловать в лабораторный стенд! Откройте /sender или /dashboard."}

    return app


app = create_app()
