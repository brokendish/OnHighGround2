"""
hazard_runtime_service.py — HazardService singleton registry

main.py が起動時に HazardService インスタンスを登録し、
pipeline_service.py がデプロイ後に hot-reload を呼び出す。
"""
from __future__ import annotations
from typing import Optional

_hazard_service = None


def set_hazard_service(svc) -> None:
    global _hazard_service
    _hazard_service = svc


def get_hazard_service():
    return _hazard_service
