#!/usr/bin/env python3
"""Reproducible local search-index benchmark; no provider credentials needed."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import time

from tuxindrive.models import SyncJob
from tuxindrive.search_index import FolderSearchIndex


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=2000)
    parser.add_argument("--content", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("dist/search-benchmark.json"))
    args = parser.parse_args()
    count = max(1, min(args.files, 100_000))
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "root"
        root.mkdir()
        for index in range(count):
            (root / f"document-{index:06d}.txt").write_text(
                f"TuxInDrive benchmark record {index}\n", encoding="utf-8"
            )
        database = Path(temporary) / "index.sqlite3"
        search = FolderSearchIndex(database, max_entries_per_job=count + 1)
        job = SyncJob(name="benchmark", account_remote="bench", local_path=str(root))
        started = time.perf_counter()
        stats = search.refresh((job,), include_content=args.content)
        indexed_seconds = time.perf_counter() - started
        started = time.perf_counter()
        matches = search.search("document-001")
        search_ms = (time.perf_counter() - started) * 1000
        result = {
            "schema": 1,
            "files": count,
            "content_indexing": args.content,
            "indexed": stats.indexed,
            "index_seconds": round(indexed_seconds, 6),
            "files_per_second": round(count / max(indexed_seconds, 0.000001), 2),
            "search_ms": round(search_ms, 3),
            "matches": len(matches),
            "database_bytes": database.stat().st_size,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
