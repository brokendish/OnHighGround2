"""
acquisition_history.py — 原本の取得履歴（acquisition history）。

dataset definition（「何を・どこから・どう取り込むべきか」）とは分離し、実際の取得事実を
複数世代で保持する。dataset definition に「最後の取得情報」を上書きしない。

保存: data_lake/admin/acquisitions/<dataset_id>.json（dataset 単位・1 file）
  {"schema_version": 1, "dataset_id": ..., "acquisitions": [<AcquisitionRecord>, ...]}
  - 更新は dataset 単位の flock 排他 + 同一 directory の tmp へ書いて fsync → os.replace（atomic）
  - active は dataset あたり高々 1 件（現在 canonical の生成元となった取得）

記録するのは事実のみ。不明な値は None / 空のまま（推測で埋めない）。既存 dataset の移行
（acquisition_migration.py）も、raw / job / history に残る事実から復元できるものだけを記録する。
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterator, List, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1
_DATASET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class AcquisitionMethod(str, Enum):
    upload = "upload"
    url = "url"
    api = "api"
    manual_import = "manual_import"
    generated = "generated"
    legacy_unknown = "legacy_unknown"


class AcquisitionStatus(str, Enum):
    received = "received"    # 受付・raw 保存済み（変換前）
    processed = "processed"  # canonical まで生成成功
    failed = "failed"        # 変換・検証失敗、または原本セット不足で拒否
    rejected = "rejected"    # 原本セット不足等で取込前に拒否


class AcquisitionValidity(str, Enum):
    """provenance の健全性（active とは別軸。active=true は「現在採用中」だけを意味する）。"""
    valid = "valid"                              # 取得元・原本・dataset の対応に矛盾が確認されていない
    provenance_mismatch = "provenance_mismatch"  # dataset 定義との明確な不一致が事実として確認された
    provenance_suspect = "provenance_suspect"    # 矛盾の可能性が高いが確定できない
    unknown = "unknown"                          # 判断材料不足（validity 未記録の既存 record も unknown）


class SourceFile(BaseModel):
    name: str
    size: Optional[int] = None
    sha256: Optional[str] = None
    container: Optional[str] = None  # bundle zip 内の原本なら bundle 名


class AcquisitionRecord(BaseModel):
    acquisition_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    dataset_id: str
    acquisition_method: AcquisitionMethod
    # 取得日時。移行で事実が無い場合は None（推測で埋めない）
    acquired_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_url: Optional[str] = None       # 実際に取得した URL（ZIP / API）
    final_url: Optional[str] = None        # redirect 後の URL（取得できた場合のみ）
    source_page_url: Optional[str] = None  # 配布ページ（取得時点で分かっている場合のみ）
    source_files: List[SourceFile] = Field(default_factory=list)
    bundle: Optional[SourceFile] = None    # 外側 bundle（管理画面の複数 upload 梱包等）
    source_year: Optional[str] = None
    source_version: Optional[str] = None
    ingest_job_id: Optional[str] = None
    raw_path: Optional[str] = None
    actor_id: Optional[str] = None
    status: AcquisitionStatus = AcquisitionStatus.received
    active: bool = False
    notes: List[str] = Field(default_factory=list)
    # recorded: 取込時に記録 / migrated: 既存 raw・job・history の事実から復元
    record_origin: str = "recorded"
    # provenance の健全性（provenance_validity.assess が確認できた事実だけで判定）。
    # validity 欄の無い既存 record は unknown として読む（valid へ自動昇格しない）。
    validity: AcquisitionValidity = AcquisitionValidity.unknown
    validity_reason: Optional[str] = None
    validity_flags: List[str] = Field(default_factory=list)  # 例: REGION_MISMATCH, SHARED_SOURCE

    @property
    def source_sha256(self) -> List[Optional[str]]:
        return [f.sha256 for f in self.source_files]


def _default_root() -> Path:
    from app.services.dataset_state_service import _ADMIN_STATE_DIR
    return Path(_ADMIN_STATE_DIR).parent / "acquisitions"


def sha256_stream(fh, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    for block in iter(lambda: fh.read(chunk), b""):
        h.update(block)
    return h.hexdigest()


def describe_source_files(path: Path, display_name: Optional[str] = None,
                          member_filter=None) -> "tuple[List[SourceFile], Optional[SourceFile]]":
    """raw として保存するファイルの原本情報（名前・サイズ・sha256）。ingest job 内で 1 回だけ計算する。

    bundle zip（member_filter が member 名に True を返すものが 1 件以上）なら、zip 内の原本ごとに
    sha256 を stream 計算し、外側 bundle も別に記録する（bundle 名だけが残る状態にしない）。"""
    path = Path(path)
    name = display_name or path.name
    with path.open("rb") as fh:
        outer = SourceFile(name=name, size=path.stat().st_size, sha256=sha256_stream(fh))
    # member_filter=None: 外側 file 自体が原本（呼び出し側が判定する）
    if member_filter is None or not zipfile.is_zipfile(path):
        return [outer], None
    members: List[SourceFile] = []
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            base = Path(info.filename).name
            if info.is_dir() or info.filename.startswith("__MACOSX/") or base.startswith(".") or not member_filter(base):
                continue
            with zf.open(info) as fh:
                members.append(SourceFile(name=base, size=info.file_size, sha256=sha256_stream(fh), container=name))
    if not members:
        return [outer], None
    return sorted(members, key=lambda f: f.name), outer


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _sort_key(r: "AcquisitionRecord") -> datetime:
    t = r.acquired_at
    if t is None:
        return _EPOCH
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


class AcquisitionStore:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else _default_root()

    def _path(self, dataset_id: str) -> Path:
        if not _DATASET_ID_RE.fullmatch(dataset_id or ""):
            raise ValueError(f"不正な dataset_id: {dataset_id!r}")
        return self.root / f"{dataset_id}.json"

    @contextmanager
    def _locked(self, dataset_id: str) -> Iterator[Path]:
        path = self._path(dataset_id)
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.root / f".{dataset_id}.lock", "a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield path
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _read(self, path: Path) -> List[AcquisitionRecord]:
        if not path.is_file():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"未知の acquisition schema_version: {data.get('schema_version')}")
        return [AcquisitionRecord.model_validate(r) for r in data.get("acquisitions", [])]

    def _write(self, path: Path, dataset_id: str, records: List[AcquisitionRecord]) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "dataset_id": dataset_id,
            "acquisitions": [r.model_dump(mode="json") for r in records],
        }
        tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()
        try:
            dfd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass

    # ── read ──
    def list(self, dataset_id: str) -> List[AcquisitionRecord]:
        """新しい順。"""
        return sorted(self._read(self._path(dataset_id)), key=_sort_key, reverse=True)

    def active(self, dataset_id: str) -> Optional[AcquisitionRecord]:
        return next((r for r in self.list(dataset_id) if r.active), None)

    def all_active(self) -> List[AcquisitionRecord]:
        """全 dataset の active record（provenance の dataset 間照合用）。"""
        out = []
        if not self.root.is_dir():
            return out
        for path in sorted(self.root.glob("*.json")):
            if path.name.startswith("."):
                continue
            try:
                rec = self.active(path.stem)
            except (ValueError, OSError):
                continue
            if rec is not None:
                out.append(rec)
        return out

    # ── write ──
    def add(self, record: AcquisitionRecord) -> AcquisitionRecord:
        with self._locked(record.dataset_id) as path:
            records = self._read(path)
            if any(r.acquisition_id == record.acquisition_id for r in records):
                raise ValueError(f"acquisition_id 重複: {record.acquisition_id}")
            if record.active:
                for r in records:
                    r.active = False
            records.append(record)
            self._write(path, record.dataset_id, records)
        return record

    def update(self, dataset_id: str, acquisition_id: str, *, status: Optional[AcquisitionStatus] = None,
               activate: bool = False, note: Optional[str] = None, **fields) -> AcquisitionRecord:
        with self._locked(dataset_id) as path:
            records = self._read(path)
            target = next((r for r in records if r.acquisition_id == acquisition_id), None)
            if target is None:
                raise KeyError(acquisition_id)
            if status is not None:
                target.status = status
            for k, v in fields.items():
                setattr(target, k, v)
            if note:
                target.notes.append(note)
            if activate:
                for r in records:
                    r.active = r.acquisition_id == acquisition_id
            self._write(path, dataset_id, records)
            return target


_default_store: Optional[AcquisitionStore] = None


def get_acquisition_store() -> AcquisitionStore:
    global _default_store
    if _default_store is None:
        _default_store = AcquisitionStore()
    return _default_store
