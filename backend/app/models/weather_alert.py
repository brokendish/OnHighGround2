"""
weather_alert.py — 気象警報・注意報の正規化モデル

JMA仕様変更に備えてアダプタ層で吸収し、UI側はこのモデルのみ参照する。
"""
from dataclasses import dataclass
from typing import Optional

# severity 優先順位（小さいほど高優先）
_SEVERITY_RANK: dict[str, int] = {
    "emergency": 0,
    "warning":   1,
    "advisory":  2,
    "unknown":   3,
    "none":      4,
}

# intensity 優先順位
_INTENSITY_RANK: dict[str, int] = {
    "severe":   0,
    "strong":   1,
    "moderate": 2,
    "weak":     3,
    "none":     4,
    "unknown":  5,
}

# OnHighGround2 避難判断に高優先度な警報・注意報の種別キーワード
HIGH_PRIORITY_KEYWORDS = frozenset([
    "大雨", "洪水", "高潮", "暴風", "暴風雪", "竜巻",
    "土砂災害", "津波",
])


@dataclass
class WeatherAlertItem:
    area_code:        Optional[str]
    area_name:        str
    source_area_type: Optional[str]
    kind:             str
    level:            str
    severity:         str   # emergency | warning | advisory | unknown | none
    status:           str
    headline:         str
    issued_at:        Optional[str]
    updated_at:       Optional[str]
    source:           str
    raw_code:         Optional[str]

    def is_high_priority(self) -> bool:
        return any(kw in self.kind for kw in HIGH_PRIORITY_KEYWORDS)


def severity_rank(severity: str) -> int:
    return _SEVERITY_RANK.get(severity, _SEVERITY_RANK["unknown"])


def max_severity(items: list[WeatherAlertItem]) -> str:
    if not items:
        return "none"
    return min((i.severity for i in items), key=severity_rank)


def to_dict(item: WeatherAlertItem) -> dict:
    return {
        "area_code":        item.area_code,
        "area_name":        item.area_name,
        "source_area_type": item.source_area_type,
        "kind":             item.kind,
        "level":            item.level,
        "severity":         item.severity,
        "status":           item.status,
        "headline":         item.headline,
        "issued_at":        item.issued_at,
        "updated_at":       item.updated_at,
        "source":           item.source,
        "raw_code":         item.raw_code,
    }
