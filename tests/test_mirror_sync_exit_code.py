"""
MIRROR-SYNC-EXIT-CODE（KTF-002、2026-10-12）: sync_frontend_tiles_mirror.sh の終了コードは同期の結果（primary）で決まり、
一時 file の後始末（cleanup）の失敗で上書きされない。

旧実装は cp / rename の失敗時に `rm -f -- "${tmp}"; log_warn ...; exit 2` としていた。operator が traverse できない
directory では rm も失敗し、set -euo pipefail によりその場で exit 1 になっていた（契約は exit 2、warning も出ない）。
現在は EXIT trap が後始末し、その結果は warning（path・rc）として残す。

  A. 同期成功・後始末なし                     → 0（一時 file は残らない）
  B. 同期失敗（exit 2）・後始末成功           → 2（一時 file は消える）
  C. 同期失敗（exit 2）・後始末失敗           → 2（後始末の失敗は path と rc を warning に残す）
  D. 同期成功・後始末失敗                     → 2（成功扱いにしない。契約の「同期自体に失敗」）
  E. 予期しない失敗（exit 1）・後始末失敗     → 1
  後始末は、この script が作る名前（dst 配下の .<name>.syncing-<pid>）以外と symlink を消さない（fail closed）。
cp / mv の失敗は PATH 先頭の spy で起こす。後始末の失敗は、spy が一時 file の位置に symlink を置いて起こす
（root でも再現できる）。実際の権限（traverse できない directory）での再現は
tests/test_runtime_mbtiles_group_contract.py の権限 matrix（Docker）が担う。
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/publish/sync_frontend_tiles_mirror.sh"
GID = os.getgid()
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash が無い")


def _spy(tmp_path: Path, name: str, body: str) -> Path:
    d = tmp_path / f"spy-{name}"
    d.mkdir()
    (d / name).write_text("#!/bin/bash\n" + body)
    (d / name).chmod(0o755)
    return d


def _run(src: Path, dst: Path, spy: Path | None = None):
    env = {**os.environ, "OHG2_LEASES_GID": str(GID)}
    if spy is not None:
        env["PATH"] = f"{spy}:{env['PATH']}"
    return subprocess.run([BASH, str(SCRIPT), str(src), str(dst)], capture_output=True, text=True, env=env)


def _tree(tmp_path: Path):
    src, dst = tmp_path / "current" / "tiles", tmp_path / "mirror" / "tiles"
    (src / "tokyo/flood").mkdir(parents=True)
    (dst / "tokyo/flood").mkdir(parents=True)
    (src / "tokyo/flood/a.mbtiles").write_bytes(b"A" * 4096)
    (dst / "tokyo/flood/a.mbtiles").write_bytes(b"A" * 4096)       # 同一内容（unchanged）
    (src / "tokyo/flood/b.mbtiles").write_bytes(b"NEW" * 1000)
    (dst / "tokyo/flood/b.mbtiles").write_bytes(b"OLD" * 1000)     # 置き換え対象
    (dst / "tokyo/flood/keep.mbtiles").write_bytes(b"K" * 100)     # source に無い既存 file（追加専用で残す）
    return src, dst


def _leftovers(dst: Path):
    return sorted(str(p.relative_to(dst)) for p in dst.rglob("*.syncing-*"))


# 一時 file（cp の最後の引数）に部分的な file を作ってから失敗する cp
CP_PARTIAL_FAIL = 'for a in "$@"; do :; done; printf partial > "$a"; exit 1\n'
# 一時 file の位置に symlink（外部の victim を指す）を置いてから失敗する cp → 後始末は symlink を消さない
CP_SYMLINK_FAIL = 'for a in "$@"; do :; done; ln -sfn "$VICTIM" "$a"; exit 1\n'


def test_A_success_returns_0_and_leaves_no_temp(tmp_path):
    src, dst = _tree(tmp_path)
    r = _run(src, dst)
    assert r.returncode == 0, r.stderr
    assert (dst / "tokyo/flood/b.mbtiles").read_bytes() == b"NEW" * 1000
    assert (dst / "tokyo/flood/keep.mbtiles").read_bytes() == b"K" * 100
    assert _leftovers(dst) == []
    assert "replaced=1 unchanged=1" in r.stdout
    assert "後始末" not in r.stderr


def test_B_cp_failure_with_cleanup_success_returns_2(tmp_path):
    src, dst = _tree(tmp_path)
    r = _run(src, dst, _spy(tmp_path, "cp", CP_PARTIAL_FAIL))
    assert r.returncode == 2, r.stderr
    assert "cp 同期に失敗" in r.stderr
    assert "後始末に失敗" not in r.stderr and "削除しない" not in r.stderr
    assert _leftovers(dst) == []                                       # 部分 file は消えている
    assert (dst / "tokyo/flood/b.mbtiles").read_bytes() == b"OLD" * 1000   # 最終名は旧内容のまま
    assert (dst / "tokyo/flood/a.mbtiles").read_bytes() == b"A" * 4096
    assert (dst / "tokyo/flood/keep.mbtiles").read_bytes() == b"K" * 100


def test_B_rename_failure_with_cleanup_success_returns_2(tmp_path):
    src, dst = _tree(tmp_path)
    r = _run(src, dst, _spy(tmp_path, "mv", "exit 1\n"))
    assert r.returncode == 2, r.stderr
    assert "rename に失敗" in r.stderr
    assert "後始末に失敗" not in r.stderr
    assert _leftovers(dst) == []
    assert (dst / "tokyo/flood/b.mbtiles").read_bytes() == b"OLD" * 1000


def test_C_cp_failure_with_cleanup_failure_keeps_2_and_logs(tmp_path, monkeypatch):
    src, dst = _tree(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("do not touch")
    monkeypatch.setenv("VICTIM", str(victim))
    r = _run(src, dst, _spy(tmp_path, "cp", CP_SYMLINK_FAIL))
    assert r.returncode == 2, r.stderr                                 # 旧実装の exit 1 にならない
    assert "cp 同期に失敗" in r.stderr
    left = _leftovers(dst)
    assert len(left) == 1 and (dst / left[0]).is_symlink()             # symlink は消さない（fail closed）
    assert victim.read_text() == "do not touch"
    assert "symlink のため削除しない" in r.stderr and left[0].split("/")[-1] in r.stderr
    assert "後始末に失敗（rc=" in r.stderr                             # cleanup の rc を残す
    assert "終了コードは同期の結果 rc=2" in r.stderr
    assert (dst / "tokyo/flood/b.mbtiles").read_bytes() == b"OLD" * 1000


def _sourced(tmp_path: Path, body: str):
    """script を source して関数だけを読み込み、EXIT trap の判定を直接確かめる（D・E は通常の流れでは起きない）。"""
    dst = tmp_path / "mirror"
    dst.mkdir(exist_ok=True)
    victim = tmp_path / "victim.txt"
    victim.write_text("do not touch")
    prog = (f'source "{SCRIPT}"\n'
            f'dst="{dst}"\n'
            f'_inflight_tmp="{dst}/.x.mbtiles.syncing-$$"\n'
            f'ln -s "{victim}" "$_inflight_tmp"\n'
            "trap _on_exit EXIT\n" + body)
    r = subprocess.run([BASH, "-c", prog], capture_output=True, text=True,
                       env={**os.environ, "OHG2_LEASES_GID": str(GID)})
    return r, victim


def test_D_success_with_cleanup_failure_is_not_success(tmp_path):
    r, victim = _sourced(tmp_path, "exit 0\n")
    assert r.returncode == 2, r.stderr
    assert "symlink のため削除しない" in r.stderr and "後始末に失敗（rc=" in r.stderr
    assert victim.read_text() == "do not touch"


def test_E_unexpected_failure_with_cleanup_failure_keeps_1(tmp_path):
    r, _ = _sourced(tmp_path, "exit 1\n")
    assert r.returncode == 1, r.stderr
    assert "後始末に失敗（rc=" in r.stderr and "終了コードは同期の結果 rc=1" in r.stderr


def test_final_rc_priority():
    prog = f'source "{SCRIPT}"\nfor p in "0 0" "0 1" "0 3" "2 0" "2 1" "1 1" "4 1"; do set -- $p; printf "%s " "$(_final_rc "$1" "$2")"; done\n'
    r = subprocess.run([BASH, "-c", prog], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["0", "2", "2", "2", "2", "1", "4"]


@pytest.mark.parametrize("name", [
    "outside",                                  # dst の外
    "mirror/tiles/tokyo/flood/b.mbtiles",       # 一時名でない（最終名）
    "mirror/tiles/tokyo/../flood/.b.mbtiles.syncing-PID",   # .. を含む
    "mirror/tiles/tokyo/flood/.b.mbtiles.syncing-1",        # 別 process の一時名
])
def test_cleanup_refuses_unexpected_paths(tmp_path, name):
    dst = tmp_path / "mirror" / "tiles"
    (dst / "tokyo/flood").mkdir(parents=True)
    (tmp_path / "outside").write_text("x")
    (dst / "tokyo/flood/b.mbtiles").write_text("x")
    prog = (f'source "{SCRIPT}"\nset +e\ndst="{dst}"\n'
            f'p="{tmp_path}/{name}"; p="${{p//PID/$$}}"\n'
            '_cleanup_tmp "$p"; echo "rc=$?"\n')
    r = subprocess.run([BASH, "-c", prog], capture_output=True, text=True)
    assert "rc=3" in r.stdout, r.stdout + r.stderr
    assert "削除しない" in r.stderr
    assert (tmp_path / "outside").exists() and (dst / "tokyo/flood/b.mbtiles").exists()


def test_static_contract_unchanged():
    sh = SCRIPT.read_text(encoding="utf-8")
    code = "\n".join(l for l in sh.splitlines() if not l.lstrip().startswith("#"))
    # 後始末を `|| true` で握りつぶさない・失敗分岐で直接 rm しない
    assert 'rm -f -- "${tmp}"; log_warn' not in code
    assert not [l for l in code.splitlines() if "rm -f" in l and "|| true" in l]
    # caller（deploy_to_runtime_atomic.sh）の解釈は不変: 0 成功 / 4 fail-loud / それ以外 warning
    caller = (ROOT / "scripts/publish/deploy_to_runtime_atomic.sh").read_text(encoding="utf-8")
    assert '[[ "${MIRROR_EXIT_CODE}" -eq 0 ]]' in caller and '[[ "${MIRROR_EXIT_CODE}" -eq 4 ]]' in caller
