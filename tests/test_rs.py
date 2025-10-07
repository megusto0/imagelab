import pytest

from app.pipelines.fec import ReedSolomonCodec, ReedSolomonConfig


def test_rs_recovers_missing_data():
    codec = ReedSolomonCodec(ReedSolomonConfig(n=12, k=8))
    original = bytes(range(120))
    shards, _ = codec.encode(original)

    shards_opt = list(shards)
    # Потеряем два информационных и один паритетный блок
    shards_opt[1] = None
    shards_opt[7] = None
    shards_opt[10] = None

    recovered, metrics = codec.decode(shards_opt, expected_len=len(original))
    assert recovered == original
    assert metrics["corrected"] >= 3


def test_rs_too_many_losses():
    codec = ReedSolomonCodec(ReedSolomonConfig(n=8, k=4))
    data = b"example-payload"
    shards, _ = codec.encode(data)
    shards_opt = list(shards)
    # Потеряно более n-k (4) блоков
    for idx in range(5):
        shards_opt[idx] = None

    with pytest.raises(ValueError):
        codec.decode(shards_opt, expected_len=len(data))
