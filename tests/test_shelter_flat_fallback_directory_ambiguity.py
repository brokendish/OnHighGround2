"""
test_shelter_flat_fallback_directory_ambiguity.py —
SHELTER-FLAT-FALLBACK-DIRECTORY-AMBIGUITY 回帰テスト。

OWNER決定（2026-09-07）: `ShelterRegistry._resolve_paths()`は、
`state.current_runtime_path`が未設定/消失している場合に
`defn.runtime_path`（複数datasetが共有しうるflat directoryそのもの）を
そのままload対象へ追加していた。これは、同じdirectory配下に同居する
`tokyo_shelter.geojson`（legacy, SHELTER-FLAT-LEGACY-DUPLICATE）や
`*.backup.geojson`まで巻き込みうる、directory-driven selectorだった。

修復後は、`state.current_validated_path`のbasenameから期待されるactive
fileを一意に組み立て（`_infer_state_from_filesystem()`のcopy_fileモード
ロジックと同じ橋渡し方式）、その具体fileが実在する場合のみ採用する。
組み立てたfileが存在しなければdirectory全体へfallbackせず、そのdataset
をskipする（fail-closed、per-dataset）。

このテストは`app_public.py`をimportせず（起動時副作用を避ける——
HAZARD-ENGINE-LARGE-DATASET-MEMORY-BLOCKER remediation時の教訓）、
`shelter_service.py`（module-level副作用なし）のみを直接importし、
active_mapping_service/dataset_definition_service/dataset_state_service
の3つの遅延importをsys.modulesスタブで差し替えて、実ファイルシステム
（tmp_path）上の挙動を検証する。
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services import shelter_service  # noqa: E402


class _FakeDefn:
    def __init__(self, dataset_id: str, runtime_path: str) -> None:
        self.dataset_id = dataset_id
        self.runtime_path = runtime_path


class _FakeState:
    def __init__(self, current_runtime_path=None, current_validated_path=None) -> None:
        self.current_runtime_path = current_runtime_path
        self.current_validated_path = current_validated_path


class _FakeActiveMappingService:
    def __init__(self, mappings):
        self._mappings = mappings

    def list_all(self):
        return self._mappings


class _FakeDefinitionService:
    def __init__(self, defns):
        self._defns = defns

    def get(self, dataset_id):
        return self._defns.get(dataset_id)


class _FakeStateService:
    def __init__(self, states):
        self._states = states

    def init_from_definition(self, defn):
        return self._states[defn.dataset_id]


def _install_fakes(monkeypatch, mappings, defns, states):
    am_mod = types.ModuleType("app.services.active_mapping_service")
    am_mod.get_active_mapping_service = lambda: _FakeActiveMappingService(mappings)
    dd_mod = types.ModuleType("app.services.dataset_definition_service")
    dd_mod.get_definition_service = lambda: _FakeDefinitionService(defns)
    ds_mod = types.ModuleType("app.services.dataset_state_service")
    ds_mod.get_state_service = lambda: _FakeStateService(states)

    monkeypatch.setitem(sys.modules, "app.services.active_mapping_service", am_mod)
    monkeypatch.setitem(sys.modules, "app.services.dataset_definition_service", dd_mod)
    monkeypatch.setitem(sys.modules, "app.services.dataset_state_service", ds_mod)


def _make_registry(monkeypatch, tmp_path, mappings, defns, states):
    monkeypatch.setattr(shelter_service, "_PROJECT_ROOT", tmp_path)
    _install_fakes(monkeypatch, mappings, defns, states)
    return shelter_service.ShelterRegistry()


def _write_geojson(path: Path, feature_count: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [139.0 + i * 0.001, 35.0]},
            "properties": {"name": f"shelter-{path.stem}-{i}", "住所": "東京都テスト区"},
        }
        for i in range(feature_count)
    ]
    import json
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )


# ── A. current_runtime_path valid → exact active file だけを使う ─────────────

def test_A_valid_current_runtime_path_resolves_exact_file(monkeypatch, tmp_path):
    active = tmp_path / "data_runtime" / "backend" / "shelters" / "tokyo-shelter-001.geojson"
    _write_geojson(active)

    mappings = [{"layer_type": "evacuation_shelter", "region": "tokyo", "dataset_id": "TOKYO-SHELTER-001"}]
    defns = {"TOKYO-SHELTER-001": _FakeDefn("TOKYO-SHELTER-001", "data_runtime/backend/shelters")}
    states = {"TOKYO-SHELTER-001": _FakeState(current_runtime_path=str(active))}

    registry = _make_registry(monkeypatch, tmp_path, mappings, defns, states)
    paths = registry._resolve_paths()

    assert paths == [active]


# ── B. legacy tokyo_shelter.geojson が同居していても巻き込まれない ────────────

def test_B_legacy_file_coexisting_is_not_swept_in(monkeypatch, tmp_path):
    shelters_dir = tmp_path / "data_runtime" / "backend" / "shelters"
    active = shelters_dir / "tokyo-shelter-001.geojson"
    legacy = shelters_dir / "tokyo_shelter.geojson"
    validated = tmp_path / "data_lake" / "validated" / "tokyo" / "shelters" / "tokyo-shelter-001.geojson"
    _write_geojson(active, feature_count=5)
    _write_geojson(legacy, feature_count=50)  # legacy has MORE features than active
    _write_geojson(validated)

    mappings = [{"layer_type": "evacuation_shelter", "region": "tokyo", "dataset_id": "TOKYO-SHELTER-001"}]
    defns = {"TOKYO-SHELTER-001": _FakeDefn("TOKYO-SHELTER-001", "data_runtime/backend/shelters")}
    # current_runtime_path is missing/None — forces the basename-reconstruction path
    states = {"TOKYO-SHELTER-001": _FakeState(current_runtime_path=None, current_validated_path=str(validated))}

    registry = _make_registry(monkeypatch, tmp_path, mappings, defns, states)
    paths = registry._resolve_paths()

    assert paths == [active]
    assert legacy not in paths


# ── C. サイズの大きいlegacyファイルが「largest file」的に選ばれないこと ───────

def test_C_larger_legacy_file_not_selected_by_size(monkeypatch, tmp_path):
    shelters_dir = tmp_path / "data_runtime" / "backend" / "shelters"
    active = shelters_dir / "tokyo-shelter-001.geojson"
    huge_legacy = shelters_dir / "tokyo_shelter.geojson"
    validated = tmp_path / "data_lake" / "validated" / "tokyo" / "shelters" / "tokyo-shelter-001.geojson"
    _write_geojson(active, feature_count=1)
    _write_geojson(huge_legacy, feature_count=500)
    _write_geojson(validated)

    mappings = [{"layer_type": "evacuation_shelter", "region": "tokyo", "dataset_id": "TOKYO-SHELTER-001"}]
    defns = {"TOKYO-SHELTER-001": _FakeDefn("TOKYO-SHELTER-001", "data_runtime/backend/shelters")}
    states = {"TOKYO-SHELTER-001": _FakeState(current_runtime_path=None, current_validated_path=str(validated))}

    registry = _make_registry(monkeypatch, tmp_path, mappings, defns, states)
    paths = registry._resolve_paths()

    assert paths == [active]
    assert huge_legacy not in paths


# ── D. backupファイルが選ばれないこと（current_runtime_pathがbackupを指す異常系込み）──

def test_D_backup_artifact_never_selected(monkeypatch, tmp_path):
    shelters_dir = tmp_path / "data_runtime" / "backend" / "shelters"
    active = shelters_dir / "tokyo-shelter-001.geojson"
    backup = shelters_dir / "tokyo-shelter-001.backup.geojson"
    validated = tmp_path / "data_lake" / "validated" / "tokyo" / "shelters" / "tokyo-shelter-001.geojson"
    _write_geojson(active)
    _write_geojson(backup)
    _write_geojson(validated)

    mappings = [{"layer_type": "evacuation_shelter", "region": "tokyo", "dataset_id": "TOKYO-SHELTER-001"}]
    defns = {"TOKYO-SHELTER-001": _FakeDefn("TOKYO-SHELTER-001", "data_runtime/backend/shelters")}

    # D1: current_runtime_path erroneously points at the backup file
    states = {"TOKYO-SHELTER-001": _FakeState(current_runtime_path=str(backup), current_validated_path=str(validated))}
    registry = _make_registry(monkeypatch, tmp_path, mappings, defns, states)
    paths = registry._resolve_paths()
    assert paths == [active]
    assert backup not in paths

    # D2: current_runtime_path missing entirely, basename reconstruction must not pick backup
    states2 = {"TOKYO-SHELTER-001": _FakeState(current_runtime_path=None, current_validated_path=str(validated))}
    registry2 = _make_registry(monkeypatch, tmp_path, mappings, defns, states2)
    paths2 = registry2._resolve_paths()
    assert paths2 == [active]
    assert backup not in paths2


def test_D_is_backup_artifact_unit():
    assert shelter_service.ShelterRegistry._is_backup_artifact(Path("tokyo-shelter-001.backup.geojson"))
    assert shelter_service.ShelterRegistry._is_backup_artifact(Path("x.backup.csv"))
    assert not shelter_service.ShelterRegistry._is_backup_artifact(Path("tokyo-shelter-001.geojson"))
    assert not shelter_service.ShelterRegistry._is_backup_artifact(Path("tokyo_shelter.geojson"))


# ── E. current_runtime_path欠落・組み立てたfileも不在 → skip（directory全体へfallbackしない）──

def test_E_unresolvable_dataset_is_skipped_not_directory_fallback(monkeypatch, tmp_path):
    shelters_dir = tmp_path / "data_runtime" / "backend" / "shelters"
    legacy = shelters_dir / "tokyo_shelter.geojson"
    _write_geojson(legacy)  # only the legacy file exists in the shared dir
    validated = tmp_path / "data_lake" / "validated" / "tokyo" / "shelters" / "tokyo-shelter-001.geojson"
    _write_geojson(validated)  # validated exists but was never deployed to runtime

    mappings = [{"layer_type": "evacuation_shelter", "region": "tokyo", "dataset_id": "TOKYO-SHELTER-001"}]
    defns = {"TOKYO-SHELTER-001": _FakeDefn("TOKYO-SHELTER-001", "data_runtime/backend/shelters")}
    states = {"TOKYO-SHELTER-001": _FakeState(current_runtime_path=None, current_validated_path=str(validated))}

    registry = _make_registry(monkeypatch, tmp_path, mappings, defns, states)
    paths = registry._resolve_paths()

    # Per-dataset resolution fails closed: the shared directory (and its legacy
    # file) must never be appended as a substitute.
    assert shelters_dir not in paths
    assert legacy not in paths
    assert paths == []


def test_E_no_validated_artifact_known_is_also_skipped(monkeypatch, tmp_path):
    shelters_dir = tmp_path / "data_runtime" / "backend" / "shelters"
    legacy = shelters_dir / "tokyo_shelter.geojson"
    _write_geojson(legacy)

    mappings = [{"layer_type": "evacuation_shelter", "region": "tokyo", "dataset_id": "TOKYO-SHELTER-001"}]
    defns = {"TOKYO-SHELTER-001": _FakeDefn("TOKYO-SHELTER-001", "data_runtime/backend/shelters")}
    states = {"TOKYO-SHELTER-001": _FakeState(current_runtime_path=None, current_validated_path=None)}

    registry = _make_registry(monkeypatch, tmp_path, mappings, defns, states)
    paths = registry._resolve_paths()

    assert paths == []


# ── F. 複数datasetが同じdirectoryを共有していても互いを巻き込まない ──────────

def test_F_multi_dataset_isolation_in_shared_directory(monkeypatch, tmp_path):
    shelters_dir = tmp_path / "data_runtime" / "backend" / "shelters"
    tokyo_active = shelters_dir / "tokyo-shelter-001.geojson"
    kanagawa_active = shelters_dir / "kanagawa" / "kanagawa-shelter-001.geojson"
    legacy = shelters_dir / "tokyo_shelter.geojson"
    tokyo_validated = tmp_path / "data_lake" / "validated" / "tokyo" / "shelters" / "tokyo-shelter-001.geojson"
    _write_geojson(tokyo_active)
    _write_geojson(kanagawa_active)
    _write_geojson(legacy)
    _write_geojson(tokyo_validated)

    mappings = [
        {"layer_type": "evacuation_shelter", "region": "tokyo", "dataset_id": "TOKYO-SHELTER-001"},
        {"layer_type": "emergency_shelter", "region": "kanagawa", "dataset_id": "KANAGAWA-SHELTER-001"},
    ]
    defns = {
        "TOKYO-SHELTER-001": _FakeDefn("TOKYO-SHELTER-001", "data_runtime/backend/shelters"),
        "KANAGAWA-SHELTER-001": _FakeDefn("KANAGAWA-SHELTER-001", "data_runtime/backend/shelters/kanagawa"),
    }
    states = {
        # Tokyo: current_runtime_path missing, resolved via validated basename
        "TOKYO-SHELTER-001": _FakeState(current_runtime_path=None, current_validated_path=str(tokyo_validated)),
        # Kanagawa: current_runtime_path valid
        "KANAGAWA-SHELTER-001": _FakeState(current_runtime_path=str(kanagawa_active)),
    }

    registry = _make_registry(monkeypatch, tmp_path, mappings, defns, states)
    paths = registry._resolve_paths()

    assert set(paths) == {tokyo_active, kanagawa_active}
    assert legacy not in paths
    assert shelters_dir not in paths


# ── G. current/versioned primary経路（atomic publish）は無傷 ─────────────────

def test_G_atomic_publish_primary_path_unmodified():
    """_try_load_from_atomic_publish()のcore logicに手を加えていないことを、
    主要な識別子（leased_version_root使用、backend/shelters・
    backend/emergency_shelters探索、_AtomicStateCorrupted変換）の
    静的存在確認で軽く保証する。"""
    import inspect
    src = inspect.getsource(shelter_service.ShelterRegistry._try_load_from_atomic_publish)
    assert "leased_version_root" in src
    assert '"shelters"' in src and '"emergency_shelters"' in src
    assert "_AtomicStateCorrupted" in src


# ── H. dedup契約（10,285 serving count semantics）は無傷 ─────────────────────

def test_H_dedup_contract_unchanged(tmp_path):
    """load_emergency_shelters_from_geojsonのdedup key
    (name, round(lat,7), round(lon,7), designation) が変更されていないことを、
    2件の完全重複featureを与えて1件に収束することで確認する。"""
    import json
    path = tmp_path / "dup.geojson"
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [139.7671, 35.6812]},
            "properties": {"施設・場所名": "テスト避難所", "住所": "東京都千代田区", "指定区分": "指定避難所"},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [139.7671, 35.6812]},
            "properties": {"施設・場所名": "テスト避難所", "住所": "東京都千代田区", "指定区分": "指定避難所"},
        },
    ]
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False), encoding="utf-8")

    shelters = []
    seen = set()
    shelter_service.load_emergency_shelters_from_geojson(path, shelters, seen)
    assert len(shelters) == 1
