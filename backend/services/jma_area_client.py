"""
気象庁エリア情報クライアント。

area.json（24h キャッシュ）を取得し、
lat/lon から対象の office_code / class10_code を解決する。

Phase2A スコープ: 関東地方を中心とした簡易バウンディングボックスマッピング。
  - 精密な市区町村境界ではなく都道府県・予報区単位の概略マッピング。
  - 不明な場合は fallback として最近傍 office を返す。
"""
import time
import logging
import urllib.request
import json
from typing import Optional

logger = logging.getLogger(__name__)

_JMA_AREA_URL = "https://www.jma.go.jp/bosai/common/const/area.json"

_AREA_DATA_CACHE: Optional[dict] = None
_AREA_DATA_FETCHED_AT: float = 0.0
_AREA_DATA_TTL = 86400.0  # 24h


# ── 静的バウンディングボックスマッピング（関東＋周辺）──────────────────────────
# (lat_min, lat_max, lon_min, lon_max, office_code, class10_code, area_name, office_name)
# 上から順に評価し、最初にマッチしたエントリを採用する。
# 優先順位: より特定エリアを先に記述。

_AREA_MAP = [
    # ── 東京都 ───────────────────────────────────────────────────────────────
    # 東京地方（23区＋多摩）: 伊豆・小笠原諸島は対象外
    (35.57, 35.83, 139.25, 139.93, "130000", "130010", "東京地方",       "気象庁"),
    # ── 神奈川県 ─────────────────────────────────────────────────────────────
    # 東部（横浜・川崎・横須賀等）
    (35.25, 35.57, 139.42, 139.82, "140000", "140010", "神奈川県東部",   "横浜地方気象台"),
    # 西部（小田原・厚木等）
    (35.10, 35.52, 138.85, 139.50, "140000", "140020", "神奈川県西部",   "横浜地方気象台"),
    # ── 千葉県 ───────────────────────────────────────────────────────────────
    (34.96, 35.88, 139.70, 140.92, "120000", "120010", "千葉県北西部",   "銚子地方気象台"),
    # ── 埼玉県 ───────────────────────────────────────────────────────────────
    (35.76, 36.35, 138.83, 139.90, "110000", "110010", "埼玉県南部",     "熊谷地方気象台"),
    # ── 茨城県 ───────────────────────────────────────────────────────────────
    (35.72, 36.95, 139.68, 140.86, "080000", "080010", "茨城県南部",     "水戸地方気象台"),
    # ── 栃木県 ───────────────────────────────────────────────────────────────
    (36.18, 37.00, 139.32, 140.28, "090000", "090010", "栃木県南部",     "宇都宮地方気象台"),
    # ── 群馬県 ───────────────────────────────────────────────────────────────
    (36.08, 37.00, 138.43, 139.70, "100000", "100010", "群馬県南部",     "前橋地方気象台"),
    # ── 山梨県 ───────────────────────────────────────────────────────────────
    (35.33, 35.96, 138.40, 138.96, "190000", "190010", "山梨県中・西部", "甲府地方気象台"),
    # ── 静岡県 ───────────────────────────────────────────────────────────────
    (34.56, 35.35, 137.46, 138.87, "220000", "220010", "静岡県中部",     "静岡地方気象台"),
]

# 広域 fallback: office のみ（class10 は area.json の最初の子を使う）
_OFFICE_FALLBACK = [
    (35.00, 36.50, 138.40, 141.00, "130000", "東京都", "気象庁"),
]


def _http_get(url: str, timeout: int = 10) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "OnHighGround2/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_area_data() -> dict:
    """area.json を返す（24h キャッシュ）。"""
    global _AREA_DATA_CACHE, _AREA_DATA_FETCHED_AT
    now = time.monotonic()
    if _AREA_DATA_CACHE and now - _AREA_DATA_FETCHED_AT < _AREA_DATA_TTL:
        logger.debug("jma area: cache hit")
        return _AREA_DATA_CACHE

    try:
        raw = _http_get(_JMA_AREA_URL)
        data = json.loads(raw)
        _AREA_DATA_CACHE = data
        _AREA_DATA_FETCHED_AT = now
        offices = len(data.get("offices", {}))
        class10s = len(data.get("class10s", {}))
        logger.info("jma area: cache miss — loaded offices=%d class10s=%d", offices, class10s)
        return data
    except Exception as exc:
        logger.warning("jma area fetch failed: %s", exc)
        return _AREA_DATA_CACHE or {}


def find_office_and_area(lat: float, lon: float) -> dict:
    """
    lat/lon から警報取得に必要なエリア情報を返す。

    Returns:
        {office_code, class10_code, area_name, office_name, match_type}
        match_type: "bbox" | "fallback"
    """
    # Phase2A: バウンディングボックスによる一致探索
    for lat_min, lat_max, lon_min, lon_max, office, class10, area_name, office_name in _AREA_MAP:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return {
                "office_code":  office,
                "class10_code": class10,
                "area_name":    area_name,
                "office_name":  office_name,
                "match_type":   "bbox",
            }

    # Fallback: 広域マッピング
    for lat_min, lat_max, lon_min, lon_max, office, area_name, office_name in _OFFICE_FALLBACK:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            # area.json から最初の class10 を取得
            area_data = fetch_area_data()
            offices_data = area_data.get("offices", {})
            office_info = offices_data.get(office, {})
            children = office_info.get("children", [])
            class10 = children[0] if children else office
            logger.warning(
                "jma area: fallback match lat=%.4f lon=%.4f → office=%s class10=%s",
                lat, lon, office, class10,
            )
            return {
                "office_code":  office,
                "class10_code": class10,
                "area_name":    area_name,
                "office_name":  office_name,
                "match_type":   "fallback",
            }

    # 完全不明: 東京をデフォルトとして返す
    logger.warning("jma area: no match for lat=%.4f lon=%.4f — using Tokyo default", lat, lon)
    return {
        "office_code":  "130000",
        "class10_code": "130010",
        "area_name":    "東京地方",
        "office_name":  "気象庁",
        "match_type":   "default",
    }
