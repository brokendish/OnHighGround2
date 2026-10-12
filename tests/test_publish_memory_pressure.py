"""
PUBLISH-MEMORY-PRESSURE（2026-10-12）: publish 中の page cache 膨張と swap-out を抑える。

VPS で読み込み経路を単独実行して実測した主因（現行コード）:
  mirror 同期の cmp（current と mirror の MBTiles を全読み比較）  cached +673MB
  flood routing の検証 sha256（artifact_record）                    cached +105MB / +134MB
対策: 16 MiB 以上を読み終えたら posix_fadvise(DONTNEED)（hint。失敗しても検証結果は変えない）。
deploy の copy は coreutils 9 の cp が既定で reflink=auto（VPS: XFS reflink）であることを明示した。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import file_hash  # noqa: E402
from app.services import flood_routing_contract as frc  # noqa: E402


@pytest.fixture
def advised(monkeypatch):
    calls = []
    monkeypatch.setattr(os, "posix_fadvise", lambda fd, off, ln, adv: calls.append(adv), raising=False)
    monkeypatch.setattr(os, "POSIX_FADV_DONTNEED", 4, raising=False)
    return calls


def _file(tmp_path, n):
    p = tmp_path / f"f{n}"
    p.write_bytes(os.urandom(n))
    return p


def test_large_file_drops_cache_after_hash(tmp_path, advised, monkeypatch):
    monkeypatch.setattr(file_hash, "DROP_CACHE_THRESHOLD", 1 << 16)
    p = _file(tmp_path, 1 << 17)
    assert file_hash.sha256_file(p, drop_cache_threshold=file_hash.DROP_CACHE_THRESHOLD) == hashlib.sha256(p.read_bytes()).hexdigest()
    assert advised == [4]


def test_small_file_does_not_call_fadvise(tmp_path, advised):
    p = _file(tmp_path, 1024)
    assert file_hash.sha256_file(p) == hashlib.sha256(p.read_bytes()).hexdigest()
    assert advised == []


def test_default_threshold_is_16mib():
    assert file_hash.DROP_CACHE_THRESHOLD == 16 << 20


def test_fadvise_failure_does_not_change_result(tmp_path, monkeypatch):
    def boom(*a):
        raise OSError("EINVAL")
    monkeypatch.setattr(os, "posix_fadvise", boom, raising=False)
    monkeypatch.setattr(os, "POSIX_FADV_DONTNEED", 4, raising=False)
    p = _file(tmp_path, 1 << 17)
    assert file_hash.sha256_file(p, drop_cache_threshold=1) == hashlib.sha256(p.read_bytes()).hexdigest()


def test_routing_contract_hash_uses_helper(tmp_path, advised, monkeypatch):
    p = _file(tmp_path, 1 << 17)
    real = file_hash.sha256_file
    monkeypatch.setattr(file_hash, "sha256_file", lambda path, chunk=1 << 20: real(path, chunk, drop_cache_threshold=1))
    assert frc.sha256_file(p) == hashlib.sha256(p.read_bytes()).hexdigest()
    assert advised == [4]


def test_deploy_copy_is_explicit_reflink():
    sh = (ROOT / "scripts/publish/deploy_to_runtime.sh").read_text(encoding="utf-8")
    assert 'cp --reflink=auto "${src}" "${dst}" 2>/dev/null || cp "${src}" "${dst}"' in sh


def test_wrapper_logs_memory_per_phase():
    w = (ROOT / "scripts/publish/deploy_to_runtime_atomic.sh").read_text(encoding="utf-8")
    assert "_mem_sample()" in w and 'log_info "[memory] $1:' in w
    assert "/proc/meminfo" in w and "pswpout" in w


@pytest.mark.skipif(not shutil.which("bash"), reason="bash が無い")
def test_mirror_sync_unchanged_and_replaced_files(tmp_path):
    src, dst = tmp_path / "src" / "tiles", tmp_path / "dst" / "tiles"
    (src / "tokyo/flood").mkdir(parents=True)
    (dst / "tokyo/flood").mkdir(parents=True)
    same, changed = os.urandom(4096), os.urandom(4096)
    (src / "tokyo/flood/a.mbtiles").write_bytes(same)
    (dst / "tokyo/flood/a.mbtiles").write_bytes(same)
    (src / "tokyo/flood/b.mbtiles").write_bytes(changed)
    (dst / "tokyo/flood/b.mbtiles").write_bytes(os.urandom(4096))
    env = {**os.environ, "OHG2_LEASES_GID": str(os.getgid())}
    out = subprocess.run(["bash", str(ROOT / "scripts/publish/sync_frontend_tiles_mirror.sh"), str(src), str(dst)],
                         capture_output=True, text=True, env=env)
    assert "replaced=1 unchanged=1" in out.stdout + out.stderr, out.stdout + out.stderr
    assert (dst / "tokyo/flood/b.mbtiles").read_bytes() == changed
    assert (dst / "tokyo/flood/a.mbtiles").read_bytes() == same


def test_mirror_sync_drops_cache_for_large_tiles_only():
    sh = (ROOT / "scripts/publish/sync_frontend_tiles_mirror.sh").read_text(encoding="utf-8")
    assert "(( size >= 16777216 )) || return 0" in sh and "iflag=nocache count=0" in sh
    i_cmp = sh.index('&& cmp -s -- "${f}" "${target}"; then')
    assert sh.index('_drop_cache_if_large "${f}"; _drop_cache_if_large "${target}"', i_cmp) < sh.index("unchanged=$((unchanged + 1))", i_cmp)
    assert 'cp --reflink=auto -- "${f}" "${tmp}" 2>/dev/null || cp -- "${f}" "${tmp}"' in sh
