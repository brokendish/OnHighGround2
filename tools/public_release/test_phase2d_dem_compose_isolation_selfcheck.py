"""
test_phase2d_dem_compose_isolation_selfcheck.py — demo Composeの DEM mount
静的構造検証（Phase 2-D Round 9、指示書第6節）。

`docker-compose.demo.yml`の backend-public serviceが、synthetic DEM
fixtureを既存loaderの期待path（`/data_runtime/backend/elevation/
elevation.tif`）へread-onlyでmountしており、production DEMや
production volume/network名を一切参照しないことを、`docker compose
config`の実測出力から静的に確認する。

実行:
    venv/bin/python -m pytest tools/public_release/test_phase2d_dem_compose_isolation_selfcheck.py -v
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEM_MOUNT_TARGET = "/data_runtime/backend/elevation/elevation.tif"
DEM_FIXTURE_SOURCE = "./tests/fixtures/dem_demo/elevation_demo.tif"


class _ComposeOverrideLoader(yaml.SafeLoader):
    pass


def _override_constructor(loader: yaml.Loader, node: yaml.Node):
    return loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode) else loader.construct_mapping(node)


_ComposeOverrideLoader.add_constructor("!override", _override_constructor)


def _load_demo_compose() -> dict:
    text = (REPO_ROOT / "docker-compose.demo.yml").read_text(encoding="utf-8")
    return yaml.load(text, Loader=_ComposeOverrideLoader)


def _dem_mount_entries() -> list[str]:
    compose = _load_demo_compose()
    volumes = compose["services"]["backend-public"]["volumes"]
    return [v for v in volumes if DEM_MOUNT_TARGET in v]


# ---------------------------------------------------------------------------
# 1. 合成DEM fixtureが既存loaderの期待path(/data_runtime/backend/elevation/
#    elevation.tif)へ、read-onlyでmountされている
# ---------------------------------------------------------------------------

def test_01_dem_fixture_mounted_at_expected_path_read_only():
    entries = _dem_mount_entries()
    assert len(entries) == 1, entries
    entry = entries[0]
    assert entry.startswith(DEM_FIXTURE_SOURCE), entry
    assert entry.endswith(":ro"), entry


# ---------------------------------------------------------------------------
# 2. production DEM（data_lake/validated配下等）を参照していない
# ---------------------------------------------------------------------------

def test_02_no_production_dem_source_referenced():
    compose = _load_demo_compose()
    volumes = compose["services"]["backend-public"]["volumes"]
    forbidden_tokens = ["data_lake/validated/tokyo/dem", "data_lake/raw/tokyo/dem"]
    for v in volumes:
        for token in forbidden_tokens:
            assert token not in v, v


# ---------------------------------------------------------------------------
# 3. DEM mountはread-write（:rwや無指定でのdefault rw）ではない
# ---------------------------------------------------------------------------

def test_03_dem_mount_is_not_writable():
    entries = _dem_mount_entries()
    for entry in entries:
        assert not entry.endswith(":rw"), entry


# ---------------------------------------------------------------------------
# 4. production container_name/network/volume名が resolved compose に
#    残っていない（Round 6/7/8で確立した既存gateの回帰確認、Round 9で
#    新規追加したvolume entryにも production名が混入していないこと）
# ---------------------------------------------------------------------------

def test_04_no_production_names_leak_into_new_dem_mount():
    entries = _dem_mount_entries()
    for entry in entries:
        assert "evacuation-navi" not in entry, entry


# ---------------------------------------------------------------------------
# 5. Martin demo config mount（Round 6由来）・OSRM read-only source /
#    output volume分離（Round 8由来）が本Round変更後も維持されている
# ---------------------------------------------------------------------------

def test_05_martin_and_osrm_isolation_still_intact():
    compose = _load_demo_compose()
    martin_volumes = compose["services"]["martin"]["volumes"]
    assert any("config/martin.demo.yaml" in v for v in martin_volumes)

    osrm_driving_volumes = compose["services"]["osrm-driving"]["volumes"]
    assert any(
        "tests/fixtures/osm_demo/validated" in v and v.endswith(":ro")
        for v in osrm_driving_volumes
    )
    assert any(v.startswith("osrm-driving-work:") for v in osrm_driving_volumes)
