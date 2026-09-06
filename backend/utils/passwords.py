"""Password hashing using scrypt from the Python standard library.

scrypt is a memory-hard key derivation function, which is what makes brute
forcing a stolen hash expensive. It needs no third-party package, so there is
no compiled wheel to break on a new Python release.

Stored format:  scrypt$<salt-hex>$<derived-key-hex>

Plaintext passwords are never stored, logged, or returned by the API.
"""

import hashlib
import secrets

# n=2**14 costs roughly 16 MB of memory and ~50-100 ms per hash, which is slow
# enough to frustrate offline cracking and fast enough for a login request.
_N = 2**14
_R = 8
_P = 1
_MAXMEM = 64 * 1024 * 1024
_SALT_BYTES = 16
_KEY_BYTES = 64

_PREFIX = "scrypt"


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_N,
        r=_R,
        p=_P,
        maxmem=_MAXMEM,
        dklen=_KEY_BYTES,
    )


def hash_password(password: str) -> str:
    """Hash a plaintext password with a fresh random salt."""
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = _derive(password, salt)
    return f"{_PREFIX}${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Check a password against a stored hash.

    Returns False rather than raising on a malformed hash, so a corrupt record
    fails the login instead of returning a 500.
    """
    try:
        prefix, salt_hex, key_hex = stored_hash.split("$")
    except (ValueError, AttributeError):
        return False
    if prefix != _PREFIX:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(key_hex)
    except ValueError:
        return False

    derived = _derive(password, salt)
    # compare_digest avoids leaking how much of the hash matched via timing.
    return secrets.compare_digest(derived, expected)
