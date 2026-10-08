"""
provenance_validity.py — acquisition record の provenance 健全性判定（active とは別軸）。

確認できた事実だけで判定し、推測で valid にしない。判定順（先に該当したもの）:

  1. 原本ファイル名から抽出した地域コードが dataset 定義の
     expected_source_region_code と異なる                         → provenance_mismatch（REGION_MISMATCH）
     （source_region_code_regex で抽出できる原本だけを判定する）
  2. 他 dataset の active 取得と同一原本（sha256 一致。sha256 が無ければ名前 + size 一致）を共有し、
     かつ 1 で自 dataset の地域コード一致が確認できていない         → provenance_suspect（SHARED_SOURCE）
  3. 取得方法が legacy_unknown、または原本が記録されていない       → unknown
  4. 上記に該当しない                                              → valid

1・2 は原本そのものの事実（ファイル名・sha256）に基づくため、取得方法が不明（legacy_unknown）でも判定する。

3 で地域コード一致が確認できている場合（例: TOKYO-RIVER-001 の A31a-*_13_* と KANAGAWA-RIVER-001 が
同じ東京原本を共有）は、共有の原因は相手側の不一致として 2 で説明されるため自 dataset は suspect にしない。
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Tuple

from app.models.admin_dataset import DatasetDefinition
from app.services.acquisition_history import AcquisitionMethod, AcquisitionRecord, AcquisitionValidity, SourceFile

REGION_MISMATCH = "REGION_MISMATCH"
SHARED_SOURCE = "SHARED_SOURCE"


def extract_region_codes(defn: DatasetDefinition, files: Iterable[SourceFile]) -> List[Tuple[str, str]]:
    """(原本名, 地域コード)。regex 未定義・抽出不能な原本は含めない。"""
    if not defn.source_region_code_regex:
        return []
    try:
        rx = re.compile(defn.source_region_code_regex)
    except re.error:
        return []
    out = []
    for f in files:
        m = rx.search(f.name)
        if m and m.groups():
            out.append((f.name, m.group(1)))
    return out


def with_region_members(defn: DatasetDefinition, outer_name: str, member_filter):
    """地域コード照合が定義された dataset で、地域コードを抽出できる zip member も原本として記録する
    （bundle 名だけで valid にしない）。

    member_filter（source_file_patterns 一致）がある場合も OR で併用する: 正式 patterns が地域 14 だけを
    許す定義でも、誤って投入された地域 13 の原本（A31a-25_13_*）を記録から落とさず mismatch として残すため。"""
    if not defn.source_region_code_regex:
        return member_filter
    try:
        rx = re.compile(defn.source_region_code_regex)
    except re.error:
        return member_filter
    if member_filter is not None:
        return lambda n: bool(member_filter(n)) or rx.search(n) is not None
    if rx.search(outer_name):
        return None  # 外側 file 自体が原本
    return lambda n: rx.search(n) is not None


def _same_file(a: SourceFile, b: SourceFile) -> bool:
    if a.sha256 and b.sha256:
        return a.sha256 == b.sha256
    return a.name == b.name and a.size is not None and a.size == b.size


def assess(defn: DatasetDefinition, record: AcquisitionRecord,
           peers: Iterable[AcquisitionRecord] = ()) -> Tuple[AcquisitionValidity, Optional[str], List[str]]:
    if not record.source_files:
        return AcquisitionValidity.unknown, "no source files recorded", []

    region_confirmed = False
    if defn.expected_source_region_code and defn.source_region_code_regex:
        codes = extract_region_codes(defn, record.source_files)
        bad = [(n, c) for n, c in codes if c != defn.expected_source_region_code]
        if bad:
            found = sorted({c for _, c in bad})
            return (AcquisitionValidity.provenance_mismatch,
                    f"source files contain region code {', '.join(found)} "
                    f"({', '.join(n for n, _ in bad)}), while dataset {defn.dataset_id} "
                    f"(region={defn.region}) expects region code {defn.expected_source_region_code}",
                    [REGION_MISMATCH])
        region_confirmed = bool(codes)

    if not region_confirmed:
        for peer in peers:
            if peer.dataset_id == record.dataset_id:
                continue
            shared = sorted({f.name for f in record.source_files for g in peer.source_files if _same_file(f, g)})
            if shared:
                return (AcquisitionValidity.provenance_suspect,
                        f"{record.dataset_id} and {peer.dataset_id} reference the same source file "
                        f"{', '.join(shared)}; requires verification",
                        [SHARED_SOURCE])
    if record.acquisition_method == AcquisitionMethod.legacy_unknown:
        return (AcquisitionValidity.unknown,
                "acquisition method / source are not recorded (legacy_unknown); source file names alone are not "
                "sufficient to confirm provenance", [])
    return AcquisitionValidity.valid, None, []


def assess_raw_region(defn: DatasetDefinition, raw_path) -> Optional[Tuple[AcquisitionValidity, str, List[str]]]:
    """現在の raw（DatasetState.current_raw_path）の地域コードを照合する（取得履歴の有無に依らない事実）。

    zip は central directory の member 名だけを読む（展開・hash しない）。地域コード照合が未定義、
    raw を読めない、地域コードを抽出できない場合は None（判定材料なし）。"""
    import zipfile
    from pathlib import Path

    if not (defn.expected_source_region_code and defn.source_region_code_regex) or not raw_path:
        return None
    path = Path(raw_path)
    try:
        if not path.is_file():
            return None
        names = [path.name]
        if zipfile.is_zipfile(path):
            from app.services.source_group import list_zip_members
            names += list_zip_members(path)
    except (OSError, zipfile.BadZipFile):
        return None
    codes = extract_region_codes(defn, [SourceFile(name=n) for n in names])
    if not codes:
        return None
    bad = [(n, c) for n, c in codes if c != defn.expected_source_region_code]
    if not bad:
        return AcquisitionValidity.valid, None, []
    found = sorted({c for _, c in bad})
    return (AcquisitionValidity.provenance_mismatch,
            f"current raw {path.name} contains source files with region code {', '.join(found)} "
            f"({', '.join(n for n, _ in bad)}), while dataset {defn.dataset_id} (region={defn.region}) "
            f"expects region code {defn.expected_source_region_code}",
            [REGION_MISMATCH])


def apply(defn: DatasetDefinition, record: AcquisitionRecord, peers: Iterable[AcquisitionRecord] = ()) -> AcquisitionRecord:
    record.validity, record.validity_reason, record.validity_flags = assess(defn, record, peers)
    return record
