#!/usr/bin/env python3
"""
formal_evidence.py — public-release formal tool の evidence を immutable / append-only で残す共通部品
（KTF-003 EVIDENCE-IMMUTABILITY、2026-10-12、OWNER 承認方針）。

経緯: AT-17 tool は固定 file 名（phase2d_round5c_release_delta_manifest.json 等）へ書いており、2026-10-12 の
Phase 2-D formal 再実行で Round 5C（2026-08-22、baseline d3eeb99）の evidence を上書きした。写しは無く復元できない
（docs/testing/known_test_failures.md KTF-003）。失われた evidence は再生成・推測復元しない。

契約:
  1. identity: 1 回の formal run は (phase, tool, round, attempt, git HEAD, run_id) で一意。run ごとに
     `tasks/public-release/evidence/<phase>/runs/<UTC>-<HEAD12>-<tool>-<round>-a<attempt>-<rand>/` を作る。
     directory が既にあれば作らずに止まる（fail closed）。同じ (phase, tool, round, HEAD) で attempt を明示し、
     その attempt の run が既にあれば止まる（attempt は省略時、既存 run の数 + 1）。
  2. append-only: file は「一時 file に書く → fsync → 読み戻して内容・sha256（JSON は parse も）を検証 →
     `os.link` で最終名へ」の順で作る。link は既存の最終名を置き換えないため、同じ名前への 2 回目の書き込みは
     FileExistsError になる（silent overwrite が起きない）。途中で失敗した一時 file は消し、最終名には残さない。
  3. provenance: finalize() が `provenance.json`（schema・phase・tool・round・attempt・HEAD・run_id・generated_at・
     実行結果・各 file の sha256 / size）を同じ方式で書き、run の file と directory を read-only にする。
     provenance.json の無い run は未完了で、formal の記録として扱わない。verify_run() が hash を照合する。
  4. 多数の箇所から直接 file を書く既存 tool（2b1・2b2・2c）は、run directory を EVIDENCE_DIR にし（新しい
     directory なので過去の run は上書きできない）、終了時に finalize_existing() で directory 内の全 file を
     provenance に記録する。途中で止まった run には provenance が無く、formal の記録にならない。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "ohg2.formal_evidence/v1"
PROVENANCE_NAME = "provenance.json"
_LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


class EvidenceError(RuntimeError):
    pass


def evidence_root(repo_root: Path, phase: str) -> Path:
    return repo_root / "tasks" / "public-release" / "evidence" / phase / "runs"


def _git_head(repo_root: Path) -> str:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True)
    head = proc.stdout.strip()
    if proc.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise EvidenceError(f"git HEAD を取得できない: {proc.stderr.strip()[:200]}")
    return head


def _git_dirty_count(repo_root: Path) -> int:
    proc = subprocess.run(["git", "status", "--porcelain"], cwd=repo_root, capture_output=True, text=True)
    return len([l for l in proc.stdout.splitlines() if l.strip()])


def _check_label(kind: str, value: str) -> str:
    if not _LABEL_RE.fullmatch(value):
        raise EvidenceError(f"{kind} は [a-z0-9_.-]（先頭は英数字、64 文字以内）: {value!r}")
    return value


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _same_identity_runs(root: Path, head12: str, tool: str, round_label: str) -> List[Path]:
    if not root.is_dir():
        return []
    pat = re.compile(rf"^\d{{8}}T\d{{6}}Z-{re.escape(head12)}-{re.escape(tool)}-{re.escape(round_label)}-a(\d+)-[0-9a-f]{{8}}$")
    return sorted(p for p in root.iterdir() if p.is_dir() and pat.match(p.name))


class FormalRun:
    """1 回の formal run の evidence directory。write_*() で file を足し、最後に finalize() する。"""

    def __init__(self, directory: Path, identity: Dict[str, Any]):
        self.directory = directory
        self.identity = identity
        self._files: Dict[str, Dict[str, Any]] = {}
        self._finalized = False

    # ── append-only な atomic write ──────────────────────────────────────────────
    def write_bytes(self, name: str, data: bytes, validate: Optional[Callable[[bytes], None]] = None) -> str:
        if self._finalized:
            raise EvidenceError("finalize 済みの run には書けない")
        if not name or "/" in name or name.startswith(".") or name == PROVENANCE_NAME:
            raise EvidenceError(f"evidence file 名が不正: {name!r}")
        return self._write(name, data, validate)

    def write_text(self, name: str, text: str) -> str:
        return self.write_bytes(name, text.encode("utf-8"))

    def write_json(self, name: str, obj: Any) -> str:
        data = (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        return self.write_bytes(name, data, validate=lambda b: json.loads(b.decode("utf-8")))

    def _write(self, name: str, data: bytes, validate: Optional[Callable[[bytes], None]]) -> str:
        final = self.directory / name
        if final.exists() or final.is_symlink():
            raise FileExistsError(f"evidence は上書きしない: {final}")
        expected = hashlib.sha256(data).hexdigest()
        tmp = self.directory / f".{name}.tmp-{secrets.token_hex(4)}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            try:
                view = memoryview(data)
                while view:
                    n = os.write(fd, view)
                    view = view[n:]
                os.fsync(fd)
            finally:
                os.close(fd)
            written = tmp.read_bytes()
            if written != data or hashlib.sha256(written).hexdigest() != expected:
                raise EvidenceError(f"一時 file の読み戻しが一致しない: {name}")
            if validate is not None:
                validate(written)
            # link は既存の最終名を置き換えない（FileExistsError）。rename と違い silent overwrite が起きない。
            os.link(tmp, final)
        finally:
            if tmp.exists():
                tmp.unlink()
        _fsync_dir(self.directory)
        self._files[name] = {"sha256": expected, "size": len(data)}
        return expected

    # ── provenance ─────────────────────────────────────────────────────────────
    def finalize_existing(self, execution_result: Dict[str, Any]) -> Path:
        """tool が直接書いた file も含め、directory 内の全 file を記録して finalize する（契約 4）。"""
        for p in sorted(self.directory.rglob("*")):
            if p.is_symlink():
                raise EvidenceError(f"run directory に symlink がある: {p}")
            if p.is_file():
                rel = p.relative_to(self.directory).as_posix()
                if rel not in self._files:
                    data = p.read_bytes()
                    self._files[rel] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        return self.finalize(execution_result)

    def finalize(self, execution_result: Dict[str, Any]) -> Path:
        if self._finalized:
            raise EvidenceError("finalize は 1 回だけ")
        stray = sorted(p.relative_to(self.directory).as_posix() for p in self.directory.rglob("*")
                       if p.is_file() and p.relative_to(self.directory).as_posix() not in self._files)
        if stray:
            raise EvidenceError(f"run directory に記録外の file がある: {stray}")
        provenance = {
            "schema": SCHEMA,
            **self.identity,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "execution_result": execution_result,
            "files": dict(sorted(self._files.items())),
        }
        data = (json.dumps(provenance, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        self._write(PROVENANCE_NAME, data, validate=lambda b: json.loads(b.decode("utf-8")))
        self._finalized = True
        ro_file = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
        ro_dir = ro_file | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        for p in sorted(self.directory.rglob("*"), key=lambda q: len(q.parts), reverse=True):
            p.chmod(ro_dir if p.is_dir() else ro_file)
        self.directory.chmod(ro_dir)
        return self.directory / PROVENANCE_NAME


def open_run(phase: str, tool: str, round_label: Optional[str] = None, attempt: Optional[int] = None,
             repo_root: Optional[Path] = None) -> FormalRun:
    """新しい run directory を作る（既にあれば・同じ identity の attempt が既にあれば止まる）。

    round / attempt は引数、無ければ環境変数 OHG2_FORMAL_ROUND / OHG2_FORMAL_ATTEMPT、それも無ければ
    round = "adhoc"、attempt = 同じ (phase, tool, round, HEAD) の既存 run 数 + 1。
    """
    repo_root = REPO_ROOT if repo_root is None else repo_root
    phase = _check_label("phase", phase)
    tool = _check_label("tool", tool)
    round_label = _check_label("round", round_label or os.environ.get("OHG2_FORMAL_ROUND") or "adhoc")
    if attempt is None and os.environ.get("OHG2_FORMAL_ATTEMPT"):
        attempt = int(os.environ["OHG2_FORMAL_ATTEMPT"])
    head = _git_head(repo_root)
    root = evidence_root(repo_root, phase)
    existing = _same_identity_runs(root, head[:12], tool, round_label)
    used = {int(re.search(r"-a(\d+)-[0-9a-f]{8}$", p.name).group(1)) for p in existing}
    if attempt is None:
        attempt = max(used, default=0) + 1
    if attempt < 1:
        raise EvidenceError(f"attempt は 1 以上: {attempt}")
    if attempt in used:
        raise EvidenceError(f"同じ identity の run が既にある（上書きしない）: {phase}/{tool}/{round_label}/a{attempt}@{head[:12]}")
    run_id = secrets.token_hex(4)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = root / f"{stamp}-{head[:12]}-{tool}-{round_label}-a{attempt}-{run_id}"
    root.mkdir(parents=True, exist_ok=True)
    directory.mkdir(exist_ok=False)  # 既にあれば FileExistsError（fail closed）
    identity = {
        "phase": phase, "tool": tool, "round": round_label, "attempt": attempt,
        "git_head": head, "git_dirty_paths": _git_dirty_count(repo_root), "run_id": run_id,
        "run_directory": directory.name,
    }
    return FormalRun(directory, identity)


def verify_run(directory: Path) -> List[str]:
    """finalize 済み run の provenance と実 file を照合する。問題の一覧（空なら一致）。"""
    issues: List[str] = []
    prov_path = directory / PROVENANCE_NAME
    if not prov_path.is_file():
        return [f"{PROVENANCE_NAME} が無い（未完了の run）"]
    prov = json.loads(prov_path.read_text(encoding="utf-8"))
    if prov.get("schema") != SCHEMA:
        issues.append(f"schema 不一致: {prov.get('schema')!r}")
    if prov.get("run_directory") != directory.name:
        issues.append("run_directory 不一致")
    files = prov.get("files") or {}
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*")
              if p.is_file() and p.relative_to(directory).as_posix() != PROVENANCE_NAME}
    for extra in sorted(actual - set(files)):
        issues.append(f"記録外の file: {extra}")
    for name, meta in files.items():
        p = directory / name
        if not p.is_file():
            issues.append(f"欠落: {name}")
            continue
        data = p.read_bytes()
        if hashlib.sha256(data).hexdigest() != meta.get("sha256") or len(data) != meta.get("size"):
            issues.append(f"内容が provenance と一致しない: {name}")
    return issues


def snapshot_tree(root: Path) -> Dict[str, str]:
    """root 配下の全 file の sha256（過去 evidence が byte 単位で保たれていることの確認用）。"""
    out: Dict[str, str] = {}
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def changed_or_removed(before: Dict[str, str], after: Dict[str, str]) -> List[str]:
    """before にあった file のうち、after で内容が変わった・消えたもの（追加は append-only なので可）。"""
    return sorted(k for k, v in before.items() if after.get(k) != v)
