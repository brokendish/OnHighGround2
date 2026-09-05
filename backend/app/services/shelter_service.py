"""
shelter_service.py — 避難場所データの読み込みと ShelterRegistry

ShelterRegistry は active_mappings.json を参照して、各地域の「有効データセット」を
リクエスト時に動的に解決し、TTL 付きキャッシュで返す。

loading ユーティリティ（parse_float, load_emergency_shelters* など）も
main.py から移動してここで一元管理する。
"""
from __future__ import annotations

import csv
import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]

# ── ファイルパス → リージョン識別子 ────────────────────────────────────────────

REGION_PATH_MAP: List[tuple] = [
    ("kanagawa", "kanagawa"),
    ("chiba",    "chiba"),
    ("saitama",  "saitama"),
    ("tokyo",    "tokyo"),
    ("13000",    "tokyo"),  # legacy Tokyo CSV ファイル名
]


def _region_from_path(path_str: str) -> str:
    """ファイルパスからリージョン識別子を返す。マッチしなければ 'unknown'。"""
    lower = path_str.lower()
    for keyword, region in REGION_PATH_MAP:
        if keyword in lower:
            return region
    return "unknown"


# ── ハザード列マッピング ────────────────────────────────────────────────────────

HAZARD_COLUMN_MAP: Dict[str, str] = {
    "洪水":               "flood",
    "崖崩れ、土石流及び地滑り": "landslide",
    "高潮":               "storm_surge",
    "地震":               "earthquake",
    "津波":               "tsunami",
    "大規模な火事":         "fire",
    "内水氾濫":            "inland_flood",
    "火山現象":            "volcano",
}

# 指定避難所ファイルに特有の列名（これらがあれば evacuation_shelter として扱う）
_EVACUATION_SHELTER_INDICATOR_KEYS = frozenset({
    "受入対象者",
    "指定緊急避難場所との住所同一",
})

# shelter_atomic_publish修復: active_mappings.json の layer_type のうち、
# 「避難所系」として扱う集合。従来 _resolve_paths() 内のローカル変数だった
# ものをmodule levelへ昇格し、scripts/publish/resolve_shelter_sources.py
# （atomic publish時に同じ集合でactive datasetを列挙する）と単一の情報源を
# 共有する。どちらか一方だけ更新して集合が乖離する事態を構造的に防ぐ。
SHELTER_LAYER_TYPES = frozenset({"shelter", "evacuation_shelter", "emergency_shelter"})


# ── ユーティリティ ──────────────────────────────────────────────────────────────

def parse_float(value: Any) -> Optional[float]:
    """文字列/数値を float に変換（失敗時は None）。"""
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _infer_file_default_designation(features: list) -> str:
    """GeoJSON の全フィーチャのプロパティ列名からファイル種別を推定する。
    指定避難所固有の列が見つかれば '指定避難所'、それ以外は '指定緊急避難場所' を返す。"""
    all_keys: set = set()
    for feat in features:
        all_keys.update((feat.get("properties") or {}).keys())
    if _EVACUATION_SHELTER_INDICATOR_KEYS & all_keys:
        return "指定避難所"
    for feat in features:
        shisetu = (feat.get("properties") or {}).get("施設種別", "")
        if shisetu in ("避難所", "指定避難所"):
            return "指定避難所"
    return "指定緊急避難場所"


# ── 避難場所ローダー ────────────────────────────────────────────────────────────

def load_emergency_shelters_from_csv(
    csv_path: Path,
    shelters: List[Dict[str, Any]],
    seen: set,
) -> None:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (
                row.get("施設・場所名")
                or row.get("name")
                or row.get("名称")
                or row.get("施設名")
                or ""
            ).strip()
            address = (row.get("住所") or row.get("address") or "").strip()
            lat = parse_float(row.get("緯度") or row.get("lat"))
            lon = parse_float(row.get("経度") or row.get("lon"))

            if lat is None or lon is None:
                continue

            designation = (row.get("designation") or "指定緊急避難場所").strip()
            if designation and designation not in (
                "指定緊急避難場所", "緊急避難場所", "指定避難所", "避難所"
            ):
                continue

            key = (name, round(lat, 7), round(lon, 7), designation)
            if key in seen:
                continue
            seen.add(key)

            hazard_types = [
                en_key for jp_col, en_key in HAZARD_COLUMN_MAP.items()
                if str(row.get(jp_col, "")).strip() == "1"
            ]
            if designation in ("指定避難所", "避難所"):
                category = "evacuation_shelter"
            else:
                category = "emergency_evacuation_site"

            src = (
                str(csv_path.relative_to(_PROJECT_ROOT))
                if csv_path.is_relative_to(_PROJECT_ROOT)
                else str(csv_path)
            )
            shelters.append({
                "name": name or "名称未設定",
                "address": address,
                "lat": lat,
                "lon": lon,
                "designation": designation or "指定緊急避難場所",
                "category": category,
                "hazard_types": hazard_types,
                "region": _region_from_path(src),
                "source_file": src,
            })


def load_emergency_shelters_from_geojson(
    geojson_path: Path,
    shelters: List[Dict[str, Any]],
    seen: set,
) -> None:
    with geojson_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if data.get("type") != "FeatureCollection":
        logger.warning("GeoJSON shelter source is not a FeatureCollection: %s", geojson_path)
        return

    features = data.get("features", [])
    _file_default_designation = _infer_file_default_designation(features)

    for feature in features:
        properties = feature.get("properties", {}) or {}
        geometry = feature.get("geometry", {}) or {}
        coordinates = geometry.get("coordinates")
        if (
            geometry.get("type") != "Point"
            or not isinstance(coordinates, list)
            or len(coordinates) < 2
        ):
            continue

        lon = parse_float(coordinates[0])
        lat = parse_float(coordinates[1])
        if lat is None or lon is None:
            continue

        name = (
            properties.get("施設・場所名")
            or properties.get("name")
            or properties.get("名称")
            or properties.get("施設名")
            or "名称未設定"
        ).strip()
        address = (
            properties.get("住所")
            or properties.get("address")
            or properties.get("所在地")
            or ""
        ).strip()
        designation = (
            properties.get("designation")
            or properties.get("指定区分")
            or _file_default_designation
        ).strip()

        if designation and designation not in (
            "指定緊急避難場所", "緊急避難場所", "指定避難所", "避難所"
        ):
            continue

        key = (name, round(lat, 7), round(lon, 7), designation)
        if key in seen:
            continue
        seen.add(key)

        hazard_types = [
            en_key for jp_col, en_key in HAZARD_COLUMN_MAP.items()
            if str(properties.get(jp_col, "")).strip() == "1"
        ]
        if designation in ("指定避難所", "避難所"):
            category = "evacuation_shelter"
        else:
            category = "emergency_evacuation_site"

        src = (
            str(geojson_path.relative_to(_PROJECT_ROOT))
            if geojson_path.is_relative_to(_PROJECT_ROOT)
            else str(geojson_path)
        )
        shelters.append({
            "name": name,
            "address": address,
            "lat": lat,
            "lon": lon,
            "designation": designation or "指定緊急避難場所",
            "category": category,
            "hazard_types": hazard_types,
            "region": _region_from_path(src),
            "source_file": src,
        })


def load_emergency_shelters(paths: List[Path]) -> List[Dict[str, Any]]:
    """指定された CSV / GeoJSON 群から指定緊急避難場所を読み込む。"""
    shelters: List[Dict[str, Any]] = []
    seen: set = set()

    for path in paths:
        if path.is_dir():
            data_paths = sorted(
                list(path.rglob("*.geojson")) + list(path.rglob("*.csv"))
            )
        else:
            data_paths = [path]

        for data_path in data_paths:
            if not data_path.exists():
                logger.warning("避難場所データが見つかりません: %s", data_path)
                continue
            try:
                if data_path.suffix.lower() == ".csv":
                    load_emergency_shelters_from_csv(data_path, shelters, seen)
                elif data_path.suffix.lower() == ".geojson":
                    load_emergency_shelters_from_geojson(data_path, shelters, seen)
            except Exception:
                logger.exception("避難場所データの読み込みに失敗しました: %s", data_path)

    logger.info("避難場所データ読み込み件数: %d", len(shelters))
    return shelters


# ── ShelterRegistry ────────────────────────────────────────────────────────────

class _AtomicStateCorrupted(Exception):
    """CODEX P2B5-CX-004（第7ラウンド）対応: is_available()==True（一度は
    初期化済み）にもかかわらずleased_version_root()が失敗した状態を、
    「そもそも未導入」と区別して表す内部専用例外。ShelterRegistryの外へは
    伝播させない（呼び出し元_load()内でキャッシュ維持またはfail-closedへ
    変換する）。"""


class ShelterRegistry:
    """
    active_mappings.json を参照して、有効な避難場所データセットのみを読み込む
    TTL 付きキャッシュ。

    優先順位:
      1. active_mappings で指定された各地域のデプロイ済みファイル
      2. data_runtime/backend/shelters/ 全体（active mapping 未設定時のフォールバック）
      3. data_lake/validated/*/shelter/（runtime が空の場合のフォールバック）

    admin で deploy/rollback が完了したら invalidate() を呼ぶことでキャッシュを
    即時クリアし、次リクエスト時にライブデータを反映させる。
    """

    # フォールバックパスのみに依存するとき大量の（古い）ファイルを誤ってロードしないよう、
    # .backup ファイルは意図的にスキップする
    _SKIP_SUFFIXES = {".backup"}

    def __init__(self, ttl_seconds: int = 30) -> None:
        self._ttl_seconds = ttl_seconds
        self._cache: Optional[List[Dict[str, Any]]] = None
        self._cache_at: Optional[datetime] = None
        self._lock = threading.Lock()
        # CODEX P2B5-CX-004（第5ラウンド）対応: atomic publish/lease機構
        # （Phase 2-B.5）経由で最後にloadしたversion IDを保持し、TTL満了を
        # 待たずにcurrentのversion変化を検知してcache invalidationできる
        # ようにする（下記_is_stale()参照）。
        self._last_loaded_version_id: Optional[str] = None

    # ── 公開 API ──────────────────────────────────────────────────────────────

    def get_shelters(self) -> List[Dict[str, Any]]:
        """有効な避難場所リストを返す（TTLキャッシュ＋atomic publish version変化検知）。"""
        with self._lock:
            if self._cache is None or self._is_stale():
                self._cache = self._load()
                self._cache_at = datetime.utcnow()
        return self._cache

    def invalidate(self) -> None:
        """キャッシュを強制クリアする。次の get_shelters() 呼び出しで再読み込みされる。"""
        with self._lock:
            self._cache = None
            self._cache_at = None
        logger.info("ShelterRegistry: cache invalidated — will reload on next request")

    # ── 内部 ──────────────────────────────────────────────────────────────────

    def _is_stale(self) -> bool:
        if self._cache_at is None:
            return True
        elapsed = (datetime.utcnow() - self._cache_at).total_seconds()
        if elapsed > self._ttl_seconds:
            return True
        # CODEX P2B5-CX-004（第5ラウンド）対応: TTL満了前でも、atomic
        # publish機構のcurrentが最後の読み込み時と異なるversionへ切り替わって
        # いれば即座にstale扱いする（TTLの30秒〜1時間を待たず、新規publishを
        # 素早く反映するため）。current解決自体が失敗する場合は判定できない
        # ため、安全側でstale扱いにしない（既存TTLだけに委ねる）。
        current_vid = self._peek_current_version_id()
        if current_vid is not None and current_vid != self._last_loaded_version_id:
            return True
        return False

    @staticmethod
    def _peek_current_version_id() -> Optional[str]:
        """`data_runtime/current`が指すversion IDを軽量に確認するだけの
        read-only probe（leaseを取得しない、`_load()`の実読み込みとは別）。
        存在しない/読めない場合はNoneを返す（呼び出し元はTTLのみに委ねる）。"""
        try:
            from app.services import runtime_version_access as rva

            if not rva.is_available():
                return None
            current_link = rva.DATA_RUNTIME_ROOT / "current"
            if not current_link.is_symlink():
                return None
            target = os.readlink(current_link)
            return Path(target).name
        except OSError:
            return None

    def _load(self) -> List[Dict[str, Any]]:
        # CODEX P2B5-CX-004（第7ラウンド）対応: 旧実装は「atomic publish機構
        # 未導入（is_available()==False）」と「導入済みだが現在corruptしている
        # （coordination.lock存在、しかしacquire_current()がLeaseError）」を
        # 区別せず、両方を同じ`RuntimeAtomicError`捕捉でlegacy pathへ静かに
        # fallbackしていた。独立検証で「初期化済みcoordination/currentの
        # 破損でもatomic snapshotを捨ててflat legacy readerへ戻る」と
        # 指摘された（CORRUPT_ATOMIC_STATE_FELL_BACK=True）。
        #
        # 前者（真に未導入）はlegacyへのfallbackが正しい（Phase 2-B.5以前の
        # 環境や、atomic対象データセットが単に存在しない場合）。
        # 後者（導入済みだが破損）はlegacyという別の・未検証の情報源へ
        # サイレントに切り替えるべきではない。直近の既知良好キャッシュが
        # あればそれを維持し、初回load時点で既に破損している場合は
        # fail-closedで例外を伝播する。
        from app.services import runtime_version_access as rva

        if rva.is_available():
            try:
                atomic_result = self._try_load_from_atomic_publish()
            except _AtomicStateCorrupted as exc:
                if self._cache is not None:
                    logger.error(
                        "ShelterRegistry: atomic publish状態が破損（%s）。"
                        "legacyへfallbackせず、直近の既知良好キャッシュ（version=%s）を維持する",
                        exc, self._last_loaded_version_id,
                    )
                    return self._cache
                logger.error(
                    "ShelterRegistry: atomic publish状態が破損しており、"
                    "既知良好キャッシュも存在しない（fail-closed）: %s", exc,
                )
                raise
            if atomic_result is not None:
                return atomic_result
            # is_available()==True だが対象datasetがversion配下に存在しない
            # （真の「未初期化／未配備」）→ legacyへのfallbackは妥当。

        self._last_loaded_version_id = None
        paths = self._resolve_paths()
        logger.info("ShelterRegistry: loading from %s", [str(p) for p in paths])
        return load_emergency_shelters(paths)

    def _try_load_from_atomic_publish(self) -> Optional[List[Dict[str, Any]]]:
        from app.services.runtime_atomic import RuntimeAtomicError
        from app.services import runtime_version_access as rva
        from app.services.runtime_lease import leased_version_root

        # `coordination.lock`の存在（is_available()）は「leases infra自体は
        # 一度runtime-initで初期化された」ことしか示さず、「操作者が一度でも
        # publish()を実行し`current`を作った」こととは別事象である。
        # `current`が一切存在しない（symlinkはおろかpathすら無い）のは、
        # runtime-init直後でまだ一度もpublishされていない正常な起動直後
        # 状態であり、これをcorruptionとして扱ってfail-closedにすると、
        # 初回デプロイ直後（最初のpublish前）に本processが必ずcrashする。
        # `current`が「存在するが不正」な場合（symlinkでない・target不正・
        # target先versionが無い）は、既存のfail-closed方針（直近の既知
        # 良好キャッシュを維持、無ければ例外伝播）を従来どおり適用する。
        current_link = rva.DATA_RUNTIME_ROOT / "current"
        if not current_link.exists() and not current_link.is_symlink():
            return None

        coordinator = rva.get_coordinator()
        try:
            with leased_version_root(coordinator, rva.DATA_RUNTIME_ROOT, "shelter-registry-load") as version_root:
                paths = []
                for sub in ("shelters", "emergency_shelters"):
                    d = version_root / "backend" / sub
                    if d.is_dir() and d.suffix not in self._SKIP_SUFFIXES:
                        paths.append(d)
                if not paths:
                    return None
                logger.info(
                    "ShelterRegistry: loading from atomic publish current (version=%s): %s",
                    version_root.name, [str(p) for p in paths],
                )
                shelters = load_emergency_shelters(paths)
                self._last_loaded_version_id = version_root.name
                return shelters
        except RuntimeAtomicError as exc:
            # is_available()（coordination.lock存在）は呼び出し元で確認済み
            # ——つまりleases infrastructure自体は一度は正しく初期化された
            # 環境である。ここでのRuntimeAtomicError（LeaseErrorはその
            # subclass）は「導入済みだが現在corruptしている」ことを意味する
            # ため、legacy fallback対象のNoneではなく、専用例外として
            # 呼び出し元へ伝播する。
            raise _AtomicStateCorrupted(str(exc)) from exc

    def _resolve_paths(self) -> List[Path]:
        """
        active_mappings の shelter エントリーから読み込みパスを決定する。
        エントリーがなければ従来の runtime dir へフォールバック。
        """
        from app.services.active_mapping_service import get_active_mapping_service
        from app.services.dataset_definition_service import get_definition_service
        from app.services.dataset_state_service import get_state_service

        ams = get_active_mapping_service()
        ds_svc = get_definition_service()
        ss_svc = get_state_service()

        # layer_type が shelter 系の active mapping を地域×データセットIDで収集
        # 1地域につき複数データセット（指定緊急避難場所＋指定避難所）を同時にロードできるよう
        # Dict[str, List[str]] で保持する
        active_shelter_map: Dict[str, List[str]] = {}
        for m in ams.list_all():
            if m["layer_type"] in SHELTER_LAYER_TYPES:
                active_shelter_map.setdefault(m["region"], []).append(m["dataset_id"])

        paths: List[Path] = []

        if active_shelter_map:
            for region in sorted(active_shelter_map):
                for dataset_id in active_shelter_map[region]:
                    defn = ds_svc.get(dataset_id)
                    if defn is None:
                        logger.warning(
                            "ShelterRegistry: active dataset '%s' not found in registry, skipping",
                            dataset_id,
                        )
                        continue

                    state = ss_svc.init_from_definition(defn)

                    # state.current_runtime_path: deploy が完了した際に書き込まれる具体パス
                    if state.current_runtime_path:
                        p = Path(state.current_runtime_path)
                        if p.exists() and p.suffix not in self._SKIP_SUFFIXES:
                            logger.info(
                                "ShelterRegistry: [%s] %s -> %s (active mapping)",
                                region, dataset_id, p,
                            )
                            paths.append(p)
                            continue
                        else:
                            logger.warning(
                                "ShelterRegistry: runtime path not found for %s: %s",
                                dataset_id, p,
                            )

                    # current_runtime_path が未設定 or 消えている場合は defn.runtime_path を試みる
                    fallback_p = (_PROJECT_ROOT / defn.runtime_path).resolve()
                    if fallback_p.exists():
                        logger.warning(
                            "ShelterRegistry: [%s] using defn runtime_path as fallback: %s",
                            region, fallback_p,
                        )
                        paths.append(fallback_p)

        if paths:
            return paths

        # active mapping なし or すべて解決失敗 → 全 runtime dir からロード（後方互換）
        for runtime_subdir in ("shelters", "emergency_shelters"):
            runtime_dir = _PROJECT_ROOT / "data_runtime" / "backend" / runtime_subdir
            if runtime_dir.exists():
                logger.info(
                    "ShelterRegistry: no active mappings resolved — loading all from %s",
                    runtime_dir,
                )
                paths.append(runtime_dir)
        if paths:
            return paths

        # さらに data_lake validated へフォールバック
        for pattern in ("data_lake/validated/*/shelters", "data_lake/validated/*/shelter",
                        "data_lake/validated/*/emergency_shelters"):
            for candidate in _PROJECT_ROOT.glob(pattern):
                if candidate.is_dir():
                    logger.warning("ShelterRegistry: fallback to data_lake: %s", candidate)
                    paths.append(candidate)

        if paths:
            return paths

        # 最終フォールバック: legacy CSV（環境によって存在しない場合がある）
        legacy = _PROJECT_ROOT / "国土地理院避難所データ" / "東京" / "13000_2" / "13000_2.csv"
        logger.warning("ShelterRegistry: using legacy fallback: %s", legacy)
        return [legacy]


# ── シングルトン ────────────────────────────────────────────────────────────────

_registry_instance: Optional[ShelterRegistry] = None


def get_shelter_registry() -> ShelterRegistry:
    """ShelterRegistry のシングルトンを返す。"""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = ShelterRegistry(ttl_seconds=3600)
    return _registry_instance
