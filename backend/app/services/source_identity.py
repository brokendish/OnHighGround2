"""
source_identity.py — 取得した原本が dataset 定義の期待する source と同じものかを判定する
（ACQUISITION-SOURCE-CONTRACT、2026-10-12）。

旧来の validity=valid は「地域コードが矛盾しない・他 dataset と原本を共有しない・取得方法が分かる」だけで、
期待する原本そのものかは見ていなかった（例: VPS の KANAGAWA-RIVER-001 raw は 2024 年版 bundle
A31a-24_14_* だが valid と判定された）。ここでは registry の source identity と記録された原本の事実
（原本名・sha256）を照合し、一致を確認できたものだけを EXPECTED_SOURCE_MATCH とする。

判定（先に該当したもの）:
  SOURCE_UNKNOWN        registry に source identity が無い（expected_source_files も sha256 も無い）、
                        または原本が記録されていない（判断材料なし）
  SOURCE_MISMATCH       原本名の集合が expected_source_files と異なる（不足・余分）、
                        または sha256 が登録値と異なる（名前が同じでも sha が違えば別物）
  SOURCE_READABLE       原本名は期待どおりだが、sha256 が登録されていない、または記録に sha256 が無い
                        （読めて名前は合うが、同一性は未確認。valid にしない）
  EXPECTED_SOURCE_MATCH 期待する全原本の sha256 が登録値と一致

読めること・normalize できること・ファイル名が合うこと・provider が合うことだけでは一致としない。
年・版（source_year / source_version）は registry の公式一覧・KS-META 由来の値で、GML 形式の版（3.2.1）とは
別物。原本名の年（A31a-24 / A31a-25 等）は原本名の集合照合で区別される。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

EXPECTED_SOURCE_MATCH = "EXPECTED_SOURCE_MATCH"
SOURCE_READABLE = "SOURCE_READABLE"
SOURCE_MISMATCH = "SOURCE_MISMATCH"
SOURCE_UNKNOWN = "SOURCE_UNKNOWN"
STATUSES = (EXPECTED_SOURCE_MATCH, SOURCE_READABLE, SOURCE_MISMATCH, SOURCE_UNKNOWN)

VALIDATOR_VERSION = "source-identity/1"


@dataclass
class IdentityResult:
    status: str
    reasons: List[str] = field(default_factory=list)
    expected: Dict[str, Optional[str]] = field(default_factory=dict)  # 原本名 → 登録 sha256（未登録は None）
    actual: Dict[str, Optional[str]] = field(default_factory=dict)    # 原本名 → 記録 sha256
    basis: Optional[str] = None

    @property
    def verified(self) -> bool:
        return self.status == EXPECTED_SOURCE_MATCH

    def to_dict(self, node: Optional[str] = None) -> dict:
        return {
            "status": self.status,
            "reasons": list(self.reasons),
            "expected_sha256": dict(self.expected),
            "actual_sha256": dict(self.actual),
            "basis": self.basis,
            "validator_version": VALIDATOR_VERSION,
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "node": node,
        }


def _name_sha(files: Iterable) -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {}
    for f in files:
        name = f.get("name") if isinstance(f, dict) else getattr(f, "name", None)
        sha = f.get("sha256") if isinstance(f, dict) else getattr(f, "sha256", None)
        if name:
            out[name] = sha
    return out


def verify(defn, source_files: Iterable) -> IdentityResult:
    """記録された原本（SourceFile または {"name","sha256"} の並び）を dataset 定義の source identity と照合する。"""
    expected_names = list(getattr(defn, "expected_source_files", None) or [])
    expected_sha = dict(getattr(defn, "expected_source_sha256", None) or {})
    basis = getattr(defn, "expected_source_sha256_basis", None)
    expected = {n: expected_sha.get(n) for n in (expected_names or expected_sha)}
    actual = _name_sha(source_files)
    res = IdentityResult(SOURCE_UNKNOWN, expected=expected, actual=actual, basis=basis)

    if not expected:
        res.reasons.append("dataset 定義に source identity（expected_source_files / expected_source_sha256）が無い")
        return res
    if not actual:
        res.reasons.append("原本が記録されていない")
        return res

    missing = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected))
    if missing or unexpected:
        res.status = SOURCE_MISMATCH
        if missing:
            res.reasons.append(f"期待する原本が無い: {', '.join(missing)}")
        if unexpected:
            res.reasons.append(f"期待しない原本がある: {', '.join(unexpected)}")
        return res

    differ = sorted(n for n, s in expected.items() if s and actual.get(n) and actual[n] != s)
    if differ:
        res.status = SOURCE_MISMATCH
        res.reasons.append(f"sha256 が登録値と異なる: {', '.join(differ)}")
        return res

    if not expected_sha or any(not s for s in expected.values()):
        res.status = SOURCE_READABLE
        res.reasons.append("原本名は期待どおりだが sha256 が登録されていない（同一性は未確認）")
        return res
    unrecorded = sorted(n for n in expected if not actual.get(n))
    if unrecorded:
        res.status = SOURCE_READABLE
        res.reasons.append(f"記録に sha256 が無い原本がある（同一性は未確認）: {', '.join(unrecorded)}")
        return res

    res.status = EXPECTED_SOURCE_MATCH
    return res
