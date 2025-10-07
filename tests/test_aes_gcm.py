from secrets import token_bytes

import pytest

from app.pipelines.crypto import AESGCMCipher


def test_aes_gcm_roundtrip():
    key = token_bytes(32)
    cipher = AESGCMCipher(key, nonce_base=123456)
    plaintext = b"labrador test payload"

    ciphertext = cipher.encrypt(plaintext, sequence=0)
    recovered = cipher.decrypt(ciphertext, sequence=0)
    assert recovered == plaintext


def test_aes_gcm_bad_tag():
    key = token_bytes(16)
    cipher = AESGCMCipher(key, nonce_base=999)
    payload = b"short block"
    ciphertext = bytearray(cipher.encrypt(payload, sequence=1))
    ciphertext[-1] ^= 0x01

    with pytest.raises(Exception):
        cipher.decrypt(bytes(ciphertext), sequence=1)
