"""Маршруты отображения и мониторинга."""

from __future__ import annotations

import datetime as dt
from typing import AsyncGenerator, Dict, List

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

from ..models import PingResponse
from ..storage import storage

router = APIRouter()


def _get_metrics(request: Request):
    return request.app.state.metrics


def _get_sse(request: Request):
    return request.app.state.sse


def _get_noise_engine(request: Request):
    return request.app.state.noise


@router.get("/images")
async def list_images() -> List[Dict]:
    """Получить список загруженных изображений."""

    return [summary.model_dump() for summary in storage.list_images()]


@router.get("/image/{file_id}", response_class=HTMLResponse)
async def view_image(file_id: str):
    """Простая HTML-страница предпросмотра."""

    path = storage.get_final_path(file_id)
    if not path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден.")
    return f"""<!doctype html>
<html lang="ru">
  <head>
    <meta charset="utf-8" />
    <title>Предпросмотр {file_id}</title>
    <style>
      body {{ font-family: sans-serif; padding: 2rem; background: #111; color: #eee; }}
      img {{ max-width: 90vw; max-height: 80vh; border: 4px solid #444; border-radius: 8px; }}
      a {{ color: #4dc0b5; }}
    </style>
  </head>
  <body>
    <h1>Файл {file_id}</h1>
    <p><a href="/api/image/{file_id}/raw" download>Скачать оригинал</a></p>
    <img src="/api/image/{file_id}/raw" alt="Превью" />
  </body>
</html>"""


@router.get("/image/{file_id}/raw")
async def download_image(file_id: str):
    """Выдать бинарное содержимое изображения."""

    path = storage.get_final_path(file_id)
    if not path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден.")
    return FileResponse(path)


@router.get("/metrics")
async def metrics_snapshot(request: Request):
    """Снимок текущих метрик."""

    return JSONResponse(_get_metrics(request).snapshot())


@router.get("/config/channel")
async def get_channel_config(request: Request):
    """Текущие параметры эмуляции канала."""

    return JSONResponse(_get_noise_engine(request).current_config())


@router.get("/events")
async def sse_events(request: Request):
    """SSE-поток для дашборда."""

    async def event_stream() -> AsyncGenerator[str, None]:
        async for msg in _get_sse(request).subscribe():
            yield msg

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/ping", response_model=PingResponse)
async def ping(request: Request) -> PingResponse:
    """Простой пинг-сервер для измерения RTT на клиенте."""

    metrics = _get_metrics(request)
    metrics.record_rtt(0.0)
    return PingResponse(rtt_ms=0.0, server_time=dt.datetime.now(dt.timezone.utc))
