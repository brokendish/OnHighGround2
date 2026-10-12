"""
PHASE-2D-FINAL-ALIGNMENT（2026-10-12）の focused self-test。container は起動しない（compose は `config` の描画だけ）。

  2b3  operator gateway の正式 path（/health・/admin/api/admin/*）を使い、旧 path（/operator/health・/api/admin/*）を
       gateway 宛てに使わない。osrm-walking の volume は base compose から機械的に写像する（osrm-provenance を含む）
  2b4  operator API は /admin/api/admin/*・/admin/api/simulation/*。public 側の拒否対象 path（/api/admin 等）は不変。
       browser E2E は login form と session cookie を使い、旧 #operator-auth-bar に依存しない。
       collection contract の 144 件は operator asset 20 file を前提にする（増減時は意識的に更新させる）
  Martin  test stack の martin は run tree 内の空 skeleton を mount し、committed config/martin.yaml の全 path を持つ。
          不正な path（/tiles 外・..）は拒否する
  RTE-004  OWNER 承認済み契約（Operator Authentication Persistence / Credential Non-Leakage）の 1〜10 を oracle が
           全て持ち、旧契約（reload 後 401）を要求しない。fixture は Local の :latest image・未 pin image を使わない
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import phase2_isolated_stack as iso  # noqa: E402

DOCKER = shutil.which("docker")


def _code_lines(path: Path) -> list[str]:
    return [l for l in path.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#")]


def _fake_seeded(tmp_path: Path) -> dict:
    seeded = {k: tmp_path / f"seed_{k}" for k in ("data_lake", "data_runtime", "railways", "osrm")}
    for p in seeded.values():
        p.mkdir(parents=True)
    (seeded["data_lake"] / "admin").mkdir()
    (seeded["osrm"] / "foot.lua").write_text("-- fixture\n")
    return seeded


# ── operator gateway の正式 path ─────────────────────────────────────────────────────

def _gateway_locations() -> set[str]:
    text = (REPO_ROOT / "operator" / "nginx.conf").read_text(encoding="utf-8")
    return set(re.findall(r"^\s*location\s+(?:=\s+)?(\S+)\s*\{", text, flags=re.M))


def test_gateway_routes_are_the_paths_the_harness_uses():
    locs = _gateway_locations()
    assert {"/health", "/admin/api/admin/", "/admin/api/simulation/", "/admin/api/login", "/admin/api/logout"} <= locs
    assert "/operator/health" not in locs and "/api/admin/" not in locs


def test_2b3_uses_current_gateway_paths():
    lines = _code_lines(HERE / "phase2b3_operator_security.py")
    gateway_urls = [l for l in lines if "operator_host_port}" in l or "local_forward_port}" in l]
    assert gateway_urls, "gateway 宛ての URL が見つからない"
    assert not [l for l in gateway_urls if "/operator/health" in l or re.search(r"\}/api/admin", l)]
    assert any("}/health" in l for l in gateway_urls)
    assert any("}/admin/api/admin/hazards" in l for l in gateway_urls)
    # backend-public 経由の public 回帰（/api/admin/config が 404）は public 契約なので残っている
    assert any('"/api/admin/config"' in l for l in lines)


def test_2b4_uses_current_operator_api_paths():
    import phase2b4_frontend_boundary as fb
    assert fb.OPERATOR_API_ADMIN == "/admin/api/admin" and fb.OPERATOR_API_SIMULATION == "/admin/api/simulation"
    lines = _code_lines(HERE / "phase2b4_frontend_boundary.py")
    assert not [l for l in lines if 'f"{base_url}/api/admin' in l or 'f"{base_url}/api/simulation' in l]
    # public 側の拒否対象（変更しない）
    assert fb.DENIAL_PREFIXES == ("/admin", "/api/admin", "/api/simulation")


def test_2b4_browser_e2e_uses_session_login_not_auth_bar():
    e2e = (HERE / "phase2b4_browser_e2e.js").read_text(encoding="utf-8")
    assert "#operator-auth-bar" not in e2e.split("// ── operator UI: token hygiene ──")[1].split("*/")[-1]
    assert "page.fill('#login-form input#token', token)" in e2e
    assert "'ohg_admin_session'" in e2e
    assert e2e.count("record(") == 23  # public 6 + operator 16 + crash 1（件数・順序は不変）


def test_2b4_collection_contract_matches_operator_asset_inventory():
    import phase2b4_frontend_boundary as fb
    assets = fb.build_operator_asset_inventory(fb.OPERATOR_FRONTEND_DIR)
    assert len(assets) == 20, "operator asset 数が変わった: FORMAL_EXPECTED_CASE_IDS（144）を見直すこと"
    assert len(fb.FORMAL_EXPECTED_CASE_IDS) == 144
    assert fb.FORMAL_EXPECTED_CASE_IDS[0] == "S11-001" and fb.FORMAL_EXPECTED_CASE_IDS[-1] == "S11-144"


# ── Martin fixture ───────────────────────────────────────────────────────────────────

def test_martin_skeleton_covers_committed_config(tmp_path):
    vols = iso.martin_service_volumes(tmp_path)
    assert vols[2] == "./config:/config:ro" and all(v.endswith(":ro") for v in vols)
    tiles = Path(vols[0].split(":")[0])
    assert tiles.is_relative_to(tmp_path.resolve())
    cfg = yaml.safe_load((REPO_ROOT / "config" / "martin.yaml").read_text(encoding="utf-8"))
    for entry in cfg["mbtiles"]["paths"]:
        assert (tiles / Path(entry).relative_to("/tiles")).is_dir(), entry
    assert not [p for p in tiles.rglob("*") if p.is_file()]  # 中身は空（実 tile を使わない）


@pytest.mark.parametrize("bad", ["/etc/tiles", "/tiles/../etc", "tiles/tokyo"])
def test_martin_skeleton_rejects_unexpected_paths(tmp_path, bad):
    cfg = tmp_path / "martin.yaml"
    cfg.write_text(yaml.dump({"mbtiles": {"paths": ["/tiles/tokyo/flood", bad]}}), encoding="utf-8")
    with pytest.raises(ValueError):
        iso.martin_service_volumes(tmp_path / "run", martin_config=cfg)


@pytest.mark.skipif(DOCKER is None, reason="docker compose が無い")
@pytest.mark.parametrize("tool", ["phase2b3_operator_security", "phase2b4_frontend_boundary"])
def test_rendered_martin_and_osrm_do_not_mount_repository_state(tmp_path, tool):
    mod = __import__(tool)
    override = mod.build_override_compose(tmp_path, _fake_seeded(tmp_path))
    rendered = iso.render_config(mod.compose_cmd(override, []), ["operator"])
    martin = {m["target"]: m["source"] for m in rendered["services"]["martin"]["volumes"]}
    assert Path(martin["/tiles"]).resolve().is_relative_to(tmp_path.resolve())
    assert Path(martin["/tiles_fallback"]).resolve().is_relative_to(tmp_path.resolve())
    osrm_targets = {m["target"] for m in rendered["services"]["osrm-walking"]["volumes"]}
    assert "/usr/local/bin/osrm-provenance" in osrm_targets
    assert iso.isolation_violations(rendered, [tmp_path]) == []


# ── RTE-004 ──────────────────────────────────────────────────────────────────────────

RTE004_CONTRACT_KEYS = [
    "1_unauth_api_401", "1_unauth_page_to_login", "2_login_issues_session", "3_4_no_credential_leak",
    "4_login_body_observed", "5_reload_keeps_session", "6_logout_invalidates", "6_replayed_cookie_rejected",
    "6_cleared_cookie_rejected", "7_query_token_rejected", "8_forged_cookie_rejected", "9_invalid_bearer_401",
    "10_cookie_attributes",
]


def _rte004_source() -> str:
    runner = (HERE / "phase2d_round12b_new_cases_runner.py").read_text(encoding="utf-8")
    return runner[runner.index("def case_new_rte_004"):runner.index("CASE_FUNCS = {")]


def test_rte004_oracle_has_every_contract_item_and_not_the_old_one():
    src = _rte004_source()
    for key in RTE004_CONTRACT_KEYS:
        assert f'"{key}":' in src, key
    assert "ok = all(checks.values())" in src
    assert 'payload.get("postReloadStatus") == 200' in src
    assert 'payload.get("postReloadStatus") == 401' not in src
    for attr in ('cookie.get("httpOnly") is True', 'cookie.get("secure") is True', 'cookie.get("sameSite") == "Strict"',
                 'cookie.get("path") == "/admin"', 'cookie.get("hostOnly") is True'):
        assert attr in src, attr


def test_rte004_fixture_uses_head_image_and_pinned_gateway():
    src = _rte004_source()
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "onhighground2-backend-operator:latest" not in code and '"nginx:alpine"' not in code
    assert 'Dockerfile.operator' in src and 'docker", "image", "rm"' in src
    assert '["services"]["operator-gateway"]["image"]' in src
    gateway_image = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]["operator-gateway"]["image"]
    assert "@sha256:" in gateway_image


def test_rte004_e2e_scans_every_required_surface_and_allows_only_login_body():
    e2e = (HERE / "phase2d_round12b_rte004_e2e.js").read_text(encoding="utf-8")
    for surface in ("'cookie'", "'localStorage'", "'sessionStorage'", "'indexedDB'", "'cacheStorage'", "'request_url:'",
                    "'request_body:'", "'redirect_location:'", "'rendered_html:post_login'", "'js_state:post_login'", "'console'"):
        assert surface in e2e, surface
    for deriv in ("raw:", "url_encoded:", "base64:", "base64url:"):
        assert deriv in e2e
    assert "r.method === 'POST' && pathOf(r.url) === '/admin/api/login'" in e2e
    assert "/api/admin/datasets'" not in e2e.replace("/admin/api/admin/datasets'", "")
    # detail に canary を出さない
    assert "_redact(" in _rte004_source()
