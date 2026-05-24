"""
Локальное хранение секретов приложения.

На Windows используется DPAPI с привязкой к текущему пользователю. На других
платформах значение кодируется с явным префиксом fallback, чтобы приложение не
ломалось, но это не считается полноценным шифрованием.
"""

import base64
import ctypes
import sys
from ctypes import wintypes


DPAPI_PREFIX = "dpapi:"
FALLBACK_PREFIX = "plain64:"


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _blob_from_bytes(data: bytes) -> DATA_BLOB:
    buffer = ctypes.create_string_buffer(data)
    blob = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob._buffer = buffer
    return blob


def _bytes_from_blob(blob: DATA_BLOB) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def _dpapi_encrypt(value: str) -> str:
    data_in = _blob_from_bytes(value.encode("utf-8"))
    data_out = DATA_BLOB()

    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(data_in),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(data_out),
    ):
        raise ctypes.WinError()

    try:
        encrypted = _bytes_from_blob(data_out)
        return DPAPI_PREFIX + base64.b64encode(encrypted).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(data_out.pbData)


def _dpapi_decrypt(value: str) -> str:
    encrypted = base64.b64decode(value[len(DPAPI_PREFIX):])
    data_in = _blob_from_bytes(encrypted)
    data_out = DATA_BLOB()

    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(data_in),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(data_out),
    ):
        raise ctypes.WinError()

    try:
        return _bytes_from_blob(data_out).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(data_out.pbData)


def protect_secret(value: str) -> str:
    value = value or ""
    if not value:
        return ""
    if value.startswith(DPAPI_PREFIX) or value.startswith(FALLBACK_PREFIX):
        return value
    if sys.platform == "win32":
        return _dpapi_encrypt(value)
    return FALLBACK_PREFIX + base64.b64encode(value.encode("utf-8")).decode("ascii")


def unprotect_secret(value: str) -> str:
    value = value or ""
    if not value:
        return ""
    if value.startswith(DPAPI_PREFIX):
        if sys.platform != "win32":
            return ""
        return _dpapi_decrypt(value)
    if value.startswith(FALLBACK_PREFIX):
        return base64.b64decode(value[len(FALLBACK_PREFIX):]).decode("utf-8")
    return value


def is_protected_secret(value: str) -> bool:
    value = value or ""
    return value.startswith(DPAPI_PREFIX) or value.startswith(FALLBACK_PREFIX)
