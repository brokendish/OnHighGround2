#!/usr/bin/env python3
"""
phase2d_typed_boundary_scan.py — finding type別boundary scanner
（Phase 2-D Round 5A、指示書第5.2節）。

旧実装は単一の`secret_boundary_scan()`が全finding種別を1つのlistへ混在させ、
VBF directory regexに一致するpathのfindingを種別を問わず一括suppressして
いた（"if path matches VBF regex: suppress every finding"という禁止パターン、
指示書第5.2節）。これは仮にVBF policyがabsolute pathを承認していても、その
directory内に紛れ込んだ実secretやprivate keyまで一緒に握りつぶしてしまう
危険な設計だった。

本moduleはfinding typeを8種類に分離し、各findingへline_number・
column_start・matched_value_sha256を付与する。VBF waiver（別module
`phase2d_vbf_waiver.py`）が参照できるのは`ABSOLUTE_USER_PATH`のfindingのみ
であり、他の7種別（SECRET_VALUE / PRIVATE_KEY / AUTHORIZATION_VALUE /
COOKIE_VALUE / PROHIBITED_FILE / EXTERNAL_SYMLINK / CACHE_OR_TEST_RESULT）は
VBF waiverの影響を一切受けない（指示書第5.5節）。
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

FINDING_TYPES = (
    "SECRET_VALUE",
    "PRIVATE_KEY",
    "AUTHORIZATION_VALUE",
    "COOKIE_VALUE",
    "PROHIBITED_FILE",
    "EXTERNAL_SYMLINK",
    "CACHE_OR_TEST_RESULT",
    "ABSOLUTE_USER_PATH",
)

PROHIBITED_NAME_PATTERNS = [
    re.compile(r"^\.env\.operator$"),
    re.compile(r"^\.env$"),
    re.compile(r"^\.env\.stream$"),
    re.compile(r"^\.env\.local$"),
]
SECRET_VALUE_PATTERN = re.compile(
    r"(?im)^([A-Za-z_][A-Za-z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD))[ \t]*=[ \t]*(\S[^\n]*)$"
)
PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
AUTHORIZATION_HEADER_PATTERN = re.compile(r"(?im)^\s*Authorization\s*:\s*(\S.*)$")
COOKIE_HEADER_PATTERN = re.compile(r"(?im)^\s*Cookie\s*:\s*(\S.*)$")
ABS_PATH_PATTERN = re.compile(r"/Users/[A-Za-z0-9_.\-]+|/home/[A-Za-z0-9_.\-]+")
_PLACEHOLDER_MARKERS = (
    "your_", "replace-with", "replace_with", "changeme", "xxxxx", "example",
    "placeholder", "<", "{", "$", "の値", "dummy", "do_not_use", "wrong_token",
    "os.environ[",
)
_CONFIG_KEY_PATH_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
SECRET_ALLOWED_VALUES = {"your_odpt_consumer_key_here", "your_jartic_key_here", ""}
SCAN_EXCLUDE_SUFFIXES = (
    "test_phase2d_at14_selfcheck.py",
    "test_phase2d_snapshot_selfcheck.py",
    "test_phase2d_provisioning.py",
    "test_phase2d_gsi_legacy_scripts.py",
    "test_phase2d_untracked_policy_selfcheck.py",
    "test_phase2d_typed_scanner_selfcheck.py",
    "test_phase2d_vbf_waiver_selfcheck.py",
)
UNEXPECTED_TRACKED_DIR_PATTERNS = [
    re.compile(r"(^|/)node_modules(/|$)"),
    re.compile(r"(^|/)__pycache__(/|$)"),
    re.compile(r"(^|/)\.pytest_cache(/|$)"),
    re.compile(r"(^|/)\.venv(/|$)"),
    re.compile(r"(^|/)venv(/|$)"),
    re.compile(r"(^|/)test-results(/|$)"),
    re.compile(r"(^|/)playwright-report(/|$)"),
    re.compile(r"\.trace\.zip$"),
]


def _is_placeholder_value(value: str) -> bool:
    lowered = value.lower()
    if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        return True
    return bool(_CONFIG_KEY_PATH_PATTERN.match(value))


def _run(cmd: list, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)


def _line_col_of(text: str, offset: int) -> tuple[int, int]:
    prefix = text[:offset]
    line = prefix.count("\n") + 1
    last_newline = prefix.rfind("\n")
    col = offset - last_newline  # 1-indexed column
    return line, col


def _sha256_str(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def scan_typed(root: Path, explicit_paths: list[str] | None = None) -> dict:
    """`root`（second cloneのような検証対象tree）を走査し、finding typeごとに
    分離したfindingリストを返す。各findingは
    {path, line_number, column_start, matched_value_sha256, ...} を持つ。

    `explicit_paths`が指定された場合、`git ls-files`（trackedのみ）の代わりに
    その一覧を走査対象とする。VBF waiver candidate生成（Round 5A）は、まだ
    approved policyで承認されていないためcommitされていないVBF fixture
    （untracked working tree file）の内容を直接スキャンする必要があり、この
    経路を使う（read-onlyのscanであり、repositoryへは一切書き込まない）。"""
    findings: dict[str, list[dict]] = {t: [] for t in FINDING_TYPES}

    if explicit_paths is not None:
        tracked = list(explicit_paths)
        gitlink_check_paths: list[str] = []
    else:
        ls = _run(["git", "ls-files", "-z"], root).stdout
        tracked = [p for p in ls.split("\x00") if p]

        ls_stage = _run(["git", "ls-files", "-s", "-z"], root).stdout
        gitlink_check_paths = ls_stage.split("\x00")

    for rec in gitlink_check_paths:
        if not rec:
            continue
        meta = rec.split("\t", 1)[0]
        mode = meta.split(" ")[0]
        if mode == "160000":
            path = rec.split("\t", 1)[-1]
            findings["PROHIBITED_FILE"].append(
                {
                    "path": path,
                    "line_number": None,
                    "column_start": None,
                    "matched_value_sha256": None,
                    "detail": "unexpected gitlink/submodule reference",
                }
            )

    for f in tracked:
        name = Path(f).name
        for pat in PROHIBITED_NAME_PATTERNS:
            if pat.match(name):
                findings["PROHIBITED_FILE"].append(
                    {
                        "path": f, "line_number": None, "column_start": None,
                        "matched_value_sha256": None, "detail": "prohibited filename",
                    }
                )
        for pat in UNEXPECTED_TRACKED_DIR_PATTERNS:
            if pat.search(f):
                findings["CACHE_OR_TEST_RESULT"].append(
                    {
                        "path": f, "line_number": None, "column_start": None,
                        "matched_value_sha256": None, "detail": "unexpected cache/test-result path",
                    }
                )

        full = root / f
        if full.is_symlink():
            target = os.readlink(full)
            resolved = (full.parent / target).resolve() if not target.startswith("/") else Path(target)
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                findings["EXTERNAL_SYMLINK"].append(
                    {
                        "path": f, "line_number": None, "column_start": None,
                        "matched_value_sha256": _sha256_str(target),
                        "detail": f"symlink target escapes root: {target}",
                    }
                )
            continue

        if f.endswith(SCAN_EXCLUDE_SUFFIXES):
            continue
        if not full.is_file():
            continue
        try:
            text = full.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for m in SECRET_VALUE_PATTERN.finditer(text):
            key, raw_value = m.group(1), m.group(2)
            value = raw_value.strip().strip("'\"")
            if value and value not in SECRET_ALLOWED_VALUES and not _is_placeholder_value(value):
                line, col = _line_col_of(text, m.start(2))
                findings["SECRET_VALUE"].append(
                    {
                        "path": f, "line_number": line, "column_start": col,
                        "matched_value_sha256": _sha256_str(value), "detail": key,
                    }
                )
        for m in PRIVATE_KEY_PATTERN.finditer(text):
            line, col = _line_col_of(text, m.start())
            findings["PRIVATE_KEY"].append(
                {
                    "path": f, "line_number": line, "column_start": col,
                    "matched_value_sha256": _sha256_str(m.group(0)), "detail": "PEM private key header",
                }
            )
        for m in AUTHORIZATION_HEADER_PATTERN.finditer(text):
            value = m.group(1).strip()
            if value and not _is_placeholder_value(value):
                line, col = _line_col_of(text, m.start(1))
                findings["AUTHORIZATION_VALUE"].append(
                    {
                        "path": f, "line_number": line, "column_start": col,
                        "matched_value_sha256": _sha256_str(value), "detail": "Authorization header",
                    }
                )
        for m in COOKIE_HEADER_PATTERN.finditer(text):
            value = m.group(1).strip()
            if value and not _is_placeholder_value(value):
                line, col = _line_col_of(text, m.start(1))
                findings["COOKIE_VALUE"].append(
                    {
                        "path": f, "line_number": line, "column_start": col,
                        "matched_value_sha256": _sha256_str(value), "detail": "Cookie header",
                    }
                )
        for m in ABS_PATH_PATTERN.finditer(text):
            value = m.group(0)
            line, col = _line_col_of(text, m.start())
            findings["ABSOLUTE_USER_PATH"].append(
                {
                    "path": f, "line_number": line, "column_start": col,
                    "matched_value_sha256": _sha256_str(value), "detail": "absolute developer path",
                }
            )

    return findings


def findings_ok(findings: dict) -> bool:
    return all(not v for v in findings.values())
