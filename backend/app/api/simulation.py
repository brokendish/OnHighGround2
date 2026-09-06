"""
simulation.py — Simulation / Inspection Mode v1.5 API

本番ナビ挙動を変えない。simulation mock は本番 API に混入しない。

エンドポイント:
  POST /api/simulation/run              — 手動シナリオ実行
  GET  /api/simulation/scenarios        — 定義済みシナリオ一覧
  POST /api/simulation/auto-run         — 定義済みシナリオ一括実行
  POST /api/simulation/point-inspect    — 1点リスク検査
  POST /api/simulation/scenarios/save   — シナリオ保存
  GET  /api/simulation/scenarios/saved  — 保存済みシナリオ一覧
"""
import logging
from fastapi import APIRouter

from app.models.simulation import (
    AutoRunResult,
    PointInspectRequest,
    ScenarioSaveRequest,
    SimulationRunRequest,
)
from app.services.simulation_service import (
    get_saved_scenarios,
    get_scenarios,
    point_inspect_simulation,
    run_auto,
    run_simulation,
    save_scenario,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/simulation/run")
async def simulation_run(body: SimulationRunRequest):
    """
    手動シナリオを実行してルート比較 × penalty breakdown を返す。

    request:
      scenario_id:          string
      origin:               [lon, lat]
      destination:          [lon, lat]
      weather:
        alert_severity:     none | advisory | warning | emergency
        current_intensity:  none | weak | moderate | strong | severe
        forecast_max_intensity: none | weak | moderate | strong | severe
        forecast_minutes:   int
        unknown:            bool  (true → 気象リスク判定不能)
      hazards:
        lowland:            bool
        flood:              bool
        inland_flood:       bool
        landslide:          bool
        tsunami:            bool
        storm_surge:        bool
        unavailable:        bool  (true → ハザード情報確認不可)
      route_hazard_overrides:
        "0": HazardScenario  (ルートインデックスごとの上書き)

    response:
      status:                      ok | unavailable
      scenario_id:
      recommended_route_index:
      routes[]:
        index, label, distance_m, duration_s
        risk_level, safety_score, risk_summary[]
        penalties[]: {type, points, reason}
        recommendation_reason
        is_recommended, is_shortest
      summary: {headline, message}
      layer_stack[]: {key, label, active}
    """
    try:
        return run_simulation(body)
    except Exception:
        # Residual Finding Remediation 06（OPERATOR-ERROR-DETAIL-LEAK）:
        # str(exc)は内部filesystem path等を含みうるためresponseへ含めない。
        # server-side logへはlogger.exception()でtracebackごと残す。
        logger.exception("simulation run error: scenario_id=%s", body.scenario_id)
        return {
            "status": "unavailable",
            "scenario_id": body.scenario_id,
            "recommended_route_index": 0,
            "routes": [],
            "summary": {"headline": "シミュレーション実行エラー", "message": "シミュレーションの実行に失敗しました"},
            "layer_stack": [],
        }


@router.get("/api/simulation/scenarios")
async def simulation_scenarios():
    """
    定義済みシナリオ一覧を返す。
    """
    try:
        return {"status": "ok", "scenarios": [s.model_dump() for s in get_scenarios()]}
    except Exception as exc:
        logger.exception("simulation scenarios error: %s", exc)
        return {"status": "unavailable", "scenarios": []}


@router.post("/api/simulation/auto-run")
async def simulation_auto_run():
    """
    定義済みシナリオを一括実行し、pass/fail レポートを返す。
    レポートは data_runtime/simulation/ に JSON + MD で保存される。
    """
    try:
        result = run_auto()
        return result
    except Exception as exc:
        logger.exception("simulation auto-run error: %s", exc)
        return {
            "status": "unavailable",
            "run_at": None,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "results": [],
            "report_path": None,
        }


@router.post("/api/simulation/point-inspect")
async def simulation_point_inspect(body: PointInspectRequest):
    """
    指定点のリスクを検査して返す。
    use_real_hazard=true のとき実ハザード API を使用（利用不可なら unavailable 扱い）。

    request:
      lat, lon: 検査座標
      weather:  WeatherScenario（気象モック）
      hazards:  HazardScenario（use_real_hazard=false 時のモック）
      use_real_hazard: bool

    response:
      lat, lon, risk_level, safety_score
      penalties[], combined_risks[], hazard_union, layer_stack[]
      data_source: "real" | "simulation"
    """
    try:
        return point_inspect_simulation(body)
    except Exception as exc:
        logger.exception("simulation point-inspect error: %s", exc)
        return {
            "lat": body.lat, "lon": body.lon,
            "risk_level": "unknown",
            "safety_score": 0.0,
            "penalties": [],
            "combined_risks": ["検査エラー"],
            "hazard_union": {},
            "layer_stack": [],
            "data_source": "simulation",
        }


@router.post("/api/simulation/scenarios/save")
async def simulation_scenario_save(body: ScenarioSaveRequest):
    """
    シナリオを data_runtime/simulation/scenarios/{id}.json に保存する。
    """
    try:
        path = save_scenario(body)
        return {"status": "ok", "path": path}
    except Exception:
        # Residual Finding Remediation 06（OPERATOR-ERROR-DETAIL-LEAK）:
        # save_scenario()はdata_runtime/simulation/scenarios/{id}.jsonへ
        # os.makedirs+open(path,"w")で書込むため、PermissionError/OSError
        # のstr(exc)には内部filesystem pathが含まれうる。responseへは
        # 含めず、server-side logへlogger.exception()でtracebackごと残す。
        logger.exception("simulation scenario save error: scenario_id=%s", body.scenario_id)
        return {"status": "error", "message": "シナリオの保存に失敗しました"}


@router.get("/api/simulation/scenarios/saved")
async def simulation_scenarios_saved():
    """
    保存済みシナリオ一覧を返す。
    """
    try:
        scenarios = get_saved_scenarios()
        return {"status": "ok", "scenarios": scenarios}
    except Exception as exc:
        logger.exception("simulation scenarios saved error: %s", exc)
        return {"status": "unavailable", "scenarios": []}
