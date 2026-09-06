"""
admin_metadata_fs.py — data_lake/admin/* runtime metadataのfile mode是正ヘルパー

Residual Finding Remediation 03 (DATA-LAKE-ADMIN-WRITER-CONTRACT):
data_lake/admin/{state,jobs,history,logs}配下のdirectoryをsetgid
（owner=operator, group=operator/leases, mode 2750）へ是正しても、
新規fileの実際のmodeはopen()呼び出し時のprocess umaskに依存するため、
directory側の是正だけでは新規fileが0644等の意図しないmodeで作られ続け、
contractが再度崩れる。write直後に明示的にchmodすることで、umask非依存に
target file mode（既定0640: owner rw, group r, other無し）を保証する。

chmod失敗時は例外を送出しない（write自体は既に成功しているため、mode是正の
失敗だけでcaller側の処理を止めない。既存の各serviceの「data_lakeが
read-only環境でもcrashさせない」設計方針と一貫させる）。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)

ADMIN_METADATA_FILE_MODE = 0o640


def chmod_quiet(path: Union[str, Path], mode: int = ADMIN_METADATA_FILE_MODE) -> None:
    """pathのmodeをmodeへ是正する。失敗しても例外を送出せず警告logのみ。"""
    try:
        os.chmod(path, mode)
    except OSError as exc:
        logger.warning("Failed to chmod %s to %o: %s", path, mode, exc)
