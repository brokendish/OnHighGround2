"""
mbtiles_install.py — Martin が監視する directory へ MBTiles を安全に配置する。

Martin 1.14 は `config/martin*.yaml` の mbtiles.paths（data_runtime/frontend/tiles/<region>/<type>）を
監視し、`*.mbtiles` の出現・変更で source を自動 reload する。そこへ直接書き込むと、

  - 生成中の `<name>.mbtiles.tmp.mbtiles`（tippecanoe 出力）を source として掴み SQLITE_BUSY
  - 上書きコピー途中の file を reload して `database disk image is malformed`

が起きる（Local 実機ログで確認）。本モジュールは、

  1. 同じ directory に Martin が拾わない一時名（`.<name>.partial-<pid>`、拡張子が .mbtiles でない）でコピー
  2. fsync、mode / group を contract（file 0640 / group leases gid）へ設定
  3. SQLite quick_check（malformed を公開しない）
  4. os.replace で最終名へ atomic rename、directory を fsync

の順に配置する。途中で失敗した場合は一時 file を消し、既存の最終 file は変更しない。
"""
from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path
from typing import Optional

MBTILES_FILE_MODE = 0o640
MBTILES_DIR_MODE = 0o750


class MbtilesInstallError(Exception):
    pass


def quick_check(path: Path) -> None:
    """SQLite quick_check と MBTiles 必須 table の存在を確認する。不正なら MbtilesInstallError。"""
    try:
        conn = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
        try:
            result = conn.execute("PRAGMA quick_check").fetchone()
            if not result or result[0] != "ok":
                raise MbtilesInstallError(f"quick_check failed: {path}: {result}")
            names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
            if not {"metadata", "tiles"} <= names:
                raise MbtilesInstallError(f"MBTiles の metadata/tiles がありません: {path}")
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise MbtilesInstallError(f"SQLite として読めません: {path}: {exc}") from exc


def _fsync_dir(directory: Path) -> None:
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def same_content(a: Path, b: Path) -> bool:
    """サイズと内容が一致するか（一致すれば再配置しない＝Martin の不要な reload を避ける）。"""
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
    except OSError:
        return False
    with a.open("rb") as fa, b.open("rb") as fb:
        while True:
            ca, cb = fa.read(1 << 20), fb.read(1 << 20)
            if ca != cb:
                return False
            if not ca:
                return True


def install_mbtiles(src: Path, dest: Path, group_id: Optional[int] = None,
                    file_mode: int = MBTILES_FILE_MODE) -> bool:
    """src を dest へ atomic に配置する。内容が同一なら何もしない（False を返す）。配置したら True。"""
    src, dest = Path(src), Path(dest)
    quick_check(src)
    missing = []
    parent = dest.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    dest.parent.mkdir(parents=True, exist_ok=True)
    for d in reversed(missing):  # 新規作成した directory にも contract（0750 / leases gid）を適用
        os.chmod(d, MBTILES_DIR_MODE)
        if group_id is not None:
            os.chown(d, -1, group_id)
    if dest.exists() and same_content(src, dest):
        # 内容は同一: 再コピーしない（Martin の reload を起こさない）。mode/group だけ contract へ揃える
        # （旧 tile build が operator の primary group で作った file を backend-public が読めるようにする）。
        st = dest.stat()
        if (st.st_mode & 0o777) != file_mode:
            os.chmod(dest, file_mode)
        if group_id is not None and st.st_gid != group_id:
            os.chown(dest, -1, group_id)
        return False
    tmp = dest.parent / f".{dest.name}.partial-{os.getpid()}"
    try:
        with src.open("rb") as fsrc, tmp.open("wb") as fdst:
            shutil.copyfileobj(fsrc, fdst, 1 << 20)
            fdst.flush()
            os.fsync(fdst.fileno())
        os.chmod(tmp, file_mode)
        if group_id is not None:
            os.chown(tmp, -1, group_id)
        quick_check(tmp)
        os.replace(tmp, dest)
        _fsync_dir(dest.parent)
        return True
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
