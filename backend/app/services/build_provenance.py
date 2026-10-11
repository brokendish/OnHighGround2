"""
build_provenance.py — build node で dataset ごとの runtime provenance record を生成する。

data_lake/provenance/<region>/<layer_type>/<dataset_id>.json に書き、publish が runtime version へ
同梱する（runtime_provenance.py 参照）。記録するのは build node で確認できた事実のみ:
  - 採用中の取得履歴（acquisition history の active record。無ければ source=None）
  - canonical（validated）の sha256
  - runtime artifact: flood は routing meta の routing_artifact_sha256 / feature_count、
    それ以外は validated をそのまま publish するので canonical と同一 sha256
  - tile（data_lake/tiles/<region>/<type>/<stem>.mbtiles があれば sha256）
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from app.services import admin_atomic_publish as aap
from app.services import runtime_provenance as rp

logger = logging.getLogger(__name__)


def _data_lake_root() -> Path:
    from app.services.dataset_state_service import _PROJECT_ROOT
    p = Path("/data_lake")
    return p if p.is_dir() else Path(_PROJECT_ROOT) / "data_lake"


def _check_registry_canonical(path: Path, dataset_id: str) -> int:
    """publish（scripts/publish/resolve_tsunami_source.py）と同じ canonical 検証。feature 数を返す。"""
    import importlib.util
    here = Path(__file__).resolve()
    for base in (Path("/scripts"), here.parents[3] / "scripts"):
        script = base / "publish" / "resolve_tsunami_source.py"
        if script.is_file():
            break
    else:
        raise ValueError("resolve_tsunami_source.py が見つからない（canonical を検証できない）")
    mods = {}
    for name, rel in (("resolve_tsunami_source", "publish/resolve_tsunami_source.py"),
                      ("normalize_tsunami", "normalize/normalize_tsunami.py")):
        spec = importlib.util.spec_from_file_location(f"_bp_{name}", script.parents[1] / rel)
        mods[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mods[name])
    return mods["resolve_tsunami_source"].check_canonical(path, dataset_id, mods["normalize_tsunami"]._extract_depth_value)


def generate(defn, state, *, store=None, cache=None, allow_hash: bool = True,
             data_lake: Optional[Path] = None) -> Dict[str, Any]:
    from app.services import dataset_runtime_reconcile as drr
    from app.services.acquisition_history import get_acquisition_store
    from app.services.flood_routing_contract import load_meta, routing_paths_for_canonical

    registry_type = defn.layer_type in drr.REGISTRY_RUNTIME_LAYER_TYPES
    if defn.layer_type not in aap.ATOMIC_PUBLISH_LAYER_TYPES and not registry_type:
        raise ValueError(f"{defn.dataset_id}: atomic publish 対象外の layer_type（{defn.layer_type}）")
    validated = Path(state.current_validated_path) if state.current_validated_path else None
    if validated is None or not validated.is_file():
        raise ValueError(f"{defn.dataset_id}: validated canonical がありません（{state.current_validated_path}）")
    cache = cache or drr.get_source_sha_cache()
    canonical_sha = cache.get(validated, allow_hash)
    if canonical_sha is None:
        raise ValueError(f"{defn.dataset_id}: canonical sha256 が未計算です（allow_hash=False）")
    if canonical_sha in drr.superseded_shas(defn):
        raise ValueError(f"{defn.dataset_id}: canonical {canonical_sha[:12]}… は置き換え済みの旧版（superseded_canonicals）")
    rel = drr.expected_runtime_rel(defn, state)
    canonical_fc = None
    if defn.layer_type == "flood":
        _routing, meta_path = routing_paths_for_canonical(validated)
        meta = load_meta(meta_path)
        if meta["source_canonical_sha256"] != canonical_sha:
            raise ValueError(f"{defn.dataset_id}: routing meta の source_canonical_sha256 が canonical と不一致"
                             "（routing を再生成してください）")
        runtime_sha, runtime_fc = meta["routing_artifact_sha256"], meta["feature_count"]
        canonical_fc = meta.get("source_feature_count")
    elif registry_type:
        # validated canonical をそのまま runtime に置く（resolve_tsunami_source.py）。publish と同じ検証
        # （全 feature の dataset_id・depth の解釈）を通した canonical だけを記録する
        runtime_sha = canonical_sha
        runtime_fc = canonical_fc = _check_registry_canonical(validated, defn.dataset_id)
    else:
        runtime_sha, runtime_fc = canonical_sha, None
    store = store or get_acquisition_store()
    try:
        acquisition = store.active(defn.dataset_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("acquisition history を読めません: %s: %s", defn.dataset_id, exc)
        acquisition = None
    data_lake = Path(data_lake) if data_lake else _data_lake_root()
    if registry_type:
        from app.services import data_ops_service as dos
        trel = dos.tile_rel(defn) if dos.tile_requirement(defn) in ("required", "optional") else None
    else:
        trel = rp.tile_rel(defn.dataset_id, defn.region, defn.layer_type) if defn.requires_tile_build else None
    tile_path = None
    if trel:
        cand = data_lake / "tiles" / defn.region / defn.layer_type / Path(trel).name
        tile_path = cand if cand.is_file() else None
    record = rp.build_record(defn, state, acquisition=acquisition, canonical_sha256=canonical_sha,
                             runtime_rel_path=rel, runtime_sha256=runtime_sha, runtime_feature_count=runtime_fc,
                             canonical_feature_count=canonical_fc, tile_path=tile_path, tile_rel_path=trel)
    # 検証結果（artifact_record 方式の publish が要求する）。確認できた事実だけを入れる。
    validation: Dict[str, Any] = {"canonical_validation_status": state.validation_status.value}
    if registry_type:
        validation["registry_canonical_check"] = "passed"  # dataset_id 全件一致・depth 解釈一致（resolve_tsunami_source）
    if defn.layer_type == "flood":
        from app.services.data_ops_service import routing_validation_from_logs
        rv = routing_validation_from_logs([acquisition.ingest_job_id if acquisition else None, state.last_job_id],
                                          Path(rel).name, runtime_fc)
        validation["routing_coverage_false_negatives"] = rv["coverage_false_negatives"] if rv else None
        validation["routing_validation_source"] = rv["source"] if rv else None
    record["validation"] = validation
    return record


def export(defn, state, **kw) -> Path:
    data_lake = Path(kw.pop("data_lake", None) or _data_lake_root())
    record = generate(defn, state, data_lake=data_lake, **kw)
    return rp.write_record(rp.build_path(data_lake, defn.region, defn.layer_type, defn.dataset_id), record)
