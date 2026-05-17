"""
simulation.py — Simulation / Inspection Mode v1 Pydantic models
"""
from typing import Optional
from pydantic import BaseModel, field_validator


class WeatherScenario(BaseModel):
    alert_severity: str = "none"        # none | advisory | warning | emergency
    current_intensity: str = "none"     # none | weak | moderate | strong | severe
    forecast_max_intensity: str = "none"
    forecast_minutes: int = 30
    unknown: bool = False               # True → weather_risk = "unknown" (気象判定不能)


class HazardScenario(BaseModel):
    lowland: bool = False
    flood: bool = False
    inland_flood: bool = False
    landslide: bool = False
    tsunami: bool = False
    storm_surge: bool = False
    unavailable: bool = False           # True → ハザード情報確認不可（warning 扱いしない）


class SimulationRunRequest(BaseModel):
    scenario_id: str = "manual"
    origin: list[float]       # [lon, lat]
    destination: list[float]  # [lon, lat]
    weather: WeatherScenario = WeatherScenario()
    hazards: HazardScenario = HazardScenario()
    # per-route hazard override: {"0": HazardScenario, ...}
    # ルートインデックスごとに hazard を上書き（scenario 008 等の差分デモ用）
    route_hazard_overrides: Optional[dict[str, HazardScenario]] = None

    @field_validator("origin", "destination")
    @classmethod
    def validate_lonlat(cls, v: list[float]) -> list[float]:
        if len(v) < 2:
            raise ValueError("must have [lon, lat]")
        lon, lat = float(v[0]), float(v[1])
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError(f"invalid lon={lon} lat={lat}")
        return [lon, lat]


class PenaltyItem(BaseModel):
    type: str
    points: float
    reason: str


class SimulationRouteResult(BaseModel):
    index: int
    label: str
    distance_m: float
    duration_s: float
    risk_level: str
    safety_score: float
    risk_summary: list[str]
    penalties: list[PenaltyItem]
    recommendation_reason: str
    is_recommended: bool = False
    is_shortest: bool = False


class LayerItem(BaseModel):
    key: str
    label: str
    active: Optional[bool]  # None = unavailable / unknown state


class SimulationResult(BaseModel):
    status: str
    scenario_id: str
    recommended_route_index: int
    routes: list[SimulationRouteResult]
    summary: dict
    layer_stack: list[LayerItem]


class ScenarioExpected(BaseModel):
    risk_level: Optional[str] = None            # exact risk_level for recommended route
    min_risk_level: Optional[str] = None        # recommended route risk >= this
    recommended_not_shortest: Optional[bool] = None  # recommended ≠ shortest


class PredefinedScenario(BaseModel):
    scenario_id: str
    title: str
    origin: list[float]
    destination: list[float]
    weather: WeatherScenario = WeatherScenario()
    hazards: HazardScenario = HazardScenario()
    route_hazard_overrides: Optional[dict[str, HazardScenario]] = None
    expected: ScenarioExpected = ScenarioExpected()


class AutoRunScenarioResult(BaseModel):
    scenario_id: str
    title: str
    status: str                    # pass | fail | skip
    risk_level: Optional[str] = None
    recommended_route_index: Optional[int] = None
    fail_reason: Optional[str] = None


class AutoRunResult(BaseModel):
    run_at: str
    total: int
    passed: int
    failed: int
    skipped: int
    results: list[AutoRunScenarioResult]
    report_path: Optional[str] = None
