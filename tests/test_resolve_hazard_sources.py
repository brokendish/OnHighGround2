"""
test_resolve_hazard_sources.py — Dual Storage Remediation Phase C1
(ATOMIC-PUBLISH-COVERAGE-GAP) テスト。

scripts/publish/resolve_hazard_sources.py が、resolve_shelter_sources.py
と同じ設計思想（registryを正本とした動的解決）でstorm_surge/flood/
pseudo_inland_flood のvalidated artifactを解決することを検証する。

重点:
  - 旧underscore命名（{region}_storm_surge.geojson等）に一切依存せず、
    hyphen/registry命名（{region}-surge-001.geojson等）のみが存在する
    fixtureでも正しく解決できること（naming drift regression）。
  - pseudo_inland_flood/kanagawa のような「registryにactive mappingが
    存在しないregion」は明示的にunsupported（出力に含まれない）であり、
    無理に生成しないこと。
  - active mappingがあるのにvalidated artifactが解決できない場合は
    fail-closed（非ゼロexit、部分出力なし）になること（silent skip禁止）。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts" / "publish" / "resolve_hazard_sources.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("resolve_hazard_sources", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_module()


def _build_services(tmp_path, mappings: dict[str, str], definitions: list[dict]):
    import json
    from app.services.dataset_definition_service import DatasetDefinitionService
    from app.services.dataset_state_service import DatasetStateService
    from app.services.active_mapping_service import ActiveMappingService

    definitions_path = tmp_path / "dataset_definitions.json"
    definitions_path.write_text(json.dumps(definitions), encoding="utf-8")

    mappings_path = tmp_path / "active_mappings.json"
    mappings_path.write_text(json.dumps(mappings), encoding="utf-8")

    definition_service = DatasetDefinitionService(definitions_path=definitions_path)
    state_service = DatasetStateService(state_dir=tmp_path / "state", history_dir=tmp_path / "history")
    mapping_service = ActiveMappingService(mappings_path=mappings_path)
    return definition_service, state_service, mapping_service


def _base_defn(**overrides) -> dict:
    base = dict(
        region="tokyo",
        category="hazard",
        display_name="test",
        description="test",
        hint_text="test",
        impact_scope="test",
        accepted_input_modes=[],
        accepted_extensions=[],
        max_browser_upload_mb=0,
        requires_normalize=False,
        requires_validation=True,
        requires_deploy=True,
        requires_osrm_rebuild=False,
        raw_storage_path="data_lake/raw/test",
        runtime_path="data_runtime/backend/hazard/test",
        deploy_mode="copy_file",
    )
    base.update(overrides)
    return base


def _run_resolver(tmp_path, region: str, layer_types: list[str], mappings, definitions):
    definition_service, state_service, mapping_service = _build_services(tmp_path, mappings, definitions)

    argv = ["resolve_hazard_sources.py", "--region", region]
    for lt in layer_types:
        argv += ["--layer-type", lt]

    with patch.object(sys, "argv", argv), \
         patch.object(mod, "get_definition_service", return_value=definition_service), \
         patch.object(mod, "get_state_service", return_value=state_service), \
         patch.object(mod, "get_active_mapping_service", return_value=mapping_service):
        return mod.main()


# ── A. storm_surge: registry source解決、hyphen命名のみで成功（naming drift回帰） ──

def test_storm_surge_resolves_with_hyphen_naming_only(tmp_path, capsys):
    validated_dir = tmp_path / "validated" / "tokyo" / "storm_surge"
    validated_dir.mkdir(parents=True)
    # 旧underscore命名ファイルは一切作らない（naming drift regressionの核心）
    hyphen_file = validated_dir / "tokyo-surge-001.geojson"
    hyphen_file.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")

    definitions = [_base_defn(
        dataset_id="TOKYO-SURGE-001", layer_type="storm_surge",
        validated_storage_path=str(validated_dir),
        runtime_path="data_runtime/backend/hazard/storm_surge",
    )]
    mappings = {"storm_surge:tokyo": "TOKYO-SURGE-001"}

    rc = _run_resolver(tmp_path, "tokyo", ["storm_surge", "flood", "pseudo_inland_flood"], mappings, definitions)

    assert rc == 0
    out = capsys.readouterr().out
    lines = [l for l in out.splitlines() if l]
    assert len(lines) == 1
    layer_type, dataset_id, path = lines[0].split("\t")
    assert layer_type == "storm_surge"
    assert dataset_id == "TOKYO-SURGE-001"
    assert path == str(hyphen_file)
    assert "_storm_surge.geojson" not in path  # 旧命名は一切使われない


# ── B. flood: canonical ではなく検証済み routing artifact を解決 ───────────────
# canonical / routing 分離契約（docs/architecture/flood_canonical_routing_split.md）。
# HazardEngine に canonical が渡る経路を resolver で断つ。

def write_flood_routing_fixture(canonical, dataset_id: str = "TOKYO-RIVER-001"):
    """canonical に対応する routing artifact と meta（契約を満たす）を作る。"""
    import json
    from app.services import flood_routing_contract as frc

    routing, meta_path = frc.routing_paths_for_canonical(canonical)
    routing.parent.mkdir(parents=True, exist_ok=True)
    routing.write_text('{"type": "FeatureCollection", "features": [{"r": 1}]}', encoding="utf-8")
    meta_path.write_text(json.dumps({
        "contract": frc.CONTRACT_VERSION, "dataset_id": dataset_id,
        "source_canonical_path": str(canonical),
        "source_canonical_sha256": frc.sha256_file(canonical),
        "routing_artifact_sha256": frc.sha256_file(routing),
        "builder_name": frc.BUILDER_NAME, "builder_version": "1.0.0",
        "tau": 0.85, "min_split_size": 0.0002, "feature_count": 1,
        "generated_at": "2026-10-05T00:00:00Z",
    }), encoding="utf-8")
    return routing


def _flood_fixture(tmp_path):
    validated_dir = tmp_path / "validated" / "tokyo" / "flood"
    validated_dir.mkdir(parents=True)
    canonical = validated_dir / "tokyo-river-001.geojson"
    canonical.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")
    definitions = [_base_defn(
        dataset_id="TOKYO-RIVER-001", layer_type="flood",
        validated_storage_path=str(validated_dir),
        runtime_path="data_runtime/backend/hazard/flood",
    )]
    return canonical, definitions, {"flood:tokyo": "TOKYO-RIVER-001"}


def test_flood_resolves_routing_artifact_not_canonical(tmp_path, capsys):
    canonical, definitions, mappings = _flood_fixture(tmp_path)
    routing = write_flood_routing_fixture(canonical)

    rc = _run_resolver(tmp_path, "tokyo", ["storm_surge", "flood", "pseudo_inland_flood"], mappings, definitions)

    assert rc == 0
    out = capsys.readouterr().out
    layer_type, dataset_id, path = out.strip().split("\t")
    assert layer_type == "flood"
    assert path == str(routing)
    assert path.endswith(".routing.geojson")
    assert routing == tmp_path / "derived" / "tokyo" / "flood" / "tokyo-river-001.routing.geojson"


def test_flood_routing_missing_fails_closed(tmp_path, capsys):
    _canonical, definitions, mappings = _flood_fixture(tmp_path)  # routing を作らない

    rc = _run_resolver(tmp_path, "tokyo", ["flood"], mappings, definitions)

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "routing artifact が存在しません" in captured.err


def test_flood_canonical_sha_mismatch_fails_closed(tmp_path, capsys):
    canonical, definitions, mappings = _flood_fixture(tmp_path)
    write_flood_routing_fixture(canonical)
    canonical.write_text('{"type": "FeatureCollection", "features": [{"new": 1}]}', encoding="utf-8")

    rc = _run_resolver(tmp_path, "tokyo", ["flood"], mappings, definitions)

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "canonical sha256" in captured.err


def test_flood_failure_does_not_change_other_types_contract(tmp_path, capsys):
    """他 hazard type は従来どおり validated artifact を解決する（flood だけが routing）。"""
    canonical, definitions, mappings = _flood_fixture(tmp_path)
    routing = write_flood_routing_fixture(canonical)
    surge_dir = tmp_path / "validated" / "tokyo" / "storm_surge"
    surge_dir.mkdir(parents=True)
    surge = surge_dir / "tokyo-surge-001.geojson"
    surge.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")
    definitions.append(_base_defn(
        dataset_id="TOKYO-SURGE-001", layer_type="storm_surge",
        validated_storage_path=str(surge_dir),
        runtime_path="data_runtime/backend/hazard/storm_surge",
    ))
    mappings["storm_surge:tokyo"] = "TOKYO-SURGE-001"

    rc = _run_resolver(tmp_path, "tokyo", ["storm_surge", "flood"], mappings, definitions)

    assert rc == 0
    lines = dict(
        (l.split("\t")[0], l.split("\t")[2]) for l in capsys.readouterr().out.splitlines() if l
    )
    assert lines == {"flood": str(routing), "storm_surge": str(surge)}


# ── C. pseudo_inland_flood: tokyo publish対象、kanagawa unsupported ───────────

def test_pseudo_inland_flood_tokyo_resolves_kanagawa_unsupported(tmp_path, capsys):
    validated_dir = tmp_path / "validated" / "tokyo" / "pseudo_inland_flood"
    validated_dir.mkdir(parents=True)
    src_file = validated_dir / "pseudo_inland_flood.geojson"
    src_file.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")

    definitions = [_base_defn(
        dataset_id="TOKYO-PSEUDO-INLAND-FLOOD-001", layer_type="pseudo_inland_flood",
        validated_storage_path=str(validated_dir),
        runtime_path="data_runtime/backend/hazard/pseudo_inland_flood",
    )]
    # kanagawa向けactive mappingは意図的に登録しない（unsupported region）
    mappings = {"pseudo_inland_flood:tokyo": "TOKYO-PSEUDO-INLAND-FLOOD-001"}

    rc_tokyo = _run_resolver(tmp_path, "tokyo", ["storm_surge", "flood", "pseudo_inland_flood"], mappings, definitions)
    out_tokyo = capsys.readouterr().out
    assert rc_tokyo == 0
    layer_type, dataset_id, path = out_tokyo.strip().split("\t")
    assert layer_type == "pseudo_inland_flood"
    assert path == str(src_file)

    rc_kanagawa = _run_resolver(tmp_path, "kanagawa", ["storm_surge", "flood", "pseudo_inland_flood"], mappings, definitions)
    out_kanagawa = capsys.readouterr().out
    assert rc_kanagawa == 0  # unsupported regionはFAILではなく単に0件
    assert out_kanagawa.strip() == ""


# ── D. Silent skip禁止: activeだがsource未解決 → fail-closed、部分出力なし ────

def test_active_mapping_without_resolvable_source_fails_closed(tmp_path, capsys):
    # validated_storage_pathを実在しないdirectoryにする（source未配備を模す）
    definitions = [
        _base_defn(
            dataset_id="TOKYO-SURGE-001", layer_type="storm_surge",
            validated_storage_path=str(tmp_path / "nonexistent" / "storm_surge"),
            runtime_path="data_runtime/backend/hazard/storm_surge",
        ),
        _base_defn(
            dataset_id="TOKYO-RIVER-001", layer_type="flood",
            validated_storage_path=str(tmp_path / "does" / "not" / "exist"),
            runtime_path="data_runtime/backend/hazard/flood",
        ),
    ]
    mappings = {"storm_surge:tokyo": "TOKYO-SURGE-001", "flood:tokyo": "TOKYO-RIVER-001"}

    rc = _run_resolver(tmp_path, "tokyo", ["storm_surge", "flood", "pseudo_inland_flood"], mappings, definitions)

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # 部分出力が無いこと（all-or-nothing）
    assert "FAIL" in captured.err


def test_unresolvable_dataset_definition_also_fails_closed(tmp_path, capsys):
    """active_mappingsが指すdataset_idがregistryに存在しない場合もfail-closed。"""
    definitions: list[dict] = []  # 空のregistry
    mappings = {"storm_surge:tokyo": "TOKYO-SURGE-001"}

    rc = _run_resolver(tmp_path, "tokyo", ["storm_surge"], mappings, definitions)

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""


# ── E. 複数type混在時、1件でも未解決ならすべて失敗（all-or-nothing） ─────────────

def test_partial_failure_blocks_all_output(tmp_path, capsys):
    validated_dir = tmp_path / "validated" / "tokyo" / "storm_surge"
    validated_dir.mkdir(parents=True)
    (validated_dir / "tokyo-surge-001.geojson").write_text("{}", encoding="utf-8")

    definitions = [
        _base_defn(
            dataset_id="TOKYO-SURGE-001", layer_type="storm_surge",
            validated_storage_path=str(validated_dir),
            runtime_path="data_runtime/backend/hazard/storm_surge",
        ),
        _base_defn(
            dataset_id="TOKYO-RIVER-001", layer_type="flood",
            validated_storage_path=str(tmp_path / "missing"),
            runtime_path="data_runtime/backend/hazard/flood",
        ),
    ]
    mappings = {"storm_surge:tokyo": "TOKYO-SURGE-001", "flood:tokyo": "TOKYO-RIVER-001"}

    rc = _run_resolver(tmp_path, "tokyo", ["storm_surge", "flood"], mappings, definitions)

    assert rc == 1
    # storm_surgeは解決可能だったが、floodが失敗したためstorm_surgeも出力されない
    assert capsys.readouterr().out == ""


# ── F. registry cross-check: 対象外layer_typeは無視される ────────────────────

def test_unrelated_layer_type_is_ignored(tmp_path, capsys):
    validated_dir = tmp_path / "validated" / "tokyo" / "tsunami"
    validated_dir.mkdir(parents=True)
    (validated_dir / "tsunami_tokyo.geojson").write_text("{}", encoding="utf-8")

    definitions = [_base_defn(
        dataset_id="TOKYO-TSUNAMI-001", layer_type="tsunami",
        validated_storage_path=str(validated_dir),
        runtime_path="data_runtime/backend/hazard/tsunami",
    )]
    mappings = {"tsunami:tokyo": "TOKYO-TSUNAMI-001"}

    # tsunamiは対象layer_typeに含めない（既存4typeの挙動を変えないscope）
    rc = _run_resolver(tmp_path, "tokyo", ["storm_surge", "flood", "pseudo_inland_flood"], mappings, definitions)

    assert rc == 0
    assert capsys.readouterr().out.strip() == ""
