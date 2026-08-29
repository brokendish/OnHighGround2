#!/usr/bin/env python3
"""
phase2d_release_delta_manifest.py — release delta manifest生成（Phase 2-D Round 3、
指示書第4節）。

AT-17が再現すべきものはHEADではなく、現在のPhase 2-A〜2-D release candidateである
（指示書第3.1節）。本moduleはPhase名ごとの手作業path listを合成せず、Git状態と
public build input rootsから機械的にcandidateを抽出し、全entryを明示分類する。

対象repository（`repo_root`）は呼び出し側が指定する。source repositoryを一切変更
しない（`git status` / `git diff` / `git cat-file` / `git ls-files` / `git rev-parse`
のみを読み取り専用で実行する）。呼び出し側がself-test用のrepo-external fixture
repositoryを指すことで、この module自体をsource repositoryへ触れずに検証できる。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

SCHEMA_VERSION = 1

REPO_ROOT = Path(__file__).resolve().parents[2]

# --- 指示書第4.3節: release roots（機械的抽出のためのprefix集合。「少なくとも」なので
# 実際のbuild input（例: operator/ — docker-compose.ymlのadmin service volume mount先）
# を追加してよい。追加は本ファイルのdocstringおよび実装報告書で明示する。) ---
DIRECTORY_RELEASE_ROOTS = (
    "backend/",
    "frontend/",
    "scripts/",
    "tools/public_release/",
    "docs/",
    "tests/fixtures/",
    "e2e/",  # 拡張: Playwright E2E spec（playwright.config.js が参照する実際のtest input）
    "operator/",  # 拡張: docker-compose.yml が ./operator/frontend-admin, ./operator/nginx.conf を直接mountする実際のbuild input
    "config/",  # 拡張（Phase 2-D Round 7、CODEX round 6再検証finding対応）:
                # docker-compose.yml が ./config を /config としてMartinへ直接
                # mountする実際のruntime config input（config/martin.yaml
                # 本体は既にtracked・変更なしのためこれまで一度もmanifestの
                # 対象にならず、root未定義という欠陥が露呈していなかった。
                # config/martin.demo.yaml新規追加で顕在化した）。
    "data/",
    "data_lake/",
    "data_runtime/",
)

# Phase 2-D Round 8（P2D-OSRM-FIXTURE-CONTAMINATION対応、指示書第5節）:
# tests/fixtures/osm_demo/ はOSRMのsource入力（.osm.pbf）とMANIFEST.jsonだけを
# 保持する「read-only source fixture」であるべきだが、Round 6のdemo Compose設計は
# osrm-driving/osrm-walking containerがこのdirectoryを直接rwでmountしていたため、
# osrm-extract/partition/customizeの出力（.osrm*、54 file）がsource fixture配下へ
# 書き込まれ、Round 7 candidateへ混入した（CODEX round 7実測）。この汚染は
# `.gitignore`でGit statusから見えなくなっても実体としてfixture配下に残り得るため、
# git状態に依存しないfilesystem直接scanで検出し、1件でも存在すればcandidate生成
# そのものをfail-closedで停止する（OWNER承認の可否とは独立した、常時有効なgate）。
OSRM_RUNTIME_ARTIFACT_FIXTURE_ROOTS = ("tests/fixtures/osm_demo/",)
OSRM_RUNTIME_ARTIFACT_FILENAME_PATTERN = re.compile(r"\.osrm(\.|$)")


def scan_osrm_runtime_contamination(repo_root: Path) -> list[str]:
    """OSRM_RUNTIME_ARTIFACT_FIXTURE_ROOTS配下に`.osrm`/`.osrm.*`ファイルが
    存在するかをfilesystemへ直接問い合わせる（git statusを経由しないため、
    `.gitignore`の影響を受けない）。見つかったrepo-relative pathをsorted listで
    返す（空listなら汚染なし）。"""
    found: list[str] = []
    for root_prefix in OSRM_RUNTIME_ARTIFACT_FIXTURE_ROOTS:
        base = repo_root / root_prefix
        if not base.is_dir():
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for filename in filenames:
                if OSRM_RUNTIME_ARTIFACT_FILENAME_PATTERN.search(filename):
                    full = Path(dirpath) / filename
                    rel = full.relative_to(repo_root).as_posix()
                    found.append(rel)
    return sorted(found)


def _raise_if_osrm_contaminated(repo_root: Path) -> None:
    contamination = scan_osrm_runtime_contamination(repo_root)
    if contamination:
        raise ManifestGenerationError(
            "OSRM runtime build artifact(s) detected inside a read-only source fixture "
            f"tree — candidate generation refuses to proceed: {contamination!r} "
            "(Phase 2-D Round 8, P2D-OSRM-FIXTURE-CONTAMINATION: fixture directories "
            "under tests/fixtures/osm_demo/ must contain only the committed .osm.pbf "
            "source input and MANIFEST.json, never osrm-extract/partition/customize "
            "output. Delete the listed artifacts — they are reproducible from the "
            "source PBF — before regenerating the candidate; do not attempt to approve "
            "them via the untracked policy.)"
        )


ROOT_FILE_PATTERN = re.compile(
    r"^("
    r"docker-compose.*\.ya?ml"
    r"|Dockerfile.*"
    r"|LICENSE.*"
    r"|ATTRIBUTIONS.*"
    r"|THIRD_PARTY_NOTICES.*"
    r"|nginx\.conf"
    r"|requirements.*\.txt"
    r"|\.gitignore"
    r"|\.dockerignore"
    r"|\.env\..*\.example"
    r")$"
)

# Phase 2-D Round 12D-B3（P2D-AT17-SNAPSHOT-ROOTDOC-001, HARNESS CLASSIFICATION
# FINDING）: repository root直下に存在する「正規の公開文書」の exact filename
# allowlist。README.md と同じ PUBLIC_DOCUMENTATION classification を与える。
#
# 意図的に exact filename の完全一致だけを許可する。以下は使わない:
#   - `.*README.*` / `.*-README\.md` 等の substring / suffix 正規表現
#   - 拡張子だけの allowlist（root の任意 `.md` 許可）
#   - `VPS-README.md` 専用の後段除外
# 未知の root file（未分類 path）を fail-closed で拒否する既存境界は変更しない
# （このallowlistにもROOT_FILE_PATTERNにも一致しない root file は
# classify() が従来どおり ManifestGenerationError を送出する）。
#
# Round 12D-B3 以前は README 系を ROOT_FILE_PATTERN の `README.*` prefix 正規表現で
# 拾っていたため、`README-secret.md` / `README.md.bak` のような紛らわしい root file
# まで PUBLIC_DOCUMENTATION として受理されていた。exact allowlist へ移行することで
# それらは未分類 path として fail-closed 拒否される。
ROOT_PUBLIC_DOCUMENTATION_FILES = frozenset(
    {
        "README.md",
        "VPS-README.md",
    }
)


def _is_root_public_documentation_file(path: str) -> bool:
    """`path` が repository root 直下（サブディレクトリ・`.`/`..` セグメント・
    末尾スラッシュを含まない単一 component）であり、かつ
    ROOT_PUBLIC_DOCUMENTATION_FILES に exact 一致する場合のみ True。

    POSIX 正規化（`PurePosixPath` による `.`・重複スラッシュ・末尾スラッシュの
    折りたたみ）を行い、正規化前後で文字列が変化する path（例: `./VPS-README.md`,
    `VPS-README.md/`）は exact ではないと判定して False を返す。`..` は
    `PurePosixPath` では折りたたまれないため `/` 判定で弾かれる。
    substring / suffix 一致は一切行わない。
    """
    if path != PurePosixPath(path).as_posix():
        return False
    if "/" in path or path in (".", ".."):
        return False
    return path in ROOT_PUBLIC_DOCUMENTATION_FILES

# tasks/ (evidenceを含む) はbuild inputと混同しない。ただし恣意的に無視せず、
# 明示的にEXCLUDED_AUDIT_EVIDENCEへ分類し理由を記録する（指示書第4.3節）。
EXCLUDED_DIR_PREFIXES = ("tasks/",)

# 生成物/cache として明示除外してよいpath（指示書第4.5節 二番目の箇条書き）。
GENERATED_CACHE_PATTERNS = (
    re.compile(r"(^|/)__pycache__(/|$)"),
    re.compile(r"(^|/)\.pytest_cache(/|$)"),
    re.compile(r"(^|/)node_modules(/|$)"),
    re.compile(r"(^|/)\.venv(/|$)"),
    re.compile(r"(^|/)venv(/|$)"),
    re.compile(r"(^|/)\.DS_Store$"),
    # Phase 2-B.6手動実行時の`--result`出力先が誤ってtracked fixture directory直下
    # （`.../results/`）を指していたため残置された、過去1回分の実行結果。
    # `backend/tests/test_phase2b6_version_binding.py` / `test_phase2b6_rollback.py`は
    # いずれも`tmp_path`へ新規出力するのみで、このtracked `results/`配下を読まない
    # （grep で確認済み）。`manifest-set.json`のartifacts一覧からも参照されない。
    # 開発者ローカルの絶対path（例: /Users/<username>/...）を記録したcommand文字列を含む
    # ため、公開release snapshotには含めない。
    re.compile(r"^tests/fixtures/public_release/version_binding/results/"),
    re.compile(r"^tests/fixtures/public_release/rollback/results/"),
)

# secret / environment file として拒否するpathパターン（指示書第4.5節 三番目の箇条書き）。
# `.example` サフィックスを持つtemplate file自体は拒否対象から明示的に除外する。
SECRET_FILENAME_PATTERNS = (
    re.compile(r"^\.env$"),
    re.compile(r"^\.env\.operator$"),
    re.compile(r"^\.env\.local$"),
    re.compile(r"^\.env\.stream$"),
    re.compile(r"^\.env\.[A-Za-z0-9_-]+$"),
    re.compile(r".*\.pem$"),
    re.compile(r".*\.key$"),
    re.compile(r"^id_rsa.*$"),
    re.compile(r".*_rsa$"),
    re.compile(r"^credentials\.json$"),
)

# Phase 2-D Round 5A（P2D-UNTRACKED-APPROVAL-POLICY、CODEX round 4再検証finding）:
# Round 3で導入した拡張子/厳密名allowlist（`KNOWN_SAFE_UNTRACKED_EXTENSIONS`等）は
# 完全に削除した。CODEXが`backend/unapproved_round4_probe.py`で実演した通り、
# 拡張子は承認根拠にならない（`.py`だから安全、という判断は誤り）。untracked file
# の採否は`tools/public_release/phase2d_untracked_policy.py`が定義する
# default-deny・exact-match（path+sha256+size+mode+object_type+classification
# 全一致）のOWNER承認policyだけに基づく。`generate_manifest()`は
# `approved_untracked_policy`引数を受け取り、policyが未提供またはentryが
# exact一致しないuntracked fileは一切ADDEDへ採用しない（指示書第3.1節）。


def _is_entry_approved(
    path: str, sha256: str, size: int, mode: str, object_type: str, classification: str,
    approved_policy: dict,
) -> bool:
    """指示書第3.5節: 1条件でも不一致なら拒否。approved directory配下へ新しい
    fileを追加しても自動承認されない（exact per-fileマッチのみ）。
    schemaの所有・load/検証は`phase2d_untracked_policy.py`の責務（このfileは
    依存を持たず、判定ロジックだけを最小限複製することで依存の循環を避ける
    ——`phase2d_untracked_policy.py`側は逆にこの moduleのclassify()を呼ぶ）。"""
    for entry in approved_policy.get("entries", []):
        if (
            entry["path"] == path
            and entry["sha256"] == sha256
            and entry["size"] == size
            and entry["mode"] == mode
            and entry["object_type"] == object_type
            and entry["classification"] == classification
        ):
            return True
    return False


class ManifestGenerationError(RuntimeError):
    """release delta manifest生成をfail-closedで停止させる例外。"""


def _run(cmd: list, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, check=True)


def _run_text(cmd: list, cwd: Path) -> str:
    return _run(cmd, cwd).stdout.decode("utf-8", errors="surrogateescape")


def _is_secret_filename(name: str) -> bool:
    if name.endswith(".example"):
        return False
    return any(pat.match(name) for pat in SECRET_FILENAME_PATTERNS)


def _is_generated_cache(path: str) -> bool:
    return any(pat.search(path) for pat in GENERATED_CACHE_PATTERNS)


def _matched_release_root(path: str) -> str | None:
    for prefix in DIRECTORY_RELEASE_ROOTS:
        if path.startswith(prefix):
            return prefix
    if _is_root_public_documentation_file(path):
        return "<repo-root-file>"
    if "/" not in path and ROOT_FILE_PATTERN.match(path):
        return "<repo-root-file>"
    return None


def _is_excluded_dir(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in EXCLUDED_DIR_PREFIXES)


def classify(path: str) -> tuple[str, str, str | None]:
    """(classification, include_reason, release_root_matched) を返す。

    未分類でrelease rootにもtasks/にもgenerated cacheにも一致しないpathは
    ManifestGenerationErrorを送出する（指示書第4.5節・第14節: 未分類pathは停止）。
    """
    if _is_generated_cache(path):
        return (
            "EXCLUDED_AUDIT_EVIDENCE",
            "生成cache/一時成果物として明示除外（指示書第4.5節）。",
            None,
        )
    root = _matched_release_root(path)
    if root is not None:
        if path.startswith("tools/public_release/") and path.startswith("tools/public_release/test_"):
            return "TEST_FIXTURE", f"public_release audit toolのself-test（root={root}）", root
        if path.startswith("tools/public_release/"):
            return "AUDIT_TOOL", f"public release audit tool本体（root={root}）", root
        if path.startswith("tests/fixtures/"):
            return "TEST_FIXTURE", f"test fixture data（root={root}）", root
        if path.startswith("e2e/"):
            return "TEST_FIXTURE", f"Playwright E2E spec（root={root}）", root
        if path.startswith("config/"):
            return "RUNTIME_CONFIG", f"runtime設定file（root={root}）", root
        if path.startswith("docs/"):
            return "PUBLIC_DOCUMENTATION", f"公開ドキュメント（root={root}）", root
        name = Path(path).name
        if root == "<repo-root-file>":
            if path == "README.md":
                # 既存挙動・include_reason を byte 単位で維持する（README.md 本文
                # および manifest entry は Round 12D-B3 の変更対象外）。
                return "PUBLIC_DOCUMENTATION", "root README", root
            if _is_root_public_documentation_file(path):
                return (
                    "PUBLIC_DOCUMENTATION",
                    "repository root 直下の正規公開文書（exact filename allowlist "
                    "ROOT_PUBLIC_DOCUMENTATION_FILES; Phase 2-D Round 12D-B3 "
                    "P2D-AT17-SNAPSHOT-ROOTDOC-001）",
                    root,
                )
            if name.startswith(("LICENSE", "ATTRIBUTIONS", "THIRD_PARTY_NOTICES")):
                return "COMPLIANCE_ARTIFACT", "third-party/ライセンス関連artifact", root
            return "RUNTIME_CONFIG", "root-level runtime/build設定file", root
        if name in ("docker-compose.yml",) or name.startswith("docker-compose") or name in (
            "nginx.conf",
        ) or name.endswith(".properties") or name.endswith(".example") or "Dockerfile" in name or name == ".env.example":
            return "RUNTIME_CONFIG", f"runtime/build設定file（root={root}）", root
        return "BUILD_INPUT", f"application build input（root={root}）", root
    if _is_excluded_dir(path):
        return (
            "EXCLUDED_AUDIT_EVIDENCE",
            "tasks/ 配下（監査指示書・実装報告書・evidence）はbuild inputと混同しない。"
            "public release snapshotへは含めないが、恣意的に無視せず本manifestへ明示記録する。",
            None,
        )
    if _is_generated_cache(path):
        return (
            "EXCLUDED_AUDIT_EVIDENCE",
            "生成cache/一時成果物として明示除外（指示書第4.5節）。",
            None,
        )
    raise ManifestGenerationError(
        f"unclassified path outside all defined release roots and outside tasks/: {path!r} "
        "(指示書第4.5節・第14節: 未分類pathは停止)"
    )


@dataclass
class GitEntry:
    state: str
    path: str
    orig_path: str | None = None
    head_blob: str | None = None  # git SHA-1 object id at HEAD, "0"*40 if absent
    head_mode: str = "000000"
    worktree_present: bool = True
    submodule: bool = False


def _parse_status_v2(repo_root: Path) -> list[GitEntry]:
    raw = _run(["git", "status", "--porcelain=v2", "-z", "--untracked-files=all"], repo_root).stdout
    parts = raw.split(b"\x00")
    entries: list[GitEntry] = []
    i = 0
    while i < len(parts):
        rec = parts[i]
        i += 1
        if not rec:
            continue
        kind = rec[:1]
        if kind == b"1":
            fields = rec.decode("utf-8", errors="surrogateescape").split(" ", 8)
            # "1 XY sub mH mI mW hH hI path"
            _, xy, sub, mH, mI, mW, hH, hI, path = fields
            is_submodule = sub[0:1] == "S"
            if xy[0] == "D" and xy[1] in (".",):
                # staged deletion (index has no entry, worktree also absent)
                entries.append(GitEntry(state="DELETED", path=path, head_blob=hH, head_mode=mH, worktree_present=False, submodule=is_submodule))
            elif xy[1] == "D":
                entries.append(GitEntry(state="DELETED", path=path, head_blob=hH, head_mode=mH, worktree_present=False, submodule=is_submodule))
            else:
                # modified in worktree relative to HEAD/index (xy[1] in {M, T, ...}) or staged-only change
                entries.append(GitEntry(state="MODIFIED", path=path, head_blob=hH, head_mode=mH, worktree_present=True, submodule=is_submodule))
        elif kind == b"2":
            fields = rec.decode("utf-8", errors="surrogateescape").split(" ", 8)
            _, xy, sub, mH, mI, mW, hH, hI, rest = fields
            # rest = "<X><score> <path>"; orig path is the NEXT NUL-delimited part
            path = rest.split(" ", 1)[1]
            orig_path = parts[i].decode("utf-8", errors="surrogateescape")
            i += 1
            is_submodule = sub[0:1] == "S"
            entries.append(GitEntry(state="RENAMED_FROM", path=orig_path, head_blob=hH, head_mode=mH, worktree_present=False, submodule=is_submodule))
            entries.append(GitEntry(state="RENAMED_TO", path=path, head_blob="0" * 40, head_mode="000000", worktree_present=True, submodule=is_submodule))
        elif kind == b"u":
            raise ManifestGenerationError("unmerged path present in git status — resolve merge conflicts before generating a release snapshot")
        elif kind == b"?":
            path = rec[2:].decode("utf-8", errors="surrogateescape")
            entries.append(GitEntry(state="ADDED", path=path, head_blob=None, head_mode="000000", worktree_present=True, submodule=False))
        elif kind == b"!":
            continue  # ignored — --untracked-files=all does not request these, but guard anyway
        else:
            raise ManifestGenerationError(f"unrecognized git status --porcelain=v2 record: {rec!r}")
    return entries


def _blob_sha256(repo_root: Path, blob_id: str) -> str:
    proc = subprocess.run(["git", "cat-file", "blob", blob_id], cwd=repo_root, capture_output=True, check=True)
    return hashlib.sha256(proc.stdout).hexdigest()


def _content_sha256(path: Path, object_type: str) -> str:
    """git blobのcontentと同じ定義でSHA-256を計算する。symlinkの場合、gitの
    blob contentはlink target文字列そのもの（readlink結果のraw bytes）である。"""
    if object_type == "SYMLINK":
        return hashlib.sha256(os.readlink(path).encode("utf-8")).hexdigest()
    return _file_sha256(path)


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _worktree_object_type_and_mode(path: Path) -> tuple[str, str]:
    st = path.lstat()
    if stat.S_ISLNK(st.st_mode):
        return "SYMLINK", "120000"
    if stat.S_ISREG(st.st_mode):
        if st.st_mode & stat.S_IXUSR:
            return "EXECUTABLE_FILE", "100755"
        return "REGULAR_FILE", "100644"
    raise ManifestGenerationError(f"unsupported filesystem object type at {path}: mode={oct(st.st_mode)}")


def _head_object_type_and_mode(head_mode: str) -> tuple[str, str]:
    if head_mode == "120000":
        return "SYMLINK", head_mode
    if head_mode == "100755":
        return "EXECUTABLE_FILE", head_mode
    if head_mode == "100644":
        return "REGULAR_FILE", head_mode
    if head_mode == "160000":
        return "GITLINK", head_mode  # 拡張値。DELETED状態のgitlink tombstone entryにのみ現れる。
    raise ManifestGenerationError(f"unsupported HEAD git mode: {head_mode!r}")


def _staged_vs_unstaged_note(repo_root: Path) -> list[str]:
    """HEAD→indexとindex→working treeの両方で差分があるpath（3-way divergence:
    一度stageした後にさらにworking treeで変更したpath）を検出する（指示書第4.4節）。
    `git diff --cached ... HEAD` = HEAD vs index（staged分）、
    `git diff ...`（HEAD引数なし）= index vs working tree（unstaged分）。
    """
    staged = set(_run_text(["git", "diff", "--cached", "--name-only", "-z", "HEAD"], repo_root).split("\x00")) - {""}
    unstaged = set(_run_text(["git", "diff", "--name-only", "-z"], repo_root).split("\x00")) - {""}
    return sorted(staged & unstaged)


def generate_manifest(repo_root: Path | None = None, approved_untracked_policy: dict | None = None) -> dict:
    """`approved_untracked_policy`: OWNERが承認したexact-match untracked policy
    （`phase2d_untracked_policy.load_approved_untracked_policy()`の戻り値）。

    Phase 2-D Round 5C（CODEX round 5B再検証finding、P2D-UNTRACKED-APPROVAL-POLICY =
    NOT VALID FOR CURRENT RELEASE BYTES対応）: Round 5Bまでの実装は、未承認の
    untracked entryを`excluded_entries`という単一の箱へ静かに退避させ、それでも
    `overall_snapshot_completeness_result = PASS`を宣言できてしまう構造的欠陥を
    持っていた（"release root内で採用対象となるfileがpendingでも、除外すれば
    snapshotがPASSしてしまう"という指示書第3.2節が明示的に禁止するアンチ
    パターン）。本実装は4つの分類を明確に分離して返す。

        entries                                  = approved_entries（overlay対象。
                                                     常にrelease対象のtracked
                                                     MODIFIED/DELETED/RENAMED、および
                                                     OWNER承認policyとexact一致した
                                                     untracked ADDEDのみ）
        explicitly_excluded_nonrelease_entries   = 固定されたnonrelease分類のみ
                                                     （generated cache、tasks/配下の
                                                     監査文書・evidence）。extension・
                                                     directory regex・unknown entryは
                                                     この分類に含めない（指示書第3.3節）
        pending_owner_approval_entries           = release root内でOWNER承認policy
                                                     とexact一致しないuntracked entry
        pending_owner_approval_count             = 上記の件数。呼び出し側
                                                     （`phase2d_at17_clean_clone.run()`）
                                                     はこれが1件でもあれば、seed clone・
                                                     overlay・second clone・completeness
                                                     PASS宣言を一切行わずfail-closedで
                                                     停止する（指示書第3.2節）

    `rejected_entries`は明確な拒否対象（secret/environment filenameパターン一致）
    用の予約バケットだが、本実装ではsecret filenameは検出次第
    `ManifestGenerationError`で即時停止するfail-closed設計を維持するため、常に
    空のまま返る（部分的に処理を継続して情報を漏らすリスクを避けるため、蓄積して
    後でまとめて報告する設計より安全側と判断した）。
    """
    repo_root = (repo_root or REPO_ROOT).resolve()
    _raise_if_osrm_contaminated(repo_root)

    head = _run_text(["git", "rev-parse", "HEAD"], repo_root).strip()
    entries_git = _parse_status_v2(repo_root)
    divergent_paths = _staged_vs_unstaged_note(repo_root)

    manifest_entries = []
    explicitly_excluded_nonrelease_entries = []
    pending_owner_approval_entries = []
    rejected_entries: list = []

    for ge in entries_git:
        path = ge.path
        if ge.submodule:
            # gitlink/submodule reference — 全release rootの外にある既知の例外
            # （.claude/worktrees/* のClaude Code worktree残留物など）。
            # CODEX round 3再検証finding: 除外するだけでは実際にsecond cloneから
            # 削除されず、HEAD由来のgitlink treeエントリが復活扱いのまま残る
            # （unexpected_gitlinks_found）。DELETED状態のgitlinkは通常のtombstone
            # entryとしてmanifest_entriesへ入れ、overlayが実際に削除するようにする。
            # gitlinkがADDED/MODIFIEDされるケースはこのrepositoryでは発生しておらず
            # 未対応のため、想定外の状態は分類せずfail-closedで停止する。
            if ge.state != "DELETED":
                raise ManifestGenerationError(
                    f"submodule/gitlink entry with unsupported state {ge.state!r} at {path!r}: "
                    "only a DELETED gitlink state is handled by this tool "
                    "(指示書第14節: 未分類/想定外pathは停止)"
                )
            manifest_entries.append(
                {
                    "path": path,
                    "state": "DELETED",
                    "object_type": "GITLINK",
                    "mode": ge.head_mode,
                    "baseline_sha256": None,
                    "release_sha256": None,
                    "phase_origin": "PRE_EXISTING_UNRELATED",
                    "classification": "EXCLUDED_AUDIT_EVIDENCE",
                    "include_reason": (
                        "git submodule/gitlink reference outside all defined release roots "
                        "(pre-existing repository state unrelated to Phase 2-D, already staged "
                        "for deletion in the git index). Recorded as a DELETED tombstone entry "
                        "so the AT-17 overlay actively removes the HEAD-committed gitlink tree "
                        "entry from the release snapshot rather than leaving it in place; not "
                        "application or build content; the removal is applied only inside the "
                        "repo-external seed clone (via `git rm --cached`) — this tool never "
                        "writes to the source repository's own index/refs)."
                    ),
                }
            )
            continue

        classification, include_reason, root = classify(path)

        if classification == "EXCLUDED_AUDIT_EVIDENCE":
            explicitly_excluded_nonrelease_entries.append(
                {
                    "path": path,
                    "state": ge.state,
                    "object_type": None,
                    "mode": None,
                    "baseline_sha256": None,
                    "release_sha256": None,
                    "phase_origin": "AUDIT",
                    "classification": classification,
                    "include_reason": include_reason,
                }
            )
            continue

        if ge.state == "ADDED":
            full = repo_root / path
            if _is_secret_filename(Path(path).name):
                raise ManifestGenerationError(
                    f"untracked path {path!r} matches a secret/environment filename pattern — "
                    "refusing to classify automatically (指示書第4.5節: secret/environment file拒否)"
                )
            object_type, mode = _worktree_object_type_and_mode(full)
            release_sha256 = _content_sha256(full, object_type)
            size = full.lstat().st_size if object_type != "SYMLINK" else len(os.readlink(full))

            approved = False
            if approved_untracked_policy is not None:
                approved = _is_entry_approved(
                    path, release_sha256, size, mode, object_type, classification,
                    approved_untracked_policy,
                )

            if not approved:
                # 指示書第3.1節 default deny + 第3.2節 fail-closed: OWNER承認policy
                # とexact一致しないuntracked fileは、release root内である以上、
                # 「除外してPASSする箱」ではなく「snapshot全体をFAILさせる理由」
                # として明確に別バケットへ記録する（Round 5B finding対応）。
                # classificationはclassify()が計算した本来の値（BUILD_INPUT等）を
                # そのまま保持する（OWNER承認判断に必要な情報のため上書きしない）。
                pending_owner_approval_entries.append(
                    {
                        "path": path,
                        "state": "ADDED",
                        "object_type": object_type,
                        "mode": mode,
                        "baseline_sha256": None,
                        "release_sha256": release_sha256,
                        "size": size,
                        "phase_origin": "PHASE_2A_2D_UNTRACKED_PENDING_APPROVAL",
                        "classification": classification,
                        "approval_status": "PENDING_OWNER_APPROVAL",
                        "include_reason": (
                            "untracked file not present in an OWNER-approved "
                            "approved_untracked_policy.json with an exact "
                            "path+sha256+size+mode+object_type+classification match "
                            "(指示書第3.1節 default deny; 指示書第3.5節 exact match)。"
                        ),
                    }
                )
                continue

            manifest_entries.append(
                {
                    "path": path,
                    "state": "ADDED",
                    "object_type": object_type,
                    "mode": mode,
                    "baseline_sha256": None,
                    "release_sha256": release_sha256,
                    "phase_origin": "PHASE_2A_2D_UNTRACKED",
                    "classification": classification,
                    "include_reason": include_reason,
                }
            )
        elif ge.state == "MODIFIED":
            full = repo_root / path
            head_obj_type, head_mode = _head_object_type_and_mode(ge.head_mode)
            baseline_sha256 = _blob_sha256(repo_root, ge.head_blob) if ge.head_blob and ge.head_blob != "0" * 40 else None
            object_type, mode = _worktree_object_type_and_mode(full)
            release_sha256 = _content_sha256(full, object_type)
            manifest_entries.append(
                {
                    "path": path,
                    "state": "MODIFIED",
                    "object_type": object_type,
                    "mode": mode,
                    "baseline_sha256": baseline_sha256,
                    "release_sha256": release_sha256,
                    "phase_origin": "PHASE_2A_2D_TRACKED_MODIFIED",
                    "classification": classification,
                    "include_reason": include_reason,
                }
            )
        elif ge.state == "DELETED":
            head_obj_type, head_mode = _head_object_type_and_mode(ge.head_mode)
            baseline_sha256 = _blob_sha256(repo_root, ge.head_blob) if ge.head_blob and ge.head_blob != "0" * 40 else None
            manifest_entries.append(
                {
                    "path": path,
                    "state": "DELETED",
                    "object_type": head_obj_type,
                    "mode": head_mode,
                    "baseline_sha256": baseline_sha256,
                    "release_sha256": None,
                    "phase_origin": "PHASE_2A_2D_TRACKED_DELETED",
                    "classification": classification,
                    "include_reason": include_reason,
                }
            )
        elif ge.state == "RENAMED_FROM":
            head_obj_type, head_mode = _head_object_type_and_mode(ge.head_mode)
            baseline_sha256 = _blob_sha256(repo_root, ge.head_blob) if ge.head_blob and ge.head_blob != "0" * 40 else None
            manifest_entries.append(
                {
                    "path": path,
                    "state": "RENAMED_FROM",
                    "object_type": head_obj_type,
                    "mode": head_mode,
                    "baseline_sha256": baseline_sha256,
                    "release_sha256": None,
                    "phase_origin": "PHASE_2A_2D_RENAMED",
                    "classification": classification,
                    "include_reason": include_reason,
                }
            )
        elif ge.state == "RENAMED_TO":
            full = repo_root / path
            object_type, mode = _worktree_object_type_and_mode(full)
            release_sha256 = _content_sha256(full, object_type)
            manifest_entries.append(
                {
                    "path": path,
                    "state": "RENAMED_TO",
                    "object_type": object_type,
                    "mode": mode,
                    "baseline_sha256": None,
                    "release_sha256": release_sha256,
                    "phase_origin": "PHASE_2A_2D_RENAMED",
                    "classification": classification,
                    "include_reason": include_reason,
                }
            )

    manifest_entries.sort(key=lambda e: e["path"])
    explicitly_excluded_nonrelease_entries.sort(key=lambda e: e["path"])
    pending_owner_approval_entries.sort(key=lambda e: e["path"])

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "baseline_head": head,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entry_count": len(manifest_entries),
        "entries": manifest_entries,
        "explicitly_excluded_nonrelease_entries": explicitly_excluded_nonrelease_entries,
        "pending_owner_approval_entries": pending_owner_approval_entries,
        "pending_owner_approval_count": len(pending_owner_approval_entries),
        "rejected_entries": rejected_entries,
        "staged_unstaged_divergent_paths": divergent_paths,
    }
    return manifest


def write_manifest(manifest: dict, output_path: Path) -> str:
    text = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=False)
    text += "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--approved-untracked-policy", type=Path, default=None,
        help="OWNER承認済みapproved_untracked_policy.json（Round 5B以降）。未指定時はdefault deny。",
    )
    args = parser.parse_args()

    approved = None
    if args.approved_untracked_policy is not None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import phase2d_untracked_policy as untracked_policy_mod

        approved = untracked_policy_mod.load_approved_untracked_policy(args.approved_untracked_policy)

    manifest = generate_manifest(args.repo_root, approved_untracked_policy=approved)
    sha = write_manifest(manifest, args.output)
    print(
        f"entry_count={manifest['entry_count']} "
        f"explicitly_excluded_count={len(manifest['explicitly_excluded_nonrelease_entries'])} "
        f"pending_owner_approval_count={manifest['pending_owner_approval_count']} "
        f"manifest_sha256={sha}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
