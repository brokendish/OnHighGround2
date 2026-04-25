#!/usr/bin/env python3
"""
OSRMウォーキングプロファイル再ビルドスクリプト
Config値を読み込み、foot.lua を更新して osrm-extract を再実行する。

バックエンドコンテナ内から呼び出される想定:
  python3 /scripts/rebuild_osrm_walking.py
"""

import json
import re
import subprocess
import sys
from pathlib import Path

LUA_PATH = Path("/osrm/foot.lua")
CONFIG_OVERRIDES_PATH = Path("/data_runtime/system/config_overrides.json")
CONFIG_DEFINITIONS_PATH = Path("/data_lake/registry/config_definitions.json")
PBF_PATH = "/data_lake/validated/tokyo/osm/walking/tokyo-kanagawa/tokyo-kanagawa-260214.osm.pbf"
OSRM_PATH = PBF_PATH.replace(".osm.pbf", ".osrm")
CONTAINER = "evacuation-navi-osrm-walking"


def get_config(key: str, fallback: float) -> float:
    overrides: dict = {}
    if CONFIG_OVERRIDES_PATH.exists():
        with CONFIG_OVERRIDES_PATH.open("r", encoding="utf-8") as f:
            overrides = json.load(f)

    if key in overrides:
        return float(overrides[key])

    if CONFIG_DEFINITIONS_PATH.exists():
        with CONFIG_DEFINITIONS_PATH.open("r", encoding="utf-8") as f:
            definitions = json.load(f)
        for item in definitions:
            if item.get("key") == key:
                return float(item.get("default_value", fallback))

    return fallback


def get_config_values() -> dict:
    return {
        "trunk_penalty":    get_config("osrm.trunk_penalty",    0.15),
        "primary_penalty":  get_config("osrm.primary_penalty",  0.25),
        "secondary_factor": get_config("osrm.secondary_factor", 0.80),
    }


def update_foot_lua(values: dict) -> None:
    if not LUA_PATH.exists():
        print(f"[ERROR] foot.lua が見つかりません: {LUA_PATH}", file=sys.stderr)
        sys.exit(1)

    content = LUA_PATH.read_text(encoding="utf-8")

    content = re.sub(
        r'local OHG_TRUNK_PENALTY\s*=\s*[\d.]+',
        f'local OHG_TRUNK_PENALTY    = {values["trunk_penalty"]}',
        content,
    )
    content = re.sub(
        r'local OHG_PRIMARY_PENALTY\s*=\s*[\d.]+',
        f'local OHG_PRIMARY_PENALTY  = {values["primary_penalty"]}',
        content,
    )
    content = re.sub(
        r'local OHG_SECONDARY_FACTOR\s*=\s*[\d.]+',
        f'local OHG_SECONDARY_FACTOR = {values["secondary_factor"]}',
        content,
    )

    LUA_PATH.write_text(content, encoding="utf-8")
    print(f"[OK] foot.lua 更新完了: {values}")


def run_cmd(cmd: list[str]) -> None:
    print(f"[RUN] {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.returncode != 0:
        print(f"[ERROR] {result.stderr}", file=sys.stderr)
        sys.exit(1)
    print("[OK] 完了")


def run_osrm_rebuild() -> None:
    run_cmd([
        "docker", "exec", CONTAINER,
        "osrm-extract", "--threads", "2", "-p", "/opt/foot.lua", PBF_PATH,
    ])
    run_cmd([
        "docker", "exec", CONTAINER,
        "osrm-partition", "--threads", "2", OSRM_PATH,
    ])
    run_cmd([
        "docker", "exec", CONTAINER,
        "osrm-customize", "--threads", "2", OSRM_PATH,
    ])

    print("[RUN] docker restart " + CONTAINER)
    subprocess.run(["docker", "restart", CONTAINER], check=True)
    print("[OK] OSRMコンテナ再起動完了")


if __name__ == "__main__":
    values = get_config_values()
    print(f"[INFO] 設定値: {values}")
    update_foot_lua(values)
    run_osrm_rebuild()
