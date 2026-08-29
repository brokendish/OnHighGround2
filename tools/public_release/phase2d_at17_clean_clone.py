#!/usr/bin/env python3
"""
phase2d_at17_clean_clone.py — Phase 2-D AT-17 release snapshot completeness gate
（Round 3全面書き換え、指示書 phase2d_claude_round3_snapshot_remediation_instruction.md）。

Round 2までの実装は固定HEADをseed cloneした後にPhase 2-Dのpathだけを手作業listで
overlayしていたため、Phase 2-A〜2-Cのbuild inputが大量欠落した
（P2D-AT17-SNAPSHOT-001、CODEX実測: overlay 48件 / 欠落62件以上）。

Round 3は指示書第3節の原則に従う:

    committed HEAD tree
    + all approved modified files from Phase 2-A〜2-D
    + all approved new files from Phase 2-A〜2-D
    - all approved deleted files from Phase 2-A〜2-D
    = complete release candidate snapshot

Phase名ごとの手作業path listを合成せず、`phase2d_release_delta_manifest.py`が
Git状態から機械的に抽出したrelease delta manifestだけを正本として使う。

流れ（指示書第5節）:
    1. source repositoryのHEADをrepo-external seedへ --no-local --no-hardlinks clone
    2. manifestのbaseline_headがseed/sourceのHEADと一致することを確認
    3. manifestの各entryをexact pathでoverlay（MODIFIED/ADDED/RENAMED_TO=上書き、
       DELETED/RENAMED_FROM=exact path削除のみ、parent directory再帰削除なし）
    4. seed clone内だけで一時commitを作成
    5. seedから第二のclean cloneを作成
    6. source release view（HEAD + manifest delta の論理和）・seed・second cloneの
       3者を比較し、completeness（指示書第6.4節の6指標）を判定する
    7. secret・boundary scanをsecond cloneに対して実行（指示書第7節）
    8. 指示書第6.3節の必須spot check・tombstoneを確認する

source repositoryでは `git clone`（読み取り専用）以外の書き込みを一切行わない
（`git add`・commit・stash・checkout・reset・rebase・merge・prune はしない。
source `.git/objects`・refs・reflogも変更しない）。

**Docker build / public起動（指示書第11節「Claudeが実行しないもの」）は本scriptの
scopeに含まない。** CODEXが次ラウンドでこのsnapshot completeness gateを独立PASSした
後に、Docker formal suiteを別途実行すること。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase2d_release_delta_manifest as manifest_mod  # noqa: E402
import phase2d_typed_boundary_scan as typed_scan_mod  # noqa: E402
import phase2d_untracked_policy as untracked_policy_mod  # noqa: E402
import phase2d_vbf_waiver as vbf_waiver_mod  # noqa: E402

REPO_ROOT = manifest_mod.REPO_ROOT

# --- 指示書第6.3節: 必須spot check（overlay後に個別存在・hash・内容identityを確認）---
REQUIRED_SPOT_CHECK_PATHS = [
    "docker-compose.yml",
    "backend/Dockerfile",
    "backend/app_public.py",
    "backend/app_operator.py",
    "backend/app/services/operator_auth.py",  # operator authentication implementation
    "backend/Dockerfile.operator",  # public/operator entrypoints
    "backend/app/services/docker_operation_gateway.py",  # Docker socket allowlist実装
    "backend/app/services/runtime_publish.py",  # atomic publish実装
    "backend/app/services/runtime_lease.py",  # lease / rollback実装
    "backend/app/services/runtime_gc.py",  # lease / rollback実装（GC側）
    "backend/app/models/simulation.py",  # simulation exclusion実装
    "backend/app/api/hazards.py",  # Phase 2-C route修正
    "backend/app/services/odpt_allowlist.py",  # Round 2 ODPT allowlist
    "frontend/js/attribution-notices.js",  # Round 2 attribution実装
    "docker-compose.demo.yml",
]

# --- 指示書第6.3節: second cloneで不存在を確認する対象（negative control）---
REQUIRED_ABSENT_PATHS = [
    "frontend/admin/datasets.css",
    "frontend/admin/datasets.html",
    "frontend/admin/datasets.js",
    "frontend/admin/hazards.css",
    "frontend/admin/hazards.html",
    "frontend/admin/hazards.js",
    "frontend/admin/simulation-map.js",
    "frontend/admin/simulation.css",
    "frontend/admin/simulation.html",
    "frontend/admin/simulation.js",
    "frontend/admin/upload-manager.js",
    "frontend/js/navigation-debug-layer.js",
]

# Phase 2-D Round 5A: secret/boundary scanのpattern定数群は
# `phase2d_typed_boundary_scan.py`（finding type別scanner）へ移設した。
# VBF waiverの適用可否ロジックは`phase2d_vbf_waiver.py`が単一の正本を持つ。


class SnapshotError(RuntimeError):
    pass


def _run(cmd: list, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)


def _run_bytes(cmd: list, cwd: Path, check: bool = True) -> bytes:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, check=check).stdout


# ---------------------------------------------------------------------------
# 5.1 seed
# ---------------------------------------------------------------------------

def seed_clone(repo_root: Path, tmp_root: Path) -> Path:
    seed = tmp_root / "seed_clone"
    _run(["git", "clone", "--no-local", "--no-hardlinks", str(repo_root), str(seed)], tmp_root)
    return seed


def verify_baseline(repo_root: Path, seed: Path, manifest: dict) -> None:
    source_head = _run(["git", "rev-parse", "HEAD"], repo_root).stdout.strip()
    seed_head = _run(["git", "rev-parse", "HEAD"], seed).stdout.strip()
    if not (source_head == seed_head == manifest["baseline_head"]):
        raise SnapshotError(
            f"baseline HEAD mismatch: source={source_head} seed={seed_head} "
            f"manifest={manifest['baseline_head']}"
        )


# ---------------------------------------------------------------------------
# 5.2 overlay
# ---------------------------------------------------------------------------

def _validate_safe_relpath(path: str) -> None:
    if not path or path.startswith("/") or path.startswith("~"):
        raise SnapshotError(f"absolute or home-relative path rejected: {path!r}")
    parts = path.split("/")
    if any(p in ("..", "") for p in parts):
        raise SnapshotError(f"parent-traversal or empty path segment rejected: {path!r}")


def _resolve_under_root(root: Path, rel_path: str) -> Path:
    root_resolved = root.resolve()
    candidate = (root / rel_path).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        raise SnapshotError(f"path escapes root via symlink/traversal: {rel_path!r} -> {candidate}")
    return candidate


def _apply_add_or_modify(repo_root: Path, seed: Path, entry: dict) -> None:
    rel = entry["path"]
    _validate_safe_relpath(rel)
    src = repo_root / rel
    if src.is_symlink() and entry["object_type"] != "SYMLINK":
        raise SnapshotError(f"unexpected symlink at non-symlink manifest entry: {rel}")
    if not src.exists() and not src.is_symlink():
        raise SnapshotError(f"manifest entry source missing from repo_root working tree: {rel}")

    dst = _resolve_under_root(seed, rel)
    dst.parent.mkdir(parents=True, exist_ok=True)

    if entry["object_type"] == "SYMLINK":
        # source realpathがsource root配下であることを確認し、symlink traversalは許可しない
        # （symlink自体をentityとしてoverlayするのみ。targetを辿った実体は扱わない）。
        target = os.readlink(src)
        if target.startswith("/"):
            raise SnapshotError(f"absolute symlink target rejected: {rel} -> {target}")
        resolved_target = (src.parent / target).resolve()
        try:
            resolved_target.relative_to(repo_root.resolve())
        except ValueError:
            raise SnapshotError(f"symlink escapes repo root: {rel} -> {target}")
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        os.symlink(target, dst)
        if os.readlink(dst) != target:
            raise SnapshotError(f"symlink overlay verification failed: {rel}")
        return

    # source realpathがsource root配下であることを確認（symlink traversal拒否）
    real_src = src.resolve()
    try:
        real_src.relative_to(repo_root.resolve())
    except ValueError:
        raise SnapshotError(f"source realpath escapes repo root: {rel} -> {real_src}")

    current_sha256 = manifest_mod._file_sha256(src)
    if current_sha256 != entry["release_sha256"]:
        raise SnapshotError(
            f"source hash mismatch vs manifest for {rel}: "
            f"manifest={entry['release_sha256']} current={current_sha256} "
            "(working tree changed since manifest generation — regenerate manifest)"
        )

    shutil.copy2(src, dst)
    if entry["object_type"] == "EXECUTABLE_FILE":
        os.chmod(dst, 0o755)
    else:
        os.chmod(dst, 0o644)

    copied_sha256 = manifest_mod._file_sha256(dst)
    if copied_sha256 != entry["release_sha256"]:
        raise SnapshotError(f"post-copy hash verification failed for {rel}")


def _apply_delete(seed: Path, entry: dict) -> None:
    rel = entry["path"]
    _validate_safe_relpath(rel)
    dst = _resolve_under_root(seed, rel)

    if entry["object_type"] == "GITLINK":
        # gitlink（submodule reference）はfile contentを持たないtree entryのため、
        # 通常のfile hash比較は使えない。`git rm --cached`でindexから直接除去する
        # （CODEX round 3再検証finding: 除外するだけでは削除されなかったバグの修正）。
        # 作業ツリー上に実体（uninitialized submoduleの空directory等）が残っていれば
        # そのpathだけを削除する（parent directoryは再帰削除しない）。
        _run(["git", "rm", "-r", "--cached", "--ignore-unmatch", "--", rel], seed)
        if dst.exists() or dst.is_symlink():
            if dst.is_dir() and not dst.is_symlink():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        remaining = _run(["git", "ls-files", "-s", "-z", "--", rel], seed).stdout
        if remaining.strip("\x00"):
            raise SnapshotError(f"gitlink deletion verification failed, still tracked: {rel}")
        return

    if not dst.exists() and not dst.is_symlink():
        raise SnapshotError(f"deletion target absent from seed clone (baseline mismatch?): {rel}")
    if entry["object_type"] != "SYMLINK":
        dst_sha256 = manifest_mod._file_sha256(dst)
        if dst_sha256 != entry["baseline_sha256"]:
            raise SnapshotError(
                f"deletion baseline hash mismatch for {rel}: "
                f"manifest={entry['baseline_sha256']} seed={dst_sha256}"
            )
    dst.unlink()  # exact path指定のみ。parent directoryは再帰削除しない。
    if dst.exists():
        raise SnapshotError(f"deletion verification failed, still present: {rel}")


def _validate_no_duplicate_paths(manifest: dict) -> None:
    seen: dict[str, int] = {}
    for entry in manifest["entries"]:
        seen[entry["path"]] = seen.get(entry["path"], 0) + 1
    duplicates = sorted(p for p, count in seen.items() if count > 1)
    if duplicates:
        raise SnapshotError(f"duplicate path(s) in manifest entries: {duplicates}")


def overlay_manifest(repo_root: Path, seed: Path, manifest: dict) -> dict:
    _validate_no_duplicate_paths(manifest)
    applied = {"MODIFIED": 0, "ADDED": 0, "DELETED": 0, "RENAMED_FROM": 0, "RENAMED_TO": 0}
    for entry in manifest["entries"]:
        state = entry["state"]
        if state in ("MODIFIED", "ADDED", "RENAMED_TO"):
            _apply_add_or_modify(repo_root, seed, entry)
        elif state in ("DELETED", "RENAMED_FROM"):
            _apply_delete(seed, entry)
        else:
            raise SnapshotError(f"unknown manifest entry state: {state!r} at {entry['path']}")
        applied[state] += 1
    return applied


# ---------------------------------------------------------------------------
# 5.3 seed commit / 5.4 second clone
# ---------------------------------------------------------------------------

def temp_commit(seed: Path) -> str:
    _run(["git", "add", "-A"], seed)
    _run(
        [
            "git", "-c", "user.email=phase2d-at17@local.invalid",
            "-c", "user.name=Phase2D AT-17 Round3 Snapshot",
            "commit", "--allow-empty", "-m",
            "TEMPORARY: Phase 2-D AT-17 Round 3 release delta overlay (seed clone only, never pushed)",
            "--no-verify",
        ],
        seed,
    )
    return _run(["git", "rev-parse", "HEAD"], seed).stdout.strip()


def second_clone(tmp_root: Path, seed: Path) -> Path:
    second = tmp_root / "second_clone"
    _run(["git", "clone", "--no-local", "--no-hardlinks", str(seed), str(second)], tmp_root)
    return second


# ---------------------------------------------------------------------------
# 6. completeness comparison — git-native raw diff (baseline_head..overlaid HEAD)
# ---------------------------------------------------------------------------

def _raw_diff(repo: Path, baseline: str, head: str) -> dict:
    """baseline..head間の変更をpath -> (statusChar, modeA, modeB, hashA, hashB) で返す。
    --find-renames は使わない（rename対はmanifest側でRENAMED_FROM/TOの2entryとして
    独立に扱うため、D+Aのpairのまま比較する方が曖昧さがない）。
    """
    out = _run_bytes(
        ["git", "diff", "--raw", "--no-renames", "-z", baseline, head], repo
    ).decode("utf-8", errors="surrogateescape")
    tokens = out.split("\x00")
    result = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        i += 1
        if not tok:
            continue
        if not tok.startswith(":"):
            continue
        # ":<modeA> <modeB> <hashA> <hashB> <status>"
        meta = tok[1:].split(" ")
        mode_a, mode_b, hash_a, hash_b, status = meta[0], meta[1], meta[2], meta[3], meta[4]
        path = tokens[i]
        i += 1
        result[path] = {
            "status": status[0],
            "mode_a": mode_a,
            "mode_b": mode_b,
            "hash_a": hash_a,
            "hash_b": hash_b,
        }
    return result


def _git_blob_sha256(repo: Path, blob_id: str) -> str | None:
    if blob_id is None or set(blob_id) == {"0"}:
        return None
    return manifest_mod._blob_sha256(repo, blob_id)


def compare_completeness(
    repo_root: Path,
    manifest: dict,
    seed: Path,
    second: Path,
    temp_head: str,
    required_spot_check_paths: list | None = None,
    required_absent_paths: list | None = None,
) -> dict:
    required_spot_check_paths = (
        REQUIRED_SPOT_CHECK_PATHS if required_spot_check_paths is None else required_spot_check_paths
    )
    required_absent_paths = (
        REQUIRED_ABSENT_PATHS if required_absent_paths is None else required_absent_paths
    )
    baseline = manifest["baseline_head"]
    seed_diff = _raw_diff(seed, baseline, temp_head)
    second_head = _run(["git", "rev-parse", "HEAD"], second).stdout.strip()
    second_diff = _raw_diff(second, baseline, second_head)

    result = {
        "baseline_head": baseline,
        "seed_temp_head": temp_head,
        "second_clone_head": second_head,
        "second_head_matches_seed_temp_head": second_head == temp_head,
        "seed_second_diff_identical": seed_diff == second_diff,
        "modified_but_stale": [],
        "deleted_but_resurrected": [],
        "new_but_missing": [],
        "unexpected": [],
        "hash_mismatch": [],
        "mode_mismatch": [],
        "spot_check": {},
        "tombstone_check": {},
    }

    # Phase 2-D Round 5C: manifest schemaが4分類（entries/explicitly_excluded_
    # nonrelease_entries/pending_owner_approval_entries/rejected_entries）を
    # 明確に分離するようになったため、`manifest["entries"]`には常に
    # overlay対象（approved）のみが入る。EXCLUDED_AUDIT_EVIDENCEやpending分の
    # フィルタリングはmanifest生成側の責務となり、ここでは不要になった
    # （旧来のfilterロジックを削除して単純化）。
    relevant_entries = manifest["entries"]
    expected_paths = {e["path"] for e in relevant_entries}

    for entry in relevant_entries:
        path = entry["path"]
        state = entry["state"]
        actual = second_diff.get(path)

        if state in ("MODIFIED", "ADDED", "RENAMED_TO"):
            if actual is None:
                (result["modified_but_stale"] if state == "MODIFIED" else result["new_but_missing"]).append(path)
                continue
            actual_sha256 = _git_blob_sha256(second, actual["hash_b"])
            if actual_sha256 != entry["release_sha256"]:
                result["hash_mismatch"].append({"path": path, "expected": entry["release_sha256"], "actual": actual_sha256})
            expected_mode = entry["mode"]
            if actual["mode_b"] != expected_mode:
                result["mode_mismatch"].append({"path": path, "expected": expected_mode, "actual": actual["mode_b"]})
        elif state in ("DELETED", "RENAMED_FROM"):
            if actual is None:
                result["deleted_but_resurrected"].append(path)
                continue
            if actual["status"] != "D":
                result["deleted_but_resurrected"].append(path)
                continue
            if entry["object_type"] == "GITLINK":
                # gitlink（submodule reference）のhash_aはblobではなくsubmodule
                # commit SHA（かつgit diff --rawではデフォルトで短縮表示される）ため
                # `git cat-file blob`によるhash検証は意味を持たず失敗する。
                # baseline_sha256も元々Noneのため、status='D'の確認のみで十分とする。
                continue
            actual_sha256 = _git_blob_sha256(second, actual["hash_a"])
            if actual_sha256 != entry["baseline_sha256"]:
                result["hash_mismatch"].append({"path": path, "expected": entry["baseline_sha256"], "actual": actual_sha256})

    unexpected_paths = set(second_diff.keys()) - expected_paths
    result["unexpected"] = sorted(unexpected_paths)

    for path in required_spot_check_paths:
        entry = next((e for e in relevant_entries if e["path"] == path), None)
        actual = second_diff.get(path)
        ok = entry is not None and actual is not None
        detail = {"in_manifest": entry is not None, "in_second_clone_diff": actual is not None}
        if ok and entry["state"] in ("MODIFIED", "ADDED"):
            actual_sha256 = _git_blob_sha256(second, actual["hash_b"])
            detail["hash_match"] = actual_sha256 == entry["release_sha256"]
            ok = ok and detail["hash_match"]
        result["spot_check"][path] = {"ok": ok, **detail}

    for path in required_absent_paths:
        second_files = _run(["git", "ls-files", "-z", "--", path], second).stdout
        present = bool(second_files.strip("\x00"))
        result["tombstone_check"][path] = {"absent_in_second_clone": not present}

    result["completeness_pass"] = (
        not result["modified_but_stale"]
        and not result["deleted_but_resurrected"]
        and not result["new_but_missing"]
        and not result["unexpected"]
        and not result["hash_mismatch"]
        and not result["mode_mismatch"]
        and result["second_head_matches_seed_temp_head"]
        and result["seed_second_diff_identical"]
        and all(v["ok"] for v in result["spot_check"].values())
        and all(v["absent_in_second_clone"] for v in result["tombstone_check"].values())
    )
    return result


# ---------------------------------------------------------------------------
# 7. secret / boundary scan (second clone)
# ---------------------------------------------------------------------------

def secret_boundary_scan(
    second: Path,
    manifest: dict,
    approved_vbf_waiver: dict | None = None,
) -> dict:
    """指示書第5.2節: finding typeごとに分離したtyped scannerを実行する。

    旧実装（Round 3/4）は単一のfinding listへ全種別を混在させ、VBF directory
    regexに一致するpathのfindingを種別を問わず一括suppressしていた
    （"if path matches VBF regex: suppress every finding"という禁止パターン）。
    本実装は`phase2d_typed_boundary_scan.scan_typed()`で8種別に分離し、
    `approved_vbf_waiver`（OWNER承認済みexact waiver、Round 5B以降）は
    `phase2d_vbf_waiver.apply_vbf_waiver()`経由で`ABSOLUTE_USER_PATH`の
    findingにのみ、exact occurrence一致で適用する。他の7種別は一切影響を
    受けない（指示書第5.5節: VBF directory内でもsecret canary等は必ずFAIL）。

    Round 5Aの時点では`approved_vbf_waiver=None`がdefaultであり、waiverは
    一切適用されない（VBF fixtureのABSOLUTE_USER_PATH findingはそのまま残る）。
    """
    typed_findings = typed_scan_mod.scan_typed(second)

    waived_findings, suppressed = vbf_waiver_mod.apply_vbf_waiver(
        typed_findings, approved_vbf_waiver, None, second
    )

    # gate判定: release snapshotへ新規bytesとして入るcontent（manifest上で
    # MODIFIED/ADDED/RENAMED_TO状態のpath）かどうかで行う（Round 4の設計を維持）。
    new_content_paths = {
        e["path"] for e in manifest["entries"]
        if e["state"] in ("MODIFIED", "ADDED", "RENAMED_TO")
    }

    def _is_new_release_content(path: str) -> bool:
        return path in new_content_paths

    gated = {}
    pre_existing = {}
    for finding_type, items in waived_findings.items():
        gated[finding_type] = [f for f in items if _is_new_release_content(f["path"])]
        pre_existing[finding_type] = [f for f in items if not _is_new_release_content(f["path"])]

    ok = all(not v for v in gated.values())

    return {
        "typed_findings_raw": waived_findings,
        "gated_findings": gated,
        "pre_existing_unchanged_findings": pre_existing,
        "suppressed_by_vbf_waiver": suppressed,
        "ok": ok,
        "pre_existing_findings_present": any(pre_existing.values()),
        "vbf_waiver_applied": approved_vbf_waiver is not None,
    }


# ---------------------------------------------------------------------------
# object count invariance
# ---------------------------------------------------------------------------

def git_object_summary(repo_root: Path) -> dict:
    out = _run(["git", "count-objects", "-v"], repo_root).stdout
    stats = {}
    for line in out.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            stats[k.strip()] = v.strip()
    return stats


# ---------------------------------------------------------------------------
# command/doc parity（Round 2で追加、Round 3も維持する既存check — 指示書第2節
# 「既存OWNER判断9点は維持する」。snapshot完全性checkとは独立の既存回帰check。
# ---------------------------------------------------------------------------

_KNOWN_NON_SERVICE_FLAGS = {"stop", "down", "config", "-v", "-d", "--profile", "up"}


def _extract_referenced_service_tokens(text: str) -> set:
    referenced = set()
    for m in re.finditer(r"docker compose(?: --profile [a-zA-Z0-9_-]+)? exec\s+([a-zA-Z0-9_.-]+)", text):
        tok = m.group(1).strip("`")
        if tok and tok not in _KNOWN_NON_SERVICE_FLAGS:
            referenced.add(tok)
    for m in re.finditer(r"docker compose(?: --profile [a-zA-Z0-9_-]+)? (?:build|up -d|up|stop)\s+([a-zA-Z0-9_ .-]+)", text):
        for tok in m.group(1).split():
            tok = tok.strip("`")
            if tok and tok not in _KNOWN_NON_SERVICE_FLAGS and not tok.startswith("-"):
                referenced.add(tok)
    return referenced


def command_doc_parity(repo_root: Path = REPO_ROOT) -> dict:
    """README.md・docs/installation.mdが挙げるcompose service名が、実
    docker-compose.ymlに実在するかを正規化比較する（Round 2第9節・第12.4節）。"""
    compose_text = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")
    real_services = set(re.findall(r"^  ([a-z][a-zA-Z0-9_-]*):\s*$", compose_text, re.MULTILINE))

    install_text = (repo_root / "docs" / "installation.md").read_text(encoding="utf-8")
    readme_text = (repo_root / "README.md").read_text(encoding="utf-8")

    referenced_install = _extract_referenced_service_tokens(install_text)
    referenced_readme = _extract_referenced_service_tokens(readme_text)
    referenced = referenced_install | referenced_readme

    unknown = sorted(referenced - real_services)
    return {
        "referenced_services_in_docs": sorted(referenced),
        "referenced_services_in_installation_md": sorted(referenced_install),
        "referenced_services_in_readme_md": sorted(referenced_readme),
        "real_compose_services": sorted(real_services),
        "unknown_services_in_docs": unknown,
        "ok": len(unknown) == 0,
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def run(
    repo_root: Path,
    manifest: dict,
    required_spot_check_paths: list | None = None,
    required_absent_paths: list | None = None,
    approved_vbf_waiver: dict | None = None,
) -> dict:
    objects_before = git_object_summary(repo_root)
    head_before = _run(["git", "rev-parse", "HEAD"], repo_root).stdout.strip()
    branch_before = _run(["git", "branch", "--show-current"], repo_root).stdout.strip()

    # Phase 2-D Round 5C（P2D-UNTRACKED-APPROVAL-POLICY = NOT VALID FOR CURRENT
    # RELEASE BYTES対応、指示書第3.2節）: release root内に1件でもOWNER未承認の
    # untracked entryが残っている場合、seed clone・overlay・temporary commit・
    # second clone・completeness PASS宣言のいずれも一切実行しない。Round 5Bまでの
    # 実装は、未承認entryを黙って除外した「部分集合」に対してPASSを宣言できて
    # しまう欠陥を持っていた（CODEX round 5B再検証finding）。
    pending_count = manifest.get("pending_owner_approval_count", 0)
    if pending_count > 0:
        objects_after = git_object_summary(repo_root)
        head_after = _run(["git", "rev-parse", "HEAD"], repo_root).stdout.strip()
        branch_after = _run(["git", "branch", "--show-current"], repo_root).stdout.strip()
        return {
            "manifest_baseline_head": manifest["baseline_head"],
            "manifest_entry_count": manifest["entry_count"],
            "pending_owner_approval_count": pending_count,
            "pending_owner_approval_entries": manifest["pending_owner_approval_entries"],
            "seed_clone_started": False,
            "overlay_started": False,
            "temp_commit_started": False,
            "second_clone_started": False,
            "source_repo_head_before": head_before,
            "source_repo_head_after": head_after,
            "source_repo_branch_before": branch_before,
            "source_repo_branch_after": branch_after,
            "source_repo_git_objects_before": objects_before,
            "source_repo_git_objects_after": objects_after,
            "source_repo_unchanged": (
                head_before == head_after
                and branch_before == branch_after
                and objects_before == objects_after
            ),
            "overall_snapshot_completeness_result": "FAIL",
            "fail_reason": "PENDING_OWNER_APPROVAL_ENTRIES_PRESENT",
            "docker_build_and_public_startup": (
                "NOT RUN — pending owner approval entries present (fail-closed stop)"
            ),
        }

    with tempfile.TemporaryDirectory(prefix="ohg2p2d_at17_r3_") as tmp:
        tmp_root = Path(tmp)

        seed = seed_clone(repo_root, tmp_root)
        verify_baseline(repo_root, seed, manifest)

        applied = overlay_manifest(repo_root, seed, manifest)
        temp_head = temp_commit(seed)

        second = second_clone(tmp_root, seed)

        completeness = compare_completeness(
            repo_root, manifest, seed, second, temp_head,
            required_spot_check_paths=required_spot_check_paths,
            required_absent_paths=required_absent_paths,
        )
        scan = secret_boundary_scan(second, manifest, approved_vbf_waiver=approved_vbf_waiver)

    objects_after = git_object_summary(repo_root)
    head_after = _run(["git", "rev-parse", "HEAD"], repo_root).stdout.strip()
    branch_after = _run(["git", "branch", "--show-current"], repo_root).stdout.strip()

    source_unchanged = (
        head_before == head_after
        and branch_before == branch_after
        and objects_before == objects_after
    )

    has_doc_parity_inputs = (
        (repo_root / "docker-compose.yml").is_file()
        and (repo_root / "docs" / "installation.md").is_file()
        and (repo_root / "README.md").is_file()
    )
    parity = command_doc_parity(repo_root) if has_doc_parity_inputs else {"ok": True, "skipped": "docker-compose.yml/README.md/docs/installation.md not present (fixture repo)"}

    overall_pass = completeness["completeness_pass"] and scan["ok"] and source_unchanged and parity["ok"]

    return {
        "manifest_baseline_head": manifest["baseline_head"],
        "manifest_entry_count": manifest["entry_count"],
        "overlay_applied_counts": applied,
        "completeness": completeness,
        "secret_boundary_scan": scan,
        "command_doc_parity": parity,
        "source_repo_head_before": head_before,
        "source_repo_head_after": head_after,
        "source_repo_branch_before": branch_before,
        "source_repo_branch_after": branch_after,
        "source_repo_git_objects_before": objects_before,
        "source_repo_git_objects_after": objects_after,
        "source_repo_unchanged": source_unchanged,
        "overall_snapshot_completeness_result": "PASS" if overall_pass else "FAIL",
        "docker_build_and_public_startup": (
            "NOT RUN — deferred to CODEX independent verification per instruction section 11"
        ),
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=REPO_ROOT,
        help="対象repository（既定: このrepository自身）。fail-closed negative controlの"
             "subprocess testがrepo-external fixture repositoryを指すために使う。",
    )
    parser.add_argument(
        "--approved-untracked-policy", type=Path, default=None,
        help="OWNER承認済みapproved_untracked_policy.json（Round 5B以降）。未指定時はdefault deny。",
    )
    parser.add_argument(
        "--approved-untracked-policy-sha256", type=str, default=None,
        help="OWNERから実際に得たapproved_untracked_policy.jsonのSHA-256（policy改ざん検知用）。",
    )
    parser.add_argument(
        "--approved-vbf-waiver", type=Path, default=None,
        help="OWNER承認済みapproved_vbf_absolute_path_waiver.json（Round 5B以降）。未指定時はwaiver適用なし。",
    )
    parser.add_argument(
        "--approved-vbf-waiver-sha256", type=str, default=None,
        help="OWNERから実際に得たapproved_vbf_absolute_path_waiver.jsonのSHA-256（policy改ざん検知用）。",
    )
    parser.add_argument(
        "--no-evidence", action="store_true",
        help="evidence file（tasks/public-release/evidence/phase2d/配下）を書かない"
             "（fixture repositoryに対するnegative control実行時に使う）。",
    )
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()

    approved_untracked = None
    if args.approved_untracked_policy is not None:
        approved_untracked = untracked_policy_mod.load_approved_untracked_policy(
            args.approved_untracked_policy, expected_sha256=args.approved_untracked_policy_sha256
        )

    approved_vbf = None
    if args.approved_vbf_waiver is not None:
        approved_vbf = vbf_waiver_mod.load_approved_vbf_waiver(
            args.approved_vbf_waiver, expected_sha256=args.approved_vbf_waiver_sha256
        )

    manifest = manifest_mod.generate_manifest(repo_root, approved_untracked_policy=approved_untracked)
    result = run(repo_root, manifest, approved_vbf_waiver=approved_vbf)

    if args.no_evidence:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("\nSNAPSHOT COMPLETENESS RESULT:", result["overall_snapshot_completeness_result"])
        return 0 if result["overall_snapshot_completeness_result"] == "PASS" else 1

    evidence_dir = repo_root / "tasks" / "public-release" / "evidence" / "phase2d"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    manifest_sha256 = manifest_mod.write_manifest(
        manifest, evidence_dir / "phase2d_round5c_release_delta_manifest.json"
    )
    result["manifest_sha256"] = manifest_sha256
    result["approved_untracked_policy_applied"] = approved_untracked is not None
    result["approved_vbf_waiver_applied"] = approved_vbf is not None

    (evidence_dir / "phase2d_round5c_at17_snapshot_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\nSNAPSHOT COMPLETENESS RESULT:", result["overall_snapshot_completeness_result"])
    print("DOCKER-DEPENDENT SCOPE:", result["docker_build_and_public_startup"])
    return 0 if result["overall_snapshot_completeness_result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
