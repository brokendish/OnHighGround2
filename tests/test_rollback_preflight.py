"""
REQUIRED-TILE-ROLLBACK-GUARD: rollback 先 version に表示必須（required）の tile が無ければ、current 切替前に
rollback を拒否する（scripts/publish/rollback_preflight.py・rollback_runtime.sh）。

判定の正は rollback 先 version の manifest と dataset registry の tile 契約だけ。version 名では判定しない。
optional の欠落は WARNING で許可、契約未定義は WARNING（required へ自動昇格しない）、not_applicable は対象外。
registry・manifest が読めない／不正なら FAIL closed。
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rollback_preflight", ROOT / "scripts/publish/rollback_preflight.py")
rpf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rpf)
SCRIPT = ROOT / "scripts/publish/rollback_preflight.py"

PSEUDO = "frontend/tiles/tokyo/pseudo_inland_flood/tokyo_pseudo_inland_flood_001.mbtiles"   # required
SURGE = "frontend/tiles/tokyo/storm_surge/tokyo_surge_001.mbtiles"                          # optional
TSUNAMI = "frontend/tiles/tokyo/tsunami/tokyo_tsunami_A40-23_13.mbtiles"                   # optional（tile_rel_path）
URBAN = "frontend/tiles/tokyo/inland_flood/tokyo_urban_001.mbtiles"                        # 契約を外して unknown にする
ALL = (PSEUDO, SURGE, TSUNAMI, URBAN)


def _registry(tmp: Path, mutate=None) -> Path:
    real = {d["dataset_id"]: d for d in json.loads((ROOT / "data_lake/registry/dataset_definitions.json").read_text(encoding="utf-8"))}
    defs = [copy.deepcopy(real[k]) for k in ("TOKYO-PSEUDO-INLAND-FLOOD-001", "TOKYO-SURGE-001", "TOKYO-TSUNAMI-001",
                                              "TOKYO-LANDSLIDE-001", "TOKYO-URBAN-001")]
    for d in defs:
        if d["dataset_id"] == "TOKYO-URBAN-001":
            d.pop("tile_requirement", None)  # requires_tile_build=true・契約未定義 → unknown
    if mutate:
        mutate(defs)
    p = tmp / "dataset_definitions.json"
    p.write_text(json.dumps(defs, ensure_ascii=False))
    return p


def _version(root: Path, vid: str, rels, tamper=()) -> Path:
    v = root / "versions" / vid
    files = {}
    for rel in rels:
        data = f"tile:{rel}".encode()
        (v / rel).parent.mkdir(parents=True, exist_ok=True)
        (v / rel).write_bytes(b"tampered" if rel in tamper else data)
        files[rel] = hashlib.sha256(data).hexdigest()
    (v / "backend").mkdir(parents=True, exist_ok=True)
    (v / "_manifest.json").write_text(json.dumps({"files": files}))
    return v


def _run(root, vid, reg, *extra):
    return subprocess.run([sys.executable, str(SCRIPT), "--data-runtime-root", str(root), "--version", vid,
                           "--registry", str(reg), *extra], capture_output=True, text=True)


def _by_id(result):
    return {c["dataset_id"]: c for c in result["checks"]}


# ── 1〜5: 判定 ────────────────────────────────────────────────────────────────

def test_required_tile_missing_blocks(tmp_path):
    v = _version(tmp_path, "V", [SURGE, TSUNAMI, URBAN])
    r = rpf.preflight(v, _registry(tmp_path))
    assert r["verdict"] == rpf.UNSAFE and [c["dataset_id"] for c in r["blocked"]] == ["TOKYO-PSEUDO-INLAND-FLOOD-001"]
    out = _run(tmp_path, "V", _registry(tmp_path))
    assert out.returncode == 4 and "BLOCK TOKYO-PSEUDO-INLAND-FLOOD-001" in out.stdout and PSEUDO in out.stdout


def test_all_tiles_present_is_safe_except_unknown_warning(tmp_path):
    r = rpf.preflight(_version(tmp_path, "V", ALL), _registry(tmp_path))
    c = _by_id(r)
    assert r["verdict"] == rpf.SAFE_WITH_WARNINGS and r["blocked"] == []
    assert [w["dataset_id"] for w in r["warnings"]] == ["TOKYO-URBAN-001"]  # 契約未定義は安全扱いしない
    assert c["TOKYO-PSEUDO-INLAND-FLOOD-001"]["severity"] == "OK" and c["TOKYO-SURGE-001"]["severity"] == "OK"


def test_fully_contracted_and_present_is_safe(tmp_path):
    reg = _registry(tmp_path, lambda ds: [d.update(tile_requirement="optional") for d in ds if d["dataset_id"] == "TOKYO-URBAN-001"])
    r = rpf.preflight(_version(tmp_path, "V", ALL), reg)
    assert r["verdict"] == rpf.SAFE and r["warnings"] == [] and _run(tmp_path, "V", reg).returncode == 0


def test_optional_missing_is_warning_and_allowed(tmp_path):
    r = rpf.preflight(_version(tmp_path, "V", [PSEUDO, URBAN]), _registry(tmp_path))
    w = {x["dataset_id"]: x for x in r["warnings"]}
    assert r["verdict"] == rpf.SAFE_WITH_WARNINGS and r["blocked"] == []
    assert w["TOKYO-SURGE-001"]["requirement"] == "optional" and "API GeoJSON" in w["TOKYO-SURGE-001"]["reason"]
    assert w["TOKYO-TSUNAMI-001"]["tile_rel_path"] == TSUNAMI  # tile_rel_path の custom path を使う
    assert _run(tmp_path, "V", _registry(tmp_path)).returncode == 0


def test_not_applicable_is_ignored(tmp_path):
    r = rpf.preflight(_version(tmp_path, "V", ALL), _registry(tmp_path))
    assert "TOKYO-LANDSLIDE-001" not in _by_id(r)


def test_unknown_contract_missing_is_warning_not_block(tmp_path):
    r = rpf.preflight(_version(tmp_path, "V", [PSEUDO, SURGE, TSUNAMI]), _registry(tmp_path))
    c = _by_id(r)["TOKYO-URBAN-001"]
    assert (c["requirement"], c["severity"]) == ("unknown", "WARNING") and r["verdict"] == rpf.SAFE_WITH_WARNINGS


# ── 8〜9: manifest / registry の不正は FAIL closed ─────────────────────────────────

def test_required_tile_not_matching_manifest_blocks(tmp_path):
    r = rpf.preflight(_version(tmp_path, "V", ALL, tamper=(PSEUDO,)), _registry(tmp_path))
    assert r["verdict"] == rpf.UNSAFE and "sha256" in r["blocked"][0]["reason"]


def test_required_tile_file_missing_on_disk_blocks(tmp_path):
    v = _version(tmp_path, "V", ALL)
    (v / PSEUDO).unlink()
    assert rpf.preflight(v, _registry(tmp_path))["verdict"] == rpf.UNSAFE


def test_unreadable_manifest_fails_closed(tmp_path):
    v = _version(tmp_path, "V", ALL)
    (v / "_manifest.json").write_text("{broken")
    out = _run(tmp_path, "V", _registry(tmp_path))
    assert out.returncode == 1 and "判定不能" in out.stderr


@pytest.mark.parametrize("mutate", [
    lambda ds: ds[0].update(tile_requirement="mandatory"),   # 不正な契約値
    lambda ds: ds[0].pop("dataset_id"),                       # 必須 field 欠落
])
def test_invalid_registry_fails_closed(tmp_path, mutate):
    _version(tmp_path, "V", ALL)
    out = _run(tmp_path, "V", _registry(tmp_path, mutate))
    assert out.returncode == 1 and "判定不能" in out.stderr


@pytest.mark.parametrize("content", ["[]", "{}", None])
def test_empty_or_missing_registry_fails_closed(tmp_path, content):
    _version(tmp_path, "V", ALL)
    reg = tmp_path / "defs.json"
    if content is not None:
        reg.write_text(content)
    assert _run(tmp_path, "V", reg).returncode == 1


def test_missing_target_version_fails_closed(tmp_path):
    assert _run(tmp_path, "NOPE", _registry(tmp_path)).returncode == 1


def test_override_allows_but_warns(tmp_path):
    _version(tmp_path, "V", [SURGE, TSUNAMI, URBAN])
    out = _run(tmp_path, "V", _registry(tmp_path), "--allow-missing-required-tiles")
    assert out.returncode == 0 and "verdict=UNSAFE_OVERRIDDEN" in out.stdout
    assert "WARNING missing required tile" in out.stdout and "TOKYO-PSEUDO-INLAND-FLOOD-001" in out.stdout and "target=V" in out.stdout


def test_json_output_is_machine_readable(tmp_path):
    _version(tmp_path, "V", [SURGE])
    r = json.loads(_run(tmp_path, "V", _registry(tmp_path), "--json").stdout)
    assert r["verdict"] == "UNSAFE_REQUIRED_TILE_MISSING" and r["blocked"][0]["dataset_id"] == "TOKYO-PSEUDO-INLAND-FLOOD-001"


def test_production_registry_required_set_comes_from_registry():
    """required の集合は registry から導く（version ID や dataset 名を hard-code しない）。"""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "20261011" not in src and "PSEUDO" not in src and "LOWLAND" not in src
    defs = rpf.load_definitions_strict(ROOT / "data_lake/registry/dataset_definitions.json")
    _, dos = rpf._import_backend()
    required = sorted(d.dataset_id for d in defs if dos.tile_requirement(d) == "required")
    assert required == ["CHIBA-TSUNAMI-001", "KANAGAWA-LOWLAND-POOR-DRAINAGE-001", "KANAGAWA-RIVER-001", "TOKYO-LOWLAND-POOR-DRAINAGE-001",
                        "TOKYO-PSEUDO-INLAND-FLOOD-001", "TOKYO-RIVER-001"]


def test_rollback_wrapper_runs_preflight_before_any_change():
    w = (ROOT / "scripts/publish/rollback_runtime.sh").read_text(encoding="utf-8")
    i_pre = w.index('"${PREFLIGHT[@]}"; rc=$?')
    for later in ('PLAN="$("${RECONCILE[@]}" --plan)"', '"${RECONCILE[@]}" --prepare', 'activate_version.py" --data-runtime-root'):
        assert i_pre < w.index(later)
    assert "--allow-missing-required-tiles) ALLOW_MISSING_REQUIRED=1" in w
    assert "read -p" not in w and "read -r" not in w  # 対話確認に依存しない


# ── Linux: rollback_runtime.sh 全体（operator identity）──────────────────────────

linux_operator = pytest.mark.skipif(not sys.platform.startswith("linux") or os.geteuid() != 10002,
                                    reason="operator identity（10002 / supplemental 20001）で実行する")


def _published_pair(tmp_path):
    sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(ROOT / "tests"))
    import sqlite3
    from app.services.runtime_publish import AtomicPublisher
    from test_atomic_publish_validation_reuse import _build, _normalize, _validator
    root = tmp_path / "data_runtime"
    (root / ".staging").mkdir(parents=True); (root / "versions").mkdir(); (root / ".publish.lock").touch(mode=0o600)
    pub = AtomicPublisher(root, expect_uid=10002, expect_gid=10002, capacity_min_free_bytes=None, min_free_inodes=None)

    def tile(rel, s):
        (s / rel).parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(s / rel); c.execute("create table metadata(name text, value text)"); c.execute("insert into metadata values ('m', ?)", (rel,)); c.commit(); c.close()
    vids = {}
    for name, vid, rels in (("old", "20261011T060000Z-0000c001", [SURGE]), ("new", "20261011T060100Z-0000c002", [PSEUDO, SURGE, TSUNAMI, URBAN])):
        s = root / ".staging" / vid; s.mkdir(mode=0o750); _build(s)
        for rel in rels:
            tile(rel, s)
        _normalize(s); pub.publish(vid, _validator(True)); vids[name] = vid
    subprocess.run([sys.executable, str(ROOT / "scripts/publish/reconcile_tile_mirror.py"), "--data-runtime-root", str(root), "--apply"], check=True, capture_output=True)
    return root, vids


def _mirror_state(root):
    base = root / "frontend" / "tiles"
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in base.rglob("*") if p.is_file()}


@linux_operator
def test_blocked_rollback_changes_nothing(tmp_path):
    root, vids = _published_pair(tmp_path)
    before = (os.readlink(root / "current"), _mirror_state(root))
    env = {**os.environ, "OHG2_DATA_RUNTIME_ROOT": str(root), "OHG2_ADMIN_DIR": str(tmp_path / "admin")}
    out = subprocess.run(["bash", str(ROOT / "scripts/publish/rollback_runtime.sh"), vids["old"]], capture_output=True, text=True, env=env)
    assert out.returncode == 1 and "rollback を拒否" in out.stdout + out.stderr
    assert (os.readlink(root / "current"), _mirror_state(root)) == before
    assert not list((root / "frontend").rglob("*.reconciling")) and not (tmp_path / "admin").exists()


@linux_operator
def test_override_rollback_proceeds_with_warning(tmp_path):
    root, vids = _published_pair(tmp_path)
    env = {**os.environ, "OHG2_DATA_RUNTIME_ROOT": str(root), "OHG2_ADMIN_DIR": str(tmp_path / "admin")}
    out = subprocess.run(["bash", str(ROOT / "scripts/publish/rollback_runtime.sh"), vids["old"], "--allow-missing-required-tiles"],
                         capture_output=True, text=True, env=env)
    log = out.stdout + out.stderr
    assert out.returncode == 0, log
    assert "WARNING missing required tile" in log and PSEUDO in log and f"target={vids['old']}" in log
    assert os.readlink(root / "current") == f"versions/{vids['old']}" and PSEUDO not in _mirror_state(root)
