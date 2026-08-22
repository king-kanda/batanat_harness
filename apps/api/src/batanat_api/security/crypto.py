"""Envelope encryption for stored credentials.

Every secret is encrypted under its own randomly generated data key; that data
key is then encrypted under the master key from the environment. Two properties
follow, and both matter:

* Rotating the master key means re-wrapping a handful of small data keys, not
  re-encrypting every token — so rotation is cheap enough to actually happen.
* A leaked ciphertext without its wrapped key is useless, and vice versa.

`Fernet` gives authenticated encryption (AES-128-CBC + HMAC-SHA256), so a
tampered ciphertext fails loudly rather than decrypting to rubbish.

The master key never leaves this module. Plaintext secrets are returned only to
the caller that asked for them, and are never placed in a log record — see the
redaction processor in `core.logging`.
"""

from __future__ import annotations

from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken

from batanat_api.config import get_settings


class EncryptionError(RuntimeError):
    """Raised when a secret cannot be sealed or opened."""


class MasterKeyMissingError(EncryptionError):
    """TOKEN_ENCRYPTION_KEY is absent or malformed."""


@dataclass(frozen=True, slots=True)
class SealedSecret:
    """A secret at rest: the ciphertext, plus its data key wrapped by the master key."""

    ciphertext: bytes
    wrapped_key: bytes

    def __repr__(self) -> str:  # pragma: no cover - defensive
        # Never let a sealed secret render its bytes into a traceback or log line.
        return f"SealedSecret(ciphertext=<{len(self.ciphertext)} bytes>, wrapped_key=<redacted>)"


def generate_master_key() -> str:
    """Generate a value suitable for TOKEN_ENCRYPTION_KEY."""
    return Fernet.generate_key().decode()


def _master_cipher() -> Fernet:
    key = get_settings().token_encryption_key
    if not key:
        raise MasterKeyMissingError(
            "TOKEN_ENCRYPTION_KEY is not set. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise MasterKeyMissingError(
            "TOKEN_ENCRYPTION_KEY is not a valid Fernet key (32 url-safe base64 bytes)."
        ) from exc


def seal(plaintext: str) -> SealedSecret:
    """Encrypt a secret under a fresh data key."""
    if plaintext is None:
        raise EncryptionError("Cannot seal None.")

    data_key = Fernet.generate_key()
    ciphertext = Fernet(data_key).encrypt(plaintext.encode())
    wrapped_key = _master_cipher().encrypt(data_key)
    return SealedSecret(ciphertext=ciphertext, wrapped_key=wrapped_key)


def open_sealed(sealed: SealedSecret) -> str:
    """Decrypt a secret. Raises `EncryptionError` if the key or ciphertext is wrong."""
    try:
        data_key = _master_cipher().decrypt(sealed.wrapped_key)
        return Fernet(data_key).decrypt(sealed.ciphertext).decode()
    except InvalidToken as exc:
        raise EncryptionError(
            "Could not decrypt: the master key does not match the one used to seal this "
            "value, or the data has been tampered with. Rotating TOKEN_ENCRYPTION_KEY "
            "invalidates stored tokens — affected users must reconnect."
        ) from exc


def rewrap(sealed: SealedSecret, *, old_master_key: str) -> SealedSecret:
    """Re-wrap a data key under the current master key, without touching the ciphertext.

    This is the whole point of the envelope: master-key rotation reads and
    rewrites one small key per row, and the (potentially large) ciphertext stays
    exactly as it is.
    """
    try:
        data_key = Fernet(old_master_key.encode()).decrypt(sealed.wrapped_key)
    except (InvalidToken, ValueError, TypeError) as exc:
        raise EncryptionError("Could not unwrap the data key with the supplied old key.") from exc

    return SealedSecret(
        ciphertext=sealed.ciphertext,
        wrapped_key=_master_cipher().encrypt(data_key),
    )
