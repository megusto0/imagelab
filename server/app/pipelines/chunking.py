"""Функции нарезки и сборки чанков."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional


@dataclass(slots=True)
class ChunkEnvelope:
    """Описание отдельного чанка большого файла."""

    chunk_id: str
    sequence: int
    payload: bytes
    is_parity: bool = False
    fec_index: Optional[int] = None
    total_chunks: Optional[int] = None
    metadata: Dict[str, int | str | float] = field(default_factory=dict)


def build_chunk_envelopes(
    chunk_id: str,
    data: bytes,
    chunk_size: int,
) -> List[ChunkEnvelope]:
    """Нарезать байты на последовательные конверты."""

    chunks: List[ChunkEnvelope] = []
    if chunk_size <= 0:
        raise ValueError("Размер чанка должен быть положительным.")

    count = (len(data) + chunk_size - 1) // chunk_size or 1

    for seq in range(count):
        start = seq * chunk_size
        payload = data[start : start + chunk_size]
        chunks.append(
            ChunkEnvelope(
                chunk_id=chunk_id,
                sequence=seq,
                payload=payload,
                total_chunks=count,
            )
        )
    return chunks


def reassemble_from_envelopes(envelopes: Iterable[ChunkEnvelope]) -> bytes:
    """Собрать полезную нагрузку из упорядоченных конвертов."""

    ordered = sorted(envelopes, key=lambda env: env.sequence)
    return b"".join(env.payload for env in ordered)


class ChunkAssembler:
    """Копит чанки, пока не появится возможность восстановить файл."""

    def __init__(self, chunk_id: str):
        self.chunk_id = chunk_id
        self._chunks: Dict[int, ChunkEnvelope] = {}
        self._parity: Dict[int, ChunkEnvelope] = {}
        self._expected: Optional[int] = None

    def add(self, envelope: ChunkEnvelope) -> None:
        if envelope.chunk_id != self.chunk_id:
            raise ValueError("Идентификатор чанка не совпадает.")
        if envelope.total_chunks is not None:
            self._expected = envelope.total_chunks

        target = self._parity if envelope.is_parity else self._chunks
        target[envelope.sequence] = envelope

    @property
    def expected(self) -> Optional[int]:
        return self._expected

    def missing_sequences(self) -> List[int]:
        if self._expected is None:
            return []
        return sorted(
            seq
            for seq in range(self._expected)
            if seq not in self._chunks
        )

    def has_all_data(self) -> bool:
        if self._expected is None:
            return False
        return len(self._chunks) >= self._expected

    def data_envelopes(self) -> Iterable[ChunkEnvelope]:
        return self._chunks.values()

    def parity_envelopes(self) -> Iterable[ChunkEnvelope]:
        return self._parity.values()

    def reassemble(self) -> bytes:
        if not self.has_all_data():
            raise ValueError("Недостаточно чанков для сборки.")
        return reassemble_from_envelopes(self._chunks.values())
