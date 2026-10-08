"""
source_group.py — 取得原本セット（source_group_mode）の判定。UI / API / pipeline の唯一の判定源。

dataset definition の source_group_mode / required_source_count / source_file_patterns に対し、
投入されるファイル名集合が取込可能かを判定する。管理画面は POST /api/admin/data-ops/{id}/source-set/check
でこの判定結果をそのまま表示し（UI 側に別ロジックを持たない）、upload / chunk upload API と
pipeline（raw 保存前・normalize 前）も同じ関数で拒否する。

  single           1 ファイルのみ
  all_required     各 pattern にちょうど 1 ファイル。欠落・重複・想定外ファイルは拒否
  any_of           いずれか 1 pattern に 1 ファイル
  optional_addons  先頭 required_source_count 個の pattern は必須、残りは任意（各 0〜1）
  multi_batch      1 ファイル以上。想定外ファイル名は警告
  None（未定義）    制約なし（従来動作）。推測で制約を補わない

bundle: 複数原本を 1 つの zip にまとめた投入（管理画面の複数ファイル upload はサーバー側で
bundle.zip に梱包する）。zip 自体が pattern に一致しなければ、zip 内のファイル名（central
directory のみ読む・展開しない）を原本集合として判定する。
"""
from __future__ import annotations

import fnmatch
import re
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence

from app.models.admin_dataset import DatasetDefinition, SourceGroupMode

# 判定結果コード（API の error_code にもそのまま使う）
SOURCE_SET_INCOMPLETE = "SOURCE_SET_INCOMPLETE"        # 必須原本の不足
SOURCE_SET_DUPLICATE = "SOURCE_SET_DUPLICATE"          # 同一 pattern に複数ファイル
SOURCE_SET_UNEXPECTED = "SOURCE_SET_UNEXPECTED_FILE"   # 想定外ファイル名
SOURCE_SET_TOO_MANY = "SOURCE_SET_TOO_MANY_FILES"      # single / any_of で複数
SOURCE_SET_EMPTY = "SOURCE_SET_EMPTY"


@dataclass
class SourceSetEvaluation:
    dataset_id: str
    source_group_mode: Optional[str]
    ingest_mode: Optional[str]
    required_count: Optional[int]
    selected_count: int
    selected_files: List[str]
    matched: Dict[str, List[str]] = field(default_factory=dict)  # pattern → ファイル名
    missing_patterns: List[str] = field(default_factory=list)
    duplicate_patterns: List[str] = field(default_factory=list)
    unexpected_files: List[str] = field(default_factory=list)
    ok: bool = True
    error_code: Optional[str] = None
    blocking_reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    replaces_canonical: bool = False
    confirm_message: Optional[str] = None
    enforced: bool = False  # source_group_mode 定義済み（制約あり）
    bundle_name: Optional[str] = None  # zip 内を原本集合として判定した場合の bundle 名

    def as_dict(self) -> dict:
        return asdict(self)


def pattern_matches(pattern: str, name: str) -> bool:
    if pattern.startswith("re:"):
        try:
            return re.fullmatch(pattern[3:], name) is not None
        except re.error:
            return False
    return fnmatch.fnmatchcase(name, pattern)


def _basename(name: str) -> str:
    # クライアント供給名・zip member 名のディレクトリ成分は判定に使わない
    return PurePosixPath(str(name).replace("\\", "/")).name


def matches_any_pattern(defn: DatasetDefinition, name: str) -> bool:
    return any(pattern_matches(p, _basename(name)) for p in defn.source_file_patterns)


def definition_problems(defn: DatasetDefinition) -> List[str]:
    """定義自体の不整合（registry 検査・テスト用）。"""
    out = []
    mode = defn.source_group_mode
    if mode in (SourceGroupMode.all_required, SourceGroupMode.any_of, SourceGroupMode.optional_addons):
        if not defn.source_file_patterns:
            out.append(f"{defn.dataset_id}: {mode.value} には source_file_patterns が必要")
    if mode == SourceGroupMode.all_required and defn.required_source_count is not None \
            and defn.source_file_patterns and defn.required_source_count != len(defn.source_file_patterns):
        out.append(f"{defn.dataset_id}: required_source_count と source_file_patterns の件数が不一致")
    if mode == SourceGroupMode.optional_addons and (defn.required_source_count or 0) > len(defn.source_file_patterns):
        out.append(f"{defn.dataset_id}: optional_addons の required_source_count が pattern 数を超える")
    return out


def evaluate_source_set(defn: DatasetDefinition, filenames: Sequence[str]) -> SourceSetEvaluation:
    names = [_basename(n) for n in filenames if _basename(n)]
    mode = defn.source_group_mode
    patterns = list(defn.source_file_patterns)
    required = defn.required_source_count
    if mode == SourceGroupMode.all_required and required is None:
        required = len(patterns)
    if mode == SourceGroupMode.single:
        required = 1
    ev = SourceSetEvaluation(
        dataset_id=defn.dataset_id,
        source_group_mode=mode.value if mode else None,
        ingest_mode=defn.ingest_mode.value if defn.ingest_mode else None,
        required_count=required,
        selected_count=len(names),
        selected_files=names,
        replaces_canonical=defn.ingest_replaces_canonical,
        enforced=mode is not None,
    )
    if defn.ingest_replaces_canonical:
        if mode == SourceGroupMode.all_required and required and required > 1:
            ev.confirm_message = f"{required} ファイルを 1 セットとして canonical を再生成します（既存 canonical は置き換わります）"
        else:
            ev.confirm_message = "今回の処理で既存 canonical が置き換わります"

    for p in patterns:
        ev.matched[p] = [n for n in names if pattern_matches(p, n)]
    matched_any = {n for v in ev.matched.values() for n in v}
    ev.unexpected_files = [n for n in names if patterns and n not in matched_any]

    def block(code: str, reason: str) -> None:
        ev.ok = False
        ev.error_code = ev.error_code or code
        ev.blocking_reasons.append(reason)

    if mode is None:
        if not names:
            block(SOURCE_SET_EMPTY, "ファイルが選択されていません")
        return ev
    if not names:
        block(SOURCE_SET_EMPTY, "ファイルが選択されていません")
        if mode == SourceGroupMode.all_required:
            ev.missing_patterns = patterns
        return ev

    if mode == SourceGroupMode.single:
        if len(names) > 1:
            block(SOURCE_SET_TOO_MANY, "このデータセットは 1 ファイルで完結します（複数選択不可）")
        if patterns and ev.unexpected_files:
            block(SOURCE_SET_UNEXPECTED, f"想定外のファイル名: {', '.join(ev.unexpected_files)}")
    elif mode == SourceGroupMode.all_required:
        ev.missing_patterns = [p for p in patterns if not ev.matched[p]]
        ev.duplicate_patterns = [p for p in patterns if len(ev.matched[p]) > 1]
        if ev.missing_patterns:
            block(SOURCE_SET_INCOMPLETE,
                  f"必須原本が不足しています（{len(patterns) - len(ev.missing_patterns)} / {len(patterns)}）。"
                  f"不足: {', '.join(ev.missing_patterns)}")
        if ev.duplicate_patterns:
            block(SOURCE_SET_DUPLICATE,
                  "同じ種類の原本が複数あります（年度違いの混在など）: "
                  + "; ".join(f"{p} → {', '.join(ev.matched[p])}" for p in ev.duplicate_patterns))
        if ev.unexpected_files:
            block(SOURCE_SET_UNEXPECTED, f"想定外のファイル名: {', '.join(ev.unexpected_files)}")
    elif mode == SourceGroupMode.any_of:
        hit = [p for p in patterns if ev.matched[p]]
        if len(names) > 1:
            block(SOURCE_SET_TOO_MANY, "候補のうち 1 ファイルだけを選択してください")
        if not hit:
            block(SOURCE_SET_INCOMPLETE, f"候補に一致するファイルがありません: {', '.join(patterns)}")
        if ev.unexpected_files:
            block(SOURCE_SET_UNEXPECTED, f"想定外のファイル名: {', '.join(ev.unexpected_files)}")
    elif mode == SourceGroupMode.optional_addons:
        req_patterns = patterns[: (defn.required_source_count or 1)]
        ev.missing_patterns = [p for p in req_patterns if not ev.matched[p]]
        ev.duplicate_patterns = [p for p in patterns if len(ev.matched[p]) > 1]
        if ev.missing_patterns:
            block(SOURCE_SET_INCOMPLETE, f"本体原本が不足しています。不足: {', '.join(ev.missing_patterns)}")
        if ev.duplicate_patterns:
            block(SOURCE_SET_DUPLICATE, f"同じ種類の原本が複数あります: {', '.join(ev.duplicate_patterns)}")
        if ev.unexpected_files:
            block(SOURCE_SET_UNEXPECTED, f"想定外のファイル名: {', '.join(ev.unexpected_files)}")
    elif mode == SourceGroupMode.multi_batch:
        if ev.unexpected_files:
            ev.warnings.append(f"想定外のファイル名（命名変更の可能性を確認してください）: {', '.join(ev.unexpected_files)}")
    return ev


def upload_start_evaluation(defn: DatasetDefinition, filename: str) -> SourceSetEvaluation:
    """chunk upload（単一ファイル）開始時の判定。

    単一ファイルは「原本そのもの」か「複数原本をまとめた bundle zip」のどちらか。原本そのもの
    （pattern に一致）なら 1 ファイル集合として判定する（all_required 4 件中の 1 件 → 拒否）。
    pattern に一致しない zip は bundle 候補として受け付け、finish 時に zip 内を判定する。"""
    name = _basename(filename)
    if defn.source_group_mode is None or matches_any_pattern(defn, name) or not name.lower().endswith(".zip"):
        return evaluate_source_set(defn, [name])
    ev = evaluate_source_set(defn, [])
    ev.ok, ev.error_code, ev.blocking_reasons = True, None, []
    ev.selected_count, ev.selected_files, ev.bundle_name = 1, [name], name
    ev.warnings.append("bundle zip として受け付けます。zip 内の原本構成はアップロード完了時にサーバーで検証します")
    return ev


def list_zip_members(path: Path) -> List[str]:
    """zip の central directory からファイル名だけを読む（展開・ハッシュしない）。"""
    with zipfile.ZipFile(path) as zf:
        return [
            _basename(i.filename) for i in zf.infolist()
            if not i.is_dir() and not i.filename.startswith("__MACOSX/") and not _basename(i.filename).startswith(".")
        ]


def evaluate_stored_file(defn: DatasetDefinition, path: Path, display_name: Optional[str] = None) -> SourceSetEvaluation:
    """raw として保存する（した）1 ファイルの判定。pipeline guard と chunk upload finish が使う。"""
    path = Path(path)
    name = display_name or path.name
    if defn.source_group_mode is None or matches_any_pattern(defn, name) or not zipfile.is_zipfile(path):
        return evaluate_source_set(defn, [name])
    try:
        members = list_zip_members(path)
    except (zipfile.BadZipFile, OSError) as exc:
        ev = evaluate_source_set(defn, [name])
        ev.ok, ev.error_code = False, SOURCE_SET_UNEXPECTED
        ev.blocking_reasons.append(f"zip を読めません: {exc}")
        return ev
    ev = evaluate_source_set(defn, members)
    ev.bundle_name = name
    return ev
