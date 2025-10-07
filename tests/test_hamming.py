from app.pipelines.fec import HammingCodec


def test_hamming_single_bit_correction():
    codec = HammingCodec()
    original = b"\xAF\x10\xFF"
    encoded = bytearray(codec.encode(original))

    # Инвертируем один бит
    encoded[2] ^= 0b00000100

    decoded, metrics = codec.decode(bytes(encoded))
    assert decoded == original
    assert metrics["corrected"] >= 1
    assert metrics["double_error"] == 0


def test_hamming_double_error_detection():
    codec = HammingCodec()
    original = b"\x7A"
    encoded = bytearray(codec.encode(original))
    encoded[0] ^= 0b00000101

    decoded, metrics = codec.decode(bytes(encoded))
    assert decoded != original
    assert metrics["double_error"] >= 1
