"""Общие Pydantic-модели."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, validator


class HandshakeRequest(BaseModel):
    client_public_key: str = Field(..., description="Публичный ключ X25519 в Base64")


class HandshakeResponse(BaseModel):
    session_id: str
    server_public_key: str
    salt: str
    nonce_base: str
    algorithm: str


class CompressionSettings(BaseModel):
    enabled: bool = False
    level: int = 6
    algorithm: str = "deflate"

    @validator("level")
    def clamp_level(cls, v: int) -> int:
        return max(0, min(v, 9))


class EncryptionSettings(BaseModel):
    enabled: bool = False
    session_id: Optional[str] = None


class FECSettings(BaseModel):
    mode: str = Field("off", pattern="^(off|hamming|rs)$")
    n: int = 120
    k: int = 100

    @validator("n", "k")
    def positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("n и k должны быть положительными")
        return v


class PipelineSettings(BaseModel):
    compression: CompressionSettings = Field(default_factory=CompressionSettings)
    encryption: EncryptionSettings = Field(default_factory=EncryptionSettings)
    fec: FECSettings = Field(default_factory=FECSettings)


class UploadInitRequest(BaseModel):
    filename: str
    mime_type: str
    pipeline: PipelineSettings
    session_id: Optional[str] = None


class UploadInitResponse(BaseModel):
    file_id: str
    chunk_size: int
    fec: Dict[str, int | str]
    pipeline: PipelineSettings


class ChunkRequest(BaseModel):
    file_id: str
    session_id: Optional[str]
    sequence: int
    total_sequences: int
    payload: bytes
    is_parity: bool = False
    fec_index: Optional[int] = None
    meta: Dict[str, int | float | str] = Field(default_factory=dict)


class FinishUploadRequest(BaseModel):
    file_id: str


class ChannelNoiseRequest(BaseModel):
    loss: float = 0.0
    ber: float = 0.0
    duplicate: float = 0.0
    reorder: float = 0.0


class PingResponse(BaseModel):
    rtt_ms: float
    server_time: datetime


class ImageSummary(BaseModel):
    file_id: str
    filename: str
    mime_type: str
    uploaded_at: datetime
    stages: Dict[str, Dict[str, float | str | int | None]]
    size_bytes: int


class StatusResponse(BaseModel):
    file_id: str
    missing_sequences: List[int] = []
    ready: bool = False
    stages: Dict[str, Dict[str, float | str | int | None]] = {}
