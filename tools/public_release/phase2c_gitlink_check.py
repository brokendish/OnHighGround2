#!/usr/bin/env python3
"""
Phase 2-C AT-15 — tracked gitlink除去の一時clean-clone検証。

tasks/public-release/phase2c_claude_implementation_instruction.md 第7節の
手順1〜6をそのまま自動化する。元repository（このscriptを実行しているworking
directory）へは一切書き込まない: 元repoの内容を `git clone --no-local` で
一時directoryへ複製し、その複製内だけでgitlink除去の一時commitを作り、
さらにその複製をもう一段cloneして「clean cloneにgitlinkが存在しない」ことを
確認する。一時repository・一時commit・一時authorは元repositoryへ一切
持ち込まない（使い終わったら両方とも削除する）。

このscriptは「元repositoryのworking treeに、対象gitlinkがすでに
`git rm --cached` 済みで`.gitignore`に`.claude/worktrees/`が追加されている」
状態、または「まだ元のgitlinkが残っている」状態のどちらでも実行できる:
前者の場合は現在のworking tree差分（indexの状態）をそのまま一時repoへ
持ち込んで検証し、後者の場合はこのscript自身が一時repo内でgitlink除去と
.gitignore追記を行ってから検証する。

終了コード: 0 = AT-15 PASS, 1 = AT-15 FAIL, 2 = 実行時エラー（前提条件不備等）。

実行:
    python3 tools/public_release/phase2c_gitlink_check.py
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

GITLINK_PATH = ".claude/worktrees/practical-villani-c3d420"
GITIGNORE_RULE = ".claude/worktrees/"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(cmd, cwd, check=True, capture=True):
    proc = subprocess.run(
        cmd, cwd=str(cwd), capture_output=capture, text=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(cmd)} (cwd={cwd})\n"
            f"stdout={proc.stdout}\nstderr={proc.stderr}"
        )
    return proc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", default=str(REPO_ROOT),
        help="検証対象の元repository（既定: このscriptを含むrepo）",
    )
    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve()

    head_sha = _run(["git", "rev-parse", "HEAD"], cwd=repo_root).stdout.strip()
    print(f"[phase2c_gitlink_check] repo_root={repo_root} HEAD={head_sha}")

    tmp_base = Path(tempfile.mkdtemp(prefix="ohg2p2c_glk_"))
    temp1 = tmp_base / "temp1"
    temp2 = tmp_base / "temp2"
    result = 2
    try:
        _run(["git", "clone", "--quiet", "--no-local", f"file://{repo_root}", str(temp1)], cwd=repo_root)
        actual_head = _run(["git", "rev-parse", "HEAD"], cwd=temp1).stdout.strip()
        print(f"[phase2c_gitlink_check] temp1 cloned at HEAD={actual_head}")

        # gitlinkがまだtemp1のindexに残っていれば、このscriptが除去する
        ls_files = _run(["git", "ls-files", "-s", GITLINK_PATH], cwd=temp1).stdout.strip()
        if ls_files:
            print(f"[phase2c_gitlink_check] temp1: removing tracked gitlink {GITLINK_PATH}")
            _run(["git", "rm", "--cached", GITLINK_PATH], cwd=temp1)
            gitignore_path = temp1 / ".gitignore"
            existing = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
            if GITIGNORE_RULE not in existing:
                with gitignore_path.open("a", encoding="utf-8") as f:
                    f.write(f"\n{GITIGNORE_RULE}\n")
            _run(["git", "add", ".gitignore"], cwd=temp1)
            _run(
                [
                    "git", "-c", "user.email=phase2c-glk-check@local",
                    "-c", "user.name=Phase2C GLK Check",
                    "commit", "--quiet", "-m",
                    "TEMPORARY: Phase 2-C AT-15 gitlink removal check (not pushed, not merged)",
                ],
                cwd=temp1,
            )
        else:
            print("[phase2c_gitlink_check] temp1: gitlink already absent from index (already fixed upstream)")

        mode_count_1 = _run(["git", "ls-tree", "-r", "HEAD"], cwd=temp1).stdout.count("160000")
        print(f"[phase2c_gitlink_check] temp1 HEAD mode-160000 entries: {mode_count_1}")

        _run(["git", "clone", "--quiet", "--no-local", f"file://{temp1}", str(temp2)], cwd=tmp_base)
        mode_count_2 = _run(["git", "ls-tree", "-r", "HEAD"], cwd=temp2).stdout.count("160000")
        submodule_status = _run(["git", "submodule", "status"], cwd=temp2, check=False)
        tracked_worktree = _run(["git", "ls-files"], cwd=temp2).stdout
        gitignore_has_rule = GITIGNORE_RULE in (temp2 / ".gitignore").read_text(encoding="utf-8")

        print(f"[phase2c_gitlink_check] temp2 (clean clone of temp1) mode-160000 entries: {mode_count_2}")
        print(f"[phase2c_gitlink_check] temp2 submodule status exit={submodule_status.returncode} "
              f"stdout={submodule_status.stdout!r} stderr={submodule_status.stderr!r}")
        print(f"[phase2c_gitlink_check] temp2 .gitignore contains {GITIGNORE_RULE!r}: {gitignore_has_rule}")

        final_head = _run(["git", "rev-parse", "HEAD"], cwd=repo_root).stdout.strip()
        original_repo_unchanged = final_head == head_sha
        print(f"[phase2c_gitlink_check] original repo HEAD before={head_sha} after={final_head}")

        # 全6 checkを単一dictへ先にまとめてから一度だけloopで出力する
        # （個別checkを都度printすると、機械的にparseするtoolがcheck名の
        # 網羅漏れ・出力形式のずれに気付けない——実際、旧実装は
        # `original_repo_head_unchanged`をこのdictへ後から追加しており、
        # 直前のloopでは出力されない構造的bugがあった）。
        checks = {
            "temp1_head_zero_mode_160000": mode_count_1 == 0,
            "temp2_clean_clone_zero_mode_160000": mode_count_2 == 0,
            "temp2_submodule_status_no_error": submodule_status.returncode == 0,
            "temp2_worktree_path_not_tracked": GITLINK_PATH not in tracked_worktree,
            "temp2_gitignore_has_rule": gitignore_has_rule,
            "original_repo_head_unchanged": original_repo_unchanged,
        }
        for name, ok in checks.items():
            print(f"[phase2c_gitlink_check] {name}: {'PASS' if ok else 'FAIL'}")

        result = 0 if all(checks.values()) else 1
    finally:
        shutil.rmtree(tmp_base, ignore_errors=True)
        print(f"[phase2c_gitlink_check] cleaned up {tmp_base}")

    # 個別check（`<name>: PASS/FAIL`形式）と機械的に区別できるよう、
    # 総合summary行は`=`区切りで出力する（":"区切りではないため、
    # `<name>: PASS/FAIL`をparseするtoolが7件目の偽checkとして誤検出しない）。
    print(f"[phase2c_gitlink_check] AT-15 overall = {'PASS' if result == 0 else 'FAIL'}")
    return result


if __name__ == "__main__":
    sys.exit(main())
