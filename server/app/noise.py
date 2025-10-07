"""Эмуляция помех канала."""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Tuple

from .pipelines.chunking import ChunkEnvelope


@dataclass(slots=True)
class NoiseConfig:
    """Параметры потерь, BER, дубликатов и перестановок."""

    loss: float = 0.0
    ber: float = 0.0
    duplicate: float = 0.0
    reorder: float = 0.0

    def clamp(self) -> "NoiseConfig":
        return NoiseConfig(
            loss=_clamp(self.loss),
            ber=_clamp(self.ber),
            duplicate=_clamp(self.duplicate),
            reorder=_clamp(self.reorder),
        )


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(value, high))


class NoiseEngine:
    """Вносит случайные искажения в передаваемые чанки."""

    def __init__(self) -> None:
        self.config = NoiseConfig()
        self.random = random.Random()

    def configure(self, config: NoiseConfig) -> NoiseConfig:
        self.config = config.clamp()
        return self.config

    def apply(self, envelopes: Iterable[ChunkEnvelope]) -> Tuple[List[ChunkEnvelope], Dict[str, float]]:
        cfg = self.config
        stats = {
            "loss": 0,
            "bit_flips": 0,
            "duplicate": 0,
            "reordered": 0,
            "input": 0,
            "output": 0,
        }

        processed: List[ChunkEnvelope] = []
        for env in envelopes:
            stats["input"] += 1
            if self.random.random() < cfg.loss:
                stats["loss"] += 1
                continue

            payload = bytearray(env.payload)
            for byte_idx in range(len(payload)):
                for bit_idx in range(8):
                    if self.random.random() < cfg.ber:
                        payload[byte_idx] ^= (1 << bit_idx)
                        stats["bit_flips"] += 1

            mutated = ChunkEnvelope(
                chunk_id=env.chunk_id,
                sequence=env.sequence,
                payload=bytes(payload),
                is_parity=env.is_parity,
                fec_index=env.fec_index,
                total_chunks=env.total_chunks,
                metadata=dict(env.metadata),
            )
            processed.append(mutated)

            if self.random.random() < cfg.duplicate:
                stats["duplicate"] += 1
                processed.append(mutated)

        if processed and self.random.random() < cfg.reorder:
            stats["reordered"] = 1
            self.random.shuffle(processed)

        stats["output"] = len(processed)
        return processed, stats

    def current_config(self) -> Dict[str, float]:
        return asdict(self.config)


# Глобальный экземпляр для удобного доступа
engine = NoiseEngine()
