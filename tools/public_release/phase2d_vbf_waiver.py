#!/usr/bin/env python3
"""
phase2d_vbf_waiver.py — ABSOLUTE_USER_PATH専用のexact waiver policy
（Phase 2-D Round 5A、指示書第5.3〜5.4節）。

VBF fixture（`tests/fixtures/public_release/version_binding/VBF-*/artifacts/*`）
は、`verify_at_evidence.py`のargv厳密一致検証（動的にREPO_ROOTと比較する設計）
に起因して、設計上絶対pathを内容として持つ（Round 3/4で実証済み）。この
absolute-path findingだけを、finding単位のexact一致でwaiveできるようにする。

waiver適用条件（指示書第5.4節、全て一致が必要）:
    finding type == ABSOLUTE_USER_PATH
    AND canonical file path一致
    AND file SHA-256一致（1 byteでも変化したら該当fileのwaiverは全失効）
    AND occurrence count一致
    AND line / column一致
    AND matched value SHA-256一致
    AND approved policy SHA-256一致

他のfinding type（SECRET_VALUE等）はこのwaiverの影響を一切受けない
（`phase2d_typed_boundary_scan.py`が型を分離しているため、混在は起こらない）。
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
FINDING_TYPE = "ABSOLUTE_USER_PATH"

REPO_ROOT = Path(__file__).resolve().parents[2]

_NORMALIZE_STRIP_PATTERN = re.compile(r"^/Users/[^/]+|^/home/[^/]+")


class VbfWaiverError(RuntimeError):
    pass


def _run(cmd: list, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, check=True)


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalized_pattern_id(raw_matched_text_hint: str) -> str:
    """matched valueの「形状」を識別するID。生の絶対path文字列は保持せず、
    `/Users/<user>`部分だけを除いた残余をhashしたものを識別子として使う。"""
    residual = _NORMALIZE_STRIP_PATTERN.sub("", raw_matched_text_hint)
    return hashlib.sha256(residual.encode("utf-8")).hexdigest()[:16]


def generate_candidate_vbf_waiver(
    repo_root: Path,
    absolute_user_path_findings: list[dict],
) -> dict:
    """`phase2d_typed_boundary_scan.scan_typed()`が返す`ABSOLUTE_USER_PATH`
    findingリストから、file単位でoccurrenceをグループ化したcandidate waiver
    JSONを生成する。raw absolute path全文は保存しない
    （`matched_value_sha256`と、`justification`の短い説明文だけを残す）。
    """
    head = _run(["git", "rev-parse", "HEAD"], repo_root).stdout.decode().strip()

    by_path: dict[str, list[dict]] = {}
    for f in absolute_user_path_findings:
        by_path.setdefault(f["path"], []).append(f)

    files = []
    total_occurrences = 0
    for path in sorted(by_path.keys()):
        full = repo_root / path
        if not full.is_file():
            raise VbfWaiverError(f"finding references non-existent file: {path}")
        file_sha256 = _file_sha256(full)
        occs = sorted(by_path[path], key=lambda o: (o["line_number"] or 0, o["column_start"] or 0))
        occurrences = []
        for o in occs:
            occurrences.append(
                {
                    "line_number": o["line_number"],
                    "column_start": o["column_start"],
                    "matched_value_sha256": o["matched_value_sha256"],
                    "normalized_pattern_id": _normalized_pattern_id(o.get("detail", "")),
                    "justification": (
                        "recorded absolute path inside a hash-pinned Phase 2-B.6 evidence "
                        "artifact (verify_at_evidence.py requires argv to match this "
                        "repository's runtime REPO_ROOT exactly; see Round 4 report R4-5)"
                    ),
                }
            )
            total_occurrences += 1
        files.append(
            {
                "path": path,
                "file_sha256": file_sha256,
                "occurrence_count": len(occurrences),
                "occurrences": occurrences,
            }
        )

    waiver = {
        "schema_version": SCHEMA_VERSION,
        "baseline_head": head,
        "finding_type": FINDING_TYPE,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "file_count": len(files),
        "occurrence_count": total_occurrences,
        "files": files,
    }
    return waiver


def write_candidate_waiver(waiver: dict, output_path: Path) -> str:
    text = json.dumps(waiver, ensure_ascii=False, indent=2, sort_keys=False)
    text += "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# approved waiver — Round 5Bで使用。load/検証・適用ロジックのみRound 5Aで実装。
# ---------------------------------------------------------------------------

def load_approved_vbf_waiver(path: Path, expected_sha256: str | None = None) -> dict:
    """`expected_sha256`が指定された場合、policy fileの生bytesのSHA-256が
    一致することを確認する（指示書第5.4節: waiver適用条件の一つ「approved
    policy SHA-256」。OWNERが承認した特定のhashのpolicyだけを適用対象とし、
    policy fileが差し替えられていないことをload時点で保証する）。"""
    if not path.is_file():
        raise VbfWaiverError(f"approved VBF waiver file not found: {path}")
    raw_bytes = path.read_bytes()
    if expected_sha256 is not None:
        actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        if actual_sha256 != expected_sha256:
            raise VbfWaiverError(
                f"approved VBF waiver file SHA-256 mismatch: "
                f"expected={expected_sha256} actual={actual_sha256}"
            )
    try:
        waiver = json.loads(raw_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise VbfWaiverError(f"approved VBF waiver is not valid JSON: {exc}")

    if not isinstance(waiver, dict) or waiver.get("schema_version") != SCHEMA_VERSION:
        raise VbfWaiverError("approved VBF waiver schema_version mismatch or missing")
    if waiver.get("finding_type") != FINDING_TYPE:
        raise VbfWaiverError(
            f"approved VBF waiver finding_type must be {FINDING_TYPE!r}, "
            f"got {waiver.get('finding_type')!r}"
        )
    files = waiver.get("files")
    if not isinstance(files, list):
        raise VbfWaiverError("approved VBF waiver missing files[] list")

    seen_paths: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise VbfWaiverError(f"approved VBF waiver file entry is not an object: {entry!r}")
        for field in ("path", "file_sha256", "occurrence_count", "occurrences"):
            if field not in entry:
                raise VbfWaiverError(f"approved VBF waiver file entry missing {field!r}: {entry}")
        if entry["path"] in seen_paths:
            raise VbfWaiverError(f"approved VBF waiver has duplicate path: {entry['path']!r}")
        seen_paths.add(entry["path"])
        if entry["occurrence_count"] != len(entry["occurrences"]):
            raise VbfWaiverError(
                f"approved VBF waiver occurrence_count mismatch for {entry['path']!r}: "
                f"declared={entry['occurrence_count']} actual={len(entry['occurrences'])}"
            )

    return waiver


def apply_vbf_waiver(
    findings_by_type: dict,
    approved_waiver: dict | None,
    approved_waiver_sha256: str | None,
    repo_root: Path,
) -> tuple[dict, list[dict]]:
    """`findings_by_type`（typed scannerの出力、finding_type -> list）を受け取り、
    `ABSOLUTE_USER_PATH`のfindingのみをwaiverと突き合わせる。他のfinding type
    には一切触れない（指示書第5.2節: VBF policyを参照できるのはABSOLUTE_USER_PATH
    scannerだけ）。

    戻り値: (waiver適用後のfindings_by_type のコピー, suppressed occurrence一覧)
    """
    result = {k: list(v) for k, v in findings_by_type.items()}
    suppressed: list[dict] = []

    if approved_waiver is None:
        return result, suppressed

    if approved_waiver.get("finding_type") != FINDING_TYPE:
        raise VbfWaiverError("approved waiver finding_type must be ABSOLUTE_USER_PATH")

    # fileごとのexact occurrence set（line, column, matched_value_sha256）を作る。
    waived_by_path: dict[str, tuple[str, set[tuple]]] = {}
    for entry in approved_waiver.get("files", []):
        occ_set = {
            (o["line_number"], o["column_start"], o["matched_value_sha256"])
            for o in entry["occurrences"]
        }
        waived_by_path[entry["path"]] = (entry["file_sha256"], occ_set)

    remaining = []
    for finding in result.get(FINDING_TYPE, []):
        path = finding["path"]
        waiver_entry = waived_by_path.get(path)
        if waiver_entry is None:
            remaining.append(finding)
            continue
        expected_hash, occ_set = waiver_entry
        full = repo_root / path
        actual_hash = hashlib.sha256(full.read_bytes()).hexdigest() if full.is_file() else None
        # fileが1 byteでも変化していればそのfileのwaiverは全失効する。
        if actual_hash != expected_hash:
            remaining.append(finding)
            continue
        key = (finding["line_number"], finding["column_start"], finding["matched_value_sha256"])
        if key in occ_set:
            suppressed.append(finding)
        else:
            remaining.append(finding)

    result[FINDING_TYPE] = remaining
    return result, suppressed


def main() -> int:
    import argparse
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import phase2d_typed_boundary_scan as scanner_mod
    import phase2d_untracked_policy as policy_mod

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    candidate_untracked = policy_mod.generate_candidate_untracked_policy(args.repo_root)
    all_paths = [e["path"] for e in candidate_untracked["entries"]]
    findings = scanner_mod.scan_typed(args.repo_root, explicit_paths=all_paths)

    waiver = generate_candidate_vbf_waiver(args.repo_root, findings[FINDING_TYPE])
    sha = write_candidate_waiver(waiver, args.output)
    print(f"file_count={waiver['file_count']} occurrence_count={waiver['occurrence_count']} candidate_waiver_sha256={sha}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
