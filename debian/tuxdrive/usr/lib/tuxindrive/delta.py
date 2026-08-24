from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BlockSignature:
    offset: int
    size: int
    digest: str


class BlockDeltaPlanner:
    """Content-addressed rolling-block planner used by direct peer jobs."""

    def __init__(self, block_size: int = 4 * 1024 * 1024) -> None:
        self.block_size = max(64 * 1024, block_size)

    def signatures(self, path: Path) -> list[BlockSignature]:
        signatures = []
        with path.open("rb") as handle:
            offset = 0
            while chunk := handle.read(self.block_size):
                signatures.append(BlockSignature(offset, len(chunk), hashlib.blake2b(chunk, digest_size=32).hexdigest()))
                offset += len(chunk)
        return signatures

    @staticmethod
    def changed(local: list[BlockSignature], remote: list[BlockSignature]) -> list[BlockSignature]:
        known = {(item.offset, item.size, item.digest) for item in remote}
        return [item for item in local if (item.offset, item.size, item.digest) not in known]

    @staticmethod
    def transferred_bytes(changed: list[BlockSignature]) -> int:
        return sum(item.size for item in changed)
