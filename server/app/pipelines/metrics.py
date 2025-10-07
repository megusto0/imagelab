"""Сбор и агрегация метрик в скользящем окне."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Iterable, Optional


@dataclass(slots=True)
class UploadSample:
    timestamp: float
    num_bytes: int
    duration: float
    stage: str = "upload"


@dataclass(slots=True)
class RTTSample:
    timestamp: float
    rtt_ms: float


@dataclass(slots=True)
class NoiseSample:
    timestamp: float
    stats: Dict[str, float]


@dataclass(slots=True)
class FECResultSample:
    timestamp: float
    corrected: int
    mode: str


class MetricAggregator:
    """Собирает статистику и агрегирует её в пределах окна."""

    def __init__(self, window_seconds: int = 60) -> None:
        self.window_seconds = window_seconds
        self._uploads: Deque[UploadSample] = deque()
        self._rtts: Deque[RTTSample] = deque()
        self._noise: Deque[NoiseSample] = deque()
        self._fec: Deque[FECResultSample] = deque()

    # ---------- Recording helpers ----------
    def record_upload(self, num_bytes: int, duration: float, stage: str = "upload") -> None:
        self._uploads.append(UploadSample(time.time(), num_bytes, duration, stage))
        self._trim()

    def record_rtt(self, rtt_ms: float) -> None:
        self._rtts.append(RTTSample(time.time(), rtt_ms))
        self._trim()

    def record_noise(self, stats: Dict[str, float]) -> None:
        self._noise.append(NoiseSample(time.time(), stats))
        self._trim()

    def record_fec_result(self, corrected: int, mode: str) -> None:
        self._fec.append(FECResultSample(time.time(), corrected, mode))
        self._trim()

    # ---------- Aggregates ----------
    def _trim(self) -> None:
        cutoff = time.time() - self.window_seconds
        for deque_ in (self._uploads, self._rtts, self._noise, self._fec):
            while deque_ and deque_[0].timestamp < cutoff:
                deque_.popleft()

    def throughput_kbps(self) -> float:
        if not self._uploads:
            return 0.0
        total_bytes = sum(sample.num_bytes for sample in self._uploads)
        total_time = sum(sample.duration for sample in self._uploads) or 1e-6
        return (total_bytes * 8 / 1000) / total_time

    def average_rtt(self) -> float:
        if not self._rtts:
            return 0.0
        return sum(sample.rtt_ms for sample in self._rtts) / len(self._rtts)

    def latest_noise(self) -> Dict[str, float]:
        return self._noise[-1].stats if self._noise else {}

    def latest_fec(self) -> Dict[str, float]:
        if not self._fec:
            return {"mode": "off", "corrected": 0}
        latest = self._fec[-1]
        return {"mode": latest.mode, "corrected": latest.corrected}

    def snapshot(self) -> Dict[str, float]:
        self._trim()
        return {
            "window_seconds": self.window_seconds,
            "throughput_kbps": round(self.throughput_kbps(), 3),
            "average_rtt_ms": round(self.average_rtt(), 3),
            "noise": self.latest_noise(),
            "fec": self.latest_fec(),
            "samples": {
                "uploads": len(self._uploads),
                "rtt": len(self._rtts),
                "noise": len(self._noise),
                "fec": len(self._fec),
            },
        }
