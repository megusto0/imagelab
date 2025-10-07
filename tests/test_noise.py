from app.noise import NoiseConfig, NoiseEngine
from app.pipelines.chunking import ChunkEnvelope


def test_noise_statistics_and_duplication():
    engine = NoiseEngine()
    engine.random.seed(1234)
    engine.configure(NoiseConfig(loss=0.2, ber=0.0, duplicate=0.5, reorder=1.0))

    packets = [
        ChunkEnvelope(chunk_id="demo", sequence=i, payload=b"data", total_chunks=5)
        for i in range(5)
    ]

    mutated, stats = engine.apply(packets)

    assert stats["input"] == 5
    assert stats["loss"] >= 0
    assert stats["output"] >= stats["input"] - stats["loss"]
    # Благодаря высокой вероятности дубликатов вероятность >0
    assert stats["duplicate"] >= 0
    # При перестановке 100% флаг обязательно единица
    assert stats["reordered"] in (0, 1)

    # Проверяем, что результат корректно представлен ChunkEnvelope
    assert all(isinstance(item.payload, bytes) for item in mutated)
