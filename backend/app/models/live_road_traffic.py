"""
live_road_traffic.py — 道路交通影響レイヤー データモデル

status 分類:
  normal      通常
  high        交通量多い
  very_high   交通量非常に多い
  low         交通量少ない
  very_low    交通量極端に少ない
  unknown     状態不明
  unavailable 取得不可

severity:
  0  normal
  1  unknown
  2  high / low
  3  very_high / very_low
  9  unavailable
"""
from __future__ import annotations

from typing import Dict, NotRequired, Optional, TypedDict

STATUS_NORMAL      = "normal"
STATUS_HIGH        = "high"
STATUS_VERY_HIGH   = "very_high"
STATUS_LOW         = "low"
STATUS_VERY_LOW    = "very_low"
STATUS_UNKNOWN     = "unknown"
STATUS_UNAVAILABLE = "unavailable"

STATUS_LABEL: Dict[str, str] = {
    STATUS_NORMAL:      "通常",
    STATUS_HIGH:        "交通量多い",
    STATUS_VERY_HIGH:   "交通量非常に多い",
    STATUS_LOW:         "交通量少ない",
    STATUS_VERY_LOW:    "交通量極端に少ない",
    STATUS_UNKNOWN:     "状態不明",
    STATUS_UNAVAILABLE: "取得不可",
}

SEVERITY: Dict[str, int] = {
    STATUS_NORMAL:      0,
    STATUS_UNKNOWN:     1,
    STATUS_HIGH:        2,
    STATUS_LOW:         2,
    STATUS_VERY_HIGH:   3,
    STATUS_VERY_LOW:    3,
    STATUS_UNAVAILABLE: 9,
}


class RoadTrafficItem(TypedDict):
    station_id:         str
    road_name:          str
    direction:          str
    lat:                float
    lng:                float
    volume_5min:        NotRequired[Optional[int]]
    volume_1h:          NotRequired[Optional[int]]
    baseline_volume_1h: NotRequired[Optional[int]]
    status:             str
    status_label:       str
    severity:           int
    observed_at:        str
    source:             str
