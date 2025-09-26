import binascii
import os
from typing import Optional

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_DEFAULT_KEY_HEX = "6a1c35292b7c5b769ff47d89a17e7bc4f0adfe1b462981d28e0e9f7ff20b8f8a"


def _get_key_bytes(key_hex: Optional[str] = None) -> bytes:
    key_hex = (key_hex or os.getenv("KITE_AUTH_KEY") or _DEFAULT_KEY_HEX).strip()
    if len(key_hex) % 2 != 0:
        raise ValueError("Auth key hex has invalid length.")
    try:
        return bytes.fromhex(key_hex)
    except ValueError as e:
        raise ValueError(f"Invalid auth key hex: {e}") from e


def generate_auth_token(eoa_address: str, *, key_hex: Optional[str] = None) -> str:
    if not isinstance(eoa_address, str) or not eoa_address.startswith("0x") or len(eoa_address) != 42:
        raise ValueError("EOA must be a 0x-prefixed 20-byte address string.")

    key = _get_key_bytes(key_hex)
    iv = os.urandom(12)

    encryptor = Cipher(algorithms.AES(key), modes.GCM(iv), backend=default_backend()).encryptor()

    ciphertext = encryptor.update(eoa_address.encode("utf-8")) + encryptor.finalize()
    token_bytes = iv + ciphertext + encryptor.tag
    return binascii.hexlify(token_bytes).decode("ascii")


def decrypt_auth_token(token_hex: str, *, key_hex: Optional[str] = None) -> str:
    raw = bytes.fromhex(token_hex)
    if len(raw) < 12 + 16:
        raise ValueError("Token too short.")

    iv = raw[:12]
    tag = raw[-16:]
    ciphertext = raw[12:-16]
    key = _get_key_bytes(key_hex)

    decryptor = Cipher(algorithms.AES(key), modes.GCM(iv, tag), backend=default_backend()).decryptor()

    plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    return plaintext.decode("utf-8")
