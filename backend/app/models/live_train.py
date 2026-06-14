"""
live_train.py — 鉄道運行影響レイヤー データモデル

status 分類:
  normal              平常
  delay               遅延
  partial_suspension  一部運休
  suspended           運転見合わせ
  unknown             状態不明
  unavailable         取得不可

severity:
  0  normal
  1  unknown
  2  delay
  3  partial_suspension
  4  suspended
  9  unavailable
"""
from __future__ import annotations

from typing import Dict, NotRequired, TypedDict

STATUS_NORMAL             = "normal"
STATUS_DELAY              = "delay"
STATUS_PARTIAL_SUSPENSION = "partial_suspension"
STATUS_SUSPENDED          = "suspended"
STATUS_UNKNOWN            = "unknown"
STATUS_UNAVAILABLE        = "unavailable"

STATUS_LABEL: Dict[str, str] = {
    STATUS_NORMAL:             "平常",
    STATUS_DELAY:              "遅延",
    STATUS_PARTIAL_SUSPENSION: "一部運休",
    STATUS_SUSPENDED:          "運転見合わせ",
    STATUS_UNKNOWN:            "状態不明",
    STATUS_UNAVAILABLE:        "取得不可",
}

SEVERITY: Dict[str, int] = {
    STATUS_NORMAL:             0,
    STATUS_UNKNOWN:            1,
    STATUS_DELAY:              2,
    STATUS_PARTIAL_SUSPENSION: 3,
    STATUS_SUSPENDED:          4,
    STATUS_UNAVAILABLE:        9,
}


class TrainInfoItem(TypedDict):
    railway_id:    str
    operator_id:   str
    operator_name: str
    railway_name:  str
    status:        str
    status_label:  str
    severity:      int
    description:   str
    updated_at:    str
    source:        str
    lat:           NotRequired[float]
    lng:           NotRequired[float]
