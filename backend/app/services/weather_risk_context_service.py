"""
weather_risk_context_service.py — 気象 × ハザード統合リスクコンテキスト (Phase2-C)

GET /api/weather/risk/context?lat=&lon= のバックエンド実装。

気象警報・降水予測 × ハザードゾーン判定を統合し、
避難判断向けの複合リスク（combined risk）を正規化して返す。

risk_level:
  none       — 危険なし
  advisory   — 注意（弱〜中程度の雨 / 注意報 / 雨+lowland）
  warning    — 警戒（strong/severe rain / 大雨系警報 / strong rain+flood等）
  emergency  — 特別警報 / severe rain + flood/inland_flood/landslide
  unknown    — 判定不能（既知のwarning/emergencyがある場合はそちらを優先）
               未分類コードの警報のみ発表中、または警報・降水の取得失敗（unavailable）を含む。
               取得失敗の区別は weather.alert_status / weather.precip_status で保持する。

weather.alert_status / weather.precip_status: "ok" | "stale" | "unavailable"
  unavailable = 取得そのものに失敗（「警報なし」「降水なし」とは区別する）
  stale       = 前回取得データで評価（既存 stale fallback policy のまま）

重要方針:
  - unknown を none に倒さない（false-safe 防止）
  - 取得失敗（unavailable）を none に倒さない
  - hazard unavailable 時は API を落とさない（graceful degradation）
  - route scoring / reroute には影響しない
"""
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from app.services.weather_alert_service import get_alerts_for_location, get_precipitation_summary
from app.services.hazard_runtime_service import get_hazard_service

logger = logging.getLogger(__name__)

_RISK_CACHE: dict = {}   # key=(round_lat, round_lon) → (data, mono_time)
_RISK_TTL   = 60.0       # 秒

_INTENSITY_RANK: dict[str, int] = {
    "severe": 4, "strong": 3, "moderate": 2, "weak": 1, "none": 0, "unknown": -1,
}
_SEV_RANK: dict[str, int] = {
    "emergency": 4, "warning": 3, "advisory": 2, "none": 0, "unknown": 0,
}


def _round_coord(v: float, digits: int = 3) -> float:
    return round(v, digits)


def get_risk_context(lat: float, lon: float) -> dict:
    """現在地の気象 × ハザード統合リスクコンテキストを返す。"""
    cache_key = (_round_coord(lat), _round_coord(lon))
    now_mono  = time.monotonic()
    now_iso   = datetime.now(timezone.utc).isoformat()

    cached = _RISK_CACHE.get(cache_key)
    if cached is not None:
        data, fetched_at = cached
        if now_mono - fetched_at < _RISK_TTL:
            return data

    try:
        data = _build_risk_context(lat, lon, now_iso)
    except Exception as exc:
        logger.warning("get_risk_context failed lat=%s lon=%s: %s", lat, lon, exc)
        data = _unavailable_response(now_iso)

    _RISK_CACHE[cache_key] = (data, now_mono)
    return data


def _unavailable_response(now_iso: str) -> dict:
    return {
        "status": "unavailable",
        "risk_level": "unknown",
        "weather": {
            "alert_status":          "unavailable",
            "precip_status":         "unavailable",
            "alert_severity":        "unknown",
            "precip_severity":       "unknown",
            "current_intensity":     "unknown",
            "forecast_max_intensity": None,
            "forecast_max_minutes":  None,
        },
        "hazards": {
            "lowland":      None,
            "flood":        None,
            "inland_flood": None,
            "landslide":    None,
            "tsunami":      None,
            "storm_surge":  None,
            "data_available": False,
        },
        "combined": [],
        "updated_at": now_iso,
    }


def _build_risk_context(lat: float, lon: float, now_iso: str) -> dict:
    # 気象警報・注意報（キャッシュ済みサービスを共有）
    try:
        alerts_data = get_alerts_for_location(lat, lon)
    except Exception as exc:
        logger.warning("risk_context: alerts fetch failed: %s", exc)
        alerts_data = {"status": "unavailable", "severity": "none", "alerts": []}

    # 降水予測（キャッシュ済みサービスを共有）
    try:
        precip_data = get_precipitation_summary(lat, lon)
    except Exception as exc:
        logger.warning("risk_context: precip fetch failed: %s", exc)
        precip_data = {"status": "unavailable", "severity": "unknown", "current": {}, "forecast": []}

    # ハザード点判定
    hazard_assessment = _fetch_hazard_assessment(lat, lon)
    hazards = _build_hazard_flags(hazard_assessment)

    # 気象サマリー（内部計算用）
    weather = _build_weather_summary(alerts_data, precip_data)

    # 複合リスク（強雨 × ハザードゾーン）
    combined = _build_combined_risks(weather, hazards)

    # 統合リスクレベル
    risk_level = _compute_risk_level(weather, hazards, combined)

    return {
        "status":     "ok",
        "risk_level": risk_level,
        "weather":    weather,
        "hazards":    hazards,
        "combined":   combined,
        "updated_at": now_iso,
    }


# ── ハザード判定 ──────────────────────────────────────────────────────────────

def _fetch_hazard_assessment(lat: float, lon: float) -> dict:
    svc = get_hazard_service()
    if svc is None:
        return {}
    try:
        return svc.assess_candidate(lat, lon)
    except Exception as exc:
        logger.warning("risk_context: hazard assess failed lat=%s lon=%s: %s", lat, lon, exc)
        return {}


def _hazard_status(v) -> str:
    """ハザード評価値（文字列 or 構造体 dict）から status 文字列を返す。"""
    if isinstance(v, dict):
        return v.get("status", "unknown")
    return v if isinstance(v, str) else "unknown"


def _build_hazard_flags(assessment: dict) -> dict:
    """ハザード評価を bool | None のフラグに正規化する。

    True  = inside（現在地がハザードゾーン内）
    False = outside
    None  = unknown / 未ロード（判定不能）
    """
    def _flag(key: str) -> Optional[bool]:
        if key not in assessment:
            return None
        status = _hazard_status(assessment[key])
        if status == "unknown":
            return None
        return status == "inside"

    return {
        "lowland":      _flag("lowland_poor_drainage"),
        "flood":        _flag("flood"),
        "inland_flood": _flag("inland_flood"),
        "landslide":    _flag("landslide"),
        "tsunami":      _flag("tsunami"),
        "storm_surge":  _flag("storm_surge"),
        "data_available": len(assessment) > 0,
    }


# ── 気象サマリー ──────────────────────────────────────────────────────────────

def _build_weather_summary(alerts_data: dict, precip_data: dict) -> dict:
    # 取得状態（status 欠落は既存呼び出し互換のため ok 扱い）
    alert_status    = (alerts_data or {}).get("status", "ok") or "ok"
    precip_status   = (precip_data or {}).get("status", "ok") or "ok"
    alert_severity  = (alerts_data or {}).get("severity", "none") or "none"
    precip_severity = (precip_data  or {}).get("severity", "none") or "none"
    current         = ((precip_data or {}).get("current") or {})
    current_intensity = current.get("intensity", "unknown") or "unknown"

    forecast = (precip_data or {}).get("forecast") or []
    forecast_max: Optional[str] = None
    forecast_max_minutes: Optional[int] = None
    max_rank = -2
    for f in forecast:
        fi   = f.get("intensity", "unknown")
        rank = _INTENSITY_RANK.get(fi, -1)
        if rank > max_rank:
            max_rank = rank
            forecast_max         = fi
            forecast_max_minutes = f.get("minutes")

    return {
        "alert_status":           alert_status,
        "precip_status":          precip_status,
        "alert_severity":         alert_severity,
        "precip_severity":        precip_severity,
        "current_intensity":      current_intensity,
        "forecast_max_intensity": forecast_max,
        "forecast_max_minutes":   forecast_max_minutes,
    }


def _effective_rain_rank(weather: dict) -> int:
    """現在強度と予測最大強度のうち高い方のランクを返す。"""
    cur_rank  = _INTENSITY_RANK.get(weather["current_intensity"], -1)
    fcst_rank = _INTENSITY_RANK.get(weather["forecast_max_intensity"] or "none", -1)
    return max(cur_rank, fcst_rank)


# ── 複合リスク構築 ────────────────────────────────────────────────────────────

def _build_combined_risks(weather: dict, hazards: dict) -> list:
    """強雨 × ハザードゾーンの複合リスクリストを構築する。

    返却形式:
        [{"type": str, "level": str, "headline": str, "message": str}, ...]

    対象: lowland / flood / inland_flood / landslide
    tsunami / storm_surge は参考情報扱い（今フェーズでは combined に含めない）
    """
    combined = []
    rain_rank = _effective_rain_rank(weather)
    minutes   = weather.get("forecast_max_minutes")
    time_pfx  = f"{minutes}分以内に" if minutes else "周辺で"

    # 強雨 + flood → warning / emergency
    if hazards.get("flood") is True and rain_rank >= 2:  # moderate 以上
        level    = "emergency" if rain_rank >= 4 else "warning"
        headline = "強雨域接近 + 洪水想定区域" if rain_rank >= 3 else "雨域 + 洪水想定区域"
        message  = (
            f"{time_pfx}強雨域接近。周辺の浸水リスクに注意してください。" if rain_rank >= 3
            else "現在地周辺が洪水想定区域です。雨量に注意してください。"
        )
        combined.append({"type": "rain_flood", "level": level, "headline": headline, "message": message})

    # 強雨 + inland_flood → warning / emergency
    if hazards.get("inland_flood") is True and rain_rank >= 2:
        level    = "emergency" if rain_rank >= 4 else "warning"
        headline = "強雨 + 内水氾濫想定区域" if rain_rank >= 3 else "雨 + 内水氾濫想定区域"
        combined.append({
            "type": "rain_inland_flood", "level": level,
            "headline": headline,
            "message":  "内水氾濫リスクがあるエリアで雨域が接近しています。",
        })

    # 強雨 + landslide → warning / emergency
    if hazards.get("landslide") is True and rain_rank >= 2:
        level    = "emergency" if rain_rank >= 3 else "warning"
        headline = "強雨 + 土砂災害警戒区域" if rain_rank >= 3 else "雨 + 土砂災害警戒区域"
        combined.append({
            "type": "rain_landslide", "level": level,
            "headline": headline,
            "message":  "土砂災害警戒区域で雨域が接近しています。早めの避難を検討してください。",
        })

    # 雨 + lowland → advisory（降水ドリブン単独でも判定）
    if hazards.get("lowland") is True and rain_rank >= 1:  # weak 以上
        combined.append({
            "type": "rain_lowland", "level": "advisory",
            "headline": "雨域 + 低地・排水困難エリア",
            "message":  "低地・排水困難エリア周辺で雨域が接近しています。周辺状況に注意してください。",
        })

    return combined


# ── リスクレベル計算 ──────────────────────────────────────────────────────────

def _compute_risk_level(weather: dict, hazards: dict, combined: list) -> str:
    """
    気象・ハザード・複合リスクから統合リスクレベルを返す。

    優先度: emergency > warning > advisory > unknown > none
    unknown は none より安全側に扱うが、既知の強い危険を上書きしない。
    unknown の要因（未分類コード / alerts 取得失敗 / 降水取得失敗）に相互の優劣は付けない。
    """
    alert_rank   = _SEV_RANK.get(weather["alert_severity"], 0)
    precip_rank  = min(_SEV_RANK.get(weather["precip_severity"], 0), 3)  # emergency は alert 専用
    combined_max = max((_SEV_RANK.get(c["level"], 0) for c in combined), default=0)

    known_rank = max(alert_rank, precip_rank, combined_max)
    if known_rank >= 4: return "emergency"
    if known_rank >= 3: return "warning"
    if known_rank >= 2: return "advisory"

    # 未分類コードの警報・注意報のみ発表中 → severity 不明。none（安全）と断定しない
    if weather["alert_severity"] == "unknown":
        return "unknown"

    # 警報・降水の取得失敗 → 「なし」ではなく判定不能（既知リスクは上で優先済み）
    if weather.get("alert_status") == "unavailable" or weather.get("precip_status") == "unavailable":
        return "unknown"

    # known_rank == 0: 確認できるリスクなし → unknown チェック
    precip_unknown = weather["precip_severity"] == "unknown"
    alert_none     = weather["alert_severity"] in ("none", "unknown")
    if alert_none and precip_unknown:
        return "unknown"

    return "none"
