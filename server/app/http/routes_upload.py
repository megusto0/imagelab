"""Маршруты загрузки и управления каналом."""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Optional, Sequence

from fastapi import APIRouter, HTTPException, Request, status

from ..config import settings
from ..models import (
    ChannelNoiseRequest,
    ChunkRequest,
    FinishUploadRequest,
    HandshakeRequest,
    HandshakeResponse,
    UploadInitRequest,
    UploadInitResponse,
)
from ..noise import NoiseConfig
from ..pipelines import AESGCMCipher, CompressionAlgo, CompressionConfig, ReedSolomonConfig, fec_decode_bytes
from ..pipelines.chunking import ChunkEnvelope
from ..pipelines.compression import decompress_bytes
from ..storage import storage

router = APIRouter()


def _get_sse(request: Request):
    return request.app.state.sse


def _get_metrics(request: Request):
    return request.app.state.metrics


def _get_noise_engine(request: Request):
    return request.app.state.noise


async def _publish_stage_metrics(
    request: Request,
    file_id: str,
    stage: str,
    metrics: Dict[str, Any],
) -> None:
    await _get_sse(request).publish(
        "stage_metrics",
        {
            "file_id": file_id,
            "stage": stage,
            "metrics": metrics,
            "ts": time.time(),
        },
    )


async def _publish_progress(
    request: Request,
    file_id: str,
    *,
    sequence: int,
    expected: Optional[int],
    received_data: int,
    received_parity: int,
    received_total: int,
    missing_total: int,
    bytes_sent: int,
    is_parity: bool,
) -> None:
    progress = None
    if expected:
        progress = received_data / expected if expected else None
    await _get_sse(request).publish(
        "upload_progress",
        {
            "file_id": file_id,
            "sequence": sequence,
            "expected": expected,
            "received_data": received_data,
            "received_parity": received_parity,
            "received_total": received_total,
            "missing_total": missing_total,
            "bytes": bytes_sent,
            "is_parity": is_parity,
            "progress": progress,
            "ts": time.time(),
        },
    )


@router.post("/handshake", response_model=HandshakeResponse)
async def create_handshake(payload: HandshakeRequest, request: Request) -> HandshakeResponse:
    """Рукопожатие X25519 → AES-GCM."""

    from ..pipelines.crypto import generate_server_handshake

    context, response = generate_server_handshake(payload.client_public_key)
    storage.store_handshake(context)
    await _get_sse(request).publish(
        "handshake",
        {"session_id": context.session_id, "ts": time.time()},
    )
    return HandshakeResponse(**response)


@router.post("/config/channel")
async def configure_channel(payload: ChannelNoiseRequest, request: Request) -> Dict[str, float]:
    """Настройка параметров помех."""

    engine = _get_noise_engine(request)
    config = engine.configure(
        NoiseConfig(
            loss=payload.loss,
            ber=payload.ber,
            duplicate=payload.duplicate,
            reorder=payload.reorder,
        )
    )
    data = {
        "loss": config.loss,
        "ber": config.ber,
        "duplicate": config.duplicate,
        "reorder": config.reorder,
    }
    await _get_sse(request).publish("noise_config", data)
    return data


@router.post("/upload", response_model=UploadInitResponse)
async def upload_init(payload: UploadInitRequest, request: Request) -> UploadInitResponse:
    """Инициализация новой загрузки."""

    if payload.pipeline.encryption.enabled and not payload.session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не передан идентификатор сессии шифрования.",
        )

    record = storage.init_upload(payload)
    chunk_size = min(settings.max_chunk_size, 256 * 1024)

    fec_info = {
        "mode": payload.pipeline.fec.mode,
        "n": payload.pipeline.fec.n,
        "k": payload.pipeline.fec.k,
    }

    storage.set_stage_metrics(
        record,
        "init",
        {
            "filename": payload.filename,
            "mime_type": payload.mime_type,
            "chunk_size_bytes": chunk_size,
            "compression_enabled": payload.pipeline.compression.enabled,
            "compression_algorithm": payload.pipeline.compression.algorithm,
            "compression_level": payload.pipeline.compression.level,
            "encryption_enabled": payload.pipeline.encryption.enabled,
            "fec_mode": payload.pipeline.fec.mode,
            "fec_n": payload.pipeline.fec.n,
            "fec_k": payload.pipeline.fec.k,
        },
    )
    await _publish_stage_metrics(
        request,
        record.file_id,
        "init",
        record.stage_metrics.get("init", {}),
    )

    await _get_sse(request).publish(
        "upload_init",
        {
            "file_id": record.file_id,
            "filename": payload.filename,
            "mime_type": payload.mime_type,
            "chunk_size_bytes": chunk_size,
            "pipeline": payload.pipeline.model_dump(),
        },
    )

    return UploadInitResponse(
        file_id=record.file_id,
        chunk_size=chunk_size,
        fec=fec_info,
        pipeline=payload.pipeline,
    )


def _envelope_from_request(req: ChunkRequest) -> ChunkEnvelope:
    return ChunkEnvelope(
        chunk_id=req.file_id,
        sequence=req.sequence,
        payload=req.payload,
        is_parity=req.is_parity,
        fec_index=req.fec_index,
        total_chunks=req.total_sequences,
        metadata=req.meta,
    )


def _apply_noise_and_store(
    record,
    envelopes: Sequence[ChunkEnvelope],
    request: Request,
) -> Dict[str, float]:
    engine = _get_noise_engine(request)
    processed: List[ChunkEnvelope] = []
    stats_aggregate: Dict[str, float] = {
        "loss": 0,
        "bit_flips": 0,
        "duplicate": 0,
        "reordered": 0,
        "input": 0,
        "output": 0,
    }

    for envelope in envelopes:
        noisy, stats = engine.apply([envelope])
        for key, value in stats.items():
            stats_aggregate[key] += value
        for item in noisy:
            for meta_key, meta_value in item.metadata.items():
                record.meta.setdefault(meta_key, meta_value)
            storage.store_chunk(record, item)
            processed.append(item)

    stats_aggregate["output"] = len(processed)
    _get_metrics(request).record_noise(stats_aggregate)
    return stats_aggregate


@router.post("/chunk")
async def upload_chunk(payload: ChunkRequest, request: Request) -> Dict[str, float]:
    """Приём очередного чанка."""

    record = storage.get_upload(payload.file_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден.")

    envelope = _envelope_from_request(payload)
    start = time.perf_counter()
    stats = _apply_noise_and_store(record, [envelope], request)
    duration = time.perf_counter() - start
    _get_metrics(request).record_upload(len(payload.payload), duration, stage="chunk")

    expected_total = record.assembler.expected or payload.total_sequences
    missing = record.assembler.missing_sequences()
    data_count = record.assembler.data_count()
    parity_count = record.assembler.parity_count()

    await _get_sse(request).publish(
        "chunk",
        {
            "file_id": payload.file_id,
            "sequence": payload.sequence,
            "parity": payload.is_parity,
            "bytes": len(payload.payload),
            "stats": stats,
        },
    )
    await _publish_progress(
        request,
        payload.file_id,
        sequence=payload.sequence,
        expected=expected_total,
        received_data=data_count,
        received_parity=parity_count,
        received_total=data_count + parity_count,
        missing_total=len(missing),
        bytes_sent=len(payload.payload),
        is_parity=payload.is_parity,
    )
    return stats


@router.post("/parity")
async def upload_parity(payload: ChunkRequest, request: Request) -> Dict[str, float]:
    """Приём чанка с избыточностью."""

    payload.is_parity = True
    return await upload_chunk(payload, request)


def _collect_shards(record) -> Sequence[Optional[bytes]]:
    pipeline = record.pipeline
    if pipeline.fec.mode == "rs":
        n = pipeline.fec.n
        shards: List[Optional[bytes]] = [None] * n
        for env in record.assembler.data_envelopes():
            idx = env.fec_index if env.fec_index is not None else env.sequence
            if 0 <= idx < n:
                shards[idx] = env.payload
        for env in record.assembler.parity_envelopes():
            idx = env.fec_index if env.fec_index is not None else env.sequence
            if 0 <= idx < n:
                shards[idx] = env.payload
        return shards

    ordered = sorted(record.assembler.data_envelopes(), key=lambda env: env.sequence)
    if not ordered:
        return []
    joined = b"".join(env.payload for env in ordered)
    return [joined]


def _decrypt_payload(record, data: bytes) -> tuple[bytes, Dict[str, Any]]:
    pipeline = record.pipeline
    metrics: Dict[str, Any] = {
        "enabled": pipeline.encryption.enabled,
        "input_bytes": len(data),
        "session_id": record.handshake_session_id or pipeline.encryption.session_id,
    }
    if not pipeline.encryption.enabled:
        metrics["output_bytes"] = len(data)
        return data, metrics

    session_id = record.handshake_session_id or pipeline.encryption.session_id
    if not session_id:
        raise RuntimeError("Отсутствует сессия шифрования.")

    handshake = storage.get_handshake(session_id)
    if not handshake:
        raise RuntimeError("Не найден сохранённый контекст рукопожатия.")

    cipher = AESGCMCipher(handshake.aes_key, handshake.nonce_base)
    decrypted = cipher.decrypt(data, sequence=0)
    metrics["output_bytes"] = len(decrypted)
    return decrypted, metrics


def _decompress_payload(record, data: bytes) -> tuple[bytes, Dict[str, Any]]:
    pipeline = record.pipeline
    try:
        algorithm = CompressionAlgo(pipeline.compression.algorithm)
    except ValueError as exc:  # noqa: BLE001
        raise RuntimeError("Неизвестный алгоритм сжатия.") from exc

    compression_cfg = CompressionConfig(
        enabled=pipeline.compression.enabled,
        level=pipeline.compression.level,
        algorithm=algorithm,
    )
    decompressed, metrics = decompress_bytes(data, compression_cfg)
    return decompressed, metrics


@router.post("/finish")
async def finish_upload(payload: FinishUploadRequest, request: Request) -> Dict[str, object]:
    """Попытка сборки файла из полученных чанков."""

    record = storage.get_upload(payload.file_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден.")

    shards = _collect_shards(record)
    if not shards:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нет данных для сборки.")

    pipeline = record.pipeline
    try:
        if pipeline.fec.mode == "rs":
            config = ReedSolomonConfig(n=pipeline.fec.n, k=pipeline.fec.k)
            expected_len = record.meta.get("rs_expected_len") or record.meta.get("encrypted_size")
            if expected_len is not None:
                try:
                    expected_len = int(expected_len)
                except (TypeError, ValueError):
                    expected_len = None
            data, fec_metrics = fec_decode_bytes(shards, "rs", config, expected_len=expected_len)
        elif pipeline.fec.mode == "hamming":
            data, fec_metrics = fec_decode_bytes(shards, "hamming")
        else:
            data, fec_metrics = fec_decode_bytes(shards, "off")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    storage.set_stage_metrics(record, "fec", fec_metrics)
    await _publish_stage_metrics(request, record.file_id, "fec", fec_metrics)
    _get_metrics(request).record_fec_result(fec_metrics.get("corrected", 0), pipeline.fec.mode)

    try:
        decrypted, encryption_metrics = _decrypt_payload(record, data)
        storage.set_stage_metrics(record, "encryption", encryption_metrics)
        await _publish_stage_metrics(request, record.file_id, "encryption", encryption_metrics)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    decompressed, compression_metrics = _decompress_payload(record, decrypted)
    storage.set_stage_metrics(record, "compression", compression_metrics)
    await _publish_stage_metrics(request, record.file_id, "compression", compression_metrics)

    expected_original = record.meta.get("original_size")
    expected_original_int: Optional[int]
    try:
        expected_original_int = int(expected_original) if expected_original is not None else None
    except (TypeError, ValueError):
        expected_original_int = None
    if expected_original_int is not None and expected_original_int != len(decompressed):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Размер восстановленного файла не совпадает с исходным. "
                "Попробуйте уменьшить помехи или включить FEC."
            ),
        )

    path = storage.complete_upload(record, decompressed, expected_size=expected_original_int)
    await _publish_stage_metrics(request, record.file_id, "final", record.stage_metrics.get("final", {}))
    await _get_sse(request).publish(
        "image_ready",
        {
            "file_id": record.file_id,
            "filename": record.filename,
            "path": str(path),
            "size_bytes": len(decompressed),
        },
    )

    return {
        "файл": record.file_id,
        "сохранён": str(path),
        "этапы": record.stage_metrics,
    }


@router.get("/status")
async def get_status(file_id: str):
    """Текущий статус загрузки."""

    record = storage.get_upload(file_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден.")
    return {
        "file_id": file_id,
        "missing": record.assembler.missing_sequences(),
        "ready": bool(record.final_path),
        "stages": record.stage_metrics,
    }
