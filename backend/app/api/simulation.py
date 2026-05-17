"""
simulation.py — Simulation / Inspection Mode v1 API (Phase3-B)

本番ナビ挙動を変えない。simulation mock は本番 API に混入しない。

エンドポイント:
  POST /api/simulation/run        — 手動シナリオ実行
  GET  /api/simulation/scenarios  — 定義済みシナリオ一覧
  POST /api/simulation/auto-run   — 定義済みシナリオ一括実行
"""
import logging
from fastapi import APIRouter
from pydantic import BaseModel

from app.models.simulation import SimulationRunRequest, AutoRunResult
from app.services.simulation_service import run_simulation, get_scenarios, run_auto

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
    except Exception as exc:
        logger.exception("simulation run error: %s", exc)
        return {
            "status": "unavailable",
            "scenario_id": body.scenario_id,
            "recommended_route_index": 0,
            "routes": [],
            "summary": {"headline": "シミュレーション実行エラー", "message": str(exc)},
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
