"""
file_hash.py — publish / 検証で使う sha256 計算（PUBLISH-MEMORY-PRESSURE、2026-10-12）。

大きいファイル（routing GeoJSON・canonical・MBTiles 等）を順次読みしてハッシュすると、読んだ内容が page cache に
残り、VPS（メモリ約 4GB）では backend のページが swap へ追い出される。DROP_CACHE_THRESHOLD 以上のファイルは
読み終えた後に posix_fadvise(DONTNEED) で page cache を手放すよう kernel に伝える。

fadvise は performance hint であって correctness ではない: 失敗してもハッシュ値・検証結果には影響させない
（例外を出さず debug log のみ）。小さいファイル（manifest・provenance record 等）には行わない。
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DROP_CACHE_THRESHOLD = 16 << 20  # 16 MiB（実測: runtime の 1.63GB / 1.69GB が 16MB 以上の 20 file）
CHUNK = 1 << 20


def drop_page_cache(fd: int, path: "str | Path" = "") -> bool:
    """fd の page cache を手放すよう kernel に伝える。成否を返す（失敗しても例外にしない）。"""
    if not hasattr(os, "posix_fadvise"):
        return False
    try:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        return True
    except OSError as exc:  # pragma: no cover - kernel / filesystem 依存
        logger.debug("posix_fadvise(DONTNEED) failed: %s: %s", path, exc)
        return False


def sha256_file(path: "str | Path", chunk_size: int = CHUNK,
                drop_cache_threshold: "int | None" = DROP_CACHE_THRESHOLD) -> str:
    """ファイル全体の sha256。drop_cache_threshold 以上なら読了後に page cache を手放す（None で無効）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
        if drop_cache_threshold is not None and size >= drop_cache_threshold:
            drop_page_cache(f.fileno(), path)
    return h.hexdigest()
