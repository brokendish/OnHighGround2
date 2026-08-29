#!/usr/bin/env python3
"""
phase2d_untracked_policy.py — untracked file default-deny承認policy
（Phase 2-D Round 5A、指示書 phase2d_claude_round5a_policy_hardening_instruction.md 第3節）。

CODEX Round 4再検証が実証した通り、拡張子・parent directory・classification等を
承認根拠にする設計は、`backend/unapproved_round4_probe.py`のような未承認fileを
「`.py`だから」という理由だけで機械的に通してしまう（negative control参照）。

本moduleはdefault denyを徹底する:

    untracked AND exact approved entryなし => 常に不採用

承認根拠として使ってはいけないもの（指示書第3.1節）:
    extension / MIME type / parent directory / filename prefix / regex / glob /
    BUILD_INPUT分類 / 過去Roundで自動採用された事実

candidateとapprovedは別schema・別fileに分離する（指示書第3.2節）。本moduleは
Round 5Aの時点ではcandidateだけを生成する。approved policyのload/検証ロジックは
実装するが、approved policy file自体はOWNER承認後（Round 5B）に別途作られる。

1 fileの承認条件（指示書第3.5節、1条件でも不一致なら拒否）:
    canonical_path一致 AND SHA-256一致 AND size一致 AND mode一致 AND
    object_type一致 AND classification一致
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase2d_release_delta_manifest as manifest_mod  # noqa: E402

SCHEMA_VERSION = 1

REPO_ROOT = Path(__file__).resolve().parents[2]


class PolicyError(RuntimeError):
    """policy生成・検証をfail-closedで停止させる例外。"""


def _run(cmd: list, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, check=True)


def validate_canonical_path(path: str) -> None:
    """指示書第3.3節の禁止事項をfail-closedで検証する。"""
    if not path:
        raise PolicyError("empty path")
    if path.startswith("/") or path.startswith("~"):
        raise PolicyError(f"absolute or home-relative path rejected: {path!r}")
    if "\\" in path:
        raise PolicyError(f"backslash in path rejected (non-canonical POSIX path): {path!r}")
    parts = path.split("/")
    if any(p in ("..", "") for p in parts):
        raise PolicyError(f"parent-traversal or empty path segment rejected: {path!r}")
    if unicodedata.normalize("NFC", path) != path:
        raise PolicyError(
            f"path is not NFC-normalized Unicode (normalization ambiguous): {path!r}"
        )


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _object_type_and_mode(path: Path) -> tuple[str, str]:
    st = path.lstat()
    if stat.S_ISLNK(st.st_mode):
        return "SYMLINK", "120000"
    if stat.S_ISREG(st.st_mode):
        if st.st_mode & stat.S_IXUSR:
            return "EXECUTABLE_FILE", "100755"
        return "REGULAR_FILE", "100644"
    raise PolicyError(f"unsupported filesystem object type at {path}: mode={oct(st.st_mode)}")


def _content_sha256(path: Path, object_type: str) -> str:
    if object_type == "SYMLINK":
        return hashlib.sha256(os.readlink(path).encode("utf-8")).hexdigest()
    return _file_sha256(path)


def _list_untracked(repo_root: Path) -> list[str]:
    raw = _run(["git", "status", "--porcelain=v2", "-z", "--untracked-files=all"], repo_root).stdout
    parts = raw.split(b"\x00")
    paths = []
    for rec in parts:
        if rec[:1] == b"?":
            paths.append(rec[2:].decode("utf-8", errors="surrogateescape"))
    return paths


def _classify_release_bucket(path: str) -> tuple[str, str | None]:
    """(bucket, classification) を返す。bucketは
    release_inclusion_candidate / generated_cache / secret_or_environment_file /
    excluded_audit_evidence / unknown のいずれか。分類は情報付与のみに使い、
    承認可否には使わない（指示書第3.1節）。

    実際の分類（BUILD_INPUT等）は`phase2d_release_delta_manifest.classify()`を
    単一の正本として再利用する（重複ロジックを避けるため）。secret/environment
    fileの判定は`classify()`の対象外のため、先にこのmoduleで判定する。
    """
    if manifest_mod._is_secret_filename(Path(path).name):
        return "secret_or_environment_file", None
    try:
        classification, _reason, _root = manifest_mod.classify(path)
    except manifest_mod.ManifestGenerationError:
        return "unknown", None
    if classification == "EXCLUDED_AUDIT_EVIDENCE":
        return "excluded_audit_evidence", None
    return "release_inclusion_candidate", classification


def check_no_duplicates_or_casefold_collisions(paths: list[str]) -> None:
    """指示書第3.3節: duplicate path / case-fold collision（大文字小文字だけが
    異なる複数pathが、case-insensitiveなfilesystem上でambiguousになる）を
    fail-closedで検出する。git自体はcase-sensitiveに複数pathを記録できるため、
    この検証はfilesystemの大文字小文字設定に依存せずpath文字列だけで判定できる
    （macOSのdefault case-insensitive filesystem上でも同じ結果になる）。"""
    seen_exact: dict[str, int] = {}
    seen_casefold: dict[str, list[str]] = {}
    for p in paths:
        seen_exact[p] = seen_exact.get(p, 0) + 1
        cf = p.casefold()
        seen_casefold.setdefault(cf, []).append(p)

    duplicates = sorted(p for p, c in seen_exact.items() if c > 1)
    if duplicates:
        raise PolicyError(f"duplicate untracked path(s) from git status: {duplicates}")

    casefold_collisions = {cf: ps for cf, ps in seen_casefold.items() if len(set(ps)) > 1}
    if casefold_collisions:
        raise PolicyError(
            f"case-fold path collision(s) detected (ambiguous on case-insensitive "
            f"filesystems): {casefold_collisions}"
        )


def generate_candidate_untracked_policy(repo_root: Path | None = None) -> dict:
    """release rootの概念や拡張子には一切依存せず、現在のuntracked file全件を
    列挙し、`release_inclusion_candidate`バケットのものだけをOWNER承認候補
    entryとして記録する。secret/generated cache/excludedはrejectedへ回す。

    このcandidateはRound 5Aの時点ではまだ何も承認しない —
    `generate_manifest()`（別module）は、OWNERが実際に承認したapproved policy
    とexact一致したentryだけを採用する設計に変更される（Round 5B）。
    """
    repo_root = (repo_root or REPO_ROOT).resolve()
    # Phase 2-D Round 8（P2D-OSRM-FIXTURE-CONTAMINATION対応）: candidate生成の
    # 入口でもfilesystem直接scanのcontamination gateを通す。これは
    # `phase2d_release_delta_manifest.generate_manifest()`とは独立した呼び出し
    # 経路であり、ここを素通りするとRound 7同様にOSRM runtime成果物が
    # candidate（＝OWNER提示物）へ混入し得る。
    try:
        manifest_mod._raise_if_osrm_contaminated(repo_root)
    except manifest_mod.ManifestGenerationError as exc:
        raise PolicyError(str(exc)) from exc
    head = _run(["git", "rev-parse", "HEAD"], repo_root).stdout.decode().strip()
    status_raw = _run(
        ["git", "status", "--porcelain=v2", "-z", "--untracked-files=all"], repo_root
    ).stdout
    source_status_sha256 = hashlib.sha256(status_raw).hexdigest()

    paths = _list_untracked(repo_root)
    check_no_duplicates_or_casefold_collisions(paths)

    entries = []
    rejected = []

    for path in sorted(paths):
        validate_canonical_path(path)
        bucket, classification = _classify_release_bucket(path)
        full = repo_root / path

        if bucket != "release_inclusion_candidate":
            rejected.append({"path": path, "reason": bucket})
            continue

        object_type, mode = _object_type_and_mode(full)
        sha256 = _content_sha256(full, object_type)
        size = full.lstat().st_size if object_type != "SYMLINK" else len(os.readlink(full))

        entries.append(
            {
                "path": path,
                "sha256": sha256,
                "size": size,
                "mode": mode,
                "object_type": object_type,
                "classification": classification,
                "phase_origin": "PHASE_2A_2D_UNTRACKED_CANDIDATE",
                "include_reason": (
                    "untracked file under current working tree; release inclusion is "
                    "NOT approved until an OWNER-signed approved_untracked_policy.json "
                    "explicitly matches this exact path+sha256+size+mode+object_type."
                ),
                "secret_scan_result": None,  # typed scannerが別途埋める（本moduleの責務外）
                "symlink_target": os.readlink(full) if object_type == "SYMLINK" else None,
            }
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "baseline_head": head,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_status_sha256": source_status_sha256,
        "entry_count": len(entries),
        "entries": entries,
        "rejected": rejected,
    }
    return manifest


def write_candidate_policy(policy: dict, output_path: Path) -> str:
    text = json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=False)
    text += "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# approved policy — Round 5Bで使用。load/検証ロジックのみRound 5Aで実装する。
# ---------------------------------------------------------------------------

REQUIRED_APPROVED_ENTRY_FIELDS = ("path", "sha256", "size", "mode", "object_type", "classification")


def load_approved_untracked_policy(path: Path, expected_sha256: str | None = None) -> dict:
    """approved_untracked_policy.jsonをfail-closedで読み込み・検証する。

    - `expected_sha256`が指定された場合、policy fileの生bytesのSHA-256が
      一致することを確認する（指示書第3.6節「OWNER承認済みpolicy SHA-256を
      実行引数または独立evidenceから照合」。呼び出し側がOWNERから実際に得た
      hash値をここへ明示的に渡すことで、policy fileが差し替えられていない
      ことをload時点で保証する）
    - schema_version必須
    - entriesの各要素がREQUIRED_APPROVED_ENTRY_FIELDSを全部持つ
    - path重複・parent traversal・絶対path・非NFC正規化を拒否
    - policy fileが自分自身のhashを内部へ自己記載していないこと
      （指示書第3.6節: policy fileが自分自身を承認する循環を作らない）
    """
    if not path.is_file():
        raise PolicyError(f"approved policy file not found: {path}")
    raw_bytes = path.read_bytes()
    if expected_sha256 is not None:
        actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        if actual_sha256 != expected_sha256:
            raise PolicyError(
                f"approved untracked policy file SHA-256 mismatch: "
                f"expected={expected_sha256} actual={actual_sha256}"
            )
    try:
        policy = json.loads(raw_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise PolicyError(f"approved policy file is not valid JSON: {exc}")

    if not isinstance(policy, dict) or policy.get("schema_version") != SCHEMA_VERSION:
        raise PolicyError(f"approved policy schema_version mismatch or missing: {path}")

    entries = policy.get("entries")
    if not isinstance(entries, list):
        raise PolicyError("approved policy missing entries[] list")

    seen_paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise PolicyError(f"approved policy entry is not an object: {entry!r}")
        missing = [f for f in REQUIRED_APPROVED_ENTRY_FIELDS if f not in entry]
        if missing:
            raise PolicyError(f"approved policy entry missing required field(s) {missing}: {entry}")
        validate_canonical_path(entry["path"])
        if entry["path"] in seen_paths:
            raise PolicyError(f"approved policy has duplicate path: {entry['path']!r}")
        seen_paths.add(entry["path"])

    self_hash_fields = ("self_sha256", "policy_sha256", "own_sha256")
    if any(f in policy for f in self_hash_fields):
        raise PolicyError(
            "approved policy must not self-record its own file hash inside the policy "
            "body (指示書第3.6節: policy bootstrap circularity is prohibited)"
        )

    return policy


def is_entry_approved(
    path: str,
    sha256: str,
    size: int,
    mode: str,
    object_type: str,
    classification: str,
    approved_policy: dict,
) -> bool:
    """指示書第3.5節: 1条件でも不一致なら拒否。approved directory配下へ新しい
    fileを追加しても自動承認されない（exact per-fileマッチのみ）。"""
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


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    policy = generate_candidate_untracked_policy(args.repo_root)
    sha = write_candidate_policy(policy, args.output)
    print(
        f"entry_count={policy['entry_count']} rejected_count={len(policy['rejected'])} "
        f"candidate_policy_sha256={sha}"
    )
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
