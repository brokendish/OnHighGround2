"""
test_deploy_to_runtime_regression.py — Dual Storage Remediation Phase C1
(ATOMIC-PUBLISH-COVERAGE-GAP) 回帰テスト。

deploy_to_runtime.sh の変更は
「backend: hazard / flood, storm_surge, pseudo_inland_flood」ブロックのみに
限定されており、既存4type（tsunami/inland_flood/landslide/
lowland_poor_drainage）およびshelter/frontend部分は一切変更していないことを
保証する。OWNER Section 11「既存4typeを壊さない」を機械的に検証する回帰テスト。

比較方法: gitの直前コミット（HEAD、= このremediation前の状態）と現在の
working treeで、"backend: hazard / tsunami" セクション見出し行以降を
完全一致で比較する。この見出し以降には今回のresolver化対象
（flood/storm_surge/pseudo_inland_flood）が一切含まれないため、
1行でも差分があれば既存ロジックへの意図しない影響を意味する。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "publish" / "deploy_to_runtime.sh"
TSUNAMI_MARKER = "# ─── backend: hazard / tsunami"


def _lines_from(text: str, marker: str) -> list[str]:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(marker):
            return lines[i:]
    raise AssertionError(f"marker not found: {marker!r}")


def _git_show_head() -> str:
    rel = SCRIPT_PATH.relative_to(REPO_ROOT)
    result = subprocess.run(
        ["git", "show", f"HEAD:{rel.as_posix()}"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    return result.stdout


def test_existing_4type_and_shelter_blocks_are_byte_identical_to_head():
    head_text = _git_show_head()
    working_text = SCRIPT_PATH.read_text(encoding="utf-8")

    head_tail = _lines_from(head_text, TSUNAMI_MARKER)
    working_tail = _lines_from(working_text, TSUNAMI_MARKER)

    assert working_tail == head_tail, (
        "tsunami以降（tsunami/inland_flood/landslide/lowland_poor_drainage/"
        "shelters/frontend/manifest）のブロックがHEADから変更されています。"
        "Phase C1のscopeはflood/storm_surge/pseudo_inland_flood部分のみです。"
    )
