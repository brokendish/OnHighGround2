"""
simulation_service.py — Simulation / Inspection Mode v1

実世界データの代わりにシナリオパラメータをモックとして使い、
既存のスコアリングロジックで penalty breakdown 付きルート評価を行う。

重要方針:
  - 本番 weather/hazard API を呼ばない（モックのみ）
  - unknown を none に倒さない
  - hazard unavailable を warning 扱いしない
  - OSRM ルート取得は本番と同じ URL を使用（実ルート形状を評価）
  - 本番 route_comparison_service の動作を変更しない
"""
import json
import logging
import math
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Optional

from app.models.simulation import (
    AutoRunResult,
    AutoRunScenarioResult,
    HazardScenario,
    LayerItem,
    PenaltyItem,
    PredefinedScenario,
    ScenarioExpected,
    SimulationResult,
    SimulationRouteResult,
    SimulationRunRequest,
    WeatherScenario,
)
from app.services.route_risk_scoring import calc_route_risk_score

logger = logging.getLogger(__name__)

# OSRM（本番と同じ URL を使用 — ルートのみ借用、ハザード/気象はモック）
_OSRM_WALKING_URL = os.environ.get(
    "OSRM_WALKING_URL",
    "http://osrm-walking:5001/route/v1/walking",
)

_REPORT_DIR = os.environ.get("SIMULATION_REPORT_DIR", "/data_runtime/simulation")

# 気象ペナルティ（route_comparison_service と同値）
_WEATHER_PENALTY: dict[str, float] = {
    "severe":   30.0,
    "strong":   15.0,
    "moderate":  5.0,
    "weak":      2.0,
}

# 複合追加ペナルティ
_COMBINED_EXTRA: dict[str, float] = {
    "strong+flood":        15.0,
    "severe+flood":        30.0,
    "strong+landslide":    15.0,
    "severe+landslide":    25.0,
    "strong+inland_flood": 10.0,
    "severe+inland_flood": 15.0,
    "strong+storm_surge":  10.0,
    "severe+storm_surge":  20.0,
}

# 強度ランク
_INTENSITY_RANK: dict[str, int] = {
    "none": 0, "weak": 1, "moderate": 2, "strong": 3, "severe": 4, "unknown": -1,
}

# weather_risk ランク（ルートランキング用）
_WR_RANK: dict[str, int] = {
    "emergency": 4, "warning": 3, "advisory": 2, "none": 0, "unknown": -1,
}

# risk_level ランク（ランキング用: 高いほど安全）
_LEVEL_RANK: dict[str, int] = {
    "none": 4, "advisory": 3, "warning": 2, "emergency": 1, "unknown": 0,
}

# 比較用: 昇順リスク順
_LEVEL_ORDER: dict[str, int] = {
    "none": 0, "advisory": 1, "warning": 2, "emergency": 3, "unknown": -1,
}

# 表示ラベル
_INTENSITY_LABEL: dict[str, str] = {
    "severe":   "非常に激しい雨域通過予測",
    "strong":   "強雨域接近",
    "moderate": "雨域を通過",
    "weak":     "弱い雨域通過予測",
    "unknown":  "気象リスク判定不能",
}

_HAZARD_LABEL: dict[str, str] = {
    "flood":        "洪水想定区域",
    "inland_flood": "内水氾濫想定区域",
    "landslide":    "土砂災害警戒区域",
    "lowland":      "低地・排水困難エリア",
    "tsunami":      "津波想定区域",
    "storm_surge":  "高潮想定区域",
}

# シナリオ→exposure キーマッピング（route_risk_scoring のキーへ）
_SCENARIO_TO_EXPOSURE: dict[str, str] = {
    "flood":        "flood",
    "inland_flood": "inland_flood",
    "landslide":    "landslide",
    "lowland":      "lowland_poor_drainage",
    "tsunami":      "tsunami",
    "storm_surge":  "storm_surge",
}


# ── OSRM ──────────────────────────────────────────────────────────────────────

def _fetch_osrm_routes(origin: list[float], destination: list[float], alternatives: int = 3) -> list:
    coord_str = f"{origin[0]},{origin[1]};{destination[0]},{destination[1]}"
    url = (
        f"{_OSRM_WALKING_URL}/{coord_str}"
        f"?overview=full&geometries=geojson&alternatives={alternatives}&steps=false"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "OnHighGround2/SimulationV1"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        logger.warning("simulation OSRM fetch failed: %s", exc)
        return []
    if data.get("code") != "Ok" or not isinstance(data.get("routes"), list):
        return []
    return data["routes"]


def _osrm_coords(route: dict) -> list[tuple[float, float]]:
    raw = (route.get("geometry") or {}).get("coordinates") or []
    return [(float(c[1]), float(c[0])) for c in raw if len(c) >= 2]


# ── 気象モック ─────────────────────────────────────────────────────────────────

def _resolve_max_intensity(weather: WeatherScenario) -> str:
    """シナリオ気象パラメータから最大降水強度を決定する。"""
    if weather.unknown:
        return "unknown"
    cur_rank = _INTENSITY_RANK.get(weather.current_intensity, -1)
    fcast_rank = _INTENSITY_RANK.get(weather.forecast_max_intensity, -1)
    if fcast_rank >= cur_rank:
        return weather.forecast_max_intensity if fcast_rank >= 0 else "none"
    return weather.current_intensity if cur_rank >= 0 else "none"


def _intensity_to_weather_risk(max_intensity: str) -> str:
    """降水強度 → weather_risk レベル変換。"""
    mapping = {
        "severe":  "emergency",
        "strong":  "warning",
        "moderate": "advisory",
        "weak":    "none",
        "none":    "none",
        "unknown": "unknown",
    }
    return mapping.get(max_intensity, "none")


def _make_weather_risk(max_intensity: str, alert_severity: str) -> str:
    """降水強度と警報 severity から weather_risk を決定する。"""
    if max_intensity == "unknown":
        return "unknown"
    precip_risk = _intensity_to_weather_risk(max_intensity)
    alert_map = {"emergency": "emergency", "warning": "warning", "advisory": "advisory", "none": "none"}
    alert_risk = alert_map.get(alert_severity, "none")
    order = {"none": 0, "advisory": 1, "warning": 2, "emergency": 3}
    if order.get(alert_risk, 0) >= order.get(precip_risk, 0):
        return alert_risk
    return precip_risk


# ── ハザードモック ─────────────────────────────────────────────────────────────

def _build_exposure(hazards: HazardScenario) -> dict[str, float]:
    """シナリオハザード → exposure_by_hazard (各フラグ=True なら exposure=1.0)。"""
    if hazards.unavailable:
        return {}
    return {
        _SCENARIO_TO_EXPOSURE[key]: 1.0
        for key in _SCENARIO_TO_EXPOSURE
        if getattr(hazards, key, False)
    }


def _build_hazard_union(hazards: HazardScenario) -> dict[str, bool]:
    """短縮キー → bool の hazard union（unavailable の場合は空）。"""
    if hazards.unavailable:
        return {}
    return {key: bool(getattr(hazards, key, False)) for key in _SCENARIO_TO_EXPOSURE}


# ── リスクレベル決定 ───────────────────────────────────────────────────────────

def _to_risk_level(
    safety_score: float,
    weather_risk: str,
    hazards_unavailable: bool,
) -> str:
    """
    simulation 版 risk_level 決定。
    - hazard unavailable + 既知気象リスクなし → unknown（warning 扱いしない）
    - weather_risk unknown + hazard なし → unknown（none に倒さない）
    """
    if hazards_unavailable:
        wr = _WR_RANK.get(weather_risk, 0)
        if wr >= 4: return "emergency"
        if wr >= 3: return "warning"
        if wr >= 2: return "advisory"
        if weather_risk == "unknown": return "unknown"
        return "unknown"  # hazard 不明 + 気象リスクなし → unknown

    wr = _WR_RANK.get(weather_risk, 0)
    if safety_score < 30 or wr >= 4:
        return "emergency"
    if safety_score < 50 or wr >= 3:
        return "warning"
    if safety_score < 75 or wr >= 2:
        return "advisory"
    if weather_risk == "unknown":
        return "unknown"
    return "none"


# ── ペナルティ生成 ─────────────────────────────────────────────────────────────

def _build_penalties(
    scoring_result: dict,
    max_intensity: str,
    hazard_union: dict[str, bool],
    hazards_unavailable: bool,
) -> list[PenaltyItem]:
    items: list[PenaltyItem] = []

    if hazards_unavailable:
        items.append(PenaltyItem(
            type="hazard_unavailable",
            points=0,
            reason="ハザード情報確認不可（警告扱いしない）",
        ))

    # 気象ベースペナルティ
    weather_base = _WEATHER_PENALTY.get(max_intensity, 0.0)
    if weather_base > 0:
        items.append(PenaltyItem(
            type=f"{max_intensity}_rain",
            points=weather_base,
            reason=_INTENSITY_LABEL.get(max_intensity, max_intensity),
        ))
    elif max_intensity == "unknown":
        items.append(PenaltyItem(
            type="weather_unknown",
            points=0,
            reason="気象リスク判定不能（安全扱いしない）",
        ))

    # ハザードペナルティ（route_risk_scoring の詳細を使用）
    if not hazards_unavailable:
        for h in scoring_result.get("risk_summary", {}).get("hazards", []):
            items.append(PenaltyItem(
                type=h["type"],
                points=h["penalty"],
                reason=h["label"],
            ))

    # 複合追加ペナルティ
    for short_key, active in hazard_union.items():
        if not active:
            continue
        combo = f"{max_intensity}+{short_key}"
        extra = _COMBINED_EXTRA.get(combo, 0.0)
        if extra > 0:
            label_h = _HAZARD_LABEL.get(short_key, short_key)
            label_w = _INTENSITY_LABEL.get(max_intensity, max_intensity)
            items.append(PenaltyItem(
                type=f"combined_{max_intensity}_{short_key}",
                points=extra,
                reason=f"{label_w.rstrip('予測接近通過域')} + {label_h}",
            ))

    return items


# ── リスクサマリーテキスト ────────────────────────────────────────────────────

def _build_risk_summary(
    max_intensity: str,
    hazards: HazardScenario,
) -> list[str]:
    summary = []
    if max_intensity in _INTENSITY_LABEL:
        summary.append(_INTENSITY_LABEL[max_intensity])
    if hazards.unavailable:
        summary.append("ハザード情報確認不可")
    else:
        for key in ("flood", "inland_flood", "landslide", "lowland", "tsunami", "storm_surge"):
            if getattr(hazards, key, False):
                if lbl := _HAZARD_LABEL.get(key):
                    summary.append(lbl)
    return summary[:3]


# ── 推奨理由テキスト ──────────────────────────────────────────────────────────

def _recommendation_reason(
    risk_level: str,
    is_recommended: bool,
    is_shortest: bool,
    hazards: HazardScenario,
) -> str:
    active_hazards = [
        _HAZARD_LABEL[k] for k in ("flood", "inland_flood", "landslide", "lowland", "tsunami", "storm_surge")
        if getattr(hazards, k, False)
    ]
    if is_recommended:
        if risk_level == "none":
            return "リスクが低いルートです"
        if risk_level == "unknown":
            return "既知リスクなし（気象またはハザード情報判定不能）"
        return "他の候補よりリスクが低いルートです"
    else:
        if is_shortest and risk_level in ("warning", "emergency"):
            if active_hazards:
                return f"最短ですが、{' / '.join(active_hazards[:2])}のリスクがあります"
            return "最短ですが、気象・浸水リスクがあります"
        if risk_level == "emergency":
            return "このルートは危険判定です"
        if risk_level in ("warning", "advisory"):
            return "このルートはリスクが高めです"
        return "他の候補より距離が長くなります"


# ── レイヤースタック ───────────────────────────────────────────────────────────

def _build_layer_stack(weather: WeatherScenario, hazards: HazardScenario) -> list[LayerItem]:
    stack: list[LayerItem] = []
    max_intensity = _resolve_max_intensity(weather)

    if weather.unknown:
        stack.append(LayerItem(key="weather_unknown", label="気象リスク判定不能", active=None))
    elif max_intensity != "none":
        stack.append(LayerItem(
            key=f"weather_{max_intensity}",
            label=f"降水: {_INTENSITY_LABEL.get(max_intensity, max_intensity)}",
            active=True,
        ))
    else:
        stack.append(LayerItem(key="weather_none", label="降水なし", active=False))

    if weather.alert_severity not in ("none", ""):
        stack.append(LayerItem(
            key=f"alert_{weather.alert_severity}",
            label=f"警報: {weather.alert_severity}",
            active=True,
        ))

    if hazards.unavailable:
        stack.append(LayerItem(key="hazard_unavailable", label="ハザード情報確認不可", active=None))
    else:
        for key, label in _HAZARD_LABEL.items():
            stack.append(LayerItem(key=key, label=label, active=bool(getattr(hazards, key, False))))

    return stack


# ── サマリー ──────────────────────────────────────────────────────────────────

def _build_summary(routes: list[dict], rec_idx: int) -> dict:
    if not routes:
        return {"headline": "ルート情報なし", "message": ""}

    rec = next((r for r in routes if r["index"] == rec_idx), routes[0])
    shortest = min(routes, key=lambda r: r["distance_m"])

    if all(r["risk_level"] == "none" for r in routes):
        return {"headline": "全ルートで大きなリスクはありません", "message": "現在の設定では安全圏内です"}

    if rec["index"] != shortest["index"]:
        diff = round((rec["distance_m"] - shortest["distance_m"]) / 10) * 10
        if diff > 0:
            return {
                "headline": "安全寄りルートがあります",
                "message": f"最短ルートより{diff}m長いですが、浸水・災害リスクが低いルートを推奨します",
            }

    if any(r["risk_level"] == "emergency" for r in routes):
        return {"headline": "危険レベルのルートがあります", "message": "避難経路を慎重に選択してください"}
    if any(r["risk_level"] == "warning" for r in routes):
        return {"headline": "警戒が必要なルートがあります", "message": "リスクの低い経路を選択してください"}
    if all(r["risk_level"] == "unknown" for r in routes):
        return {"headline": "気象・ハザード情報が判定不能です", "message": "情報が揃い次第、再確認してください"}

    return {"headline": "リスク確認済み", "message": "推奨ルートで進んでください"}


# ── ルート評価 ────────────────────────────────────────────────────────────────

def _assess_route(
    idx: int,
    raw_route: dict,
    weather: WeatherScenario,
    hazards: HazardScenario,
) -> dict:
    distance_m = round(raw_route.get("distance", 0))
    duration_s = round(raw_route.get("duration", 0))
    max_intensity = _resolve_max_intensity(weather)
    weather_risk = _make_weather_risk(max_intensity, weather.alert_severity)

    exposure = _build_exposure(hazards)
    hazard_union = _build_hazard_union(hazards)

    if hazards.unavailable:
        hazard_safety = 100.0
        scoring_result: dict = {"risk_summary": {"hazards": [], "notes": []}}
    else:
        scoring_result = calc_route_risk_score(exposure)
        hazard_safety = scoring_result["safety_score"]

    # 気象ペナルティ（combined extra は hazard union が有効な場合のみ）
    weather_base = _WEATHER_PENALTY.get(max_intensity, 0.0)
    combined_extra = 0.0
    if not hazards.unavailable:
        for short_key, active in hazard_union.items():
            if active:
                combined_extra += _COMBINED_EXTRA.get(f"{max_intensity}+{short_key}", 0.0)
    weather_penalty = weather_base + combined_extra

    combined_safety = max(0.0, min(100.0, hazard_safety - weather_penalty))
    risk_level = _to_risk_level(combined_safety, weather_risk, hazards.unavailable)

    penalties = _build_penalties(scoring_result, max_intensity, hazard_union, hazards.unavailable)
    risk_summary = _build_risk_summary(max_intensity, hazards)

    return {
        "index":        idx,
        "distance_m":   distance_m,
        "duration_s":   duration_s,
        "risk_level":   risk_level,
        "safety_score": round(combined_safety, 1),
        "risk_summary": risk_summary,
        "penalties":    penalties,
        "hazards":      hazards,
    }


# ── ランキング ─────────────────────────────────────────────────────────────────

def _rank_routes(assessed: list[dict]) -> int:
    def sort_key(r: dict) -> tuple:
        return (_LEVEL_RANK.get(r["risk_level"], 0), r["safety_score"], -r["distance_m"])
    return max(assessed, key=sort_key)["index"]


# ── メインエントリ ─────────────────────────────────────────────────────────────

def run_simulation(req: SimulationRunRequest) -> SimulationResult:
    """シナリオを実行して Inspection 結果を返す。"""
    raw_routes = _fetch_osrm_routes(req.origin, req.destination, alternatives=3)
    if not raw_routes:
        return SimulationResult(
            status="unavailable",
            scenario_id=req.scenario_id,
            recommended_route_index=0,
            routes=[],
            summary={"headline": "ルートを取得できません", "message": "出発地・目的地を確認してください"},
            layer_stack=_build_layer_stack(req.weather, req.hazards),
        )

    assessed: list[dict] = []
    for idx, raw in enumerate(raw_routes[:3]):
        # per-route hazard override（シナリオ 008 等の差分デモ用）
        hazards = req.hazards
        if req.route_hazard_overrides and str(idx) in req.route_hazard_overrides:
            hazards = req.route_hazard_overrides[str(idx)]
        assessed.append(_assess_route(idx, raw, req.weather, hazards))

    rec_idx = _rank_routes(assessed)
    shortest_idx = min(assessed, key=lambda r: r["distance_m"])["index"]

    routes_out: list[SimulationRouteResult] = []
    for r in assessed:
        is_rec = r["index"] == rec_idx
        is_short = r["index"] == shortest_idx
        reason = _recommendation_reason(r["risk_level"], is_rec, is_short, r["hazards"])
        routes_out.append(SimulationRouteResult(
            index=r["index"],
            label=chr(65 + r["index"]),
            distance_m=r["distance_m"],
            duration_s=r["duration_s"],
            risk_level=r["risk_level"],
            safety_score=r["safety_score"],
            risk_summary=r["risk_summary"],
            penalties=r["penalties"],
            recommendation_reason=reason,
            is_recommended=is_rec,
            is_shortest=is_short,
        ))

    summary = _build_summary(
        [{"index": r.index, "distance_m": r.distance_m, "risk_level": r.risk_level} for r in routes_out],
        rec_idx,
    )

    return SimulationResult(
        status="ok",
        scenario_id=req.scenario_id,
        recommended_route_index=rec_idx,
        routes=routes_out,
        summary=summary,
        layer_stack=_build_layer_stack(req.weather, req.hazards),
    )


# ── 定義済みシナリオ ──────────────────────────────────────────────────────────

_ORIGIN = [139.767125, 35.681236]      # 東京駅付近
_DEST   = [139.780000, 35.690000]      # 浜町付近

PREDEFINED_SCENARIOS: list[PredefinedScenario] = [
    PredefinedScenario(
        scenario_id="001",
        title="平常時",
        origin=_ORIGIN,
        destination=_DEST,
        weather=WeatherScenario(),
        hazards=HazardScenario(),
        expected=ScenarioExpected(risk_level="none"),
    ),
    PredefinedScenario(
        scenario_id="002",
        title="強雨のみ",
        origin=_ORIGIN,
        destination=_DEST,
        weather=WeatherScenario(forecast_max_intensity="strong"),
        hazards=HazardScenario(),
        expected=ScenarioExpected(min_risk_level="advisory"),
    ),
    PredefinedScenario(
        scenario_id="003",
        title="強雨 + 洪水想定区域",
        origin=_ORIGIN,
        destination=_DEST,
        weather=WeatherScenario(forecast_max_intensity="strong"),
        hazards=HazardScenario(flood=True),
        expected=ScenarioExpected(min_risk_level="warning"),
    ),
    PredefinedScenario(
        scenario_id="004",
        title="非常に激しい雨 + 土砂災害",
        origin=_ORIGIN,
        destination=_DEST,
        weather=WeatherScenario(forecast_max_intensity="severe"),
        hazards=HazardScenario(landslide=True),
        expected=ScenarioExpected(min_risk_level="emergency"),
    ),
    PredefinedScenario(
        scenario_id="005",
        title="中程度の雨 + 低地・排水困難",
        origin=_ORIGIN,
        destination=_DEST,
        weather=WeatherScenario(forecast_max_intensity="moderate"),
        hazards=HazardScenario(lowland=True),
        expected=ScenarioExpected(min_risk_level="advisory"),
    ),
    PredefinedScenario(
        scenario_id="006",
        title="気象リスク判定不能",
        origin=_ORIGIN,
        destination=_DEST,
        weather=WeatherScenario(unknown=True),
        hazards=HazardScenario(),
        expected=ScenarioExpected(risk_level="unknown"),
    ),
    PredefinedScenario(
        scenario_id="007",
        title="ハザード情報確認不可",
        origin=_ORIGIN,
        destination=_DEST,
        weather=WeatherScenario(),
        hazards=HazardScenario(unavailable=True),
        expected=ScenarioExpected(risk_level="unknown"),
    ),
    PredefinedScenario(
        scenario_id="008",
        title="リスク最短ルート vs 安全長ルート（per-route ハザード差分）",
        origin=_ORIGIN,
        destination=_DEST,
        weather=WeatherScenario(forecast_max_intensity="strong"),
        hazards=HazardScenario(),  # デフォルト（route 0 のみ override）
        route_hazard_overrides={
            "0": HazardScenario(flood=True, lowland=True),
            # route 1+ はハザードなし
        },
        expected=ScenarioExpected(recommended_not_shortest=True),
    ),
]


def get_scenarios() -> list[PredefinedScenario]:
    return PREDEFINED_SCENARIOS


# ── auto-run ──────────────────────────────────────────────────────────────────

_LEVEL_ORDER_CMP: dict[str, int] = {
    "none": 0, "advisory": 1, "warning": 2, "emergency": 3, "unknown": -1,
}


def _check_expected(result: SimulationResult, expected: ScenarioExpected) -> tuple[bool, str]:
    """期待条件を検証し、(passed, fail_reason) を返す。"""
    if result.status != "ok" or not result.routes:
        return False, "status != ok or routes empty"

    rec = next((r for r in result.routes if r.index == result.recommended_route_index), None)
    if rec is None:
        return False, "recommended route not found"

    if expected.risk_level is not None:
        if rec.risk_level != expected.risk_level:
            return False, f"risk_level: expected {expected.risk_level!r}, got {rec.risk_level!r}"

    if expected.min_risk_level is not None:
        min_ord = _LEVEL_ORDER_CMP.get(expected.min_risk_level, 0)
        got_ord = _LEVEL_ORDER_CMP.get(rec.risk_level, -1)
        if got_ord < min_ord:
            return False, (
                f"min_risk_level: expected >= {expected.min_risk_level!r} "
                f"(ord {min_ord}), got {rec.risk_level!r} (ord {got_ord})"
            )

    if expected.recommended_not_shortest is True:
        if len(result.routes) < 2:
            # ルートが1本しかなければ skip とみなす
            return True, ""
        shortest = min(result.routes, key=lambda r: r.distance_m)
        if result.recommended_route_index == shortest.index:
            return False, (
                f"recommended_not_shortest: recommended={result.recommended_route_index}, "
                f"shortest={shortest.index}"
            )

    return True, ""


def run_auto() -> AutoRunResult:
    """全定義済みシナリオを実行してレポートを返す。"""
    now = datetime.now(timezone.utc)
    now_jst = now.astimezone(timezone.utc)
    run_at = now_jst.isoformat()

    results: list[AutoRunScenarioResult] = []
    for sc in PREDEFINED_SCENARIOS:
        req = SimulationRunRequest(
            scenario_id=sc.scenario_id,
            origin=sc.origin,
            destination=sc.destination,
            weather=sc.weather,
            hazards=sc.hazards,
            route_hazard_overrides=sc.route_hazard_overrides,
        )
        try:
            sim_result = run_simulation(req)
        except Exception as exc:
            logger.warning("auto-run scenario %s failed: %s", sc.scenario_id, exc)
            results.append(AutoRunScenarioResult(
                scenario_id=sc.scenario_id,
                title=sc.title,
                status="fail",
                fail_reason=str(exc),
            ))
            continue

        rec = next(
            (r for r in sim_result.routes if r.index == sim_result.recommended_route_index),
            None,
        )
        passed, fail_reason = _check_expected(sim_result, sc.expected)

        results.append(AutoRunScenarioResult(
            scenario_id=sc.scenario_id,
            title=sc.title,
            status="pass" if passed else "fail",
            risk_level=rec.risk_level if rec else None,
            recommended_route_index=sim_result.recommended_route_index,
            fail_reason=fail_reason if not passed else None,
        ))

    total = len(results)
    passed_count = sum(1 for r in results if r.status == "pass")
    failed_count = sum(1 for r in results if r.status == "fail")
    skipped_count = sum(1 for r in results if r.status == "skip")

    report = AutoRunResult(
        run_at=run_at,
        total=total,
        passed=passed_count,
        failed=failed_count,
        skipped=skipped_count,
        results=results,
    )

    # レポート保存
    report_path = _save_report(report, now)
    report.report_path = report_path

    return report


def _save_report(report: AutoRunResult, now: datetime) -> Optional[str]:
    """JSON + MD レポートを data_runtime/simulation/ に保存する。"""
    try:
        os.makedirs(_REPORT_DIR, exist_ok=True)
        ts = now.strftime("%Y%m%d_%H%M%S")
        json_path = os.path.join(_REPORT_DIR, f"simulation_report_{ts}.json")
        md_path   = os.path.join(_REPORT_DIR, f"simulation_report_{ts}.md")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report.model_dump(), f, ensure_ascii=False, indent=2)

        # Markdown レポート生成
        lines = [
            f"# Simulation Auto-Run Report",
            f"",
            f"- 実行日時: {report.run_at}",
            f"- 合計: {report.total}",
            f"- PASS: {report.passed}",
            f"- FAIL: {report.failed}",
            f"",
            f"## 結果詳細",
            f"",
        ]
        for r in report.results:
            icon = "✅" if r.status == "pass" else "❌" if r.status == "fail" else "⏭"
            lines.append(f"### {icon} [{r.scenario_id}] {r.title}")
            lines.append(f"- status: **{r.status}**")
            if r.risk_level:
                lines.append(f"- risk_level: {r.risk_level}")
            if r.recommended_route_index is not None:
                lines.append(f"- recommended_route_index: {r.recommended_route_index}")
            if r.fail_reason:
                lines.append(f"- FAIL reason: {r.fail_reason}")
            lines.append("")

        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        logger.info("simulation report saved: %s", json_path)
        return json_path
    except Exception as exc:
        logger.warning("simulation report save failed: %s", exc)
        return None
