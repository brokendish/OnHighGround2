"""
test_local_runtime_profile_selfcheck.py — local runtime profile 回帰 selfcheck

対象（Phase A〜C）:
  - scripts/local/bootstrap_runtime_volumes.sh
  - config/martin-local.yaml
  - docker-compose.override.example.yml（B: local runtime profile ブロック）

方針:
  - ファイル内容の静的検証は Docker 無しで常に実行する。
  - Compose マージ検証は `docker compose config` を使い、docker が無ければ skip する。
  - owner Compose の起動・production 接続は一切行わない。

実行:
    venv/bin/python -m pytest tools/public_release/test_local_runtime_profile_selfcheck.py -v
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


class _ComposeLoader(yaml.SafeLoader):
    """docker compose の `!override` タグを、対象シーケンス/マッピングとして素通しする。"""


_ComposeLoader.add_constructor(
    "!override",
    lambda loader, node: (
        loader.construct_sequence(node, deep=True)
        if isinstance(node, yaml.SequenceNode)
        else loader.construct_mapping(node, deep=True)
    ),
)


def _load_yaml(p: Path):
    return yaml.load(p.read_text(encoding="utf-8"), Loader=_ComposeLoader)


REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / "scripts" / "local" / "bootstrap_runtime_volumes.sh"
MARTIN_BASE = REPO / "config" / "martin.yaml"
MARTIN_LOCAL = REPO / "config" / "martin-local.yaml"
OVERRIDE_EXAMPLE = REPO / "docker-compose.override.example.yml"
BASE_COMPOSE = REPO / "docker-compose.yml"

PUBLIC_UID = "10001"
PUBLIC_GID = "10001"


# ─────────────────────────────────────────────────────────────────────────────
# Phase A — bootstrap helper
# ─────────────────────────────────────────────────────────────────────────────
def test_helper_exists_and_executable():
    assert HELPER.is_file()
    assert HELPER.stat().st_mode & 0o111, "helper に実行ビットが無い"


def test_helper_shell_syntax_ok():
    r = subprocess.run(["bash", "-n", str(HELPER)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _noncomment(body: str) -> str:
    return "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))


def test_helper_sets_public_ownership_and_safe_mode():
    body = HELPER.read_text(encoding="utf-8")
    assert f'PUBLIC_UID="${{OHG2_PUBLIC_UID:-{PUBLIC_UID}}}"' in body
    assert f'PUBLIC_GID="${{OHG2_PUBLIC_GID:-{PUBLIC_GID}}}"' in body
    assert "chown ${PUBLIC_UID}:${PUBLIC_GID}" in body
    assert 'CHILD_VOLUME_MODE="0750"' in body
    # world-writable / 0777 は禁止（§10）
    assert "0777" not in body
    assert not re.search(r"chmod\s+\S*o\+w", body)


def test_helper_does_not_take_over_runtime_init_responsibilities():
    """helper は .publish.lock / .staging / versions を作らない（§12）。"""
    body = HELPER.read_text(encoding="utf-8")
    # 生成コマンド（mkdir/touch/os.open 相当）で作っていないこと。
    assert not re.search(r"(mkdir|touch)[^\n]*\.publish\.lock", body)
    assert not re.search(r"(mkdir|touch)[^\n]*/(\.staging|versions)\b", body)
    # 参照（存在確認・コメント）は許容 — 実際に verify ブロックで「作っていない」ことを自己確認する。
    assert ".publish.lock" in body and ".staging" in body and "versions" in body


def test_helper_is_non_recursive_non_destructive():
    code = _noncomment(HELPER.read_text(encoding="utf-8"))
    assert "chown -R" not in code
    assert "chmod -R" not in code
    assert not re.search(r"\brm\s+-[rf]", code), "破壊的な rm -r/-f を含む"


def test_helper_nested_mountpoints_cover_contract():
    """helper が作る nested mountpoint が Compose contract を満たす（§8）。"""
    body = HELPER.read_text(encoding="utf-8")
    # 明示リスト
    m = re.search(r"NESTED_DIRS=\(([^)]*)\)", body)
    assert m, "NESTED_DIRS 配列が見つからない"
    explicit = set(m.group(1).split())
    assert {"logs", "cache", "backend", "frontend", "frontend/tiles"} <= explicit
    # tile ディレクトリは martin-local.yaml から動的抽出している（drift 防止）
    assert "martin-local.yaml" in body or "MARTIN_LOCAL_CONFIG" in body
    assert "/data_runtime/frontend/tiles/" in body


def test_helper_default_image_is_pinned_and_matches_compose():
    body = HELPER.read_text(encoding="utf-8")
    m = re.search(r"OHG2_BOOTSTRAP_IMAGE:-([^\s}]+)", body)
    assert m, "既定 bootstrap image が見つからない"
    image = m.group(1)
    assert "@sha256:" in image, "helper の既定 image が digest pin されていない"
    assert image in BASE_COMPOSE.read_text(encoding="utf-8"), (
        "helper の既定 image が docker-compose.yml の pin と一致しない"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase B — Martin local config
# ─────────────────────────────────────────────────────────────────────────────
def _martin_paths(p: Path) -> list[str]:
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    return list(doc["mbtiles"]["paths"])


def test_martin_local_exists():
    assert MARTIN_LOCAL.is_file()


def test_martin_local_only_reparents_tiles_root():
    base = _martin_paths(MARTIN_BASE)
    local = _martin_paths(MARTIN_LOCAL)
    assert len(base) == len(local)
    for b, l in zip(base, local):
        assert b.startswith("/tiles/")
        assert l == "/data_runtime/frontend/tiles/" + b[len("/tiles/"):], (
            f"path 対応が /tiles → /data_runtime/frontend/tiles だけの付け替えになっていない: {b} vs {l}"
        )


def test_martin_local_stems_match_base():
    base_stems = [p.rsplit("/", 1)[-1] for p in _martin_paths(MARTIN_BASE)]
    local_stems = [p.rsplit("/", 1)[-1] for p in _martin_paths(MARTIN_LOCAL)]
    assert base_stems == local_stems


def test_martin_local_preserves_listen_and_no_extra_keys():
    base = yaml.safe_load(MARTIN_BASE.read_text(encoding="utf-8"))
    local = yaml.safe_load(MARTIN_LOCAL.read_text(encoding="utf-8"))
    assert local["listen_addresses"] == base["listen_addresses"]
    # datasource semantics を勝手に増やさない（§15）
    assert set(local.keys()) <= set(base.keys()) | {"listen_addresses", "mbtiles"}
    assert set(local["mbtiles"].keys()) == {"paths"}


def test_base_martin_config_unchanged_shape():
    """base config の path は /tiles ルートのまま（§13: base を正本とする / 触らない）。"""
    for p in _martin_paths(MARTIN_BASE):
        assert p.startswith("/tiles/")


# ─────────────────────────────────────────────────────────────────────────────
# Phase C — docker-compose.override.example.yml
# ─────────────────────────────────────────────────────────────────────────────
def test_override_example_declares_named_volumes():
    doc = _load_yaml(OVERRIDE_EXAMPLE)
    vols = doc.get("volumes") or {}
    for key in ("data-runtime", "data-runtime-logs", "data-runtime-cache"):
        assert key in vols, f"volume {key} が宣言されていない"
        name = vols[key]["name"]
        assert "COMPOSE_PROJECT_NAME" in name, (
            f"{key} の name が ${{COMPOSE_PROJECT_NAME}} で名前空間分離されていない"
        )


def test_override_example_preserves_carto_mount():
    """A: CARTO ランタイム公開設定の mount を消さない（§21）。"""
    doc = _load_yaml(OVERRIDE_EXAMPLE)
    fe = doc["services"]["frontend"]["volumes"]
    assert any("runtime-config.local.js" in str(v) for v in fe), (
        "frontend の CARTO runtime-config mount が失われている"
    )


def test_override_example_wires_three_runtime_services():
    doc = _load_yaml(OVERRIDE_EXAMPLE)
    svc = doc["services"]
    assert any("data-runtime:/data_runtime" in str(v) for v in svc["runtime-init"]["volumes"])
    bp = [str(v) for v in svc["backend-public"]["volumes"]]
    assert any("data-runtime:/data_runtime:ro" in v for v in bp)
    assert any("data-runtime-logs:/data_runtime/logs" in v for v in bp)
    assert any("data-runtime-cache:/data_runtime/cache" in v for v in bp)
    assert svc["martin"]["command"] == "--config /config/martin-local.yaml"


# ─────────────────────────────────────────────────────────────────────────────
# Compose マージ検証（docker が必要。無ければ skip）
# ─────────────────────────────────────────────────────────────────────────────
def _compose_config_json() -> dict:
    r = subprocess.run(
        ["docker", "compose", "-f", str(BASE_COMPOSE), "-f", str(OVERRIDE_EXAMPLE),
         "config", "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker 未インストール")
def test_compose_merge_contract():
    d = _compose_config_json()

    vols = {k: v.get("name") for k, v in d["volumes"].items()}
    assert vols["data-runtime"].endswith("-data-runtime")
    assert vols["data-runtime-logs"].endswith("-data-runtime-logs")
    assert vols["data-runtime-cache"].endswith("-data-runtime-cache")

    def mounts(svc):
        return {(m.get("source"), m.get("target"), bool(m.get("read_only")))
                for m in d["services"][svc].get("volumes", [])}

    bp = mounts("backend-public")
    assert ("data-runtime", "/data_runtime", True) in bp, "backend parent が read-only でない"
    assert ("data-runtime-logs", "/data_runtime/logs", False) in bp, "logs が rw でない"
    assert ("data-runtime-cache", "/data_runtime/cache", False) in bp, "cache が rw でない"
    # base の host bind による /data_runtime* は残っていない
    assert not any(t in ("/data_runtime", "/data_runtime/logs", "/data_runtime/cache")
                   and str(s).startswith("/") for (s, t, _ro) in bp), (
        "base の ./data_runtime host bind が残っている"
    )

    mt = mounts("martin")
    assert ("data-runtime", "/data_runtime", True) in mt
    assert d["services"]["martin"]["command"] == ["--config", "/config/martin-local.yaml"]
    # !override により旧 /tiles / /tiles_fallback bind は消えている
    assert not any(t in ("/tiles", "/tiles_fallback") for (_s, t, _ro) in mt)

    ri = mounts("runtime-init")
    assert ("data-runtime", "/data_runtime", False) in ri, "runtime-init が /data_runtime を rw で持たない"

    # A: CARTO mount 保持
    fe = mounts("frontend")
    assert any(t == "/usr/share/nginx/html/js/shared/runtime-config.js" for (_s, t, _ro) in fe)
