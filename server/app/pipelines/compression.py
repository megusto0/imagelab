"""Функции сжатия на базе zlib/deflate."""

from __future__ import annotations

import enum
import zlib
from dataclasses import dataclass
from typing import Dict, Tuple


class CompressionAlgo(str, enum.Enum):
    """Поддерживаемые алгоритмы сжатия."""

    DEFLATE = "deflate"
    GZIP = "gzip"


@dataclass(slots=True)
class CompressionConfig:
    """Настройки этапа сжатия."""

    enabled: bool = False
    level: int = 6
    algorithm: CompressionAlgo = CompressionAlgo.DEFLATE


def _compress_deflate(data: bytes, level: int) -> bytes:
    compressor = zlib.compressobj(level, zlib.DEFLATED, -zlib.MAX_WBITS)
    return compressor.compress(data) + compressor.flush()


def _compress_gzip(data: bytes, level: int) -> bytes:
    compressor = zlib.compressobj(level, zlib.DEFLATED, zlib.MAX_WBITS | 16)
    return compressor.compress(data) + compressor.flush()


def compress_bytes(data: bytes, config: CompressionConfig) -> Tuple[bytes, Dict[str, float]]:
    """Сжать массив байтов согласно настройкам."""

    if not config.enabled:
        return data, {
            "enabled": False,
            "algorithm": None,
            "level": None,
            "input_bytes": len(data),
            "output_bytes": len(data),
            "ratio": 1.0,
        }

    level = max(0, min(config.level, 9))
    if config.algorithm == CompressionAlgo.GZIP:
        compressed = _compress_gzip(data, level)
    else:
        compressed = _compress_deflate(data, level)

    input_len = len(data)
    output_len = len(compressed)
    ratio = output_len / input_len if input_len else 1.0
    return compressed, {
        "enabled": True,
        "algorithm": config.algorithm.value,
        "level": level,
        "input_bytes": input_len,
        "output_bytes": output_len,
        "ratio": ratio,
    }


def decompress_bytes(data: bytes, config: CompressionConfig) -> Tuple[bytes, Dict[str, float]]:
    """Обратная операция к :func:`compress_bytes`."""

    if not config.enabled:
        return data, {
            "enabled": False,
            "algorithm": None,
            "input_bytes": len(data),
            "output_bytes": len(data),
        }

    if config.algorithm == CompressionAlgo.GZIP:
        decompressed = zlib.decompress(data, zlib.MAX_WBITS | 16)
    else:
        decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
        decompressed = decompressor.decompress(data) + decompressor.flush()

    return decompressed, {
        "enabled": True,
        "algorithm": config.algorithm.value,
        "input_bytes": len(data),
        "output_bytes": len(decompressed),
    }
