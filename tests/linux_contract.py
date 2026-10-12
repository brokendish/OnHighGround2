"""
Linux 専用の runtime 契約テストの振り分け（ROLLBACK-PORTABILITY-LINUX-CONTRACT、2026-10-12）。

本番の atomic publish は Linux の renameat2(RENAME_NOREPLACE) に依存する（backend/app/services/runtime_atomic.py）。
macOS には無く、macOS 用の代替実装は作らない。テストは次のように振り分ける:

  - その場で renameat2(RENAME_NOREPLACE) が実際に動く（Linux kernel + 対応 filesystem）→ テスト本体をそのまま実行
  - 動かない（macOS 等）→ scripts/test/run_linux_contract.sh で同じテストを Linux container 内で実行し、
    その結果をこのテストの結果にする（container 内の失敗・skip はこちらの失敗になる）
  - container 内（OHG2_LINUX_CONTRACT_INNER=1）で動かない → 失敗（再委譲しない）
  - Docker / base image が無い → 失敗（「Linux formal runner required」）。skip にはしない

判定は OS 名ではなく、実際に renameat2 を呼んで確かめる（Linux でも kernel・filesystem によっては使えない）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "test" / "run_linux_contract.sh"
INNER_ENV = "OHG2_LINUX_CONTRACT_INNER"
EVIDENCE_PREFIX = "LINUX_CONTRACT_EVIDENCE "


def renameat2_capability(directory: Path) -> Tuple[bool, str]:
    """directory 上で renameat2(RENAME_NOREPLACE) が動き、既存の置き換え先を拒否するか。"""
    sys.path.insert(0, str(ROOT / "backend"))
    from app.services.runtime_atomic import RuntimeAtomicError, open_dir_fd, renameat2_noreplace

    d = tempfile.mkdtemp(prefix=".renameat2-probe-", dir=str(directory))
    try:
        for n in ("a", "b"):
            Path(d, n).write_text(n)
        with open_dir_fd(Path(d)) as fd:
            renameat2_noreplace(fd, "a", fd, "c")
            try:
                renameat2_noreplace(fd, "b", fd, "c")
            except FileExistsError:
                return True, "renameat2(RENAME_NOREPLACE) が使える"
            return False, "RENAME_NOREPLACE が既存の置き換え先を上書きした"
    except RuntimeAtomicError as exc:
        return False, str(exc)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def run_in_linux_container(nodeids, timeout: int = 1800) -> dict:
    """nodeids を Linux container 内で実行し、全件 PASS（skip なし）でなければ失敗させる。evidence を返す。
    nodeids が空なら runner の Linux 契約一式（scripts/test/run_linux_contract.sh の DEFAULT_TESTS）を実行する。"""
    if os.environ.get(INNER_ENV) == "1":
        pytest.fail("Linux container 内で renameat2(RENAME_NOREPLACE) が使えない（再委譲しない）")
    if not shutil.which("docker"):
        pytest.fail("Linux formal runner required: docker が無い（scripts/test/run_linux_contract.sh を Linux container で実行する）")
    r = subprocess.run(["bash", str(RUNNER), *nodeids], capture_output=True, text=True, timeout=timeout)
    out = r.stdout + r.stderr
    line = next((l for l in reversed(r.stdout.splitlines()) if l.startswith(EVIDENCE_PREFIX)), None)
    assert r.returncode == 0 and line, f"Linux formal runner が失敗（exit {r.returncode}）:\n{out[-4000:]}"
    evidence = json.loads(line[len(EVIDENCE_PREFIX):])
    summary = evidence["summary"]
    assert evidence["result"] == "PASS" and evidence["renameat2_noreplace"] is True, evidence
    assert evidence["uname"].startswith("Linux "), evidence
    count = str(len(nodeids)) if nodeids and all("::" in n for n in nodeids) else "[1-9][0-9]*"
    assert re.fullmatch(rf"{count} passed in [0-9.]+s( \([0-9:]+\))?", summary.strip("= ")), \
        f"container 内で全件 PASS していない（skip も不可）: {summary}\n{out[-4000:]}"
    print(EVIDENCE_PREFIX + json.dumps(evidence, ensure_ascii=False))
    return evidence


def run_natively_or_in_linux(test_file: str, test_name: str, tmp_path: Path) -> bool:
    """その場で renameat2 が使えるなら True（呼び出し側がテスト本体を実行する）。
    使えなければ同じテストを Linux container 内で実行して False を返す（本体はここでは実行しない）。"""
    capable, why = renameat2_capability(tmp_path)
    if capable:
        return True
    nodeid = f"{Path(test_file).resolve().relative_to(ROOT)}::{test_name}"
    print(f"renameat2 をここで使えない（{why}）。Linux container で実行する: {nodeid}")
    run_in_linux_container([nodeid])
    return False
