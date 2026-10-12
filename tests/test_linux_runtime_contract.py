"""
Linux 専用の runtime 契約一式（ROLLBACK-PORTABILITY-LINUX-CONTRACT、2026-10-12）。

atomic publish / rollback / mirror 整合 / required tile guard / 退役 / tile path 移行のテストのうち、Linux kernel の
renameat2(RENAME_NOREPLACE) と operator identity（uid 10002・supplemental gid 20001）を要するものは、macOS では
その場で実行できない（各テストは skip または Linux container へ委譲）。

その場で renameat2 が使えない環境では、このテストが scripts/test/run_linux_contract.sh で一式を Linux container
（named volume 上、operator identity）で 1 回実行し、全件 PASS（skip なし）でなければ失敗する。
その場で renameat2 が使える Linux では、一式は同じ regression の中で直接実行されるため委譲しない。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import linux_contract  # noqa: E402


def test_linux_runtime_contract_suite(tmp_path):
    if os.environ.get(linux_contract.INNER_ENV) == "1":
        pytest.fail("container 内でこの wrapper を実行しない（runner は一式を直接実行する）")
    capable, why = linux_contract.renameat2_capability(tmp_path)
    if capable:
        return  # 一式はこの環境で直接実行される
    evidence = linux_contract.run_in_linux_container([])
    assert evidence["identity"] == "10002:10002 + 20001"
    # fixture は Linux の filesystem（named volume）上。macOS との共有 mount（virtiofs・fuse 等）では判定しない
    assert evidence["mount"] and evidence["mount"].split()[2] in ("ext4", "xfs", "btrfs"), evidence
