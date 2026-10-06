"""
runtime_dataset_validate の GeoJSON ストリーミング検証（RUNTIME-VALIDATE-STREAMING）。

VPS（RAM 3.9GB・swap 枯渇）で publish 時に flood routing（254MB, json.load で RSS 約 2GB）や
前 version の flood canonical（524MB）を全量展開しないよう、top-level FeatureCollection の
.geojson は ijson でストリーミングする。検証内容（構文・schema・必須キー・型・値域・件数）は
従来の json.load 経路と同一であることを固定する。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services import runtime_dataset_validate as rdv  # noqa: E402
from app.services.runtime_atomic import RuntimeAtomicError  # noqa: E402

KEYS = frozenset({"flood_rank"})
TYPES = {"flood_rank": (int,)}
RANGES = {"flood_rank": (1, 5)}


def _feat(rank=2, nested=True):
    props = {"flood_rank": rank}
    if nested:
        props["extra"] = {"a": [1, 2, {"b": None}], "c": "x"}
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "Polygon",
                         "coordinates": [[[139.0, 35.0], [139.1, 35.0], [139.1, 35.1], [139.0, 35.0]]]}}


def _write(tmp_path, obj, name="x.geojson"):
    p = tmp_path / name
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")
    return p


def test_feature_collection_validated_without_json_load(tmp_path):
    p = _write(tmp_path, {"type": "FeatureCollection", "name": "n", "features": [_feat() for _ in range(5)]})
    with patch.object(rdv.json, "load", side_effect=AssertionError("json.load を使ってはいけない")):
        assert rdv._validate_json_file(p, True, KEYS, TYPES, RANGES) == 5
        assert rdv._count_features_in_file(p) == 5


def test_type_key_after_features_is_accepted(tmp_path):
    p = _write(tmp_path, '{"features": [' + json.dumps(_feat()) + '], "type": "FeatureCollection"}')
    assert rdv._validate_json_file(p, True, KEYS, TYPES, RANGES) == 1
    assert rdv._count_features_in_file(p) == 1


@pytest.mark.parametrize("rank,match", [
    ("2", "型"), (2.0, "型"), (9, "値域"), (True, "型"),
])
def test_property_type_and_range_checks_unchanged(tmp_path, rank, match):
    p = _write(tmp_path, {"type": "FeatureCollection", "features": [_feat(), _feat(rank=rank)]})
    with pytest.raises(RuntimeAtomicError):
        rdv._validate_json_file(p, True, KEYS, TYPES, RANGES)


def test_missing_required_key_rejected(tmp_path):
    f = _feat()
    del f["properties"]["flood_rank"]
    p = _write(tmp_path, {"type": "FeatureCollection", "features": [f]})
    with pytest.raises(RuntimeAtomicError):
        rdv._validate_json_file(p, True, KEYS, TYPES, RANGES)


@pytest.mark.parametrize("text,match", [
    ('{"type":"FeatureCollection","features":[', "不正なJSON構文"),
    ("", "不正なJSON構文"),
    ("[1,2]", "top-levelがobjectでない"),
    ('{"type":"FeatureCollection"}', "features配列がない"),
    ('{"type":"FeatureCollection","features":{}}', "features配列がない"),
    ('{"type":"FeatureCollection","features":[1]}', "Feature"),
    ('{"type":"Nope","features":[]}', "top-level type"),
    ('{"type":"FeatureCollection","features":[]} trailing', "不正なJSON構文"),
])
def test_invalid_inputs_rejected(tmp_path, text, match):
    p = _write(tmp_path, text)
    with pytest.raises(RuntimeAtomicError, match=match):
        rdv._validate_json_file(p, True, KEYS, TYPES, RANGES)


def test_single_feature_and_geometry_still_supported(tmp_path):
    assert rdv._validate_json_file(_write(tmp_path, _feat(), "f.geojson"), True, KEYS, TYPES, RANGES) == 1
    geom = _write(tmp_path, {"type": "Point", "coordinates": [139.0, 35.0]}, "g.geojson")
    assert rdv._validate_json_file(geom, True) == 1
    with pytest.raises(RuntimeAtomicError, match="素のgeometry"):
        rdv._validate_json_file(geom, True, KEYS, TYPES, RANGES)


def test_count_matches_json_load_semantics(tmp_path):
    fc = {"type": "FeatureCollection", "features": [_feat() for _ in range(13)]}
    p = _write(tmp_path, fc)
    assert rdv._count_features_in_file(p) == len(fc["features"]) == 13
    assert rdv._count_features_in_file(_write(tmp_path, _feat(), "one.geojson")) == 1
    assert rdv._count_features_in_file(_write(tmp_path, "{broken", "bad.geojson")) == 0
    assert rdv._count_features_in_file(_write(tmp_path, {"type": "FeatureCollection"}, "nof.geojson")) == 0


def test_non_schema_json_still_uses_json_load(tmp_path):
    p = _write(tmp_path, {"anything": [1, 2]}, "meta.json")
    assert rdv._validate_json_file(p, False) == 0
    with pytest.raises(RuntimeAtomicError, match="不正なJSON構文"):
        rdv._validate_json_file(_write(tmp_path, "{", "bad.json"), False)
