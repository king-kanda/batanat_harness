"""Password hashing.

`hashlib.scrypt` from the standard library — memory-hard, no dependency with
native build steps. n=2^15, r=8, p=1 is 32MB and ~0.6s per hash here: right for
the login path, where it happens once.

Nowhere else. `/api/auth/me` once called `verify_password` to derive whether an
account was still on the seeded password, putting 0.6s on the endpoint the UI
hits every page load. If you are hashing to derive a fact, store the fact.

Stored hashes carry their own parameters, so raising the cost later is safe —
`needs_rehash` flags them for upgrade on the next login.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

#: Bumping any of these is safe: existing hashes carry the values they were made
#: with, and `needs_rehash` flags them for upgrade.
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
KEY_BYTES = 32

#: scrypt needs 128 * n * r bytes — 32MB at these parameters, which is exactly
#: OpenSSL's default ceiling, so it fails without an explicit allowance. Set
#: with headroom so raising the cost later does not resurface this.
SCRYPT_MAXMEM = 128 * 1024 * 1024

PREFIX = "scrypt"


def hash_password(password: str) -> str:
    """Hash a password. Returns `scrypt$n$r$p$salt$key`, all base64."""
    if not password:
        raise ValueError("Password must not be empty.")

    salt = secrets.token_bytes(SALT_BYTES)
    key = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=KEY_BYTES,
        maxmem=SCRYPT_MAXMEM,
    )
    return "$".join(
        [
            PREFIX,
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            base64.b64encode(salt).decode(),
            base64.b64encode(key).decode(),
        ]
    )


def verify_password(password: str, stored: str | None) -> bool:
    """Check a password against a stored hash. False on anything malformed.

    Compared with `compare_digest`: an early-exit comparison leaks the hash a
    byte at a time to anyone who can measure the response.
    """
    if not stored or not password:
        return False

    try:
        prefix, n, r, p, salt_b64, key_b64 = stored.split("$")
        if prefix != PREFIX:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(key_b64)
        candidate = hashlib.scrypt(
            password.encode(),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
            maxmem=SCRYPT_MAXMEM,
        )
    except (ValueError, TypeError, MemoryError):
        return False

    return hmac.compare_digest(candidate, expected)


def needs_rehash(stored: str | None) -> bool:
    """True when a hash was made with weaker parameters than we now use."""
    if not stored:
        return True
    try:
        prefix, n, r, p, _, _ = stored.split("$")
    except ValueError:
        return True
    return prefix != PREFIX or (int(n), int(r), int(p)) != (SCRYPT_N, SCRYPT_R, SCRYPT_P)


def set_password(user, password: str) -> None:
    """Give a user a real password and clear the must-change flag.

    Both halves belong together: a stored flag that says "still on the seeded
    default" is only trustworthy if nothing can set a password without clearing
    it. Use this rather than assigning `password_hash` directly.
    """
    user.password_hash = hash_password(password)
    user.must_change_password = False
