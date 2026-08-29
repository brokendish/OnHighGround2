"""
simulation.py — Simulation / Inspection Mode v1.5 Pydantic models
"""
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator


class WeatherScenario(BaseModel):
    # Phase 2-B.3 (5.2節): 未知fieldを拒否する（extra="forbid"）。
    model_config = ConfigDict(extra="forbid")

    alert_severity: str = "none"        # none | advisory | warning | emergency
    current_intensity: str = "none"     # none | weak | moderate | strong | severe
    forecast_max_intensity: str = "none"
    forecast_minutes: int = 30
    unknown: bool = False               # True → weather_risk = "unknown" (気象判定不能)


class HazardScenario(BaseModel):
    # Phase 2-B.3 (5.2節): 未知fieldを拒否する（extra="forbid"）。
    model_config = ConfigDict(extra="forbid")

    lowland: bool = False
    flood: bool = False
    inland_flood: bool = False
    landslide: bool = False
    tsunami: bool = False
    storm_surge: bool = False
    unavailable: bool = False           # True → ハザード情報確認不可（warning 扱いしない）


class SimulationRunRequest(BaseModel):
    # Phase 2-B.3 (5.2節): 未知fieldを拒否する（extra="forbid"）。
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = "manual"
    origin: list[float]       # [lon, lat]
    destination: list[float]  # [lon, lat]
    weather: WeatherScenario = WeatherScenario()
    hazards: HazardScenario = HazardScenario()
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
    coordinates: list[list[float]] = []  # [[lat, lon], ...] Leaflet 用


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
    risk_level: Optional[str] = None
    min_risk_level: Optional[str] = None
    recommended_not_shortest: Optional[bool] = None


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


# ── v1.5 追加モデル ────────────────────────────────────────────────────────────

class PointInspectRequest(BaseModel):
    # Phase 2-B.3 (5.2節): 未知fieldを拒否する（extra="forbid"）。
    model_config = ConfigDict(extra="forbid")

    lat: float
    lon: float
    weather: WeatherScenario = WeatherScenario()
    hazards: HazardScenario = HazardScenario()
    use_real_hazard: bool = True  # True: 実ハザードAPI使用、False: シナリオ mock 使用


class PointInspectResult(BaseModel):
    lat: float
    lon: float
    risk_level: str
    safety_score: float
    penalties: list[PenaltyItem]
    combined_risks: list[str]
    hazard_union: dict
    layer_stack: list[LayerItem]
    data_source: str = "simulation"  # "real" | "simulation"


class ScenarioSaveRequest(BaseModel):
    # Phase 2-B.3 (5.2節): 未知fieldを拒否する（extra="forbid"）。
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    title: str
    origin: list[float]
    destination: list[float]
    weather: WeatherScenario = WeatherScenario()
    hazards: HazardScenario = HazardScenario()

    @field_validator("scenario_id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        import re
        if not re.match(r'^[a-zA-Z0-9_\-]{1,64}$', v):
            raise ValueError("scenario_id must be alphanumeric/underscore/hyphen, 1-64 chars")
        return v

    @field_validator("origin", "destination")
    @classmethod
    def validate_lonlat(cls, v: list[float]) -> list[float]:
        if len(v) < 2:
            raise ValueError("must have [lon, lat]")
        return [float(v[0]), float(v[1])]
