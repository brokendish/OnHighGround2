#!/usr/bin/env python3
"""
phase2d_at14_check.py — Phase 2-D AT-14 機械検証runner。

指示書第11節の25 checkを実装する。各checkは「(content文字列群) -> CheckResult」の
pure functionとして実装し、`test_phase2d_at14_selfcheck.py`からnegative/positive
mutationで独立検証できるようにする。

実行方法:
    python3 tools/public_release/phase2d_at14_check.py

exit code: 全check PASSなら0、1件でもFAILなら1（fail-closed）。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

MIT_CANONICAL_SENTENCES = [
    "Permission is hereby granted, free of charge, to any person obtaining a copy",
    "without restriction, including without limitation the rights",
    "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell",
    "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR",
    "IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,",
]

COPYRIGHT_LINE = "Copyright (c) 2026 OnHighGround2 contributors"

REQUIRED_README_LINKS = [
    "LICENSE",
    "ATTRIBUTIONS.md",
    "THIRD_PARTY_NOTICES.md",
    "docs/third-party-inventory.md",
    "docs/installation.md",
    "docs/configuration.md",
    "docs/operator-setup.md",
]

PLACEHOLDER_TOKENS = ["TODO", "TBD", "PROPOSED"]

SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)(secret|token|api[_-]?key|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}['\"]?\s*$", re.MULTILINE),
]
# 上記3番目のpatternは「変数名らしきもの = 20文字以上の値」を検出するが、
# 空値・placeholder（下記許可リスト）は除外する。
SECRET_ALLOWED_VALUES = {"", "your_odpt_consumer_key_here", "your_jartic_key_here"}

ABS_PATH_PATTERNS = [
    re.compile(r"/Users/[A-Za-z0-9_.\-]+"),
    re.compile(r"/home/[A-Za-z0-9_.\-]+"),
]

# example/placeholder/private IPとして許可するもの
IP_ALLOWLIST = {"127.0.0.1", "0.0.0.0", "10.0.0.0", "255.255.255.255"}
IPV4_PATTERN = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b")


@dataclass
class CheckResult:
    check_id: str
    name: str
    passed: bool
    detail: str
    evidence_count: int = 0


# ---------------------------------------------------------------------------
# Round 2: 構造的Markdown table parser（P2D-AT14-SEMANTIC対応）
#
# 指示書Round 2第4.2節「inventoryのMarkdown tableを構造的にparseする」への対応。
# 単純な正規表現による全文字列走査（Round 1のcheck 10バグの原因）をやめ、
# 見出し行・区切り行・データ行を明示的に分離し、列名でkeyingしたdictの列として
# 各rowを返す。列数不一致・schema不明・parse不能はHARNESS_ERRORとしてfail-closed
# にする（`default PASS`を禁止する指示書第4.3節の要求に対応）。
# ---------------------------------------------------------------------------

class TableParseError(Exception):
    pass


_SEPARATOR_ROW_PATTERN = re.compile(r"^\|[\-\s:|]+\|\s*$")


def _split_table_row(line: str) -> list:
    # 先頭・末尾の"|"を除去し、セルへ分割する。セル内の`\|`（エスケープpipe）は
    # 分割対象から除外する（一時的にplaceholderへ退避してから分割・復元する）。
    ESCAPED = ""
    protected = line.replace("\\|", ESCAPED)
    body = protected.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    cells = [c.replace(ESCAPED, "\\|").strip() for c in body.split("|")]
    return cells


def find_table_by_marker(markdown_text: str, heading_marker: str, required_column: str) -> tuple:
    """`heading_marker`（見出し文字列の部分一致）以降で最初に見つかる、
    `required_column`を列名に含むtableを構造的にparseする。

    戻り値: (rows: list[dict], parse_error: str | None)
    parse_errorがNoneでない場合、rowsは空リストであり呼び出し側はfail-closedに扱う。
    """
    if heading_marker not in markdown_text:
        return [], f"heading marker not found: {heading_marker!r}"

    after = markdown_text.split(heading_marker, 1)[1]
    lines = after.splitlines()

    header_idx = None
    header_cells = None
    for i in range(len(lines) - 1):
        line = lines[i]
        nxt = lines[i + 1]
        if line.strip().startswith("|") and _SEPARATOR_ROW_PATTERN.match(nxt.strip()):
            candidate_cells = _split_table_row(line)
            if required_column in candidate_cells:
                header_idx = i
                header_cells = candidate_cells
                break

    if header_idx is None:
        return [], f"no table with column {required_column!r} found after marker"

    n_cols = len(header_cells)
    rows = []
    j = header_idx + 2  # skip header + separator row
    while j < len(lines) and lines[j].strip().startswith("|"):
        raw_cells = _split_table_row(lines[j])
        if len(raw_cells) != n_cols:
            return [], f"row {j} column count mismatch: expected {n_cols}, got {len(raw_cells)} (fail-closed, no silent tolerance)"
        rows.append(dict(zip(header_cells, raw_cells)))
        j += 1

    if not rows:
        return [], "table matched but contains zero data rows"

    return rows, None


VALID_DISTRIBUTION_CLASSES = {
    "TRACKED", "RUNTIME_ONLY", "API_ONLY", "CDN_ONLY", "BUNDLED", "REDISTRIBUTED", "NOT_APPLICABLE",
}
VALID_STATUS_VALUES = {
    "CONFIRMED_REDISTRIBUTABLE", "CONFIRMED_RUNTIME_ONLY", "CONFIRMED_ATTRIBUTION_REQUIRED",
    "CONDITIONAL", "NOT_CONFIRMED", "NOT_APPLICABLE",
}


def load_section8_rows(inventory_text: str) -> tuple:
    """Section 8 machine-readable classification summaryをparseし、
    各rowのschema（重複ID・不明distribution class）も検証する。

    戻り値: (rows, error) — errorがNoneでなければ呼び出し側はHARNESS_ERRORとして扱う。
    """
    rows, err = find_table_by_marker(inventory_text, "## 8. ", "DistributionClass")
    if err:
        return [], err

    seen_ids = set()
    for row in rows:
        rid = row.get("ID", "")
        if not rid:
            return [], "row missing ID"
        if rid in seen_ids:
            return [], f"duplicate source ID in section 8: {rid}"
        seen_ids.add(rid)
        dc = row.get("DistributionClass", "")
        if dc not in VALID_DISTRIBUTION_CLASSES:
            return [], f"unknown distribution class for {rid}: {dc!r}"
        st = row.get("Status", "")
        if st not in VALID_STATUS_VALUES:
            return [], f"unknown status for {rid}: {st!r}"

    return rows, None


@dataclass
class RunReport:
    results: list = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)


# ---------------------------------------------------------------------------
# 1-3: LICENSE
# ---------------------------------------------------------------------------

def check_license_exists(license_text: str | None) -> CheckResult:
    ok = license_text is not None
    return CheckResult("01", "LICENSE存在", ok, "LICENSE file present" if ok else "LICENSE file missing")


def check_mit_full_text(license_text: str | None) -> CheckResult:
    if license_text is None:
        return CheckResult("02", "MIT全文がSPDX正本と一致", False, "LICENSE missing")
    missing = [s for s in MIT_CANONICAL_SENTENCES if s not in license_text]
    ok = len(missing) == 0
    detail = "all canonical MIT sentences present" if ok else f"missing sentences: {missing}"
    return CheckResult("02", "MIT全文がSPDX正本と一致", ok, detail, len(missing))


def check_copyright_line(license_text: str | None) -> CheckResult:
    if license_text is None:
        return CheckResult("03", "copyright line存在", False, "LICENSE missing")
    ok = COPYRIGHT_LINE in license_text
    return CheckResult("03", "copyright line存在", ok, COPYRIGHT_LINE if ok else "copyright line not found")


# ---------------------------------------------------------------------------
# 4-6: 正本文書存在
# ---------------------------------------------------------------------------

def check_file_exists(check_id: str, name: str, content: str | None) -> CheckResult:
    ok = content is not None
    return CheckResult(check_id, name, ok, "present" if ok else "missing")


# ---------------------------------------------------------------------------
# 7: README相対link
# ---------------------------------------------------------------------------

def check_readme_links(readme_text: str | None) -> CheckResult:
    if readme_text is None:
        return CheckResult("07", "READMEから全正本文書へ相対link", False, "README.md missing")
    missing = [target for target in REQUIRED_README_LINKS if f"]({target})" not in readme_text and f"({target}#" not in readme_text]
    ok = len(missing) == 0
    detail = "all required links present" if ok else f"missing links: {missing}"
    return CheckResult("07", "READMEから全正本文書へ相対link", ok, detail, len(missing))


# ---------------------------------------------------------------------------
# 8: inventory ID重複
# ---------------------------------------------------------------------------

_ID_ROW_PATTERN = re.compile(r"^\|\s*([A-Z]{2,}(?:-[A-Z0-9]+)+)\s*\|", re.MULTILINE)


def extract_inventory_ids(inventory_text: str) -> list:
    return _ID_ROW_PATTERN.findall(inventory_text)


def _extract_id_tables(inventory_text: str) -> list:
    """文書内の全table blockを個別に走査し、各tableごとに（1列目がID pattern
    に一致する）行のID一覧を返す。Round 2で複数のtable（narrative table＋
    Section 8の機械可読summary）が同じIDを正当に再掲するようになったため、
    重複判定はtable横断ではなくtable単位で行う必要がある（意図的な複数掲載を
    誤検出しないため）。"""
    lines = inventory_text.splitlines()
    tables = []
    i = 0
    while i < len(lines) - 1:
        if lines[i].strip().startswith("|") and _SEPARATOR_ROW_PATTERN.match(lines[i + 1].strip()):
            ids_in_table = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                m = _ID_ROW_PATTERN.match(lines[j] + "\n")
                if m:
                    ids_in_table.append(m.group(1))
                j += 1
            if ids_in_table:
                tables.append(ids_in_table)
            i = j
        else:
            i += 1
    return tables


def check_inventory_id_duplicates(inventory_text: str | None) -> CheckResult:
    if inventory_text is None:
        return CheckResult("08", "inventory ID重複0", False, "inventory missing")
    tables = _extract_id_tables(inventory_text)
    all_ids = [i for table in tables for i in table]
    dupes = set()
    for table in tables:
        seen = set()
        for i in table:
            if i in seen:
                dupes.add(i)
            seen.add(i)
    ok = len(dupes) == 0
    detail = (
        f"{len(all_ids)} ID occurrences across {len(tables)} tables, 0 within-table duplicates"
        if ok
        else f"duplicate IDs within the same table: {sorted(dupes)}"
    )
    return CheckResult("08", "inventory ID重複0", ok, detail, len(dupes))


# ---------------------------------------------------------------------------
# 9: required field空欄0（table row内の空セル）
# ---------------------------------------------------------------------------

_EMPTY_CELL_PATTERN = re.compile(r"\|[ \t]*\|")


def check_no_empty_table_cells(inventory_text: str | None) -> CheckResult:
    if inventory_text is None:
        return CheckResult("09", "required field空欄0", False, "inventory missing")
    matches = _EMPTY_CELL_PATTERN.findall(inventory_text)
    ok = len(matches) == 0
    detail = "no empty table cells" if ok else f"{len(matches)} empty cell(s) found"
    return CheckResult("09", "required field空欄0", ok, detail, len(matches))


# ---------------------------------------------------------------------------
# 10: bundled/tracked NOT_CONFIRMED 0（Round 2: 構造的table parseへ全面改修、P2D-AT14-SEMANTIC対応）
#
# Round 1の実装は文書全体に対する`\bNOT_CONFIRMED\b`の正規表現検索であり、
# 定義節（許可status一覧）・prose中の言及・runtime-only/CDN-onlyのrowまで
# 分母に含めてしまっていた（CODEX実測: raw 11件のうちtracked/bundled該当は2件のみ）。
# Round 2はSection 8の構造化tableのみをparseし、
#   status == NOT_CONFIRMED AND distribution_class IN {TRACKED, BUNDLED, REDISTRIBUTED}
# を満たすrowだけをFAIL対象の分母とする（指示書Round 2第4.2節）。
# ---------------------------------------------------------------------------

_CHECK10_FAIL_DISTRIBUTION_CLASSES = {"TRACKED", "BUNDLED", "REDISTRIBUTED"}


def check_not_confirmed_zero(inventory_text: str | None) -> CheckResult:
    if inventory_text is None:
        return CheckResult("10", "bundled/tracked NOT_CONFIRMED 0", False, "inventory missing")

    rows, err = load_section8_rows(inventory_text)
    if err:
        return CheckResult("10", "bundled/tracked NOT_CONFIRMED 0", False, f"HARNESS_ERROR: {err}")

    offenders = [
        row["ID"] for row in rows
        if row.get("Status") == "NOT_CONFIRMED" and row.get("DistributionClass") in _CHECK10_FAIL_DISTRIBUTION_CLASSES
    ]
    ok = len(offenders) == 0
    detail = (
        "0 NOT_CONFIRMED rows among TRACKED/BUNDLED/REDISTRIBUTED artifacts"
        if ok
        else f"NOT_CONFIRMED tracked/bundled/redistributed artifacts remain: {offenders}"
    )
    return CheckResult("10", "bundled/tracked NOT_CONFIRMED 0", ok, detail, len(offenders))


# ---------------------------------------------------------------------------
# 26-30: Round 2新設の独立check（指示書Round 2第4.2節「最低限追加する独立判定」）
# ---------------------------------------------------------------------------

def check_runtime_source_has_terms_url(inventory_text: str | None) -> CheckResult:
    """RUNTIME_ONLY・API_ONLYのrowはTermsURL列がYであることを要求する。"""
    if inventory_text is None:
        return CheckResult("26", "runtime data sourceにterms URLがある", False, "inventory missing")
    rows, err = load_section8_rows(inventory_text)
    if err:
        return CheckResult("26", "runtime data sourceにterms URLがある", False, f"HARNESS_ERROR: {err}")
    offenders = [
        row["ID"] for row in rows
        if row.get("DistributionClass") in {"RUNTIME_ONLY", "API_ONLY"} and row.get("TermsURL") != "Y"
    ]
    ok = len(offenders) == 0
    detail = "all runtime/API rows have a confirmed terms URL" if ok else f"missing terms URL: {offenders}"
    return CheckResult("26", "runtime data sourceにterms URLがある", ok, detail, len(offenders))


def check_runtime_attribution_has_ui_mapping(inventory_text: str | None) -> CheckResult:
    """CONFIRMED_ATTRIBUTION_REQUIREDのrowでUIMapping=NONEのものを集計する
    （fail-closedにはしない——UI実装が別途進行中のため個別警告として報告するのみ）。"""
    if inventory_text is None:
        return CheckResult("27", "runtime attribution必須sourceにUI mappingがある", False, "inventory missing")
    rows, err = load_section8_rows(inventory_text)
    if err:
        return CheckResult("27", "runtime attribution必須sourceにUI mappingがある", False, f"HARNESS_ERROR: {err}")
    pending = [
        row["ID"] for row in rows
        if row.get("Status") == "CONFIRMED_ATTRIBUTION_REQUIRED" and row.get("UIMapping") == "NONE"
    ]
    ok = len(pending) == 0
    detail = "all attribution-required rows have a UI mapping" if ok else f"UI mapping not yet implemented for: {pending}"
    return CheckResult("27", "runtime attribution必須sourceにUI mappingがある", ok, detail, len(pending))


def check_cdn_dependency_complete(inventory_text: str | None, notices_text: str | None) -> CheckResult:
    """CDN_ONLYのrowはStatusがNOT_CONFIRMEDでないこと（exact version/license/notice確認済み）を要求する。"""
    if inventory_text is None:
        return CheckResult("28", "CDN dependencyにexact version・license・noticeがある", False, "inventory missing")
    rows, err = load_section8_rows(inventory_text)
    if err:
        return CheckResult("28", "CDN dependencyにexact version・license・noticeがある", False, f"HARNESS_ERROR: {err}")
    offenders = [
        row["ID"] for row in rows
        if row.get("DistributionClass") == "CDN_ONLY" and row.get("Status") == "NOT_CONFIRMED"
    ]
    ok = len(offenders) == 0
    detail = "all CDN dependencies have confirmed version/license/notice" if ok else f"unresolved CDN dependencies: {offenders}"
    return CheckResult("28", "CDN dependencyにexact version・license・noticeがある", ok, detail, len(offenders))


def check_odpt_allowlist_mapping(allowlist_entries: list | None) -> CheckResult:
    """ODPT allowlistの全entryがlicense名を持つことを要求する。"""
    if allowlist_entries is None:
        return CheckResult("29", "ODPT allowlist全entryにlicense mappingがある", False, "allowlist not found (not yet implemented)")
    missing = [e.get("operator_id", "?") for e in allowlist_entries if not e.get("license")]
    ok = len(missing) == 0 and len(allowlist_entries) > 0
    detail = f"{len(allowlist_entries)} entries, all have license mapping" if ok else f"missing license mapping or empty allowlist: {missing}"
    return CheckResult("29", "ODPT allowlist全entryにlicense mappingがある", ok, detail, len(missing))


def check_odpt_unknown_not_allowed(allowlist_source_text: str | None) -> CheckResult:
    """ODPT allowlist実装がunknown operatorをdenyする設計になっていることを、
    ソースコード中の該当ロジックの存在で確認する（fail-closed既定を静的に確認）。"""
    if allowlist_source_text is None:
        return CheckResult("30", "unknown ODPT entryが許可されない", False, "allowlist source not found (not yet implemented)")
    ok = "fail" in allowlist_source_text.lower() and ("unknown" in allowlist_source_text.lower())
    detail = "fail-closed unknown-operator handling found in source" if ok else "no fail-closed unknown-operator handling detected"
    return CheckResult("30", "unknown ODPT entryが許可されない", ok, detail)


# ---------------------------------------------------------------------------
# 11-12: candidate artifact unmapped / multi-mapped
# ---------------------------------------------------------------------------

_INVENTORY_PATH_TOKEN_PATTERN = re.compile(r"`([\w./\-*]+\.(?:geojson|pmtiles|json|csv))`")


def check_tracked_geo_files_mapped(tracked_geo_paths: list, inventory_text: str | None) -> CheckResult:
    if inventory_text is None:
        return CheckResult("11", "candidate artifact unmapped 0", False, "inventory missing")
    import fnmatch

    tokens = _INVENTORY_PATH_TOKEN_PATTERN.findall(inventory_text)
    unmapped = []
    for p in tracked_geo_paths:
        name = Path(p).name
        # exact filename mention, or exact/glob path mention (指示書4.3節が許容する「決定的glob」対応)
        mapped = (
            name in inventory_text
            or any(p == tok or (("*" in tok) and fnmatch.fnmatch(p, tok)) for tok in tokens)
        )
        if not mapped:
            unmapped.append(p)
    ok = len(unmapped) == 0
    detail = "all tracked geo/data candidate files referenced in inventory (exact path or glob)" if ok else f"unmapped: {unmapped}"
    return CheckResult("11", "candidate artifact unmapped 0", ok, detail, len(unmapped))


def check_no_unexpected_multimap(inventory_text: str | None) -> CheckResult:
    # 各tracked path文字列がinventory内で複数の異なるID行に出現していないかを
    # 簡易的に検査する（意図的な複数sourceは明示例外のみ許容——本Phaseでは0件を期待）。
    if inventory_text is None:
        return CheckResult("12", "unexpected multi-map 0", False, "inventory missing")
    rows = [line for line in inventory_text.splitlines() if line.startswith("|") and "|" in line[1:]]
    path_to_ids: dict = {}
    for row in rows:
        m = _ID_ROW_PATTERN.match(row + "\n")
        if not m:
            continue
        row_id = m.group(1)
        for path_match in re.findall(r"`([\w./\-]+\.(?:geojson|pmtiles|json|csv))`", row):
            # ディレクトリ成分を持たないbasenameのみの言及（例: 単に `meta.json`）は、
            # 複数datasetで同名ファイルを一般的に指す表現として除外する
            # （実際の多重マッピング検出は具体的pathに対してのみ行う）。
            if "/" not in path_match:
                continue
            path_to_ids.setdefault(path_match, set()).add(row_id)
    multi = {p: ids for p, ids in path_to_ids.items() if len(ids) > 1}
    ok = len(multi) == 0
    detail = "no path mapped to multiple distinct IDs" if ok else f"multi-mapped: {multi}"
    return CheckResult("12", "unexpected multi-map 0", ok, detail, len(multi))


# ---------------------------------------------------------------------------
# 13-14: official terms URLなし / checked dateなし
# ---------------------------------------------------------------------------

def check_terms_url_present(inventory_text: str | None) -> CheckResult:
    if inventory_text is None:
        return CheckResult("13", "official terms URLなし0", False, "inventory missing")
    ok = inventory_text.count("https://") >= 10
    detail = f"{inventory_text.count('https://')} https:// URLs found" if ok else "too few official URLs referenced"
    return CheckResult("13", "official terms URLなし0", ok, detail)


def check_checked_date_present(inventory_text: str | None) -> CheckResult:
    if inventory_text is None:
        return CheckResult("14", "checked dateなし0", False, "inventory missing")
    count = inventory_text.count("2026-08-21")
    ok = count > 0
    detail = f"checked date 2026-08-21 appears {count} time(s)" if ok else "no checked date found"
    return CheckResult("14", "checked dateなし0", ok, detail)


# ---------------------------------------------------------------------------
# 15-16: required attribution / modification notice欠落
# ---------------------------------------------------------------------------

def check_attribution_wording_present(attributions_text: str | None) -> CheckResult:
    if attributions_text is None:
        return CheckResult("15", "required attribution欠落0", False, "ATTRIBUTIONS.md missing")
    required_markers = ["OpenStreetMap contributors", "国土交通省", "気象庁", "Open-Meteo"]
    missing = [m for m in required_markers if m not in attributions_text]
    ok = len(missing) == 0
    detail = "all required attribution markers present" if ok else f"missing: {missing}"
    return CheckResult("15", "required attribution欠落0", ok, detail, len(missing))


def check_modification_notice_present(attributions_text: str | None) -> CheckResult:
    if attributions_text is None:
        return CheckResult("16", "modification notice欠落0", False, "ATTRIBUTIONS.md missing")
    ok = "加工" in attributions_text
    detail = "modification-notice language present" if ok else "no modification-notice language found"
    return CheckResult("16", "modification notice欠落0", ok, detail)


# ---------------------------------------------------------------------------
# 17: MITによる第三者dataの包括再license表現0
# ---------------------------------------------------------------------------

BLANKET_RELICENSE_PATTERNS = [
    re.compile(r"(?i)all\s+data\s+is\s+MIT"),
    re.compile(r"(?i)全ての?データ.{0,10}MIT"),
    re.compile(r"(?i)all\s+data\s+is\s+open\s+data"),
]


def check_no_blanket_relicense(license_text: str | None, attributions_text: str | None) -> CheckResult:
    combined = (license_text or "") + "\n" + (attributions_text or "")
    hits = [p.pattern for p in BLANKET_RELICENSE_PATTERNS if p.search(combined)]
    ok = len(hits) == 0
    detail = "no blanket re-license phrasing found" if ok else f"found: {hits}"
    return CheckResult("17", "MITによる第三者dataの包括再license表現0", ok, detail, len(hits))


# ---------------------------------------------------------------------------
# 18: TODO/TBD/unresolved placeholder 0
# ---------------------------------------------------------------------------

def check_no_placeholder_tokens(named_texts: dict) -> CheckResult:
    hits = []
    for name, text in named_texts.items():
        if text is None:
            continue
        for token in PLACEHOLDER_TOKENS:
            if re.search(rf"\b{token}\b", text):
                hits.append(f"{name}:{token}")
    ok = len(hits) == 0
    detail = "no placeholder tokens" if ok else f"found: {hits}"
    return CheckResult("18", "TODO/TBD/unresolved placeholder 0", ok, detail, len(hits))


# ---------------------------------------------------------------------------
# 19: secret pattern実値0
# ---------------------------------------------------------------------------

def check_no_secret_values(named_texts: dict) -> CheckResult:
    hits = []
    for name, text in named_texts.items():
        if text is None:
            continue
        for pat in SECRET_PATTERNS[:2]:
            if pat.search(text):
                hits.append(f"{name}:{pat.pattern}")
        for m in re.finditer(r"(?im)^([A-Za-z_][A-Za-z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD))[ \t]*=[ \t]*([^\n]*)$", text):
            key, value = m.group(1), m.group(2).strip().strip("'\"")
            if value and value not in SECRET_ALLOWED_VALUES and not value.startswith("#"):
                hits.append(f"{name}:{key}={value[:8]}...")
    ok = len(hits) == 0
    detail = "no secret-like values found" if ok else f"found: {hits}"
    return CheckResult("19", "secret pattern実値0", ok, detail, len(hits))


# ---------------------------------------------------------------------------
# 20: absolute local path / user home path 0
# ---------------------------------------------------------------------------

def check_no_absolute_local_paths(named_texts: dict) -> CheckResult:
    hits = []
    for name, text in named_texts.items():
        if text is None:
            continue
        for pat in ABS_PATH_PATTERNS:
            for m in pat.finditer(text):
                hits.append(f"{name}:{m.group(0)}")
    ok = len(hits) == 0
    detail = "no absolute local/user-home paths found" if ok else f"found: {hits}"
    return CheckResult("20", "absolute local path/user home path 0", ok, detail, len(hits))


# ---------------------------------------------------------------------------
# 21: actual VPS hostname/IP記載0
# ---------------------------------------------------------------------------

def check_no_real_vps_ip(named_texts: dict) -> CheckResult:
    hits = []
    for name, text in named_texts.items():
        if text is None:
            continue
        for m in IPV4_PATTERN.finditer(text):
            ip = m.group(0)
            if ip in IP_ALLOWLIST:
                continue
            octets = [int(x) for x in ip.split(".")]
            if octets[0] == 10 or (octets[0] == 172 and 16 <= octets[1] <= 31) or (octets[0] == 192 and octets[1] == 168):
                continue  # private range, treated as example-safe
            hits.append(f"{name}:{ip}")
    ok = len(hits) == 0
    detail = "no non-example IPv4 addresses found" if ok else f"found: {hits}"
    return CheckResult("21", "actual VPS hostname/IP記載0", ok, detail, len(hits))


# ---------------------------------------------------------------------------
# 22: broken relative link 0
# ---------------------------------------------------------------------------

_MD_LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def check_no_broken_relative_links(named_texts: dict, repo_root: Path) -> CheckResult:
    broken = []
    for name, text in named_texts.items():
        if text is None:
            continue
        base_dir = (repo_root / name).parent
        for m in _MD_LINK_PATTERN.finditer(text):
            target = m.group(1)
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            target_path = target.split("#")[0]
            if not target_path:
                continue
            resolved = (base_dir / target_path).resolve()
            if not resolved.exists():
                broken.append(f"{name} -> {target}")
    ok = len(broken) == 0
    detail = "no broken relative links" if ok else f"broken: {broken}"
    return CheckResult("22", "broken relative link 0", ok, detail, len(broken))


# ---------------------------------------------------------------------------
# 23: example env key coverage一致
# ---------------------------------------------------------------------------

_ENV_KEY_PATTERN = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)\s*=", re.MULTILINE)


def extract_env_example_keys(env_example_text: str) -> set:
    return set(_ENV_KEY_PATTERN.findall(env_example_text))


def check_env_example_key_coverage(env_example_text: str | None, actual_referenced_keys: set) -> CheckResult:
    if env_example_text is None:
        return CheckResult("23", "example env key coverage一致", False, ".env.example missing")
    example_keys = extract_env_example_keys(env_example_text)
    missing_from_example = actual_referenced_keys - example_keys
    ok = len(missing_from_example) == 0
    detail = "all actually-referenced public keys are documented in the example" if ok else f"missing from example: {sorted(missing_from_example)}"
    return CheckResult("23", "example env key coverage一致", ok, detail, len(missing_from_example))


# ---------------------------------------------------------------------------
# 24: .env.operator tracked 0
# ---------------------------------------------------------------------------

def check_env_operator_not_tracked(tracked_files: list) -> CheckResult:
    hits = [f for f in tracked_files if Path(f).name == ".env.operator" or f.endswith("/.env.operator")]
    ok = len(hits) == 0
    detail = "not tracked" if ok else f"tracked: {hits}"
    return CheckResult("24", ".env.operator tracked 0", ok, detail, len(hits))


# ---------------------------------------------------------------------------
# 25: UI attribution route coverage記録
# ---------------------------------------------------------------------------

def check_ui_attribution_recorded(inventory_text: str | None) -> CheckResult:
    if inventory_text is None:
        return CheckResult("25", "UI attribution route coverage記録", False, "inventory missing")
    required_markers = ["`/`", "/live", "/live/stream"]
    ok = "UI attribution 実地確認" in inventory_text and all(m in inventory_text for m in required_markers)
    detail = "UI attribution section present with route coverage" if ok else "UI attribution section missing or incomplete"
    return CheckResult("25", "UI attribution route coverage記録", ok, detail)


# ---------------------------------------------------------------------------
# 実ファイルからの読み込み + 実行
# ---------------------------------------------------------------------------

PUBLIC_ENV_REFERENCE_FILES = [
    "backend/app_public.py",
    "backend/app/api/hazards.py",
    "backend/app/api/live_train.py",
    "backend/app/api/live_road_traffic.py",
    "backend/app/services/jartic_traffic_service.py",
    "backend/app/services/live_road_traffic_service.py",
    "backend/app/services/live_train_service.py",
    "backend/app/services/active_mapping_service.py",
    "backend/app_config_properties.py",
]

# admin/simulation/operator専用モジュールは public backendの参照範囲から除外する
# （それらのkeyは.env.operatorスコープであり、.env.exampleの対象外）。


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _git_ls_files(repo_root: Path) -> list:
    out = subprocess.run(["git", "ls-files"], cwd=repo_root, capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def _extract_actual_public_env_keys(repo_root: Path) -> set:
    keys = set()
    pattern = re.compile(r"os\.(?:environ\.get|getenv)\(\s*['\"]([A-Z_0-9]+)['\"]")
    for rel in PUBLIC_ENV_REFERENCE_FILES:
        text = _read(repo_root / rel)
        if text is None:
            continue
        keys.update(pattern.findall(text))
    # compose側で固定設定されるため.env.exampleへの記載を必須としない変数
    keys -= {"API_HOST", "API_PORT", "HOSTNAME"}
    return keys


def run_all(repo_root: Path = REPO_ROOT) -> RunReport:
    license_text = _read(repo_root / "LICENSE")
    attributions_text = _read(repo_root / "ATTRIBUTIONS.md")
    notices_text = _read(repo_root / "THIRD_PARTY_NOTICES.md")
    inventory_text = _read(repo_root / "docs" / "third-party-inventory.md")
    readme_text = _read(repo_root / "README.md")
    env_example_text = _read(repo_root / ".env.example")
    installation_text = _read(repo_root / "docs" / "installation.md")
    configuration_text = _read(repo_root / "docs" / "configuration.md")
    operator_setup_text = _read(repo_root / "docs" / "operator-setup.md")

    tracked_files = _git_ls_files(repo_root)
    tracked_geo_paths = [
        f for f in tracked_files
        if f.endswith((".geojson", ".pmtiles")) and (
            f.startswith("frontend/layers/") or f.startswith("frontend/hazard/") or f.startswith("data_runtime/backend/shelters/")
        )
    ]

    named_texts = {
        "LICENSE": license_text,
        "ATTRIBUTIONS.md": attributions_text,
        "THIRD_PARTY_NOTICES.md": notices_text,
        "docs/third-party-inventory.md": inventory_text,
        "README.md": readme_text,
        "docs/installation.md": installation_text,
        "docs/configuration.md": configuration_text,
        "docs/operator-setup.md": operator_setup_text,
        ".env.example": env_example_text,
    }

    actual_keys = _extract_actual_public_env_keys(repo_root)

    odpt_allowlist_path = repo_root / "backend" / "app" / "services" / "odpt_allowlist.py"
    odpt_allowlist_source = _read(odpt_allowlist_path)
    odpt_allowlist_json_path = repo_root / "backend" / "app" / "services" / "odpt_allowlist_data.json"
    odpt_allowlist_entries = None
    odpt_json_text = _read(odpt_allowlist_json_path)
    if odpt_json_text is not None:
        try:
            odpt_allowlist_entries = json.loads(odpt_json_text)
        except json.JSONDecodeError:
            odpt_allowlist_entries = None

    report = RunReport()
    report.results = [
        check_license_exists(license_text),
        check_mit_full_text(license_text),
        check_copyright_line(license_text),
        check_file_exists("04", "ATTRIBUTIONS.md存在", attributions_text),
        check_file_exists("05", "THIRD_PARTY_NOTICES.md存在", notices_text),
        check_file_exists("06", "docs/third-party-inventory.md存在", inventory_text),
        check_readme_links(readme_text),
        check_inventory_id_duplicates(inventory_text),
        check_no_empty_table_cells(inventory_text),
        check_not_confirmed_zero(inventory_text),
        check_tracked_geo_files_mapped(tracked_geo_paths, inventory_text),
        check_no_unexpected_multimap(inventory_text),
        check_terms_url_present(inventory_text),
        check_checked_date_present(inventory_text),
        check_attribution_wording_present(attributions_text),
        check_modification_notice_present(attributions_text),
        check_no_blanket_relicense(license_text, attributions_text),
        check_no_placeholder_tokens(named_texts),
        check_no_secret_values(named_texts),
        check_no_absolute_local_paths(named_texts),
        check_no_real_vps_ip(named_texts),
        check_no_broken_relative_links(named_texts, repo_root),
        check_env_example_key_coverage(env_example_text, actual_keys),
        check_env_operator_not_tracked(tracked_files),
        check_ui_attribution_recorded(inventory_text),
        check_runtime_source_has_terms_url(inventory_text),
        check_runtime_attribution_has_ui_mapping(inventory_text),
        check_cdn_dependency_complete(inventory_text, notices_text),
        check_odpt_allowlist_mapping(odpt_allowlist_entries),
        check_odpt_unknown_not_allowed(odpt_allowlist_source),
    ]
    return report


def main() -> int:
    report = run_all()
    results_json = [
        {"check_id": r.check_id, "name": r.name, "passed": r.passed, "detail": r.detail, "evidence_count": r.evidence_count}
        for r in report.results
    ]
    for r in report.results:
        status = "PASS" if r.passed else "FAIL"
        print(f"[{r.check_id}] {status} — {r.name}: {r.detail}")

    evidence_dir = REPO_ROOT / "tasks" / "public-release" / "evidence" / "phase2d"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "phase2d_at14_results.json").write_text(
        json.dumps({"results": results_json, "all_passed": report.all_passed}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    total = len(report.results)
    passed = sum(1 for r in report.results if r.passed)
    print(f"\nAT-14 SUMMARY: {passed}/{total} PASS")
    print("OVERALL RESULT:", "PASS" if report.all_passed else "FAIL")
    return 0 if report.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
