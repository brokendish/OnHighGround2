"""
runtime_dataset_validate.py — Phase 2-B.5 staging dataset validator。

tasks/public-release/phase2b5_claude_implementation_instruction.md 第5.3節 step 3
（schema、件数、checksum、参照整合性、必須file、permissionの検証）。

CODEX P2B5-CX-003対応: 旧`_validate_staging()`は「空でない」「backend
directoryがある」だけを見ており、不正JSON・checksumなしdatasetでも
publishが成功していた。本moduleは以下を検証する。

  - 既知拡張子（.json/.geojson/.geojsonl）のfileが構文的に有効なJSONである
  - `.geojson`/`.geojsonl`は、さらにGeoJSON schema（RFC 7946）として
    構造的に妥当であることも検証する（CODEX第4ラウンド対応: valid JSON
    構文だけではvalid GeoJSONであることを意味せず、
    `{"not_geojson": true}`のような構文的には正しいが意味的に不正な
    dataがpublishされてしまう問題を独立検証で指摘された）
  - .mbtilesが有効なSQLite databaseとして開ける（壊れたbinaryを拒否する）
  - 全fileのsha256を計算し、`_manifest.json`をversion root直下へ生成する
    （publish後、任意時点で内容の完全性を再検証できるようにする）
  - 既存manifest（再publish・再検証時）と実fileのcontentが一致し、disk上に
    manifest未記録の追加fileが存在しないことを検証する
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional

from .runtime_atomic import RuntimeAtomicError

JSON_LIKE_SUFFIXES = {".json"}
GEOJSON_SUFFIXES = {".geojson"}
JSONL_SUFFIXES = {".geojsonl"}
SQLITE_SUFFIXES = {".mbtiles"}

# RFC 7946 (GeoJSON) が定義するtop-level／geometry typeの全集合。
_GEOJSON_GEOMETRY_TYPES = {
    "Point", "MultiPoint", "LineString", "MultiLineString",
    "Polygon", "MultiPolygon", "GeometryCollection",
}
_GEOJSON_TOP_LEVEL_TYPES = {"Feature", "FeatureCollection"} | _GEOJSON_GEOMETRY_TYPES


# CODEX P2B5-CX-003（第6ラウンド）対応: 座標の有限性・WGS84範囲。
# 高度（3要素目）は範囲制約の対象外（RFC 7946は高度の値域を規定しない）。
_LON_RANGE = (-180.0, 180.0)
_LAT_RANGE = (-90.0, 90.0)


def _validate_geojson_position(pos: Any, path: Path, context: str) -> None:
    """RFC 7946 3.1.1節: positionは2要素以上（経度・緯度、任意で高度）の
    数値配列。CODEX第5ラウンド指摘: 旧実装は`coordinates`がlistである
    ことしか見ておらず、空配列や文字列要素を含むpositionを受理していた
    （独立検証で`RFC7946_INVALID_POINT_EMPTY_COORDINATES_ACCEPTED=True`
    ／`RFC7946_INVALID_POINT_STRING_COORDINATE_ACCEPTED=True`として実証）。

    CODEX第6ラウンド指摘: 非有限値（NaN/Infinity）とWGS84範囲外の経度・
    緯度も受理していた（`point_nonfinite`／`point_out_of_range`として
    独立再現）。数値であることに加え、有限であること・経度緯度が
    WGS84の値域内であることも検証する。
    """
    if not isinstance(pos, list) or len(pos) < 2:
        raise RuntimeAtomicError(
            f"不正なGeoJSON position（要素数2以上の配列でない）: {path} [{context}]: {pos!r}"
        )
    for i, v in enumerate(pos):
        # bool は Python では int のsubclassのため、明示的に除外する
        # （True/Falseが座標値として紛れ込むことを防ぐ）。
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise RuntimeAtomicError(
                f"不正なGeoJSON position要素（数値でない）: {path} [{context}][{i}]: {v!r}"
            )
        if not math.isfinite(v):
            raise RuntimeAtomicError(
                f"不正なGeoJSON position要素（非有限値）: {path} [{context}][{i}]: {v!r}"
            )
    lon, lat = pos[0], pos[1]
    if not (_LON_RANGE[0] <= lon <= _LON_RANGE[1]):
        raise RuntimeAtomicError(
            f"不正なGeoJSON position（経度がWGS84範囲外）: {path} [{context}]: lon={lon!r}"
        )
    if not (_LAT_RANGE[0] <= lat <= _LAT_RANGE[1]):
        raise RuntimeAtomicError(
            f"不正なGeoJSON position（緯度がWGS84範囲外）: {path} [{context}]: lat={lat!r}"
        )


def _validate_position_list(coords: Any, path: Path, context: str, min_len: int) -> None:
    """positionのリスト（LineString、MultiPoint等）を検証する。"""
    if not isinstance(coords, list) or len(coords) < min_len:
        raise RuntimeAtomicError(
            f"不正なGeoJSON coordinates（{min_len}点以上のposition配列でない）: {path} [{context}]"
        )
    for i, pos in enumerate(coords):
        _validate_geojson_position(pos, path, f"{context}[{i}]")


def _validate_linear_ring(coords: Any, path: Path, context: str) -> None:
    """RFC 7946 3.1.6節: Polygon linear ringは4点以上、かつ始点と終点が
    一致していなければならない。CODEX第6ラウンド指摘: 旧実装はこれを
    検証しておらず、短い未閉鎖ringも受理していた
    （`polygon_unclosed_short_ring`として独立再現）。"""
    _validate_position_list(coords, path, context, min_len=4)
    if coords[0] != coords[-1]:
        raise RuntimeAtomicError(
            f"不正なGeoJSON linear ring（始点と終点が一致しない、未閉鎖）: {path} [{context}]"
        )


def _validate_polygon_coords(coords: Any, path: Path, context: str) -> None:
    if not isinstance(coords, list) or not coords:
        raise RuntimeAtomicError(f"不正なGeoJSON Polygon（ring配列が空）: {path} [{context}]")
    for i, ring in enumerate(coords):
        _validate_linear_ring(ring, path, f"{context}[{i}]")


def _validate_multilinestring_coords(coords: Any, path: Path, context: str) -> None:
    if not isinstance(coords, list) or not coords:
        raise RuntimeAtomicError(f"不正なGeoJSON MultiLineString（配列が空）: {path} [{context}]")
    for i, line in enumerate(coords):
        _validate_position_list(line, path, f"{context}[{i}]", min_len=2)


def _validate_multipolygon_coords(coords: Any, path: Path, context: str) -> None:
    if not isinstance(coords, list) or not coords:
        raise RuntimeAtomicError(f"不正なGeoJSON MultiPolygon（配列が空）: {path} [{context}]")
    for i, polygon in enumerate(coords):
        _validate_polygon_coords(polygon, path, f"{context}[{i}]")


def _validate_geojson_geometry(obj: Any, path: Path, context: str) -> None:
    """geometry typeごとのcardinality／closure要件（RFC 7946 3.1節）を
    typeに応じて分岐して検証する。CODEX第6ラウンド指摘: 旧実装はdepthだけ
    でcoordinatesを再帰しており、LineStringの1点（`linestring_one_position`）
    のようなtype固有の最小点数・閉環要件を検証していなかった。"""
    if not isinstance(obj, dict):
        raise RuntimeAtomicError(f"不正なGeoJSON geometry（objectでない）: {path} [{context}]")
    t = obj.get("type")
    if t not in _GEOJSON_GEOMETRY_TYPES:
        raise RuntimeAtomicError(f"不正なGeoJSON geometry type: {path} [{context}]: type={t!r}")
    if t == "GeometryCollection":
        geometries = obj.get("geometries")
        if not isinstance(geometries, list):
            raise RuntimeAtomicError(f"GeometryCollectionにgeometries配列がない: {path} [{context}]")
        for i, g in enumerate(geometries):
            _validate_geojson_geometry(g, path, f"{context}.geometries[{i}]")
        return
    if "coordinates" not in obj:
        raise RuntimeAtomicError(
            f"GeoJSON geometryにcoordinatesがない: {path} [{context}]: type={t}"
        )
    coords = obj["coordinates"]
    coord_context = f"{context}.coordinates"
    if t == "Point":
        _validate_geojson_position(coords, path, coord_context)
    elif t == "MultiPoint":
        _validate_position_list(coords, path, coord_context, min_len=1)
    elif t == "LineString":
        _validate_position_list(coords, path, coord_context, min_len=2)
    elif t == "MultiLineString":
        _validate_multilinestring_coords(coords, path, coord_context)
    elif t == "Polygon":
        _validate_polygon_coords(coords, path, coord_context)
    elif t == "MultiPolygon":
        _validate_multipolygon_coords(coords, path, coord_context)


def _validate_geojson_feature(
    obj: Any,
    path: Path,
    context: str,
    required_property_keys: Optional[FrozenSet[str]] = None,
    required_property_types: Optional[Dict[str, tuple]] = None,
    required_property_ranges: Optional[Dict[str, tuple]] = None,
) -> None:
    if not isinstance(obj, dict) or obj.get("type") != "Feature":
        raise RuntimeAtomicError(f"不正なGeoJSON Feature: {path} [{context}]")
    if "properties" not in obj:
        raise RuntimeAtomicError(f"GeoJSON Featureにpropertiesがない: {path} [{context}]")
    # CODEX第5ラウンド指摘: propertiesが文字列等でも受理していた
    # （`RFC7946_INVALID_FEATURE_STRING_PROPERTIES_ACCEPTED=True`）。
    # RFC 7946 3.2節: propertiesはobjectまたはnullでなければならない。
    properties = obj["properties"]
    if properties is not None and not isinstance(properties, dict):
        raise RuntimeAtomicError(
            f"GeoJSON Featureのpropertiesがobjectでもnullでもない: {path} [{context}]: "
            f"type={type(properties).__name__}"
        )
    # CODEX P2B5-CX-003（第6ラウンド）対応: dataset固有schema検証。
    # hazard typeごとに正規化scriptが常に出力する必須propertiesキー
    # （_HAZARD_TYPE_REQUIRED_PROPERTY_KEYS参照）が欠落しているFeatureを
    # 拒否する。「構文的に妥当なGeoJSON」と「業務的に正しいhazard dataset」
    # は別の検証層であるという、これまでの開示（第19.1節等）で未実装だった
    # 部分に対応する。
    if required_property_keys:
        present = set(properties.keys()) if isinstance(properties, dict) else set()
        missing = required_property_keys - present
        if missing:
            raise RuntimeAtomicError(
                f"dataset固有schema違反（必須propertiesキー不足）: {path} [{context}]: "
                f"missing={sorted(missing)}"
            )
    # CODEX P2B5-CX-003（第7ラウンド）対応: 必須キーの「存在」だけでなく
    # 「値の型」も検証する。独立検証で`properties.flood_rank = {"not":
    # "a rank"}`（dict）がキー存在だけの検証をすり抜けてpublishできる
    # ことを再現された。期待型は実データ全件走査（第21.1節と同様の手法）
    # で確定した型のみをそのまま要求する（boolはintのsubclassのため
    # 明示的に除外する）。
    if required_property_types and isinstance(properties, dict):
        for key, expected_types in required_property_types.items():
            if key not in properties:
                continue
            value = properties[key]
            if isinstance(value, bool) or not isinstance(value, expected_types):
                raise RuntimeAtomicError(
                    f"dataset固有schema違反（propertiesの値型が不正）: {path} [{context}]: "
                    f"{key}={value!r}（期待型={[t.__name__ for t in expected_types]}、"
                    f"実際={type(value).__name__}）"
                )
    # CODEX P2B5-CX-003（第8ラウンド）対応: 型検証だけでは業務値域外の
    # 値（`flood_rank=999`等）を検出できないと指摘された。normalize
    # scriptのmapping定義から読み取ったinclusive範囲（min, max）で
    # 数値keyの値域を検証する。
    if required_property_ranges and isinstance(properties, dict):
        for key, (min_v, max_v) in required_property_ranges.items():
            if key not in properties:
                continue
            value = properties[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue  # 型不正は上の required_property_types 側で検出済み
            if not (min_v <= value <= max_v):
                raise RuntimeAtomicError(
                    f"dataset固有schema違反（propertiesの値が業務値域外）: {path} [{context}]: "
                    f"{key}={value!r}（許容範囲={min_v}〜{max_v}）"
                )
    geometry = obj.get("geometry")
    if geometry is not None:
        _validate_geojson_geometry(geometry, path, f"{context}.geometry")


def _validate_geojson_schema(
    obj: Any,
    path: Path,
    required_property_keys: Optional[FrozenSet[str]] = None,
    required_property_types: Optional[Dict[str, tuple]] = None,
    required_property_ranges: Optional[Dict[str, tuple]] = None,
) -> int:
    """RFC 7946のtop-level type（Feature/FeatureCollection/各geometry種別）
    のうちいずれかとして構造的に妥当であることを検証する。構文的に有効な
    JSONというだけでは、GeoJSONとして意味を持つ保証にならない
    （CODEX第4ラウンド指摘: `{"not_geojson": true}`はvalid JSONだが
    GeoJSONとしては不正であり、旧実装はこれを検出しなかった）。

    検証したFeature件数を返す（CODEX P2B5-CX-003対応の件数検証に使用）。
    """
    if not isinstance(obj, dict):
        raise RuntimeAtomicError(f"GeoJSONとして不正（top-levelがobjectでない）: {path}")
    t = obj.get("type")
    if t not in _GEOJSON_TOP_LEVEL_TYPES:
        raise RuntimeAtomicError(
            f"GeoJSONとして不正なtop-level type: {path}: type={t!r}"
            f"（RFC 7946が定義する型のいずれでもない）"
        )
    # CODEX P2B5-CX-003（第7ラウンド）対応: top-levelが素のgeometry型
    # （Point/Polygon等）の場合、Feature/FeatureCollectionを前提とする
    # propertiesベースのdataset固有schema検証（必須キー・値型）を一切
    # 経由せずにpublishできてしまう（独立検証で
    # `backend/hazard/flood/raw-geometry.geojson`が`{"type":"Point",
    # "coordinates":[139,35]}`のまま受理されることを再現された）。
    # RFC 7946はtop-level geometryを許可するが、本projectのpublish
    # pipelineが実際に発行するdatasetは常にFeature／FeatureCollection
    # であり（全hazard type・shelters・全regionで確認済み）、素のgeometry
    # はmetadataを一切持てず配信datasetとして意味を持たない。
    # required_property_keysが設定されている（＝dataset固有schemaの
    # 検証対象である）file種別では、top-level geometryを拒否する。
    if required_property_keys and t not in ("Feature", "FeatureCollection"):
        raise RuntimeAtomicError(
            f"dataset固有schema違反（top-levelが素のgeometryでproperties検証を経由できない）: "
            f"{path}: type={t!r}"
        )
    if t == "FeatureCollection":
        features = obj.get("features")
        if not isinstance(features, list):
            raise RuntimeAtomicError(f"FeatureCollectionにfeatures配列がない: {path}")
        for i, feat in enumerate(features):
            _validate_geojson_feature(
                feat, path, f"features[{i}]", required_property_keys, required_property_types, required_property_ranges
            )
        return len(features)
    elif t == "Feature":
        _validate_geojson_feature(
            obj, path, "$", required_property_keys, required_property_types, required_property_ranges
        )
        return 1
    else:
        _validate_geojson_geometry(obj, path, "$")
        return 1


# CODEX P2B5-CX-003（第6ラウンド）対応: dataset固有schema検証。
#
# 各keyは「最新のnormalize scriptが出力する完全schema」ではなく、
# `scripts/publish/deploy_to_runtime.sh --region {tokyo,kanagawa} --dry-run`
# で実際にstagingされる全fileを直接読み、tokyo/kanagawa両regionかつ
# 新旧複数世代の正規化済みfileすべてに共通して存在することを実測で
# 確認したintersectionだけを required に採用している（例:
# storm_surgeは地域によってhazard_type/depth_textの有無が割れており
# `storm_surge_rank`だけが両方に共通、floodは`water_depth`/`source`が
# tokyo世代限定・`hazard_type`/`depth_text`/`dataset_id`がkanagawa世代限定
# のため共通集合は`flood_rank`/`river_name`/`river_number`のみ）。
# 正規化scriptのsource定義だけを見て「保証されるはずのkey」を仮定すると、
# data_lakeに現存する複数世代の正規化済みfileを誤ってvalidation failureに
# する（実際に本ラウンドの実装中、storm_surge/tsunami/inland_floodで
# この誤りを一度作り込み、dry-run照合で発見して修正した）。
_HAZARD_TYPE_REQUIRED_PROPERTY_KEYS: Dict[str, FrozenSet[str]] = {
    # floodはkanagawa世代のfileの一部featureがriver_name/river_numberを
    # 欠く（実測: kanagawa_flood_check.geojsonlの545,127件中408,882件で
    # 欠落）ため、全世代・全regionで欠落0件を実測確認した flood_rank
    # だけをrequiredとする。
    "flood": frozenset({"flood_rank"}),
    "storm_surge": frozenset({"storm_surge_rank"}),
    "landslide": frozenset(
        {"hazard_type", "landslide_type", "zone_type", "severity_level", "zone_name", "pref_code", "source"}
    ),
    "inland_flood": frozenset({"depth_rank", "depth_min_m", "depth_label", "zone_name", "city_code"}),
    # tsunamiは国土数値情報A40の生column（都道府県名／都道府県code／
    # 浸水深ラベル）をそのまま通す世代のfileが正規経路で配信され続けている
    # ため、hazard_type等の後付けkeyではなく、全世代・全regionに共通する
    # 生columnをrequiredとする。
    "tsunami": frozenset({"A40_001", "A40_002", "A40_003"}),
    # CODEX P2B5-CX-003（第7ラウンド）対応: lowland_poor_drainageは
    # _WIRED_HAZARD_TYPESに含まれ配線済みだが、required key未定義のため
    # `properties: {}`のような空Featureをそのまま受理していた（独立検証で
    # `backend/hazard/lowland_poor_drainage/no-schema.geojson`として
    # 再現された）。scripts/normalize/normalize_lowland_poor_drainage.pyが
    # 出力し、tokyo/kanagawa両regionの実file全件で欠落0件を確認した
    # 必須keyを追加する。
    "lowland_poor_drainage": frozenset(
        {"dataset", "source", "risk", "risk_score", "region", "elevation_m", "depth_below_tide_m"}
    ),
}

# CODEX P2B5-CX-003（第7ラウンド）対応: 必須キーの「存在」だけでなく
# 「値の型」も検証する。各型はtokyo/kanagawa両region・複数世代の実file
# 全件を走査して確定した型のみを要求する（上のKEYSと同じ手法・同じ
# 実測データに基づく。値型の推測はしていない）。
_HAZARD_TYPE_REQUIRED_PROPERTY_TYPES: Dict[str, Dict[str, tuple]] = {
    "flood": {"flood_rank": (int,)},
    "storm_surge": {"storm_surge_rank": (int,)},
    "landslide": {
        "hazard_type": (str,), "landslide_type": (str,), "zone_type": (str,),
        "severity_level": (str,), "zone_name": (str,), "pref_code": (str,), "source": (str,),
    },
    "inland_flood": {
        "depth_rank": (int,), "depth_min_m": (int, float), "depth_label": (str,),
        "zone_name": (str,), "city_code": (str,),
    },
    "tsunami": {"A40_001": (str,), "A40_002": (str,), "A40_003": (str,)},
    "lowland_poor_drainage": {
        "dataset": (str,), "source": (str,), "risk": (str,), "risk_score": (int,),
        "region": (str,), "elevation_m": (int, float), "depth_below_tide_m": (int, float),
    },
}

# CODEX P2B5-CX-003（第8ラウンド）対応: 型だけでは業務値域外の値
# （`flood_rank=999`等）を検出できないと指摘された（独立検証で
# `flood_rank_999 ACCEPTED`として再現）。各hazard typeのrank/score系
# 数値keyについて、対応するnormalize scriptが定義するmapping（例:
# `normalize_flood.DEPTH_TO_RANK`の値域、`normalize_storm_surge.
# DEPTH_TABLE`のrank値域）から直接読み取ったinclusive範囲を要求する。
# 推測ではなく、各normalize scriptのsource定義を確認して確定した値域
# のみを使用する。
_HAZARD_TYPE_PROPERTY_RANGES: Dict[str, Dict[str, tuple]] = {
    # normalize_flood.DEPTH_TO_RANK = {1:1,2:2,3:3,4:4,5:5,6:5} → 値域1-5
    "flood": {"flood_rank": (1, 5)},
    # normalize_storm_surge.DEPTH_TABLE最大rank=7、未知labelはrank=0
    "storm_surge": {"storm_surge_rank": (0, 7)},
    # normalize_inland_flood._DEPTH_MAP最大depth_rank=7、未知labelは0
    "inland_flood": {"depth_rank": (0, 7)},
    # normalize_lowland_poor_drainage.REQUIRED_PROPERTIESはrisk_score=1の
    # 定数だが、将来の多段階化を見込みsaneな上限のみ設ける
    "lowland_poor_drainage": {"risk_score": (0, 10)},
}

# CODEX P2B5-CX-003（第8ラウンド）対応: 件数整合性（前versionとの比較）は
# 初回publish（比較対象となる前versionが存在しない）には適用できず、
# 独立検証はこの状況で「1 Featureだけの任意dataset」が受理されることを
# 指摘した（`one_feature_only ACCEPTED`）。region間の正当な件数差
# （194〜926,000件超）を考慮し、各hazard typeについて`deploy_to_runtime.sh
# --dry-run`で実際にstagingされた実dataの最小観測件数を直接確認した上で、
# それを十分に下回る絶対floorを設定する（floorは「現実的にありえない
# 極端な過少publish」だけを排除する安全側の値であり、典型値ではない）。
# 実測最小値: flood=545,127（kanagawa）、storm_surge=59,039（tokyo）、
# tsunami=33,124（tokyo）、inland_flood=194（tokyo/kanagawa共通）、
# landslide=29,943（tokyo）、lowland_poor_drainage=1,483（tokyo）。
_HAZARD_TYPE_MIN_FEATURE_COUNT: Dict[str, int] = {
    "flood": 100,
    "storm_surge": 100,
    "tsunami": 100,
    "inland_flood": 50,
    "landslide": 100,
    "lowland_poor_drainage": 50,
}

_HAZARD_STAGING_PATH_RE = re.compile(r"(?:^|/)backend/hazard/([^/]+)/")

# CODEX P2B5-CX-003（第14〜15ラウンド）対応: app_public.pyのtsunami loader
# （`_filename = f"tsunami_{_target}.geojson"`）が実際に参照する厳密な
# filename契約。`tsunami_[a-z0-9_]+\.geojson`というpattern一致は「命名
# 規約に従っている」ことしか保証せず、「実際にconsumerが読む」ことは
# 保証しない。target名がconsumer設定と一致するかは別途、この後の
# exact-match検証で判定する。
_TSUNAMI_FILENAME_RE = re.compile(r"^tsunami_([a-z0-9_]+)\.geojson$")

_TSUNAMI_CONSUMER_CONFIG_KEY = "hazard.tsunami.targets"

# CODEX P2B5-CX-003（第16〜17ラウンド）対応: 「deploy_to_runtime.shが
# 生成しうるtarget」のhardcode許可リスト（旧`_TSUNAMI_KNOWN_TARGETS`）は
# 「consumerが実際に読み込むtarget」とは別物であり、両者を混同すると
# consumer未設定targetの余剰・consumer設定targetの欠落のどちらも見逃す。
# 第18ラウンドでは許可リストを廃止し、`app_public.py`が実際に用いる
# `hazard.tsunami.targets`の解決結果（`_resolve_configured_tsunami_
# targets()`）1本だけを正本とし、staging側のtarget集合とexact-match
# させる（欠落・余剰のいずれも拒否）。

# app_public.pyの既定値: `APP_CONFIG.get("hazard.tsunami.targets", "tokyo")`
# → `parse_csv(..., ["tokyo"])`。設定file不在・key不在・値が空文字列の
# いずれも、最終的にこの既定値へ収束する（parse_csvの実装により、値が
# 空/空白のみの場合もdefaultへfallbackするため）。
_TSUNAMI_CONSUMER_DEFAULT_TARGETS = frozenset({"tokyo"})


def _resolve_configured_tsunami_targets() -> "tuple[Optional[FrozenSet[str]], Optional[str]]":
    """`app_public.py`が実際に用いるtsunami target集合を、consumerと
    完全に同一の設定解決ロジック（`backend/app_config_properties.py`、
    CODEX P2B5-CX-003第18ラウンド対応で新設した単一情報源module）を
    経由して導出する。

    戻り値は`(target集合, None)`または`(None, エラー理由)`。

    consumerと安全に共有できるfallbackだけを使う:
      - 設定file不在／key不在／値が空 → consumer側も同じ入力から同じ
        既定値`{"tokyo"}`へ解決するため、この既定値を共有する。
      - 設定file存在下での読取エラー（例: permission denied）→
        consumer側の`APP_CONFIG = load_properties(CONFIG_PATH)`は
        module top-levelで同じOSErrorを一切捕捉せず、app_public.py
        自体のimportが失敗してapp起動不可になる。この状態と同一の
        effective configを保証できないため、Noneとエラー理由を返し、
        呼び出し側にfail-closedでpublishを拒否させる（validator独自の
        None／空集合skipは行わない——呼び出し側は必ずエラーとして扱う）。

    正常解決時、戻り値のtarget集合は`parse_csv`の既定値fallback仕様に
    より必ず非空になる（consumer側の実際の既定値ロジックと同じ理由で、
    validator側が独自に空集合を許容することはない）。
    """
    try:
        import app_config_properties as _cfg
    except ImportError as exc:
        return None, f"設定解決module app_config_properties をimportできない: {exc!r}"

    base_dir = Path(__file__).resolve().parents[2]
    config_path = _cfg.resolve_config_path(base_dir)

    try:
        properties = _cfg.load_properties(config_path)
    except OSError as exc:
        return None, (
            f"tsunami consumer設定file読取不能: {config_path}: {exc!r}"
            f"（consumer側のAPP_CONFIG = load_properties(CONFIG_PATH)はこの"
            f"OSErrorを捕捉せず、app_public.py自体のimportが失敗しapp起動"
            f"不可になる。同一のeffective configを保証できない）"
        )

    raw_value = properties.get(_TSUNAMI_CONSUMER_CONFIG_KEY, "tokyo")
    targets = frozenset(_cfg.parse_csv(raw_value, ["tokyo"]))
    if not targets:
        # parse_csvの既定値fallback仕様上、理論上到達しないはずの状態。
        # 到達した場合はvalidator独自の解釈を持ち込まず、fail-closedとする。
        return None, "consumer設定解決の結果、tsunami target集合が空になった（想定外の状態）"
    return targets, None


def _required_property_keys_for_staging_path(rel: str) -> Optional[FrozenSet[str]]:
    m = _HAZARD_STAGING_PATH_RE.search(rel.replace("\\", "/"))
    if not m:
        return None
    return _HAZARD_TYPE_REQUIRED_PROPERTY_KEYS.get(m.group(1))


def _required_property_types_for_staging_path(rel: str) -> Optional[Dict[str, tuple]]:
    m = _HAZARD_STAGING_PATH_RE.search(rel.replace("\\", "/"))
    if not m:
        return None
    return _HAZARD_TYPE_REQUIRED_PROPERTY_TYPES.get(m.group(1))


def _required_property_ranges_for_staging_path(rel: str) -> Optional[Dict[str, tuple]]:
    m = _HAZARD_STAGING_PATH_RE.search(rel.replace("\\", "/"))
    if not m:
        return None
    return _HAZARD_TYPE_PROPERTY_RANGES.get(m.group(1))


def _min_feature_count_for_staging_path(rel: str) -> int:
    m = _HAZARD_STAGING_PATH_RE.search(rel.replace("\\", "/"))
    if not m:
        return 1
    return _HAZARD_TYPE_MIN_FEATURE_COUNT.get(m.group(1), 1)


# CODEX P2B5-CX-003（第6ラウンド）対応: 参照整合性（reference整合性）。
# `backend/hazard/<type>/`として配置してよいtype名をhazards.py／
# app_public.pyが実際に配線しているhazard typeの集合に限定する。
# 配線されていないtype名のdirectoryが公開されると、そのdataは
# どのconsumerからも読まれないまま存在し続ける（サイレントに孤立した
# publishを許してしまう）ため、参照整合性違反として拒否する。
_WIRED_HAZARD_TYPES = frozenset(
    {"flood", "storm_surge", "tsunami", "inland_flood", "landslide", "lowland_poor_drainage"}
)

MANIFEST_BASENAME = "_manifest.json"

# deploy_to_runtime.shが実際に生成するtop-level構造。全部が毎回存在するとは
# 限らない（region/hazard typeにより一部は欠落しうる）ため、「backend」
# directory自体の存在だけを必須とし、配下の個別hazard typeは存在するもの
# だけを検証する（存在しないtypeを必須化すると、正当なregionだけの部分
# publishまで壊してしまうため）。
REQUIRED_TOP_LEVEL_ENTRIES = ("backend",)


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _validate_json_file(
    path: Path,
    require_geojson_schema: bool = False,
    required_property_keys: Optional[FrozenSet[str]] = None,
    required_property_types: Optional[Dict[str, tuple]] = None,
    required_property_ranges: Optional[Dict[str, tuple]] = None,
) -> int:
    """検証したFeature件数を返す（geojson schema検証を行わない場合は0）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeAtomicError(f"不正なJSON構文: {path}: {exc}") from exc
    except OSError as exc:
        raise RuntimeAtomicError(f"file読取失敗: {path}: {exc}") from exc
    if require_geojson_schema:
        return _validate_geojson_schema(
            obj, path, required_property_keys, required_property_types, required_property_ranges
        )
    return 0


def _validate_jsonl_file(
    path: Path,
    require_geojson_schema: bool = False,
    required_property_keys: Optional[FrozenSet[str]] = None,
    required_property_types: Optional[Dict[str, tuple]] = None,
    required_property_ranges: Optional[Dict[str, tuple]] = None,
) -> int:
    """検証したFeature件数（行数）を返す。"""
    feature_count = 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeAtomicError(f"不正なJSONL行: {path}:{lineno}: {exc}") from exc
                if require_geojson_schema:
                    try:
                        feature_count += _validate_geojson_schema(
                            obj, path, required_property_keys, required_property_types, required_property_ranges
                        )
                    except RuntimeAtomicError as exc:
                        raise RuntimeAtomicError(f"{exc} (line {lineno})") from exc
                else:
                    feature_count += 1
    except UnicodeDecodeError as exc:
        raise RuntimeAtomicError(f"不正なJSONL構文（encoding）: {path}: {exc}") from exc
    except OSError as exc:
        raise RuntimeAtomicError(f"file読取失敗: {path}: {exc}") from exc
    return feature_count


def _validate_sqlite_file(path: Path) -> None:
    # Claude自己検証で発見した実バグ: sqlite3のfile: URIはpath先頭が偶然
    # 二重slash（`//data_runtime/...`）になっていると、"//"直後の最初の
    # segment（例: "data_runtime"）をauthority（host）として解釈し、
    # 空でもlocalhostでもないauthorityとしてfail-closedで拒否する
    # （`sqlite3.OperationalError: invalid uri authority`）。二重slashは
    # 通常のfilesystem呼び出し（open/stat）では単一slashと等価に扱われ無害だが、
    # URI構築だけがこれに敏感なため、"//"を含み得るPathを直接f-stringへ
    # 渡す前に必ず正規化する（`os.path.normpath`はPOSIX規約によりちょうど2つの
    # 先頭slashを意図的に保持するため使えない。`Path.resolve()`で単一slashへ
    # 確実に畳み込む）。
    path = path.resolve()
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            conn.execute("SELECT name FROM sqlite_master LIMIT 1")
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise RuntimeAtomicError(f"不正なmbtiles(SQLite) file: {path}: {exc}") from exc
    except OSError as exc:
        raise RuntimeAtomicError(f"file読取失敗: {path}: {exc}") from exc


# CODEX P2B5-CX-003（第8ラウンド）対応: 件数検証。従来はFeature件数≥1と
# いう構文的下限だけであり、独立検証で1 Featureだけの任意datasetを
# 受理することを指摘された（`one_feature_only ACCEPTED`）。固定の期待値は
# region間で正当な件数差（194〜926,000件超）があるため設定できないが、
# 「前回publishしたversionの同一fileから件数が壊滅的に減少していないか」
# はmanifestから導出できる（CODEXの提案「version manifestやpublish入力
# から期待値を導出する」に対応）。前回件数の50%未満への急減を、データ
# 欠損・誤配置・切り詰めの疑いとしてfail-closedで拒否する。前回manifestが
# ない（初回publish）場合は比較対象がなく、この検証はskipされる。
_COUNT_DROP_THRESHOLD = 0.5
_COUNT_DROP_MIN_BASELINE = 10


def _count_features_in_file(path: Path) -> int:
    """CODEX P2B5-CX-003（第11ラウンド）対応: 記録された値を信用せず、
    実fileを直接re-parseしてFeature件数を導出する。前versionは既に
    publish時にschema検証済みのため、ここではcardinality/型/値域の
    再検証はせず件数のcount目的に限定する。読み取れない場合は0を返す
    （呼び出し側は0を「比較不能」として扱い、その1件だけを検証対象から
    除外する——`_COUNT_DROP_MIN_BASELINE`未満は比較しない既存規約と
    同じ安全側の挙動）。"""
    suffix = path.suffix.lower()
    try:
        if suffix in GEOJSON_SUFFIXES or suffix in JSON_LIKE_SUFFIXES:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            if isinstance(obj, dict):
                t = obj.get("type")
                if t == "FeatureCollection":
                    features = obj.get("features")
                    return len(features) if isinstance(features, list) else 0
                if t == "Feature":
                    return 1
            return 0
        if suffix in JSONL_SUFFIXES:
            count = 0
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        count += 1
            return count
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return 0
    return 0


def _derive_actual_feature_counts(version_path: Path) -> Dict[str, int]:
    """`version_path`配下の実fileを直接re-parseし、相対path→Feature件数の
    辞書を構築する。manifestの`feature_counts`フィールドは一切参照しない
    （CODEX P2B5-CX-003第11ラウンド対応: manifest上の記録値改ざんによる
    件数整合性検証の無効化を防ぐため）。"""
    counts: Dict[str, int] = {}
    if not version_path.is_dir():
        return counts
    for p in sorted(version_path.rglob("*")):
        if not p.is_file() or p.name == MANIFEST_BASENAME:
            continue
        suffix = p.suffix.lower()
        if suffix not in GEOJSON_SUFFIXES and suffix not in JSONL_SUFFIXES:
            continue
        rel = str(p.relative_to(version_path))
        counts[rel] = _count_features_in_file(p)
    return counts


def validate_and_manifest_staging(
    staging_path: Path, previous_version_path: Optional[Path] = None
) -> "tuple[Dict[str, str], Dict[str, int]]":
    """staging directory配下を検証し、(checksum manifest, feature件数)を
    構築して返す（呼び出し側がmanifestをfileへ書き出す）。検証失敗時は
    RuntimeAtomicError。

    `previous_version_path`が与えられ、そのversionに`_manifest.json`が
    存在する場合、同一相対pathのfileについて件数整合性を検証する
    （CODEX P2B5-CX-003第8ラウンド対応）。
    """
    if not staging_path.is_dir():
        raise RuntimeAtomicError(f"staging directoryが存在しない: {staging_path}")
    entries = [p for p in staging_path.iterdir() if p.name != MANIFEST_BASENAME]
    if not entries:
        raise RuntimeAtomicError(f"staging directoryが空: {staging_path}")
    for name in REQUIRED_TOP_LEVEL_ENTRIES:
        if not (staging_path / name).is_dir():
            raise RuntimeAtomicError(f"staging直下に必須directoryが無い: {name}")

    # CODEX P2B5-CX-003（第6ラウンド）対応: 参照整合性。backend/hazard/配下に
    # 配線されていないhazard type名のdirectoryがあれば、そのdataはどの
    # consumerからも読まれずに孤立する。staging段階で拒否する。
    hazard_root = staging_path / "backend" / "hazard"
    if hazard_root.is_dir():
        for child in sorted(hazard_root.iterdir()):
            if child.is_dir() and child.name not in _WIRED_HAZARD_TYPES:
                raise RuntimeAtomicError(
                    f"参照整合性違反: 配線されていないhazard type directory: "
                    f"backend/hazard/{child.name}（既知type={sorted(_WIRED_HAZARD_TYPES)}）"
                )

    # CODEX P2B5-CX-003（第14〜18ラウンド）対応: hazard type directory名の
    # 照合だけでは、directory内部の個々のfilenameがconsumerの参照契約に
    # 合っているか・tsunami directoryそのものが欠落していないか・存在する
    # target集合がconsumer設定と過不足なく一致するかまでは検証できない。
    # `app_public.py`のtsunami loaderは`_filename = f"tsunami_{_target}
    # .geojson"`という厳密なexact filename参照のみを行い（flood/
    # storm_surge/inland_flood/landslide/lowland_poor_drainageのような
    # glob('*.geojson')ではない）、consumerが実際に設定していないtarget名
    # のfile・consumerが要求するtargetの欠落は、いずれもconsumerから
    # 永久に不可視のまま孤立する（前者は無駄なdeploy、後者はcoverageの
    # 無言の消失）。
    #
    # 第18ラウンド以前は、この検証全体が`if tsunami_root.is_dir():`で
    # gateされており、tsunami directoryがまるごと欠落したsnapshotは検証
    # そのものをbypassして受理された。また`configured_targets`の解決に
    # 失敗・空だった場合も`if configured_targets:`というtruthy条件で
    # 検証全体をskipしていた（fail-open）。第18ラウンドでは、
    # configured targetの導出をtsunami directory存在判定より先に行い、
    # 導出結果を必ず使う（truthy skip禁止）よう構造を反転させる。
    configured_targets, config_error = _resolve_configured_tsunami_targets()
    if config_error:
        raise RuntimeAtomicError(
            f"参照整合性違反: tsunami consumer設定を解決できない: {config_error}"
            f"（consumerと同一のeffective configを保証できないためfail-closedで拒否する）"
        )
    # ここに到達した時点でconfigured_targetsは必ず非空（_resolve_
    # configured_tsunami_targets()の契約）。

    tsunami_root = hazard_root / "tsunami"
    present_targets: set = set()
    if tsunami_root.is_dir():
        for child in sorted(tsunami_root.iterdir()):
            if child.is_dir():
                raise RuntimeAtomicError(
                    f"参照整合性違反: backend/hazard/tsunami配下はflat構成のみ許可されるが、"
                    f"directoryが存在する: backend/hazard/tsunami/{child.name}"
                )
            m = _TSUNAMI_FILENAME_RE.match(child.name)
            if not m:
                raise RuntimeAtomicError(
                    f"参照整合性違反: tsunami consumerの参照契約（`tsunami_<target>.geojson`）"
                    f"に一致しないfilename: backend/hazard/tsunami/{child.name}"
                    f"（このfileはconsumerから永久に読まれず孤立する）"
                )
            present_targets.add(m.group(1))

    # staging側のtsunami target集合とconsumer設定target集合をexact-match
    # させる。欠落（consumerが要求するのにstagingに無い）・余剰（stagingに
    # あるがconsumerが設定していない）のいずれも、consumer未設定targetの
    # 混入やcoverageの無言の消失につながるため拒否する
    # （tsunami directoryそのものが欠落している場合はpresent_targets=∅
    # となり、configured_targetsは非空が保証されるため、この一致検証で
    # 自動的に拒否される——専用のdirectory存在判定を別途持たない）。
    if present_targets != configured_targets:
        missing = configured_targets - present_targets
        extra = present_targets - configured_targets
        raise RuntimeAtomicError(
            f"参照整合性違反: tsunami staging target集合がconsumer設定と完全一致しない"
            f"（consumer設定 {_TSUNAMI_CONSUMER_CONFIG_KEY}={sorted(configured_targets)}）: "
            f"欠落={sorted(missing)} 余剰={sorted(extra)}"
            f"（欠落はcoverageの無言消失、余剰はconsumerが読まないtargetの混入を意味する）"
        )

    # CODEX P2B5-CX-003（第10ラウンド）対応: 前versionのmanifestが破損／
    # 削除されている場合、従来は「比較対象なし」として黙って件数整合性
    # 検証全体をskipしていた（`except (OSError, json.JSONDecodeError):
    # previous_feature_counts = {}`）。独立検証は、これが「前manifestを
    # 不正JSON化する」または「削除する」だけで、1000→100件の急減や
    # dataset完全消失の検出を丸ごと無効化できる抜け穴であることを実証した
    # （`existing current + corrupt/missing manifest`を「初回publish相当」
    # へ誤って読み替えていた）。
    #
    # `previous_version_path`が`None`（＝`current`が一度も設定されていない
    # 真の初回publish）である場合だけを、比較対象なしの正当なケースとする。
    # `previous_version_path`が非Noneということは`current`が実在の
    # versionを指しているということであり、そのversionは必ず本system
    # の`AtomicPublisher.publish()`（このmodule自身のvalidate_fn経由）を
    # 通って作られている——つまりmanifestは常に書かれているはずである。
    # manifestの不在／破損は「比較対象がない」ではなく「整合性記録の
    # 改ざん・破損」を意味するため、fail-closedで新規publish自体を拒否する。
    # 例外は、`feature_counts`キー自体が無い（本ラウンド以前に発行された
    # manifestで、feature件数を記録する仕様がまだ存在しなかった）場合のみ
    # ——これは破損ではなく仕様差であり、比較対象なしとして扱ってよい。
    if previous_version_path is not None:
        prev_manifest_path = previous_version_path / MANIFEST_BASENAME
        if not prev_manifest_path.is_file():
            raise RuntimeAtomicError(
                f"件数整合性検証違反（前versionのmanifestが存在しない、改ざん／破損の疑い）: "
                f"{prev_manifest_path}"
            )
        try:
            json.loads(prev_manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeAtomicError(
                f"件数整合性検証違反（前versionのmanifestが読み取れない、改ざん／破損の疑い）: "
                f"{prev_manifest_path}: {exc}"
            ) from exc

    # CODEX P2B5-CX-003（第11ラウンド）対応: 前ラウンドまではmanifestに
    # 記録された`feature_counts`フィールドの値をそのまま信用していた。
    # 独立検証は、manifestが構文的に有効なJSONのままでも、
    # `feature_counts`キーの削除・空object化・記録件数の過小な改ざんの
    # いずれかだけで、1000→100件の急減publishを受理させられることを
    # 実証した。manifestはpublish時に書かれるとはいえ、事後にその特定
    # fieldだけを書き換える・古いまま残すことは、sha256による記録の
    # 正当性検証の対象外だったため検出できていなかった。
    #
    # 「記録された数値を信用する」設計そのものをやめ、前versionの実file
    # （`previous_version_path`配下の実際のbyte）を都度直接re-parseして
    # 真のFeature件数を導出する（`_derive_actual_feature_counts()`）。
    # manifestのfeature_countsは監査・観測用の記録として書き続けるが、
    # 件数整合性検証の判断根拠には一切使わない。
    #
    # CODEX P2B5-CX-003（第13ラウンド）対応: 前ラウンドで「実fileを
    # re-parseして真の件数を導出する」設計に変更したが、re-parseする
    # 対象file自体が改ざん・破損している場合の扱いが抜けていた。独立検証は
    # 次の3ケースすべてでpublishが受理されることを実証した。
    #   (a) 前versionの実fileを不正JSON化 → 件数countがJSONDecodeErrorで
    #       0件になり、`_COUNT_DROP_MIN_BASELINE`未満として比較自体が
    #       skipされていた（fail-open）
    #   (b) 前versionの実fileをmode 000で読取不能化 → 同様にOSErrorで
    #       0件になりskip（fail-open）
    #   (c) 前versionの実fileの内容をmanifest記録のsha256と不一致にした
    #       （＝file自体は読めて件数もcountできるが、その内容がpublish時
    #       に検証された内容と異なる） → re-parseはそのまま「新しい
    #       （改ざん後の）内容」に基づく件数を返してしまい、checksumとの
    #       不一致を一切検査していなかった
    #
    # (a)(b)は「countできない＝比較対象外」という安全側のつもりの設計が
    # 実質的なfail-openになっていたもの、(c)は「re-parseした値」の
    # 正当性そのものを検証していなかったもの。共通の対策として、
    # 前versionの実fileをfeature count導出に使う前に、`verify_manifest_
    # matches_disk()`（既存のrollback完全性確認と同じ関数）でその
    # version全体のchecksum整合性を確認する。読取不能・破損・改ざんの
    # いずれも、この関数がRuntimeAtomicErrorとして検出しfail-closedで
    # 新規publish自体を拒否する。
    if previous_version_path is not None:
        try:
            verify_manifest_matches_disk(previous_version_path)
        except RuntimeAtomicError as exc:
            raise RuntimeAtomicError(
                f"件数整合性検証違反（前versionの実fileがmanifestのchecksumと不一致、"
                f"改ざん／破損の疑い）: {previous_version_path}: {exc}"
            ) from exc

    previous_feature_counts: Dict[str, int] = (
        _derive_actual_feature_counts(previous_version_path) if previous_version_path is not None else {}
    )

    manifest: Dict[str, str] = {}
    feature_counts: Dict[str, int] = {}
    invalid: List[str] = []
    file_count = 0
    for p in sorted(staging_path.rglob("*")):
        if not p.is_file():
            continue
        if p.name == MANIFEST_BASENAME:
            continue
        file_count += 1
        rel = str(p.relative_to(staging_path))
        suffix = p.suffix.lower()
        required_keys = _required_property_keys_for_staging_path(rel)
        required_types = _required_property_types_for_staging_path(rel)
        required_ranges = _required_property_ranges_for_staging_path(rel)
        try:
            if suffix in GEOJSON_SUFFIXES:
                feature_count = _validate_json_file(
                    p, require_geojson_schema=True,
                    required_property_keys=required_keys, required_property_types=required_types,
                    required_property_ranges=required_ranges,
                )
                # CODEX P2B5-CX-003（第6ラウンド→第8ラウンド）対応:
                # 件数検証。当初は0件拒否のみだったが、独立検証で
                # 「1 Featureだけの任意dataset」の受理を指摘された
                # （`one_feature_only ACCEPTED`）。既知hazard typeは
                # 実測最小観測件数を十分下回るfloor
                # （_HAZARD_TYPE_MIN_FEATURE_COUNT）で判定し、それ以外の
                # geojson/geojsonlは従来通り0件のみを拒否する。
                min_count = _min_feature_count_for_staging_path(rel)
                if feature_count < min_count:
                    raise RuntimeAtomicError(
                        f"dataset固有件数違反（Feature {feature_count}件、最小要求={min_count}件）: {p}"
                    )
                _check_count_consistency(rel, feature_count, previous_feature_counts, p)
                feature_counts[rel] = feature_count
            elif suffix in JSON_LIKE_SUFFIXES:
                _validate_json_file(p, require_geojson_schema=False)
            elif suffix in JSONL_SUFFIXES:
                feature_count = _validate_jsonl_file(
                    p, require_geojson_schema=True,
                    required_property_keys=required_keys, required_property_types=required_types,
                    required_property_ranges=required_ranges,
                )
                min_count = _min_feature_count_for_staging_path(rel)
                if feature_count < min_count:
                    raise RuntimeAtomicError(
                        f"dataset固有件数違反（Feature {feature_count}件、最小要求={min_count}件）: {p}"
                    )
                _check_count_consistency(rel, feature_count, previous_feature_counts, p)
                feature_counts[rel] = feature_count
            elif suffix in SQLITE_SUFFIXES:
                _validate_sqlite_file(p)
        except RuntimeAtomicError as exc:
            invalid.append(str(exc))
            continue
        manifest[rel] = _sha256_of(p)

    if invalid:
        raise RuntimeAtomicError(
            f"staging検証failure {len(invalid)}件（最大5件表示）: " + " | ".join(invalid[:5])
        )
    if file_count == 0:
        raise RuntimeAtomicError(f"staging配下に検証対象fileが1件もない: {staging_path}")

    # CODEX P2B5-CX-003（第9ラウンド）対応: 上のfile単位の件数整合性検証
    # （_check_count_consistency）は新staging側に存在するfileだけを走査する
    # ため、前versionには存在した実質的なdatasetがnew staging側から
    # まるごと消えているケース（rel pathそのものが存在しない）を検出
    # できなかった（独立検証で「前versionのdatasetを丸ごと欠落させた
    # publishも受理」として再現された）。前回`_COUNT_DROP_MIN_BASELINE`
    # 件以上あったrel pathが新staging側に一切存在しない場合も、件数が
    # 0件へ急減した場合と同様にfail-closedで拒否する。
    disappeared = [
        rel for rel, prev_count in previous_feature_counts.items()
        if prev_count >= _COUNT_DROP_MIN_BASELINE and rel not in feature_counts
    ]
    if disappeared:
        raise RuntimeAtomicError(
            f"dataset固有件数整合性違反（前versionに存在したdatasetが新staging側から消失）: "
            f"{sorted(disappeared)[:5]}"
        )

    return manifest, feature_counts


def _check_count_consistency(
    rel: str, feature_count: int, previous_feature_counts: Dict[str, int], p: Path
) -> None:
    prev_count = previous_feature_counts.get(rel)
    if prev_count is None or prev_count < _COUNT_DROP_MIN_BASELINE:
        return
    if feature_count < prev_count * _COUNT_DROP_THRESHOLD:
        raise RuntimeAtomicError(
            f"dataset固有件数整合性違反（前versionから壊滅的に減少）: {p}: "
            f"前回={prev_count}件 → 今回={feature_count}件"
            f"（閾値={_COUNT_DROP_THRESHOLD * 100:.0f}%未満）"
        )


def write_manifest(
    staging_path: Path, manifest: Dict[str, str], mode: int, feature_counts: Optional[Dict[str, int]] = None
) -> None:
    import os

    manifest_path = staging_path / MANIFEST_BASENAME
    payload = json.dumps(
        {
            "files": manifest,
            "file_count": len(manifest),
            # CODEX P2B5-CX-003（第8ラウンド）対応: 次回publish時の件数整合性
            # 検証（_check_count_consistency）が参照する、当版の各fileの
            # Feature件数。
            "feature_counts": feature_counts or {},
        },
        sort_keys=True, indent=2,
    )
    tmp_path = staging_path / f".{MANIFEST_BASENAME}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp_path, mode)
    os.rename(tmp_path, manifest_path)


def verify_manifest_matches_disk(version_path: Path) -> None:
    """publish後の版で、manifestが記録するchecksumと実file内容が一致することを
    再検証する（rollback対象の完全性確認、CODEX P2B5-CX-003第13ラウンド対応の
    件数整合性検証の前提確認等に使用）。"""
    manifest_path = version_path / MANIFEST_BASENAME
    if not manifest_path.is_file():
        raise RuntimeAtomicError(f"manifestが存在しない: {manifest_path}")
    recorded = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
    mismatches = []
    for rel, expected_sha in recorded.items():
        fp = version_path / rel
        if not fp.is_file():
            mismatches.append(f"missing:{rel}")
            continue
        # CODEX P2B5-CX-003（第13ラウンド）対応: 旧実装は`_sha256_of()`が
        # 送出する`OSError`（読取不能ファイル、mode 000等）を捕捉しておらず、
        # 生の例外がそのまま送出されていた。独立検証で「previous fileを
        # mode 000で読取不能化」した場合、この関数を経由しない別経路
        # （feature count導出側）ではfail-openになっていたことが指摘された
        # ため、mismatchとして統一的に扱う。
        try:
            actual_sha = _sha256_of(fp)
        except OSError as exc:
            mismatches.append(f"unreadable:{rel}({exc})")
            continue
        if actual_sha != expected_sha:
            mismatches.append(f"checksum-mismatch:{rel}")

    # CODEX P2B5-CX-003（第3ラウンド）対応: 旧実装はmanifestに記録された
    # pathだけを走査しており、publish後にmanifest未記録のfileがversion tree
    # へ追加されたケースを検出できなかった（独立検証で
    # ROLLBACK_WITH_UNRECORDED_INVALID_EXTRA_SUCCEEDEDとして再現された）。
    # disk上の実file集合とmanifestの記録集合が完全一致すること（recorded
    # 側のmissing/checksum不一致だけでなく、disk側のextraも）を検証する。
    actual_files = set()
    for p in version_path.rglob("*"):
        if not p.is_file():
            continue
        if p.name == MANIFEST_BASENAME:
            continue
        actual_files.add(str(p.relative_to(version_path)))
    extra_files = actual_files - set(recorded.keys())
    if extra_files:
        mismatches.extend(f"unrecorded-extra:{rel}" for rel in sorted(extra_files))

    if mismatches:
        raise RuntimeAtomicError(f"manifest不一致 {len(mismatches)}件: {mismatches[:5]}")
