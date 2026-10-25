"""Protect credentials at rest; legacy plaintext remains readable.

Windows uses per-user DPAPI (pywin32 is already a project dependency).
Other platforms use an available system keyring. A missing secure backend
raises rather than silently writing new secrets in plaintext.
"""
from __future__ import annotations

import base64
import sys
import uuid

_DPAPI = "jarvis:dpapi:v1:"
_KEYRING = "jarvis:keyring:v1:"
_SERVICE = "JARVIS desktop"
_SECRET_KEYS = {"api_key", "password", "token", "access_token", "refresh_token", "client_secret"}


def _secret_key(name: str) -> bool:
    name = name.lower()
    return name in _SECRET_KEYS or name.endswith(("_api_key", "_password", "_token", "_secret"))


def protect(value: str) -> str:
    if not value or value.startswith((_DPAPI, _KEYRING)):
        return value
    if sys.platform == "win32":
        import win32crypt
        blob = win32crypt.CryptProtectData(value.encode("utf-8"), _SERVICE, None, None, None, 1)
        return _DPAPI + base64.b64encode(blob).decode("ascii")
    try:
        import keyring
        backend = keyring.get_keyring()
        if backend.priority <= 0 or "keyrings.alt" in type(backend).__module__:
            raise RuntimeError("No secure system credential store is available")
        identifier = uuid.uuid4().hex
        keyring.set_password(_SERVICE, identifier, value)
        return _KEYRING + identifier
    except Exception as exc:
        raise RuntimeError("Cannot save credentials securely; configure the system keyring") from exc


def reveal(value: str) -> str:
    if value.startswith(_DPAPI):
        if sys.platform != "win32":
            raise RuntimeError("This credential belongs to a Windows user; enter it again on this system")
        import win32crypt
        blob = base64.b64decode(value[len(_DPAPI):], validate=True)
        return win32crypt.CryptUnprotectData(blob, None, None, None, 1)[1].decode("utf-8")
    if value.startswith(_KEYRING):
        import keyring
        plain = keyring.get_password(_SERVICE, value[len(_KEYRING):])
        if plain is None:
            raise RuntimeError("Credential not found in the system keyring")
        return plain
    return value


def decode_config(data):
    if isinstance(data, dict):
        return {key: decode_config(value) for key, value in data.items()}
    if isinstance(data, list):
        return [decode_config(value) for value in data]
    return reveal(data) if isinstance(data, str) else data


def encode_config(data):
    if isinstance(data, dict):
        return {key: protect(value) if _secret_key(key) and isinstance(value, str)
                else encode_config(value) for key, value in data.items()}
    if isinstance(data, list):
        return [encode_config(value) for value in data]
    return data
