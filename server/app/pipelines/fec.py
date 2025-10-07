"""Вспомогательные средства помехоустойчивого кодирования."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from reedsolo import RSCodec  # type: ignore[import]


# ------------------------------
# Hamming(7,4)
# ------------------------------


def _parity(*bits: int) -> int:
    acc = 0
    for bit in bits:
        acc ^= bit & 1
    return acc


def _bit(value: int, index: int) -> int:
    return (value >> index) & 1


class HammingCodec:
    """Хэмминг(7,4) поверх полуоктетов."""

    def encode(self, payload: bytes) -> bytes:
        encoded: List[int] = []
        for byte in payload:
            high = (byte >> 4) & 0x0F
            low = byte & 0x0F
            encoded.append(self._encode_nibble(high))
            encoded.append(self._encode_nibble(low))
        return bytes(encoded)

    def decode(self, payload: bytes) -> Tuple[bytes, Dict[str, int]]:
        if len(payload) % 2:
            raise ValueError("Длина полезной нагрузки для Хэмминга должна быть чётной.")

        corrected = 0
        detected_double = 0
        decoded: List[int] = []

        for i in range(0, len(payload), 2):
            high_code = payload[i]
            low_code = payload[i + 1]
            high, corr_high, dbl_high = self._decode_codeword(high_code)
            low, corr_low, dbl_low = self._decode_codeword(low_code)
            corrected += corr_high + corr_low
            detected_double += dbl_high + dbl_low
            decoded.append((high << 4) | low)

        return bytes(decoded), {
            "corrected": corrected,
            "double_error": detected_double,
        }

    @staticmethod
    def _encode_nibble(nibble: int) -> int:
        d3 = _bit(nibble, 3)
        d2 = _bit(nibble, 2)
        d1 = _bit(nibble, 1)
        d0 = _bit(nibble, 0)

        p1 = _parity(d3, d2, d0)
        p2 = _parity(d3, d1, d0)
        p3 = _parity(d2, d1, d0)

        # Position indices (1-based):
        # 1:p1 2:p2 3:d3 4:p3 5:d2 6:d1 7:d0
        return (
            (p1 << 6)
            | (p2 << 5)
            | (d3 << 4)
            | (p3 << 3)
            | (d2 << 2)
            | (d1 << 1)
            | d0
        )

    @staticmethod
    def _decode_codeword(code: int) -> Tuple[int, int, int]:
        bits = [(code >> (6 - i)) & 1 for i in range(7)]

        p1, p2, d3, p3, d2, d1, d0 = bits

        s1 = _parity(p1, d3, d2, d0)
        s2 = _parity(p2, d3, d1, d0)
        s3 = _parity(p3, d2, d1, d0)

        syndrome = (s1 << 2) | (s2 << 1) | s3
        corrected = 0
        double_error = 0
        if syndrome:
            pos = syndrome - 1
            if 0 <= pos < 7:
                bits[pos] ^= 1
                corrected = 1
            else:
                double_error = 1

        _, _, d3, _, d2, d1, d0 = bits
        nibble = (d3 << 3) | (d2 << 2) | (d1 << 1) | d0
        return nibble, corrected, double_error


# ------------------------------
# Reed-Solomon
# ------------------------------


@dataclass(slots=True)
class ReedSolomonConfig:
    n: int = 120
    k: int = 100

    def __post_init__(self) -> None:
        if self.n <= self.k:
            raise ValueError("Для кода Рида–Соломона нужно n > k.")
        if self.k <= 0:
            raise ValueError("Параметр k должен быть положительным.")


class ReedSolomonCodec:
    """Разбиение байтов на n фрагментов при помощи систематического RS(n, k)."""

    def __init__(self, config: ReedSolomonConfig):
        self.config = config
        self._codec = RSCodec(self.config.n - self.config.k)

    @property
    def shard_size(self) -> int:
        return self.config.k

    def _split_data(self, data: bytes) -> List[bytearray]:
        shard_len = (len(data) + self.config.k - 1) // self.config.k
        shard_len = max(1, shard_len)
        shards = [bytearray(shard_len) for _ in range(self.config.k)]
        for idx, byte in enumerate(data):
            shard_idx = idx % self.config.k
            offset = idx // self.config.k
            shards[shard_idx][offset] = byte
        # Pad remainder with zeros already
        return shards

    def encode(self, data: bytes) -> Tuple[List[bytes], Dict[str, int]]:
        data_shards = self._split_data(data)
        shard_len = len(data_shards[0])
        parity_shards = [bytearray(shard_len) for _ in range(self.config.n - self.config.k)]

        for offset in range(shard_len):
            column = bytes(shard[offset] for shard in data_shards)
            encoded = self._codec.encode(column)
            parity = encoded[self.config.k :]
            for p_idx, value in enumerate(parity):
                parity_shards[p_idx][offset] = value

        shards: List[bytes] = [bytes(s) for s in data_shards] + [bytes(s) for s in parity_shards]
        return shards, {
            "n": self.config.n,
            "k": self.config.k,
            "input_bytes": len(data),
            "shard_len": shard_len,
        }

    def decode(
        self,
        shards: Sequence[Optional[bytes]],
        expected_len: Optional[int] = None,
    ) -> Tuple[bytes, Dict[str, int]]:
        if len(shards) != self.config.n:
            raise ValueError(f"Ожидалось {self.config.n} блоков, получено {len(shards)}.")

        present = [s for s in shards if s is not None]
        if not present:
            raise ValueError("Не переданы блоки для декодирования.")
        shard_len = len(present[0])
        recovered_columns: List[bytes] = []
        corrected = 0

        for offset in range(shard_len):
            column_symbols = []
            erase_pos = []
            for idx, shard in enumerate(shards):
                if shard is None:
                    column_symbols.append(0)
                    erase_pos.append(idx)
                else:
                    column_symbols.append(shard[offset])

            if len(erase_pos) > (self.config.n - self.config.k):
                raise ValueError("Слишком много потерь для восстановления.")

            decoded, _ = self._codec.decode(bytes(column_symbols), erase_pos=tuple(erase_pos))
            corrected += len(erase_pos)
            recovered_columns.append(decoded)

        # Rebuild original bytes
        data: bytearray = bytearray()
        for column_idx, column in enumerate(recovered_columns):
            for shard_idx in range(self.config.k):
                data.append(column[shard_idx])

        result = bytes(data)
        if expected_len is not None:
            result = result[:expected_len]
        else:
            result = result.rstrip(b"\x00")

        return result, {
            "corrected": corrected,
            "n": self.config.n,
            "k": self.config.k,
        }


def fec_encode_bytes(
    data: bytes,
    mode: str,
    rs_config: Optional[ReedSolomonConfig] = None,
) -> Tuple[Iterable[bytes], Dict[str, int]]:
    """Выбрать подходящую схему FEC для кодирования."""

    if mode == "off":
        return [data], {"mode": "off", "parts": 1}
    if mode == "hamming":
        codec = HammingCodec()
        encoded = codec.encode(data)
        return [encoded], {"mode": "hamming", "parts": 1, "output_bytes": len(encoded)}
    if mode == "rs":
        codec = ReedSolomonCodec(rs_config or ReedSolomonConfig())
        shards, metrics = codec.encode(data)
        metrics["mode"] = "rs"
        metrics["parts"] = len(shards)
        return shards, metrics
    raise ValueError(f"Неподдерживаемый режим FEC: {mode}")


def fec_decode_bytes(
    data: Sequence[Optional[bytes]],
    mode: str,
    rs_config: Optional[ReedSolomonConfig] = None,
    expected_len: Optional[int] = None,
) -> Tuple[bytes, Dict[str, int]]:
    if mode == "off":
        if len(data) != 1 or data[0] is None:
            raise ValueError("При отключённом FEC ожидается один блок данных.")
        return data[0], {"mode": "off"}
    if mode == "hamming":
        codec = HammingCodec()
        decoded, metrics = codec.decode(data[0] or b"")
        metrics["mode"] = "hamming"
        return decoded, metrics
    if mode == "rs":
        codec = ReedSolomonCodec(rs_config or ReedSolomonConfig())
        decoded, metrics = codec.decode(data, expected_len=expected_len)
        metrics["mode"] = "rs"
        return decoded, metrics
    raise ValueError(f"Неподдерживаемый режим FEC: {mode}")
