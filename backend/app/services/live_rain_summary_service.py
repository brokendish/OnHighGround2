"""
live_rain_summary_service.py — 雨雲危険度集計サービス (Phase 2-D)

主方式: 雨雲タイル面スキャン（Phase 2-D 移行）
  JMA nowcast タイルをグリッドスキャンし strong/severe ピクセルを「面」で検出する。
  地点サンプリングでは取り逃す帯状・局地的強雨（千葉県沿岸等）に対応する。

旧方式（サンプリング）は fallback / テスト資産として build_rain_section_from_samples() で保持。

判定ロジック:
  tile scan 正常完了                → evaluated=True, reason=tile_scan
  all tiles fetch failed           → evaluated=False, reason=scan_failed
  too_many_tiles                   → evaluated=False, reason=too_many_tiles
  JMA タイル情報取得失敗            → evaluated=False, reason=source_unavailable (offline)

false-safe 防止:
  evaluated=False のとき strong_rain_detected は必ず null（False にしない）

キャッシュ TTL: 120 秒（JMA nowcast への過剰アクセスを防ぐ）
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_JST = timezone(timedelta(hours=9))
_CACHE_TTL = 120.0   # 秒
_MAX_WORKERS = 8     # 並列数制限
_TOTAL_SAMPLING_TIMEOUT = 30.0   # 全サンプリングの待ち時間上限（秒）
_MAX_AREAS = 5       # areas 最大件数（danger 優先）

_rain_summary_cache: Optional[tuple[dict, float]] = None

# ── サンプリング地点（Phase 2-C: 47都道府県代表点 + 29地域ブロック代表点 = 76地点）──

LIVE_RAIN_SAMPLE_POINTS: List[Dict[str, Any]] = [
    # ── 47都道府県代表点（prefecture_capital）────────────────────────────────────
    {"id": "hokkaido",  "label": "北海道付近",   "prefecture": "北海道",   "lat": 43.0642, "lng": 141.3469, "kind": "prefecture_capital"},
    {"id": "aomori",   "label": "青森県付近",   "prefecture": "青森県",   "lat": 40.8244, "lng": 140.7400, "kind": "prefecture_capital"},
    {"id": "iwate",    "label": "岩手県付近",   "prefecture": "岩手県",   "lat": 39.7036, "lng": 141.1527, "kind": "prefecture_capital"},
    {"id": "miyagi",   "label": "宮城県付近",   "prefecture": "宮城県",   "lat": 38.2688, "lng": 140.8721, "kind": "prefecture_capital"},
    {"id": "akita",    "label": "秋田県付近",   "prefecture": "秋田県",   "lat": 39.7186, "lng": 140.1024, "kind": "prefecture_capital"},
    {"id": "yamagata", "label": "山形県付近",   "prefecture": "山形県",   "lat": 38.2404, "lng": 140.3633, "kind": "prefecture_capital"},
    {"id": "fukushima","label": "福島県付近",   "prefecture": "福島県",   "lat": 37.7503, "lng": 140.4676, "kind": "prefecture_capital"},
    {"id": "ibaraki",  "label": "茨城県付近",   "prefecture": "茨城県",   "lat": 36.3418, "lng": 140.4468, "kind": "prefecture_capital"},
    {"id": "tochigi",  "label": "栃木県付近",   "prefecture": "栃木県",   "lat": 36.5657, "lng": 139.8836, "kind": "prefecture_capital"},
    {"id": "gunma",    "label": "群馬県付近",   "prefecture": "群馬県",   "lat": 36.3911, "lng": 139.0608, "kind": "prefecture_capital"},
    {"id": "saitama",  "label": "埼玉県付近",   "prefecture": "埼玉県",   "lat": 35.8569, "lng": 139.6489, "kind": "prefecture_capital"},
    {"id": "chiba",    "label": "千葉県付近",   "prefecture": "千葉県",   "lat": 35.6047, "lng": 140.1233, "kind": "prefecture_capital"},
    {"id": "tokyo",    "label": "東京都付近",   "prefecture": "東京都",   "lat": 35.6895, "lng": 139.6917, "kind": "prefecture_capital"},
    {"id": "kanagawa", "label": "神奈川県付近", "prefecture": "神奈川県", "lat": 35.4478, "lng": 139.6425, "kind": "prefecture_capital"},
    {"id": "niigata",  "label": "新潟県付近",   "prefecture": "新潟県",   "lat": 37.9026, "lng": 139.0232, "kind": "prefecture_capital"},
    {"id": "toyama",   "label": "富山県付近",   "prefecture": "富山県",   "lat": 36.6953, "lng": 137.2113, "kind": "prefecture_capital"},
    {"id": "ishikawa", "label": "石川県付近",   "prefecture": "石川県",   "lat": 36.5947, "lng": 136.6256, "kind": "prefecture_capital"},
    {"id": "fukui",    "label": "福井県付近",   "prefecture": "福井県",   "lat": 36.0652, "lng": 136.2216, "kind": "prefecture_capital"},
    {"id": "yamanashi","label": "山梨県付近",   "prefecture": "山梨県",   "lat": 35.6642, "lng": 138.5683, "kind": "prefecture_capital"},
    {"id": "nagano",   "label": "長野県付近",   "prefecture": "長野県",   "lat": 36.6513, "lng": 138.1810, "kind": "prefecture_capital"},
    {"id": "gifu",     "label": "岐阜県付近",   "prefecture": "岐阜県",   "lat": 35.3912, "lng": 136.7223, "kind": "prefecture_capital"},
    {"id": "shizuoka", "label": "静岡県付近",   "prefecture": "静岡県",   "lat": 34.9769, "lng": 138.3831, "kind": "prefecture_capital"},
    {"id": "aichi",    "label": "愛知県付近",   "prefecture": "愛知県",   "lat": 35.1802, "lng": 136.9066, "kind": "prefecture_capital"},
    {"id": "mie",      "label": "三重県付近",   "prefecture": "三重県",   "lat": 34.7303, "lng": 136.5086, "kind": "prefecture_capital"},
    {"id": "shiga",    "label": "滋賀県付近",   "prefecture": "滋賀県",   "lat": 35.0045, "lng": 135.8686, "kind": "prefecture_capital"},
    {"id": "kyoto",    "label": "京都府付近",   "prefecture": "京都府",   "lat": 35.0211, "lng": 135.7556, "kind": "prefecture_capital"},
    {"id": "osaka",    "label": "大阪府付近",   "prefecture": "大阪府",   "lat": 34.6937, "lng": 135.5023, "kind": "prefecture_capital"},
    {"id": "hyogo",    "label": "兵庫県付近",   "prefecture": "兵庫県",   "lat": 34.6913, "lng": 135.1830, "kind": "prefecture_capital"},
    {"id": "nara",     "label": "奈良県付近",   "prefecture": "奈良県",   "lat": 34.6851, "lng": 135.8048, "kind": "prefecture_capital"},
    {"id": "wakayama", "label": "和歌山県付近", "prefecture": "和歌山県", "lat": 34.2260, "lng": 135.1675, "kind": "prefecture_capital"},
    {"id": "tottori",  "label": "鳥取県付近",   "prefecture": "鳥取県",   "lat": 35.5039, "lng": 134.2383, "kind": "prefecture_capital"},
    {"id": "shimane",  "label": "島根県付近",   "prefecture": "島根県",   "lat": 35.4723, "lng": 133.0505, "kind": "prefecture_capital"},
    {"id": "okayama",  "label": "岡山県付近",   "prefecture": "岡山県",   "lat": 34.6618, "lng": 133.9350, "kind": "prefecture_capital"},
    {"id": "hiroshima","label": "広島県付近",   "prefecture": "広島県",   "lat": 34.3963, "lng": 132.4594, "kind": "prefecture_capital"},
    {"id": "yamaguchi","label": "山口県付近",   "prefecture": "山口県",   "lat": 34.1859, "lng": 131.4714, "kind": "prefecture_capital"},
    {"id": "tokushima","label": "徳島県付近",   "prefecture": "徳島県",   "lat": 34.0658, "lng": 134.5593, "kind": "prefecture_capital"},
    {"id": "kagawa",   "label": "香川県付近",   "prefecture": "香川県",   "lat": 34.3401, "lng": 134.0434, "kind": "prefecture_capital"},
    {"id": "ehime",    "label": "愛媛県付近",   "prefecture": "愛媛県",   "lat": 33.8416, "lng": 132.7661, "kind": "prefecture_capital"},
    {"id": "kochi",    "label": "高知県付近",   "prefecture": "高知県",   "lat": 33.5597, "lng": 133.5311, "kind": "prefecture_capital"},
    {"id": "fukuoka",  "label": "福岡県付近",   "prefecture": "福岡県",   "lat": 33.5902, "lng": 130.4017, "kind": "prefecture_capital"},
    {"id": "saga",     "label": "佐賀県付近",   "prefecture": "佐賀県",   "lat": 33.2494, "lng": 130.2988, "kind": "prefecture_capital"},
    {"id": "nagasaki", "label": "長崎県付近",   "prefecture": "長崎県",   "lat": 32.7448, "lng": 129.8737, "kind": "prefecture_capital"},
    {"id": "kumamoto", "label": "熊本県付近",   "prefecture": "熊本県",   "lat": 32.7898, "lng": 130.7417, "kind": "prefecture_capital"},
    {"id": "oita",     "label": "大分県付近",   "prefecture": "大分県",   "lat": 33.2382, "lng": 131.6126, "kind": "prefecture_capital"},
    {"id": "miyazaki", "label": "宮崎県付近",   "prefecture": "宮崎県",   "lat": 31.9111, "lng": 131.4239, "kind": "prefecture_capital"},
    {"id": "kagoshima","label": "鹿児島県付近", "prefecture": "鹿児島県", "lat": 31.5602, "lng": 130.5581, "kind": "prefecture_capital"},
    {"id": "okinawa",  "label": "沖縄県付近",   "prefecture": "沖縄県",   "lat": 26.2124, "lng": 127.6792, "kind": "prefecture_capital"},
    # ── 地域ブロック代表点（regional）────────────────────────────────────────────
    # 北海道
    {"id": "hokkaido_asahikawa", "label": "北海道 旭川付近",  "prefecture": "北海道",   "lat": 43.7706, "lng": 142.3649, "kind": "regional"},
    {"id": "hokkaido_hakodate",  "label": "北海道 函館付近",  "prefecture": "北海道",   "lat": 41.7687, "lng": 140.7288, "kind": "regional"},
    {"id": "hokkaido_kushiro",   "label": "北海道 釧路付近",  "prefecture": "北海道",   "lat": 42.9849, "lng": 144.3818, "kind": "regional"},
    # 東北
    {"id": "aomori_hachinohe",   "label": "青森県 八戸付近",  "prefecture": "青森県",   "lat": 40.5123, "lng": 141.4884, "kind": "regional"},
    {"id": "iwate_miyako",       "label": "岩手県 宮古付近",  "prefecture": "岩手県",   "lat": 39.6414, "lng": 141.9571, "kind": "regional"},
    {"id": "fukushima_iwaki",    "label": "福島県 いわき付近","prefecture": "福島県",   "lat": 37.0505, "lng": 140.8877, "kind": "regional"},
    # 関東
    {"id": "tokyo_tama",         "label": "東京都 多摩付近",      "prefecture": "東京都",   "lat": 35.6664, "lng": 139.3160, "kind": "regional"},
    {"id": "tokyo_islands",      "label": "東京都 伊豆諸島付近",  "prefecture": "東京都",   "lat": 34.7500, "lng": 139.3550, "kind": "regional"},
    {"id": "kanagawa_odawara",   "label": "神奈川県 小田原付近",  "prefecture": "神奈川県", "lat": 35.2556, "lng": 139.1597, "kind": "regional"},
    {"id": "chiba_tateyama",     "label": "千葉県 館山付近",      "prefecture": "千葉県",   "lat": 34.9965, "lng": 139.8700, "kind": "regional"},
    {"id": "ibaraki_tsukuba",    "label": "茨城県 つくば付近",    "prefecture": "茨城県",   "lat": 36.0835, "lng": 140.0764, "kind": "regional"},
    # 中部
    {"id": "niigata_nagaoka",    "label": "新潟県 長岡付近",  "prefecture": "新潟県",   "lat": 37.4462, "lng": 138.8513, "kind": "regional"},
    {"id": "nagano_matsumoto",   "label": "長野県 松本付近",  "prefecture": "長野県",   "lat": 36.2380, "lng": 137.9720, "kind": "regional"},
    {"id": "shizuoka_hamamatsu", "label": "静岡県 浜松付近",  "prefecture": "静岡県",   "lat": 34.7108, "lng": 137.7261, "kind": "regional"},
    {"id": "aichi_toyohashi",    "label": "愛知県 豊橋付近",  "prefecture": "愛知県",   "lat": 34.7692, "lng": 137.3915, "kind": "regional"},
    {"id": "ishikawa_noto",      "label": "石川県 能登付近",  "prefecture": "石川県",   "lat": 37.3900, "lng": 136.9000, "kind": "regional"},
    # 関西
    {"id": "kyoto_maizuru",      "label": "京都府 舞鶴付近",      "prefecture": "京都府",   "lat": 35.4748, "lng": 135.3859, "kind": "regional"},
    {"id": "hyogo_toyooka",      "label": "兵庫県 豊岡付近",      "prefecture": "兵庫県",   "lat": 35.5445, "lng": 134.8202, "kind": "regional"},
    {"id": "wakayama_shingu",    "label": "和歌山県 新宮付近",    "prefecture": "和歌山県", "lat": 33.7241, "lng": 135.9925, "kind": "regional"},
    {"id": "osaka_sakai",        "label": "大阪府 堺付近",        "prefecture": "大阪府",   "lat": 34.5733, "lng": 135.4828, "kind": "regional"},
    # 中国・四国
    {"id": "hiroshima_fukuyama", "label": "広島県 福山付近",  "prefecture": "広島県",   "lat": 34.4859, "lng": 133.3623, "kind": "regional"},
    {"id": "shimane_hamada",     "label": "島根県 浜田付近",  "prefecture": "島根県",   "lat": 34.8993, "lng": 132.0796, "kind": "regional"},
    {"id": "ehime_uwajima",      "label": "愛媛県 宇和島付近","prefecture": "愛媛県",   "lat": 33.2232, "lng": 132.5600, "kind": "regional"},
    {"id": "kochi_shimanto",     "label": "高知県 四万十付近","prefecture": "高知県",   "lat": 32.9916, "lng": 132.9339, "kind": "regional"},
    # 九州・沖縄
    {"id": "fukuoka_kitakyushu", "label": "福岡県 北九州付近",   "prefecture": "福岡県",   "lat": 33.8834, "lng": 130.8751, "kind": "regional"},
    {"id": "nagasaki_sasebo",    "label": "長崎県 佐世保付近",   "prefecture": "長崎県",   "lat": 33.1799, "lng": 129.7151, "kind": "regional"},
    {"id": "kumamoto_amakusa",   "label": "熊本県 天草付近",     "prefecture": "熊本県",   "lat": 32.4594, "lng": 130.1930, "kind": "regional"},
    {"id": "kagoshima_amami",    "label": "鹿児島県 奄美付近",   "prefecture": "鹿児島県", "lat": 28.3772, "lng": 129.4937, "kind": "regional"},
    {"id": "okinawa_ishigaki",   "label": "沖縄県 石垣付近",     "prefecture": "沖縄県",   "lat": 24.3407, "lng": 124.1556, "kind": "regional"},
]

# 強度 → level 変換（warning 以上のみ areas に追加）
_INTENSITY_TO_LEVEL: Dict[str, Optional[str]] = {
    "none":     None,
    "weak":     None,
    "moderate": "watch",
    "strong":   "warning",
    "severe":   "danger",
    "unknown":  None,
}

_UNKNOWN_RATE_THRESHOLD = 0.5


def _intensity_qualifies_as_strong(intensity: str) -> bool:
    return intensity in ("strong", "severe")


# ── サンプリング（同期・内部用）──────────────────────────────────────────────

def _sample_all_points_sync(tile_url_template: str) -> List[Dict[str, Any]]:
    """全サンプリング地点の降水強度を並列取得する（同期版、asyncio.to_thread から呼ぶ）。"""
    from services.jma_rain_tile_service import get_precip_intensity_at

    results: List[Dict[str, Any]] = []

    def _fetch_one(pt: Dict[str, Any]) -> Dict[str, Any]:
        res = get_precip_intensity_at(pt["lat"], pt["lng"], tile_url_template)
        return {**pt, **res}

    def _unknown_entry(pt: Dict[str, Any], source: str = "error") -> Dict[str, Any]:
        return {**pt, "intensity": "unknown", "rain_class": -1, "source": source}

    completed: set = set()

    executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS)
    try:
        future_to_pt = {executor.submit(_fetch_one, pt): pt for pt in LIVE_RAIN_SAMPLE_POINTS}
        try:
            for future in as_completed(future_to_pt, timeout=_TOTAL_SAMPLING_TIMEOUT):
                pt = future_to_pt[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    logger.warning("rain sample failed %s: %s", pt["id"], exc)
                    results.append(_unknown_entry(pt))
                completed.add(future)
        except concurrent.futures.TimeoutError:
            logger.warning("rain sampling timed out after %.1fs", _TOTAL_SAMPLING_TIMEOUT)

        # タイムアウトで完了しなかった地点を unknown として追加
        for future, pt in future_to_pt.items():
            if future not in completed:
                results.append(_unknown_entry(pt, source="timeout"))
                future.cancel()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    return results


# ── セクション構築（純粋関数・テスト容易）────────────────────────────────────

def build_rain_section_from_samples(
    samples: List[Dict[str, Any]],
    observed_at: str,
) -> Dict[str, Any]:
    """
    サンプル結果リストから rain セクション辞書を構築する。

    samples の各要素は LIVE_RAIN_SAMPLE_POINTS の各地点属性 +
    get_precip_intensity_at の返り値 (intensity, rain_class, source) を持つ。
    """
    sample_count = len(samples)
    if sample_count == 0:
        return _offline_rain_section()

    unknown_count = sum(1 for s in samples if s.get("intensity") == "unknown")

    obs_tag = observed_at.replace(":", "").replace("-", "").replace("+", "")[:13]

    # warning/danger 地点を抽出して areas 候補を構築
    all_qualifying: List[Dict[str, Any]] = []
    for s in samples:
        intensity = s.get("intensity", "none")
        if not _intensity_qualifies_as_strong(intensity):
            continue
        level = _INTENSITY_TO_LEVEL.get(intensity)
        if level not in ("warning", "danger"):
            continue
        all_qualifying.append({
            "id":          f"rain-{s['id']}-{obs_tag}",
            "label":       f"{s['prefecture']}付近",
            "prefecture":  s["prefecture"],
            "area_name":   s["label"],
            "level":       level,
            "type":        "rain",
            "source":      "jma_nowcast",
            "lat":         s["lat"],
            "lng":         s["lng"],
            "observed_at": observed_at,
            "description": "強雨域を検出",
        })

    strong_rain_detected = len(all_qualifying) > 0

    # unknown 率が高い かつ 強雨未検出 → 評価不能（false-safe 防止）
    if not strong_rain_detected and unknown_count / sample_count >= _UNKNOWN_RATE_THRESHOLD:
        return {
            "status":    "unknown",
            "evaluated": False,
            "reason":    "too_many_unknown_samples",
            "summary": {
                "strong_rain_detected": None,
                "warning_area_count":   None,
                "danger_area_count":    None,
                "sample_count":         sample_count,
                "unknown_count":        unknown_count,
            },
            "areas": [],
        }

    # 全検出件数を集計（areas 上限適用前）
    warning_count = sum(1 for a in all_qualifying if a["level"] == "warning")
    danger_count  = sum(1 for a in all_qualifying if a["level"] == "danger")

    # danger 優先で最大 _MAX_AREAS 件に絞る
    all_qualifying.sort(key=lambda a: 0 if a["level"] == "danger" else 1)
    areas = all_qualifying[:_MAX_AREAS]

    return {
        "status":    "ok",
        "evaluated": True,
        "reason":    "sampled_nowcast",
        "summary": {
            "strong_rain_detected": strong_rain_detected,
            "warning_area_count":   warning_count,
            "danger_area_count":    danger_count,
            "sample_count":         sample_count,
            "unknown_count":        unknown_count,
        },
        "areas": areas,
    }


# ── タイル面スキャン（Phase 2-D 主方式）──────────────────────────────────────

def build_rain_section_from_scan(
    scan_result: Dict[str, Any],
    observed_at: str,
) -> Dict[str, Any]:
    """
    scan_rain_tiles() の結果から rain セクション辞書を構築する（Phase 2-D 主方式）。

    false-safe 防止:
      - 全タイル fetch 失敗 → evaluated=False, strong_rain_detected=null
      - too_many_tiles      → evaluated=False, strong_rain_detected=null
      - scan 正常完了       → evaluated=True,  strong_rain_detected=bool
    """
    from app.services.live_rain_tile_scan_service import PIXEL_STRIDE as _DEFAULT_STRIDE

    scan_status     = scan_result.get("status", "scan_failed")
    scan_tile_count = scan_result.get("scan_tile_count")
    pixel_stride    = scan_result.get("scan_pixel_stride", _DEFAULT_STRIDE)

    def _unevaluated(reason: str) -> Dict[str, Any]:
        return {
            "status":    "unknown",
            "evaluated": False,
            "reason":    reason,
            "summary": {
                "strong_rain_detected": None,
                "warning_area_count":   None,
                "danger_area_count":    None,
                "sample_count":         None,
                "unknown_count":        None,
                "scan_tile_count":      scan_tile_count,
                "scan_pixel_stride":    pixel_stride,
            },
            "areas": [],
        }

    if scan_status == "too_many_tiles":
        return _unevaluated("too_many_tiles")

    if scan_status != "ok":
        return _unevaluated("scan_failed")

    # 全タイル fetch 失敗チェック（false-safe 防止）
    tile_results = scan_result.get("tile_results", [])
    if tile_results:
        succeeded = [r for r in tile_results if not r.get("fetch_failed")]
        if not succeeded:
            return _unevaluated("scan_failed")

    qualifying_areas = scan_result.get("areas", [])
    warning_count    = scan_result.get("warning_area_count", 0) or 0
    danger_count     = scan_result.get("danger_area_count",  0) or 0
    unknown_count    = scan_result.get("unknown_count",      0) or 0
    strong_rain_detected = len(qualifying_areas) > 0

    # danger 優先ソート → 最大 _MAX_AREAS 件
    obs_tag = observed_at.replace(":", "").replace("-", "").replace("+", "")[:13]
    qualifying_areas.sort(key=lambda a: 0 if a.get("level") == "danger" else 1)
    # Phase 3-C: 観察ログ（候補件数 / 採用件数 / stride）
    logger.info(
        "live rain observation: candidates=%d areas=%d stride=%s max_areas=%d",
        len(qualifying_areas),
        min(len(qualifying_areas), _MAX_AREAS),
        pixel_stride,
        _MAX_AREAS,
    )

    areas = []
    for a in qualifying_areas[:_MAX_AREAS]:
        logger.debug(
            "rain_scan area: name=%s risk=%s tile=(%s,%s)",
            a.get("label"), a.get("level"), a.get("tx"), a.get("ty"),
        )
        areas.append({
            "id":          f"rain-scan-{a['tx']}-{a['ty']}-{obs_tag}",
            "label":       a.get("label", "日本周辺"),
            "prefecture":  a.get("prefecture", "日本周辺"),
            "area_name":   a.get("label", "日本周辺"),
            "level":       a["level"],
            "type":        "rain",
            "source":      "jma_nowcast_scan",
            "lat":         a["lat"],
            "lng":         a["lng"],
            "observed_at": observed_at,
            "description": "雨雲面スキャンで強雨域を検出",
        })

    return {
        "status":    "ok",
        "evaluated": True,
        "reason":    "tile_scan",
        "summary": {
            "strong_rain_detected": strong_rain_detected,
            "warning_area_count":   warning_count,
            "danger_area_count":    danger_count,
            "sample_count":         None,
            "unknown_count":        unknown_count,
            "scan_tile_count":      scan_tile_count,
            "scan_pixel_stride":    pixel_stride,
        },
        "areas": areas,
    }


# ── パブリック API（async）────────────────────────────────────────────────────

async def build_live_rain_summary() -> Dict[str, Any]:
    """
    雨雲危険度サマリーを返す（120 秒キャッシュ）。

    Phase 2-D: 雨雲タイル面スキャンを主方式とする。
    失敗時は status=offline, evaluated=False (strong_rain_detected=null)。
    """
    global _rain_summary_cache

    now_mono = time.monotonic()
    if _rain_summary_cache is not None:
        cached, fetched_at = _rain_summary_cache
        if now_mono - fetched_at < _CACHE_TTL:
            return cached

    try:
        from services.jma_rain_tile_service import get_rain_tile_latest
        from app.services.live_rain_tile_scan_service import scan_rain_tiles

        tile_info = await asyncio.to_thread(get_rain_tile_latest)
        if tile_info is None:
            logger.warning("live_rain_summary: タイル情報取得失敗")
            return _offline_rain_section()

        tile_url    = tile_info["tile_url_template"]
        observed_at = datetime.now(_JST).isoformat()

        scan_result = await asyncio.to_thread(scan_rain_tiles, tile_url, LIVE_RAIN_SAMPLE_POINTS)
        result = build_rain_section_from_scan(scan_result, observed_at)
        _rain_summary_cache = (result, now_mono)

        summary = result.get("summary", {})
        logger.info(
            "live_rain_summary: evaluated=%s detected=%s tiles=%s stride=%s unknown=%s",
            result.get("evaluated"),
            summary.get("strong_rain_detected"),
            summary.get("scan_tile_count"),
            summary.get("scan_pixel_stride"),
            summary.get("unknown_count"),
        )
        return result

    except Exception as exc:
        logger.warning("live_rain_summary: 集計失敗: %s", exc)
        return _offline_rain_section()


def _offline_rain_section() -> Dict[str, Any]:
    return {
        "status":    "offline",
        "evaluated": False,
        "reason":    "source_unavailable",
        "summary": {
            "strong_rain_detected": None,
            "warning_area_count":   None,
            "danger_area_count":    None,
            "sample_count":         None,
            "unknown_count":        None,
            "scan_tile_count":      None,
            "scan_pixel_stride":    None,
        },
        "areas": [],
    }
