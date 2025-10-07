from app.pipelines.chunking import ChunkAssembler, build_chunk_envelopes


def test_chunk_builder_and_assembler():
    payload = b"0123456789" * 64
    chunk_size = 32
    envelopes = build_chunk_envelopes("file123", payload, chunk_size)
    assert len(envelopes) == (len(payload) + chunk_size - 1) // chunk_size

    assembler = ChunkAssembler("file123")
    for env in envelopes:
        assembler.add(env)

    assert assembler.has_all_data()
    assert assembler.missing_sequences() == []
    rebuilt = assembler.reassemble()
    assert rebuilt == payload


def test_missing_sequences_detected():
    payload = b"abcdefghij"
    envelopes = build_chunk_envelopes("demo", payload, 3)
    assembler = ChunkAssembler("demo")
    for env in envelopes[:-1]:
        assembler.add(env)
    missing = assembler.missing_sequences()
    assert missing == [len(envelopes) - 1]
