"""
live_train_service.py — 鉄道運行影響レイヤー サービス

ODPT (Open Data for Public Transportation) から鉄道運行情報を取得し、
正規化して返す。

環境変数:
  ODPT_API_KEY      - ODPTアクセストークン（未設定時はunavailable扱い）
  ODPT_API_BASE_URL - ODPT APIベースURL（デフォルト: https://api.odpt.org/api/v4）

キャッシュ:
  TTL 120秒。取得失敗時はstale cacheを返し、stale=Trueを付与する。

ログ:
  live train summary: items=X unavailable / stale / ok
"""
from __future__ import annotations

import logging
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError
import json

from app.models.live_train import (
    SEVERITY,
    STATUS_DELAY,
    STATUS_LABEL,
    STATUS_NORMAL,
    STATUS_PARTIAL_SUSPENSION,
    STATUS_SUSPENDED,
    STATUS_UNAVAILABLE,
    STATUS_UNKNOWN,
    TrainInfoItem,
)
from app.services.odpt_allowlist import get_operator_license_info, is_operator_allowed

logger = logging.getLogger(__name__)

_JST = timezone(timedelta(hours=9))
_CACHE_TTL = 120.0  # 秒

_cache: Optional[Dict[str, Any]] = None
_cache_at: float = 0.0


# ── ODPT 設定 ──────────────────────────────────────────────────────────────────

def _odpt_api_key() -> Optional[str]:
    return os.getenv("ODPT_API_KEY") or None


def _odpt_base_url() -> str:
    return os.getenv("ODPT_API_BASE_URL", "https://api.odpt.org/api/v4")


# ── オペレーター→都道府県 マッピング ─────────────────────────────────────────

_OPERATOR_PREFECTURES: Dict[str, List[str]] = {
    # JR系
    "JR-East": [
        "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
        "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
        "新潟県", "山梨県", "長野県", "静岡県",
    ],
    "JR-Central": ["愛知県", "静岡県", "岐阜県", "三重県", "長野県"],
    "JR-West": [
        "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
        "岡山県", "広島県", "鳥取県", "島根県", "山口県",
    ],
    "JR-Hokkaido": ["北海道"],
    "JR-Shikoku":  ["香川県", "愛媛県", "高知県", "徳島県"],
    "JR-Kyushu":   ["福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県"],
    # 東京・首都圏
    "TokyoMetro":        ["東京都"],
    "Toei":              ["東京都"],
    "Tokyu":             ["東京都", "神奈川県"],
    "Keio":              ["東京都", "神奈川県"],
    "Odakyu":            ["東京都", "神奈川県"],
    "Seibu":             ["東京都", "埼玉県"],
    "Tobu":              ["東京都", "埼玉県", "栃木県", "群馬県"],
    "Sotetsu":           ["神奈川県"],
    "Keikyu":            ["東京都", "神奈川県"],
    "Keisei":            ["東京都", "千葉県"],
    "Hokuso":            ["千葉県"],
    "Yurikamome":        ["東京都"],
    "TWR":               ["東京都"],
    "TamaMonorail":      ["東京都"],
    "MIR":               ["埼玉県"],
    "Minatomirai":       ["神奈川県"],
    "YokohamaMunicipal": ["神奈川県"],
    "ShibaYama":         ["千葉県"],
    # 近畿圏
    "Keihan":      ["大阪府", "京都府"],
    "Hankyu":      ["大阪府", "京都府", "兵庫県"],
    "Hanshin":     ["大阪府", "兵庫県"],
    "Kintetsu":    ["大阪府", "奈良県", "京都府", "三重県", "愛知県"],
    "Nankai":      ["大阪府", "和歌山県"],
    "Osaka":       ["大阪府"],
    "OsakaMonorail": ["大阪府"],
    "Semboku":     ["大阪府"],
    "Kobe":        ["兵庫県"],
    "KobeNewTransit": ["兵庫県"],
    "Sanyo":       ["兵庫県", "岡山県"],
    "Aichi":       ["愛知県"],
    "Nagoya":      ["愛知県"],
    # 九州・中国・四国
    "Nishitetsu":  ["福岡県"],
    "Fukuoka":     ["福岡県"],
    "Sapporo":     ["北海道"],
    "Sendai":      ["宮城県"],
    # その他
    "Enoden":      ["神奈川県"],
    "Hakone":      ["神奈川県"],
}

# 都道府県→オペレーターの逆引きを事前構築
_PREF_OPERATORS: Dict[str, List[str]] = {}
for _op, _prefs in _OPERATOR_PREFECTURES.items():
    for _pref in _prefs:
        _PREF_OPERATORS.setdefault(_pref, []).append(_op)


# ── 鉄道・事業者名 ルックアップ ────────────────────────────────────────────────

_OPERATOR_NAMES: Dict[str, str] = {
    "JR-East":        "JR東日本",
    "JR-Central":     "JR東海",
    "JR-West":        "JR西日本",
    "JR-Hokkaido":    "JR北海道",
    "JR-Shikoku":     "JR四国",
    "JR-Kyushu":      "JR九州",
    "TokyoMetro":     "東京メトロ",
    "Toei":           "都営",
    "Tokyu":          "東急電鉄",
    "Keio":           "京王電鉄",
    "Odakyu":         "小田急電鉄",
    "Seibu":          "西武鉄道",
    "Tobu":           "東武鉄道",
    "Sotetsu":        "相鉄",
    "Keikyu":         "京急電鉄",
    "Keisei":         "京成電鉄",
    "Hokuso":         "北総鉄道",
    "Yurikamome":     "ゆりかもめ",
    "TWR":            "東京臨海高速鉄道",
    "TamaMonorail":   "多摩都市モノレール",
    "MIR":            "埼玉高速鉄道",
    "Minatomirai":    "横浜高速鉄道",
    "YokohamaMunicipal": "横浜市交通局",
    "ShibaYama":      "芝山鉄道",
    "Keihan":         "京阪電気鉄道",
    "Hankyu":         "阪急電鉄",
    "Hanshin":        "阪神電気鉄道",
    "Kintetsu":       "近畿日本鉄道",
    "Nankai":         "南海電気鉄道",
    "Osaka":          "大阪メトロ",
    "OsakaMonorail":  "大阪モノレール",
    "Semboku":        "泉北高速鉄道",
    "Kobe":           "神戸市交通局",
    "KobeNewTransit": "神戸新交通",
    "Sanyo":          "山陽電気鉄道",
    "Aichi":          "名古屋市交通局",
    "Nagoya":         "名古屋鉄道",
    "Nishitetsu":     "西日本鉄道",
    "Fukuoka":        "福岡市交通局",
    "Sapporo":        "札幌市交通局",
    "Sendai":         "仙台市交通局",
    "Enoden":         "江ノ島電鉄",
    "Hakone":         "箱根登山鉄道",
}

_RAILWAY_NAMES: Dict[str, str] = {
    # 東京メトロ
    "TokyoMetro.Ginza":      "銀座線",
    "TokyoMetro.Marunouchi": "丸ノ内線",
    "TokyoMetro.Hibiya":     "日比谷線",
    "TokyoMetro.Tozai":      "東西線",
    "TokyoMetro.Chiyoda":    "千代田線",
    "TokyoMetro.Yurakucho":  "有楽町線",
    "TokyoMetro.Hanzomon":   "半蔵門線",
    "TokyoMetro.Namboku":    "南北線",
    "TokyoMetro.Fukutoshin": "副都心線",
    # 都営
    "Toei.Asakusa":   "浅草線",
    "Toei.Mita":      "三田線",
    "Toei.Shinjuku":  "新宿線",
    "Toei.Oedo":      "大江戸線",
    # JR東日本主要路線
    "JR-East.Yamanote":       "山手線",
    "JR-East.ChuoRapid":      "中央線快速",
    "JR-East.ChuoSobuLocal":  "中央・総武線各停",
    "JR-East.Keihin-Tohoku":  "京浜東北線",
    "JR-East.Joban":          "常磐線",
    "JR-East.Takasaki":       "高崎線",
    "JR-East.Utsunomiya":     "宇都宮線",
    "JR-East.SaikyoKawagoe":  "埼京線",
    "JR-East.Yokohama":       "横浜線",
    "JR-East.Sobu":           "総武線",
    "JR-East.Tokaido":        "東海道線",
    "JR-East.Shonan-Shinjuku": "湘南新宿ライン",
    "JR-East.Ueno-Tokyo":     "上野東京ライン",
    "JR-East.Tohoku":         "東北本線",
    # 小田急
    "Odakyu.Odawara":  "小田原線",
    "Odakyu.Tama":     "多摩線",
    "Odakyu.Enoshima": "江ノ島線",
    # 東急
    "Tokyu.DenEnToshi":  "田園都市線",
    "Tokyu.Toyoko":      "東横線",
    "Tokyu.Meguro":      "目黒線",
    "Tokyu.Oimachi":     "大井町線",
    "Tokyu.Ikegami":     "池上線",
    "Tokyu.Setagaya":    "世田谷線",
    # 京急
    "Keikyu.Main":        "京急本線",
    "Keikyu.Airport":     "空港線",
    "Keikyu.Daishi":      "大師線",
    "Keikyu.Zushi":       "逗子線",
    # 西武
    "Seibu.Ikebukuro": "池袋線",
    "Seibu.Shinjuku":  "新宿線",
    # 東武
    "Tobu.Isesaki":     "伊勢崎線",
    "Tobu.Nikko":       "日光線",
    "Tobu.Tojo":        "東上線",
    # 実際のODPT railway_id表記（Isesaki/Tojoではなく以下が使われる）
    "Tobu.TobuSkytree": "伊勢崎線",
    "Tobu.TobuTojo":    "東上線",
    # 近鉄
    "Kintetsu.Osaka":      "大阪線",
    "Kintetsu.Nara":       "奈良線",
    "Kintetsu.Kyoto":      "京都線",
    "Kintetsu.Nagoya":     "名古屋線",
    # 阪急
    "Hankyu.Kobe":   "神戸線",
    "Hankyu.Takarazuka": "宝塚線",
    "Hankyu.Kyoto":  "京都線",
    # 阪神
    "Hanshin.Main":    "本線",
    "Hanshin.Namba":   "なんば線",
}


# ── チャレンジ/期間限定データ除外 ───────────────────────────────────────────────
# ODPTチャレンジ限定・期間限定・実験的公開データには追随しない。
# odpt:operator / odpt:railway / @id のみを対象に判定する（dc:date 等の日付フィールドは
# 対象外にし、日付文字列に含まれる年号による誤爆を避ける）。
# ODPT_EXCLUDE_KEYWORDS 環境変数（カンマ区切り）で上書き可能。

_DEFAULT_EXCLUDE_KEYWORDS: Tuple[str, ...] = (
    "challenge", "contest", "2026", "limited", "temporary", "experimental",
)


def _excluded_keywords() -> Tuple[str, ...]:
    raw = os.getenv("ODPT_EXCLUDE_KEYWORDS")
    if raw is None:
        return _DEFAULT_EXCLUDE_KEYWORDS
    keywords = tuple(k.strip().lower() for k in raw.split(",") if k.strip())
    return keywords or _DEFAULT_EXCLUDE_KEYWORDS


def _is_excluded_source(raw: Dict[str, Any]) -> bool:
    """チャレンジ2026限定・期間限定・実験的データを識別子から判定する。"""
    keywords = _excluded_keywords()
    if not keywords:
        return False
    id_fields = (
        str(raw.get("odpt:operator") or ""),
        str(raw.get("odpt:railway") or ""),
        str(raw.get("@id") or ""),
    )
    haystack = " ".join(id_fields).lower()
    return any(kw in haystack for kw in keywords)


# ── GeoJSON 一致診断 (matched_geojson) ────────────────────────────────────────
# frontend の live-train-osm-layer.js / live-stream-railway-layer.js が実際に
# 実路線ジオメトリ描画に使う静的ファイルを「利用」して、路線ごとの一致有無を診断する。
# フロント資産は改変しない（ファイルを読み取るだけ）。

_GEOJSON_PATH = (
    Path(__file__).resolve().parents[3] / "frontend" / "layers" / "railways" / "kanto_railways.geojson"
)
_geojson_names_cache: Optional[Set[str]] = None
_MIN_BARE_NAME_LEN = 3  # これ未満の短い路線名は完全一致のみ許可（誤一致対策）


def _load_geojson_route_names() -> Set[str]:
    """静的GeoJSONから路線名の集合を読み込む（初回のみ・以降はキャッシュ）。"""
    global _geojson_names_cache
    if _geojson_names_cache is not None:
        return _geojson_names_cache
    names: Set[str] = set()
    try:
        with open(_GEOJSON_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for feat in data.get("features", []):
            props = feat.get("properties") or {}
            for key in ("name", "name:ja"):
                name = props.get(key)
                if name:
                    names.add(str(name).strip())
    except Exception as exc:
        logger.warning("live train: GeoJSON路線名読み込み失敗: %s", exc)
        names = set()
    _geojson_names_cache = names
    return names


def _matches_geojson(railway_name: str) -> bool:
    """railway_name (bare名) が静的GeoJSONの実路線名に一致するか判定する。

    OSM名は事業者名接頭辞付き表記が多い（例: 東京メトロ有楽町線）ため、
    OSM名がbare名を含むかで判定する。ただし短すぎるbare名（例: 本線）は
    誤一致しやすいため完全一致のみ許可する。
    """
    bare = (railway_name or "").strip()
    if not bare:
        return False
    names = _load_geojson_route_names()
    if len(bare) < _MIN_BARE_NAME_LEN:
        return bare in names
    return any(osm_name == bare or bare in osm_name for osm_name in names)


# ── ステータス正規化 ───────────────────────────────────────────────────────────

def _extract_ja_text(value: Any) -> str:
    """ODPT MultiLanguageString または文字列から日本語テキストを取得する。"""
    if value is None:
        return ""
    if isinstance(value, dict):
        return value.get("ja") or value.get("en") or ""
    return str(value)


def normalize_status(status_obj: Any, text_obj: Any = None) -> str:
    """
    ODPT trainInformationStatus + trainInformationText から
    内部ステータスに正規化する。
    """
    status_text = _extract_ja_text(status_obj)
    desc_text   = _extract_ja_text(text_obj)
    combined    = status_text + " " + desc_text

    # 平常
    if not status_text or "平常" in status_text:
        return STATUS_NORMAL

    # 一部運休（suspended より先に判定：Partial Service Suspended を正しく分類するため）
    if "一部運休" in combined or "partial" in combined.lower():
        return STATUS_PARTIAL_SUSPENSION

    # 運転見合わせ
    if "見合わせ" in combined or "suspended" in combined.lower():
        return STATUS_SUSPENDED

    # 遅延
    if "遅延" in combined or "delay" in combined.lower():
        return STATUS_DELAY

    # テキストがある = 状態不明
    if status_text:
        return STATUS_UNKNOWN

    return STATUS_NORMAL


# ── ODPT レスポンス正規化 ─────────────────────────────────────────────────────

def _operator_key(operator_id: str) -> str:
    """'odpt.Operator:JR-East' → 'JR-East'"""
    return operator_id.split(":")[-1] if ":" in operator_id else operator_id


def _railway_key(railway_id: str) -> str:
    """'odpt.Railway:JR-East.Yamanote' → 'JR-East.Yamanote'"""
    return railway_id.split(":")[-1] if ":" in railway_id else railway_id


def _railway_name_from_id(railway_id: str) -> str:
    """railway_id からローカルテーブル引き → なければ ID 末尾を返す。"""
    key = _railway_key(railway_id)
    if key in _RAILWAY_NAMES:
        return _RAILWAY_NAMES[key]
    # fallback: camelCase 末尾部分をそのまま返す
    parts = key.split(".")
    return parts[-1] if parts else key


def _operator_name_from_id(operator_id: str) -> str:
    key = _operator_key(operator_id)
    return _OPERATOR_NAMES.get(key, key)


def normalize_odpt_item(raw: Dict[str, Any]) -> Optional[TrainInfoItem]:
    """ODPT TrainInformation 1件を TrainInfoItem に正規化する。"""
    railway_id  = raw.get("odpt:railway") or ""
    operator_id = raw.get("odpt:operator") or ""
    if not railway_id:
        return None

    status_obj = raw.get("odpt:trainInformationStatus")
    text_obj   = raw.get("odpt:trainInformationText")
    status     = normalize_status(status_obj, text_obj)

    # 平常は不要（障害なしとして扱う）
    if status == STATUS_NORMAL:
        return None

    updated_at = raw.get("dc:date") or raw.get("dct:valid") or ""
    description = _extract_ja_text(text_obj) or STATUS_LABEL.get(status, "")

    railway_name = _railway_name_from_id(railway_id)
    item = TrainInfoItem(
        railway_id=railway_id,
        operator_id=operator_id,
        operator_name=_operator_name_from_id(operator_id),
        railway_name=railway_name,
        status=status,
        status_label=STATUS_LABEL[status],
        severity=SEVERITY[status],
        description=description,
        updated_at=updated_at,
        source="ODPT",
        matched_geojson=_matches_geojson(railway_name),
    )
    point = _operator_representative_latlng(operator_id)
    if point is not None:
        item["lat"], item["lng"] = point

    # Phase 2-D Round 2 (P2D-ODPT-TERMS): allowlist登録operatorのみここへ到達する
    # （呼び出し元の_fetch_all_disruptionsがunknown operatorを事前に除外するため）。
    # UI表示用にlicense/terms情報を付与する（第6.5節「applicable license/terms link」）。
    license_info = get_operator_license_info(_operator_key(operator_id))
    if license_info is not None:
        item["license"] = license_info["license"]
        item["license_terms_url"] = license_info["terms_url"]
        item["license_confirmed_at"] = license_info["confirmed_date"]
    return item


# ── ODPT API 取得 ─────────────────────────────────────────────────────────────

def _fetch_odpt_train_information(api_key: str, base_url: str) -> List[Dict[str, Any]]:
    """ODPT TrainInformation を同期的に取得する（asyncio.to_thread 経由で呼ぶ）。"""
    url = f"{base_url}/odpt:TrainInformation?acl:consumerKey={api_key}"
    req = Request(url, headers={"User-Agent": "OnHighGround2/live-train-layer"})
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


# ── 都道府県フィルター ─────────────────────────────────────────────────────────

def _operator_prefectures(operator_id: str) -> List[str]:
    key = _operator_key(operator_id)
    return _OPERATOR_PREFECTURES.get(key, [])


def _operator_representative_latlng(operator_id: str) -> Optional[Tuple[float, float]]:
    """事業者の対応都道府県代表点の平均を、MVP表示用の代表座標として返す。"""
    prefs = _operator_prefectures(operator_id)
    if not prefs:
        return None
    try:
        from app.services.jma_weather_adapter import _PREF_CENTROIDS  # type: ignore[import]
        pref_points = {
            info[0]: (float(info[1]), float(info[2]))
            for info in _PREF_CENTROIDS.values()
        }
        points = [pref_points[p] for p in prefs if p in pref_points]
        if not points:
            return None
        lat = sum(point[0] for point in points) / len(points)
        lng = sum(point[1] for point in points) / len(points)
        return lat, lng
    except Exception:
        return None


def _item_matches_prefecture(item: TrainInfoItem, prefecture: str) -> bool:
    prefs = _operator_prefectures(item["operator_id"])
    return prefecture in prefs


def _nearest_prefecture_from_latlon(lat: float, lon: float) -> Optional[str]:
    """
    lat/lon から最寄りの都道府県名を返す。
    jma_weather_adapter._PREF_CENTROIDS を使用する。
    """
    try:
        from app.services.jma_weather_adapter import _PREF_CENTROIDS  # type: ignore[import]
        best_pref: Optional[str] = None
        best_dist = float("inf")
        for _code, info in _PREF_CENTROIDS.items():
            pref_name, c_lat, c_lon = info
            dist = math.sqrt((lat - c_lat) ** 2 + (lon - c_lon) ** 2)
            if dist < best_dist:
                best_dist = dist
                best_pref = pref_name
        return best_pref
    except Exception:
        return None


# ── キャッシュ ────────────────────────────────────────────────────────────────

def _monotonic() -> float:
    return time.monotonic()


def _now_jst() -> str:
    return datetime.now(_JST).isoformat()


async def _fetch_all_disruptions() -> List[TrainInfoItem]:
    """ODPT から全路線の運行障害情報を取得・正規化して返す。"""
    import asyncio

    api_key  = _odpt_api_key()
    base_url = _odpt_base_url()
    if not api_key:
        raise ValueError("ODPT_API_KEY not set")

    raw_list: List[Dict[str, Any]] = await asyncio.to_thread(
        _fetch_odpt_train_information, api_key, base_url
    )

    items: List[TrainInfoItem] = []
    excluded_count = 0
    denied_unknown_operator_count = 0
    for raw in raw_list:
        if _is_excluded_source(raw):
            excluded_count += 1
            continue
        # Phase 2-D Round 2 (P2D-ODPT-TERMS): source-controlled allowlist（第7節）。
        # allowlist未登録operatorはcache/UI到達前にここで拒否する（fail-closed、
        # 「従来どおり表示」へのfallbackはしない）。tokenやresponse全量はlogへ出さない。
        operator_id = str(raw.get("odpt:operator") or "")
        if not is_operator_allowed(_operator_key(operator_id)):
            denied_unknown_operator_count += 1
            continue
        item = normalize_odpt_item(raw)
        if item is not None:
            items.append(item)

    items.sort(key=lambda x: (-x["severity"], x["updated_at"]), reverse=False)
    items.sort(key=lambda x: x["severity"], reverse=True)

    if excluded_count:
        logger.info("live train summary: excluded=%d (challenge/experimental等)", excluded_count)
    if denied_unknown_operator_count:
        logger.info(
            "live train summary: denied_unknown_operator=%d (ODPT allowlist未登録、非表示・非cache)",
            denied_unknown_operator_count,
        )
    logger.info("live train summary: items=%d", len(items))
    return items


# ── 公開 API ──────────────────────────────────────────────────────────────────

async def build_train_summary(
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    prefecture: Optional[str] = None,
) -> Dict[str, Any]:
    """
    鉄道運行影響サマリーを返す。

    Args:
        lat: 緯度（現在地周辺モード）
        lng: 経度（現在地周辺モード）
        prefecture: 都道府県名（prefecture モード、優先）

    Returns:
        {
            "status": "ok" | "unavailable" | "stale",
            "stale": bool,
            "scope": {...},
            "updated_at": str,
            "items": [TrainInfoItem, ...]
        }
    """
    global _cache, _cache_at

    # APIキー未設定
    if not _odpt_api_key():
        result = {
            "status":  "unavailable",
            "stale":   False,
            "message": "鉄道運行情報を取得できません",
            "scope":   {},
            "updated_at": _now_jst(),
            "items":   [],
        }
        return _apply_scope(result, lat, lng, prefecture)

    now = _monotonic()

    # キャッシュヒット
    if _cache is not None and (now - _cache_at) < _CACHE_TTL:
        cached = dict(_cache)
        return _apply_scope(cached, lat, lng, prefecture)

    # 新規取得
    try:
        items = await _fetch_all_disruptions()
        result: Dict[str, Any] = {
            "status":     "ok",
            "stale":      False,
            "scope":      {},
            "updated_at": _now_jst(),
            "items":      items,
        }
        _cache    = result
        _cache_at = now
        logger.info("live train summary: ok items=%d", len(items))
        return _apply_scope(dict(result), lat, lng, prefecture)

    except URLError as exc:
        logger.warning("live train: ODPT取得失敗 (URLError): %s", exc)
    except Exception as exc:
        logger.warning("live train: ODPT取得失敗: %s", exc)

    # stale cache
    if _cache is not None:
        stale = dict(_cache)
        stale["stale"] = True
        logger.info("live train summary: stale items=%d", len(stale.get("items", [])))
        return _apply_scope(stale, lat, lng, prefecture)

    # キャッシュなし → unavailable
    logger.warning("live train summary: unavailable (no cache)")
    result = {
        "status":     "unavailable",
        "stale":      False,
        "message":    "鉄道運行情報を取得できません",
        "scope":      {},
        "updated_at": _now_jst(),
        "items":      [],
    }
    return _apply_scope(result, lat, lng, prefecture)


def _apply_scope(
    result: Dict[str, Any],
    lat: Optional[float],
    lng: Optional[float],
    prefecture: Optional[str],
) -> Dict[str, Any]:
    """結果に scope フィルターを適用する。prefecture が優先。"""
    all_items: List[TrainInfoItem] = result.get("items", [])

    if prefecture:
        filtered = [it for it in all_items if _item_matches_prefecture(it, prefecture)]
        result["scope"] = {"mode": "prefecture", "prefecture": prefecture}
        result["items"] = filtered
        return result

    if lat is not None and lng is not None:
        pref = _nearest_prefecture_from_latlon(lat, lng)
        if pref:
            filtered = [it for it in all_items if _item_matches_prefecture(it, pref)]
            result["scope"] = {"mode": "location", "prefecture": pref}
            result["items"] = filtered
            return result

    # スコープなし → 全障害情報
    result["scope"] = {"mode": "all"}
    return result
