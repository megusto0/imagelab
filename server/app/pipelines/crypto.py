"""Рукопожатие X25519 и вспомогательные функции AES-GCM."""

from __future__ import annotations

import base64
import json
import os
import secrets
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Dict, Optional, Tuple

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

HANDSHAKE_INFO = b"image-http-lab-handshake"


def b64encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64decode(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"))


@dataclass(slots=True)
class HandshakeContext:
    """Контекст установленного шифрования."""

    session_id: str
    client_public_key: bytes
    server_private_key: bytes
    server_public_key: bytes
    shared_secret: bytes
    salt: bytes
    aes_key: bytes
    nonce_base: int
    created_at: float

    def as_response(self) -> Dict[str, str]:
        """Подготовить словарь для ответа клиенту."""

        return {
            "session_id": self.session_id,
            "server_public_key": b64encode(self.server_public_key),
            "salt": b64encode(self.salt),
            "nonce_base": b64encode(self.nonce_base.to_bytes(12, "big")),
        }

    def export(self) -> str:
        """Экспорт контекста в JSON для хранения."""

        payload = asdict(self)
        payload["client_public_key"] = b64encode(self.client_public_key)
        payload["server_private_key"] = b64encode(self.server_private_key)
        payload["server_public_key"] = b64encode(self.server_public_key)
        payload["shared_secret"] = b64encode(self.shared_secret)
        payload["salt"] = b64encode(self.salt)
        payload["aes_key"] = b64encode(self.aes_key)
        payload["nonce_base"] = self.nonce_base
        return json.dumps(payload)

    @staticmethod
    def parse(raw: str) -> "HandshakeContext":
        data = json.loads(raw)
        return HandshakeContext(
            session_id=data["session_id"],
            client_public_key=b64decode(data["client_public_key"]),
            server_private_key=b64decode(data["server_private_key"]),
            server_public_key=b64decode(data["server_public_key"]),
            shared_secret=b64decode(data["shared_secret"]),
            salt=b64decode(data["salt"]),
            aes_key=b64decode(data["aes_key"]),
            nonce_base=int(data["nonce_base"]),
            created_at=float(data["created_at"]),
        )


def derive_aes_gcm_key(shared_secret: bytes, salt: bytes) -> bytes:
    """Вывести 256-битный ключ AES посредством HKDF-SHA256."""

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=HANDSHAKE_INFO,
    )
    return hkdf.derive(shared_secret)


def generate_server_handshake(client_public_b64: str) -> Tuple[HandshakeContext, Dict[str, str]]:
    """Выполнить рукопожатие X25519 с переданным публичным ключом клиента."""

    client_public_key = x25519.X25519PublicKey.from_public_bytes(b64decode(client_public_b64))
    server_private_key = x25519.X25519PrivateKey.generate()
    server_public_key = server_private_key.public_key()
    shared_secret = server_private_key.exchange(client_public_key)
    salt = secrets.token_bytes(16)
    aes_key = derive_aes_gcm_key(shared_secret, salt)
    nonce_base = int.from_bytes(secrets.token_bytes(12), "big") & ((1 << 96) - 1)
    session_id = uuid.uuid4().hex

    ctx = HandshakeContext(
        session_id=session_id,
        client_public_key=client_public_key.public_bytes(Encoding.Raw, PublicFormat.Raw),
        server_private_key=server_private_key.private_bytes(
            encoding=Encoding.Raw,
            format=PrivateFormat.Raw,
            encryption_algorithm=NoEncryption(),
        ),
        server_public_key=server_public_key.public_bytes(Encoding.Raw, PublicFormat.Raw),
        shared_secret=shared_secret,
        salt=salt,
        aes_key=aes_key,
        nonce_base=nonce_base,
        created_at=time.time(),
    )

    response = {
        **ctx.as_response(),
        "algorithm": "x25519-hkdf-sha256/aes-gcm",
    }
    return ctx, response


class AESGCMCipher:
    """Обёртка AES-GCM, вычисляющая одноразовые числа как base+sequence."""

    def __init__(self, key: bytes, nonce_base: int):
        if len(key) not in (16, 24, 32):
            raise ValueError("AES-GCM key must be 128/192/256 bits")
        self._aesgcm = AESGCM(key)
        self.key = key
        self.nonce_base = nonce_base & ((1 << 96) - 1)

    def _nonce_for(self, sequence: int) -> bytes:
        seq_val = (self.nonce_base + sequence) & ((1 << 96) - 1)
        return seq_val.to_bytes(12, "big")

    def encrypt(self, payload: bytes, sequence: int, aad: Optional[bytes] = None) -> bytes:
        return self._aesgcm.encrypt(self._nonce_for(sequence), payload, aad)

    def decrypt(self, payload: bytes, sequence: int, aad: Optional[bytes] = None) -> bytes:
        return self._aesgcm.decrypt(self._nonce_for(sequence), payload, aad)


def load_handshake_context(raw: str) -> HandshakeContext:
    """Загрузить сохранённый контекст рукопожатия."""

    return HandshakeContext.parse(raw)
