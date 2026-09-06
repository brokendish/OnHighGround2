"""
test_resolve_hazard_sources_dry_run.py — Dual Storage Remediation Phase C1
ローカルdry-run（OWNER Section 15）。

実際のVPS/本番data_lake（27MB+）を使わず、ローカルfixtureで
storm_surge/flood/pseudo_inland_flood（tokyo+kanagawa）を一括解決し、
resolve_hazard_sources.pyの出力から、deploy_to_runtime.shが実際に構築する
staging先パス（backend/hazard/{layer_type}/{region}/{basename}）を
シミュレートして、Phase C1が意図するversioned構造と一致することを検証する。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts" / "publish" / "resolve_hazard_sources.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("resolve_hazard_sources_dry_run", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_module()


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


def _simulate_staging_dest(runtime_backend: Path, layer_type: str, region: str, src_path: Path) -> Path:
    """deploy_to_runtime.shの新blockが構築するdestinationを再現する
    （`${RUNTIME_BACKEND}/hazard/${_hz_layer_type}/${REGION}/$(basename src)`）。"""
    return runtime_backend / "hazard" / layer_type / region / src_path.name


def test_dry_run_produces_expected_staging_layout_for_all_three_gap_types(tmp_path):
    from app.services.dataset_definition_service import DatasetDefinitionService
    from app.services.dataset_state_service import DatasetStateService
    from app.services.active_mapping_service import ActiveMappingService

    # ── fixture: tokyo+kanagawaのflood/storm_surge、tokyoのみのpseudo_inland_flood ──
    fixtures = {
        ("flood", "tokyo"): ("TOKYO-RIVER-001", "tokyo-river-001.geojson"),
        ("flood", "kanagawa"): ("KANAGAWA-RIVER-001", "kanagawa-river-001.geojson"),
        ("storm_surge", "tokyo"): ("TOKYO-SURGE-001", "tokyo-surge-001.geojson"),
        ("storm_surge", "kanagawa"): ("KANAGAWA-SURGE-001", "kanagawa-surge-001.geojson"),
        ("pseudo_inland_flood", "tokyo"): ("TOKYO-PSEUDO-INLAND-FLOOD-001", "pseudo_inland_flood.geojson"),
        # pseudo_inland_flood:kanagawa は意図的に未登録（registryにactive mappingなし）
    }

    definitions = []
    mappings: dict[str, str] = {}
    src_paths: dict[tuple[str, str], Path] = {}

    for (layer_type, region), (dataset_id, basename) in fixtures.items():
        validated_dir = tmp_path / "validated" / region / layer_type
        validated_dir.mkdir(parents=True)
        src_file = validated_dir / basename
        src_file.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")
        src_paths[(layer_type, region)] = src_file

        definitions.append(_base_defn(
            dataset_id=dataset_id, region=region, layer_type=layer_type,
            validated_storage_path=str(validated_dir),
            runtime_path=f"data_runtime/backend/hazard/{layer_type}",
        ))
        mappings[f"{layer_type}:{region}"] = dataset_id

    definitions_path = tmp_path / "dataset_definitions.json"
    definitions_path.write_text(json.dumps(definitions), encoding="utf-8")
    mappings_path = tmp_path / "active_mappings.json"
    mappings_path.write_text(json.dumps(mappings), encoding="utf-8")

    definition_service = DatasetDefinitionService(definitions_path=definitions_path)
    state_service = DatasetStateService(state_dir=tmp_path / "state", history_dir=tmp_path / "history")
    mapping_service = ActiveMappingService(mappings_path=mappings_path)

    runtime_backend = tmp_path / "staging" / "backend"
    staged: list[tuple[str, str, Path, Path]] = []

    for region in ("tokyo", "kanagawa"):
        argv = [
            "resolve_hazard_sources.py", "--region", region,
            "--layer-type", "flood", "--layer-type", "storm_surge",
            "--layer-type", "pseudo_inland_flood",
        ]
        with patch.object(sys, "argv", argv), \
             patch.object(mod, "get_definition_service", return_value=definition_service), \
             patch.object(mod, "get_state_service", return_value=state_service), \
             patch.object(mod, "get_active_mapping_service", return_value=mapping_service), \
             patch("builtins.print") as mock_print:
            rc = mod.main()
            assert rc == 0, f"dry-run resolver failed for region={region}"

        for call in mock_print.call_args_list:
            args = call.args
            if not args or "\t" not in args[0]:
                continue
            layer_type, dataset_id, src_path_str = args[0].split("\t")
            src_path = Path(src_path_str)
            dest = _simulate_staging_dest(runtime_backend, layer_type, region, src_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src_path.read_bytes())
            staged.append((layer_type, region, src_path, dest))

    staged_keys = {(lt, region) for lt, region, _, _ in staged}

    # 5件（pseudo_inland_flood:kanagawaを除く全組み合わせ）がstagingされること
    assert staged_keys == {
        ("flood", "tokyo"), ("flood", "kanagawa"),
        ("storm_surge", "tokyo"), ("storm_surge", "kanagawa"),
        ("pseudo_inland_flood", "tokyo"),
    }

    # pseudo_inland_flood:kanagawaは強制生成されていないこと
    assert not (runtime_backend / "hazard" / "pseudo_inland_flood" / "kanagawa").exists()

    # 各stagingファイルが期待する versioned 構造（hazard/{type}/{region}/{file}）と
    # 内容一致であること
    for layer_type, region, src_path, dest in staged:
        expected_dest = runtime_backend / "hazard" / layer_type / region / src_path.name
        assert dest == expected_dest
        assert dest.read_bytes() == src_path.read_bytes()

    # 旧underscore命名は一切staging先に登場しないこと（naming drift regression）
    all_dest_names = {dest.name for _, _, _, dest in staged}
    assert not any(name.endswith("_storm_surge.geojson") for name in all_dest_names)
    assert not any(name.endswith("_flood_check.geojsonl") for name in all_dest_names)
