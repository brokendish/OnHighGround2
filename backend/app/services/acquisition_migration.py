"""
acquisition_migration.py — 既存 dataset の取得履歴を「事実から復元できる範囲だけ」移行する。

復元に使う一次情報（推測しない）:
  - DatasetState.current_raw_path が指す raw file（実在するもの）
  - data_lake/admin/history/<dataset_id>.jsonl の ingest 成功記録（source_file_name が raw と一致）
  - data_lake/admin/jobs/<job_id>.json（job_type → 取得方法、fetch_url、actor_id、作成時刻）
  - raw zip の central directory と各 member の sha256（bundle 内原本名）

どれかが欠ければその項目は None / legacy_unknown のまま残す。既に取得履歴がある dataset は変更しない
（冪等）。active は「current_raw_path の raw から normalize / validation が成功している」場合だけ付ける。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.models.admin_dataset import DatasetDefinition, DatasetState, NormalizeStatus, ValidationStatus
from app.services import source_group
from app.services.acquisition_history import (
    AcquisitionMethod,
    AcquisitionRecord,
    AcquisitionStatus,
    AcquisitionStore,
    describe_source_files,
)

_JOB_METHOD = {
    "ingest_upload": AcquisitionMethod.upload,
    "ingest_fetch_url": AcquisitionMethod.url,
    "ingest_fetch_official": AcquisitionMethod.url,
    "generate": AcquisitionMethod.generated,
}


def _admin_dir() -> Path:
    from app.services.dataset_state_service import _ADMIN_STATE_DIR
    return Path(_ADMIN_STATE_DIR).parent


def _ingest_history(admin_dir: Path, dataset_id: str, raw_name: str) -> Optional[Dict[str, Any]]:
    path = admin_dir / "history" / f"{dataset_id}.jsonl"
    if not path.is_file():
        return None
    hit = None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            h = json.loads(line)
        except ValueError:
            continue
        if h.get("operation_type") in ("ingest", "generate") and h.get("result") == "success" \
                and h.get("source_file_name") == raw_name:
            hit = h  # 同名 raw が複数回 ingest された場合は最新（current_raw_path を最後に書いたもの）
    return hit


def _job(admin_dir: Path, job_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not job_id:
        return None
    path = admin_dir / "jobs" / f"{job_id}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _utc(value: Optional[str]) -> Optional[datetime]:
    """history / job の時刻は datetime.utcnow() の naive 値（UTC）。"""
    if not value:
        return None
    try:
        t = datetime.fromisoformat(value)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _host_path(container_path: str) -> Path:
    """state の path は container 内（/data_lake/...）。host 実行時は project 直下へ読み替える。"""
    p = Path(container_path)
    if p.exists():
        return p
    project = Path(__file__).resolve().parents[3]
    if container_path.startswith("/data_lake/"):
        alt = project / container_path.lstrip("/")
        if alt.exists():
            return alt
    return p


def read_state_readonly(dataset_id: str, admin_dir: Optional[Path] = None) -> Optional[DatasetState]:
    """state file を読むだけ（DatasetStateService.load は stale path と判断すると state file を削除して
    再推定するため、移行・点検では使わない）。無ければ None。"""
    path = (admin_dir or _admin_dir()) / "state" / f"{dataset_id}.json"
    try:
        return DatasetState(**json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def build_migrated_record(defn: DatasetDefinition, state: DatasetState,
                          admin_dir: Optional[Path] = None) -> Optional[AcquisitionRecord]:
    admin_dir = admin_dir or _admin_dir()
    if not state.current_raw_path:
        return None
    raw = _host_path(state.current_raw_path)
    if not raw.is_file():
        return None
    hist = _ingest_history(admin_dir, defn.dataset_id, raw.name)
    job = _job(admin_dir, hist.get("job_id") if hist else None)
    notes: List[str] = ["migrated: DatasetState.current_raw_path と既存 history / job 記録から復元"]
    method = _JOB_METHOD.get((job or {}).get("job_type"), AcquisitionMethod.legacy_unknown)
    if method == AcquisitionMethod.legacy_unknown:
        notes.append("取得方法を示す job 記録が見つからないため legacy_unknown")

    if defn.source_file_patterns and source_group.matches_any_pattern(defn, raw.name):
        member_filter = None  # raw 自体が原本
    elif defn.source_file_patterns:
        member_filter = lambda n: source_group.matches_any_pattern(defn, n)  # noqa: E731
    elif raw.name.startswith(f"{defn.dataset_id}_bundle_"):
        member_filter = lambda n: True  # noqa: E731 — 管理画面の複数ファイル upload が梱包した bundle
    else:
        member_filter = None
    from app.services.provenance_validity import with_region_members
    member_filter = with_region_members(defn, raw.name, member_filter)
    files, bundle = describe_source_files(raw, member_filter=member_filter)

    canonical_ok = state.normalize_status in (NormalizeStatus.success, NormalizeStatus.not_required) \
        and state.validation_status in (ValidationStatus.passed, ValidationStatus.not_required)
    if not canonical_ok:
        notes.append("normalize / validation が成功していないため active にしない")
    return AcquisitionRecord(
        dataset_id=defn.dataset_id,
        acquisition_method=method,
        acquired_at=_utc((hist or {}).get("executed_at")) or _utc((job or {}).get("created_at")),
        source_url=(job or {}).get("fetch_url") or None,
        source_files=files,
        bundle=bundle,
        ingest_job_id=(hist or {}).get("job_id"),
        raw_path=state.current_raw_path,
        actor_id=(job or {}).get("actor_id"),
        status=AcquisitionStatus.processed if canonical_ok else AcquisitionStatus.received,
        active=canonical_ok,
        notes=notes,
        record_origin="migrated",
    )


def migrate_all(ds=None, ss=None, store: Optional[AcquisitionStore] = None, *, dry_run: bool = False,
                dataset_ids: Optional[List[str]] = None, admin_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """取得履歴を事実から復元する。dataset_ids 指定時はその dataset だけを出力・記録する。

    provenance の dataset 間照合（同一原本の共有）のため、復元候補は全 dataset 分を作るが、
    記録するのは指定 dataset だけ。validity は provenance_validity.assess で判定し、valid へ
    自動昇格しない（mismatch / suspect / unknown も履歴としては保存し、warning を出す）。"""
    import logging

    from app.services import provenance_validity

    log = logging.getLogger(__name__)
    if ds is None:
        from app.services.dataset_definition_service import get_definition_service
        ds = get_definition_service()
    # ss: dataset_id → DatasetState の読み取り関数（テスト用）。既定は state file の読み取り専用 read。
    store = store or AcquisitionStore()
    selected = set(dataset_ids or [])
    defns = ds.list_all()
    unknown_ids = sorted(selected - {d.dataset_id for d in defns})

    results: Dict[str, Dict[str, Any]] = {}
    candidates: Dict[str, AcquisitionRecord] = {}
    for defn in defns:
        if store.list(defn.dataset_id):
            results[defn.dataset_id] = {"dataset_id": defn.dataset_id, "action": "skip_existing"}
            continue
        state = read_state_readonly(defn.dataset_id, admin_dir) if ss is None else ss(defn.dataset_id)
        if state is None:
            results[defn.dataset_id] = {"dataset_id": defn.dataset_id, "action": "no_state"}
            continue
        try:
            rec = build_migrated_record(defn, state, admin_dir=admin_dir)
        except Exception as exc:  # noqa: BLE001
            results[defn.dataset_id] = {"dataset_id": defn.dataset_id, "action": "error",
                                        "error": f"{type(exc).__name__}: {exc}"}
            continue
        if rec is None:
            results[defn.dataset_id] = {"dataset_id": defn.dataset_id, "action": "no_facts"}
            continue
        candidates[defn.dataset_id] = rec

    peers = [r for r in candidates.values() if r.active] + [
        r for r in store.all_active() if r.dataset_id not in candidates]
    by_id = {d.dataset_id: d for d in defns}
    for dataset_id, rec in candidates.items():
        provenance_validity.apply(by_id[dataset_id], rec, peers)
        results[dataset_id] = {
            "dataset_id": dataset_id, "action": "dry_run" if dry_run else "migrated",
            "method": rec.acquisition_method.value, "active": rec.active,
            "validity": rec.validity.value, "validity_reason": rec.validity_reason,
            "validity_flags": rec.validity_flags,
            "source_files": [f.name for f in rec.source_files],
            "bundle": rec.bundle.name if rec.bundle else None,
            "acquired_at": rec.acquired_at.isoformat() if rec.acquired_at else None,
        }

    out = []
    for defn in defns:
        if selected and defn.dataset_id not in selected:
            continue
        row = results[defn.dataset_id]
        rec = candidates.get(defn.dataset_id)
        if rec is not None and not dry_run:
            store.add(rec)
            if rec.validity != rec.validity.valid:
                log.warning("acquisition backfilled with validity=%s: %s (%s)",
                            rec.validity.value, defn.dataset_id, rec.validity_reason)
        out.append(row)
    for dataset_id in unknown_ids:
        out.append({"dataset_id": dataset_id, "action": "error", "error": "dataset definition がありません"})
    return out
