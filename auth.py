import hashlib
import hmac
import os

from fastapi import HTTPException, Request, status

# scrypt parameters: matches common defaults (e.g. Django's) for interactive login use.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return salt.hex() + ":" + derived.hex()


def verify_password(password: str, stored_hash: str) -> bool:
    salt_hex, derived_hex = stored_hash.split(":")
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(derived_hex)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return hmac.compare_digest(derived, expected)


def require_login(request: Request) -> None:
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
