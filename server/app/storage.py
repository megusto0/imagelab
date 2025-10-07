"""Хранилище загрузок и управление метаданными."""

from __future__ import annotations

import json
import ntpath
import posixpath
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .config import settings
from .models import ChunkRequest, ImageSummary, PipelineSettings, UploadInitRequest
from .pipelines.chunking import ChunkAssembler, ChunkEnvelope, build_chunk_envelopes
from .pipelines.crypto import HandshakeContext


@dataclass(slots=True)
class UploadRecord:
    file_id: str
    filename: str
    mime_type: str
    pipeline: PipelineSettings
    handshake_session_id: Optional[str]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    assembler: ChunkAssembler = field(init=False)
    stage_metrics: Dict[str, Dict[str, int | float | str | bool | None]] = field(default_factory=dict)
    meta: Dict[str, int | float | str] = field(default_factory=dict)
    final_path: Optional[Path] = None
    original_size: Optional[int] = None

    def __post_init__(self) -> None:
        self.assembler = ChunkAssembler(chunk_id=self.file_id)


class Storage:
    """Метаданные держим в памяти, файлы складываем на диск."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "raw").mkdir(exist_ok=True)
        (self.root / "final").mkdir(exist_ok=True)
        self._handshakes: Dict[str, str] = {}
        self._uploads: Dict[str, UploadRecord] = {}
        self._lock = threading.RLock()

    # -------- Управление рукопожатием --------
    def store_handshake(self, ctx: HandshakeContext) -> None:
        with self._lock:
            self._handshakes[ctx.session_id] = ctx.export()

    def get_handshake(self, session_id: str) -> Optional[HandshakeContext]:
        raw = self._handshakes.get(session_id)
        return HandshakeContext.parse(raw) if raw else None

    # -------- Управление загрузкой --------
    def init_upload(self, request: UploadInitRequest) -> UploadRecord:
        file_id = uuid.uuid4().hex
        record = UploadRecord(
            file_id=file_id,
            filename=request.filename,
            mime_type=request.mime_type,
            pipeline=request.pipeline,
            handshake_session_id=request.session_id,
        )
        with self._lock:
            self._uploads[file_id] = record
        return record

    def get_upload(self, file_id: str) -> Optional[UploadRecord]:
        return self._uploads.get(file_id)

    def create_raw_chunks(
        self,
        record: UploadRecord,
        data: bytes,
        chunk_size: int,
    ) -> Iterable[ChunkEnvelope]:
        record.original_size = len(data)
        return build_chunk_envelopes(record.file_id, data, chunk_size)

    def store_chunk(self, record: UploadRecord, envelope: ChunkEnvelope) -> None:
        record.assembler.add(envelope)

    def missing_sequences(self, record: UploadRecord) -> List[int]:
        return record.assembler.missing_sequences()

    def set_stage_metrics(
        self,
        record: UploadRecord,
        stage: str,
        metrics: Dict[str, int | float | str | bool | None],
    ) -> None:
        record.stage_metrics[stage] = metrics

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Удалить управляющие символы и пути, оставив безопасное имя."""

        candidate = ntpath.basename(filename)
        candidate = posixpath.basename(candidate)
        candidate = Path(candidate).name
        if candidate in ("", ".", ".."):
            candidate = "file"
        candidate = re.sub(r"[^A-Za-z0-9._-]", "_", candidate)
        return candidate or "file"

    def complete_upload(
        self,
        record: UploadRecord,
        data: bytes,
        expected_size: Optional[int] = None,
    ) -> Path:
        safe_name = self._sanitize_filename(record.filename)
        final_path = self.root / "final" / f"{record.file_id}_{safe_name}"
        final_path.write_bytes(data)
        record.final_path = final_path
        record.stage_metrics.setdefault("final", {})
        record.stage_metrics["final"]["size_bytes"] = len(data)
        record.stage_metrics["final"]["expected_size_bytes"] = expected_size
        if expected_size is not None:
            record.stage_metrics["final"]["matches_expected_size"] = len(data) == expected_size
        return final_path

    def list_images(self) -> List[ImageSummary]:
        summaries: List[ImageSummary] = []
        for record in self._uploads.values():
            if not record.final_path:
                continue
            summaries.append(
                ImageSummary(
                    file_id=record.file_id,
                    filename=record.filename,
                    mime_type=record.mime_type,
                    uploaded_at=record.created_at,
                    stages=record.stage_metrics,
                    size_bytes=record.stage_metrics.get("final", {}).get("size_bytes", 0),  # type: ignore[arg-type]
                )
            )
        return summaries

    def get_final_path(self, file_id: str) -> Optional[Path]:
        record = self._uploads.get(file_id)
        return record.final_path if record else None

    def export_state(self) -> str:
        payload = {
            "uploads": {
                file_id: {
                    "filename": rec.filename,
                    "mime_type": rec.mime_type,
                    "pipeline": json.loads(rec.pipeline.model_dump_json()),
                    "stage_metrics": rec.stage_metrics,
                    "created_at": rec.created_at.isoformat(),
                    "final_path": str(rec.final_path) if rec.final_path else None,
                    "original_size": rec.original_size,
                }
                for file_id, rec in self._uploads.items()
            }
        }
        return json.dumps(payload, indent=2)


storage = Storage(settings.data_dir)
