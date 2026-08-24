"""Bounded, integrity-checked multi-frame QR transport for encrypted profiles."""

from __future__ import annotations

import base64
import hashlib
import zlib


QR_PREFIX = "TUXINDRIVE-PROFILE"
QR_VERSION = "1"
QR_CHUNK_SIZE = 1400
QR_MAX_FRAMES = 256
QR_MAX_PROFILE_SIZE = 2 * 1024 * 1024


class ProfileQrError(ValueError):
    pass


def encode_profile_frames(data: bytes, chunk_size: int = QR_CHUNK_SIZE) -> list[str]:
    if not data or len(data) > QR_MAX_PROFILE_SIZE:
        raise ProfileQrError("The mobile profile must be between 1 byte and 2 MiB")
    if not 256 <= chunk_size <= QR_CHUNK_SIZE:
        raise ProfileQrError("The QR chunk size is outside the supported range")
    compressed = zlib.compress(data, level=9)
    encoded = base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")
    chunks = [encoded[index:index + chunk_size] for index in range(0, len(encoded), chunk_size)]
    if not chunks or len(chunks) > QR_MAX_FRAMES:
        raise ProfileQrError("The encrypted profile is too large for QR transfer; use the .tdx file")
    digest = hashlib.sha256(data).hexdigest()
    transfer_id = digest[:16]
    total = len(chunks)
    return [
        f"{QR_PREFIX}/{QR_VERSION}/{transfer_id}/{index}/{total}/{digest}/{chunk}"
        for index, chunk in enumerate(chunks, start=1)
    ]


def decode_profile_frames(frames: list[str]) -> bytes:
    chunks: dict[int, str] = {}
    identity: tuple[str, int, str] | None = None
    for frame in frames:
        parts = frame.split("/", 6)
        if len(parts) != 7 or parts[:2] != [QR_PREFIX, QR_VERSION]:
            raise ProfileQrError("This is not a TuxInDrive profile QR frame")
        transfer_id, index_text, total_text, digest, chunk = parts[2:]
        try:
            index, total = int(index_text), int(total_text)
        except ValueError as exc:
            raise ProfileQrError("The profile QR sequence is invalid") from exc
        if (
            len(transfer_id) != 16 or any(value not in "0123456789abcdef" for value in transfer_id)
            or len(digest) != 64 or any(value not in "0123456789abcdef" for value in digest)
            or total not in range(1, QR_MAX_FRAMES + 1) or index not in range(1, total + 1)
            or not chunk or len(chunk) > QR_CHUNK_SIZE
            or any(value not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for value in chunk)
        ):
            raise ProfileQrError("The profile QR frame is outside the safety limits")
        current = (transfer_id, total, digest)
        if identity is None:
            identity = current
        elif current != identity:
            raise ProfileQrError("The QR frames belong to different profile transfers")
        chunks[index] = chunk
    if identity is None or len(chunks) != identity[1]:
        raise ProfileQrError("Not all profile QR frames were provided")
    encoded = "".join(chunks[index] for index in range(1, identity[1] + 1))
    try:
        compressed = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        inflater = zlib.decompressobj()
        data = inflater.decompress(compressed, QR_MAX_PROFILE_SIZE + 1)
        data += inflater.flush(max(1, QR_MAX_PROFILE_SIZE + 1 - len(data)))
    except (ValueError, zlib.error) as exc:
        raise ProfileQrError("The profile QR data is invalid") from exc
    if len(data) > QR_MAX_PROFILE_SIZE or not inflater.eof:
        raise ProfileQrError("The QR profile exceeds the 2 MiB safety limit")
    digest = hashlib.sha256(data).hexdigest()
    if digest != identity[2] or not digest.startswith(identity[0]):
        raise ProfileQrError("The profile QR transfer failed its integrity check")
    return data
