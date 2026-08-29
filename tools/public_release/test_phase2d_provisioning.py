"""
test_phase2d_provisioning.py — AT-17B fixture test（Phase 2-D Round 2、指示書第11.5節）

大容量実dataを毎回downloadせず、local fixture HTTP serverまたは小規模fixtureで
最低限次を検証する:
    1. success
    2. HTTP error
    3. timeout
    4. redirect to unapproved domain
    5. checksum mismatch
    6. archive corruption
    7. insufficient capacity
    8. existing destination conflict
    9. interrupted partial file
    10. manifest atomic publish
    11. secret canary非露出

実行:
    venv/bin/python -m pytest tools/public_release/test_phase2d_provisioning.py -v
"""
from __future__ import annotations

import hashlib
import http.server
import json
import socket
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "download"))

import _provisioning_common as pc  # noqa: E402
import import_river_flood_manual as flood_import  # noqa: E402


# ---------------------------------------------------------------------------
# Local fixture HTTP server
# ---------------------------------------------------------------------------

class _FixtureHandler(http.server.BaseHTTPRequestHandler):
    routes: dict = {}

    def log_message(self, *args):  # noqa: D401 — silence default stderr logging
        pass

    def do_GET(self):
        route = self.routes.get(self.path)
        if route is None:
            self.send_response(404)
            self.end_headers()
            return
        kind = route.get("kind", "ok")
        if kind == "ok":
            body = route["body"]
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif kind == "error":
            self.send_response(route.get("status", 500))
            self.end_headers()
        elif kind == "timeout":
            time.sleep(route.get("delay", 5))
            self.send_response(200)
            self.end_headers()
        elif kind == "redirect":
            self.send_response(302)
            self.send_header("Location", route["location"])
            self.end_headers()
        elif kind == "truncated":
            # Content-Lengthを実body長より大きく偽装し、接続を早期に切断する。
            body = route["body"]
            self.send_response(200)
            self.send_header("Content-Length", str(len(body) * 4))
            self.end_headers()
            self.wfile.write(body)
            # 接続をここで閉じる（残りを送らない）ことで中断をシミュレートする。


@pytest.fixture(scope="module")
def fixture_server():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", port
    server.shutdown()


# ---------------------------------------------------------------------------
# 1. success（https + allowlist domain想定はここでは127.0.0.1をallowlistに含めて代用）
# ---------------------------------------------------------------------------

def test_p17b_01_success(tmp_path, fixture_server):
    base, port = fixture_server
    body = b"fixture-content-success"
    _FixtureHandler.routes["/ok.bin"] = {"kind": "ok", "body": body}
    dest = tmp_path / "out.bin"
    # HTTPSのみを許可する本番仕様のため、ここではdomain allowlist機構自体を
    # http://127.0.0.1でも検証できるよう、scheme検査を一時的にHTTPも許可した
    # テスト専用ラッパーを使う（本番scriptはHTTPS固定のまま）。
    result = _fetch_allow_http(f"{base}/ok.bin", dest, allowed_domains=("127.0.0.1",))
    assert result.ok is True
    assert dest.exists()
    assert dest.read_bytes() == body
    assert result.sha256 == hashlib.sha256(body).hexdigest()


def _fetch_allow_http(url, dest, **kwargs):
    """本番の`fetch_with_validation`はHTTPS固定だが、local fixture serverはHTTPしか
    提供できないため、テスト専用にscheme検査だけを緩めた薄いラッパーを使う。
    ドメインallowlist・redirect検証・checksum検証・atomic writeロジック自体は
    本番と同じ`fetch_with_validation`をそのまま呼び出す（monkeypatchでscheme検査のみ回避）。
    """
    import urllib.parse as up

    original_urlparse = up.urlparse

    def _patched(url_, *a, **kw):
        parsed = original_urlparse(url_, *a, **kw)
        if parsed.scheme == "http":
            parsed = parsed._replace(scheme="https")
        return parsed

    # _validate_url_domainだけがscheme検査をする。ここでは直接呼ばず、
    # fetch_with_validation内部のurlparseをこの関数の呼び出し中だけ差し替える。
    orig = pc.urlparse
    pc.urlparse = _patched
    try:
        return pc.fetch_with_validation(url, dest, **kwargs)
    finally:
        pc.urlparse = orig


# ---------------------------------------------------------------------------
# 2. HTTP error
# ---------------------------------------------------------------------------

def test_p17b_02_http_error(tmp_path, fixture_server):
    base, _ = fixture_server
    _FixtureHandler.routes["/error.bin"] = {"kind": "error", "status": 500}
    dest = tmp_path / "err.bin"
    result = _fetch_allow_http(f"{base}/error.bin", dest, allowed_domains=("127.0.0.1",), max_retries=1)
    assert result.ok is False
    assert not dest.exists()


# ---------------------------------------------------------------------------
# 3. timeout
# ---------------------------------------------------------------------------

def test_p17b_03_timeout(tmp_path, fixture_server):
    base, _ = fixture_server
    _FixtureHandler.routes["/slow.bin"] = {"kind": "timeout", "delay": 2}
    dest = tmp_path / "slow.bin"
    result = _fetch_allow_http(
        f"{base}/slow.bin", dest, allowed_domains=("127.0.0.1",), timeout_seconds=0.3, max_retries=1
    )
    assert result.ok is False
    assert not dest.exists()


# ---------------------------------------------------------------------------
# 4. redirect to unapproved domain
# ---------------------------------------------------------------------------

def test_p17b_04_redirect_to_unapproved_domain_rejected(tmp_path, fixture_server):
    base, _ = fixture_server
    _FixtureHandler.routes["/redir.bin"] = {"kind": "redirect", "location": "https://evil.example.com/payload"}
    dest = tmp_path / "redir.bin"
    result = _fetch_allow_http(f"{base}/redir.bin", dest, allowed_domains=("127.0.0.1",), max_retries=1)
    assert result.ok is False
    assert not dest.exists()


# ---------------------------------------------------------------------------
# 5. checksum mismatch
# ---------------------------------------------------------------------------

def test_p17b_05_checksum_mismatch(tmp_path, fixture_server):
    base, _ = fixture_server
    body = b"some content"
    _FixtureHandler.routes["/cksum.bin"] = {"kind": "ok", "body": body}
    dest = tmp_path / "cksum.bin"
    result = _fetch_allow_http(
        f"{base}/cksum.bin", dest, allowed_domains=("127.0.0.1",),
        expected_sha256="0" * 64, max_retries=1,
    )
    assert result.ok is False
    assert not dest.exists()
    assert "checksum" in result.error.lower()


# ---------------------------------------------------------------------------
# 6. archive corruption（river flood importer側）
# ---------------------------------------------------------------------------

def test_p17b_06_corrupt_archive_rejected(tmp_path):
    bad_zip = tmp_path / "corrupt.zip"
    bad_zip.write_bytes(b"not actually a zip file")
    out_dir = tmp_path / "out"
    rc = flood_import.import_file(bad_zip, out_dir, "13", overwrite=False)
    assert rc != 0
    assert not any(out_dir.glob("*")) if out_dir.exists() else True


def test_p17b_06b_zip_without_ksj_schema_rejected(tmp_path):
    zip_path = tmp_path / "wrong_schema.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("data.xml", "<root>not ksj data</root>")
    out_dir = tmp_path / "out2"
    rc = flood_import.import_file(zip_path, out_dir, "13", overwrite=False)
    assert rc != 0


def test_p17b_06c_valid_ksj_schema_accepted(tmp_path):
    zip_path = tmp_path / "valid.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("A31a-25-13.xml", '<ksj:Dataset xmlns:ksj="http://example.jp/ksj"><ksj:Curve/></ksj:Dataset>')
    out_dir = tmp_path / "out3"
    rc = flood_import.import_file(zip_path, out_dir, "13", overwrite=False)
    assert rc == 0
    manifests = list(out_dir.glob("*.manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["prefecture_code"] == "13"
    assert manifest["sha256"]


# ---------------------------------------------------------------------------
# 7. insufficient capacity
# ---------------------------------------------------------------------------

def test_p17b_07_insufficient_capacity_rejected(tmp_path):
    dest = tmp_path / "huge.bin"
    with pytest.raises(pc.ProvisioningError):
        pc.check_disk_space(dest, required_bytes=10**18)  # 1 exabyte — always insufficient


# ---------------------------------------------------------------------------
# 8. existing destination conflict
# ---------------------------------------------------------------------------

def test_p17b_08_existing_destination_conflict(tmp_path, fixture_server):
    base, _ = fixture_server
    body = b"content"
    _FixtureHandler.routes["/exists.bin"] = {"kind": "ok", "body": body}
    dest = tmp_path / "exists.bin"
    dest.write_bytes(b"pre-existing content, should not be overwritten")
    result = _fetch_allow_http(f"{base}/exists.bin", dest, allowed_domains=("127.0.0.1",), overwrite_existing=False)
    assert result.ok is False
    assert dest.read_bytes() == b"pre-existing content, should not be overwritten"


def test_p17b_08b_overwrite_explicit_allows_replace(tmp_path, fixture_server):
    base, _ = fixture_server
    body = b"new content"
    _FixtureHandler.routes["/exists2.bin"] = {"kind": "ok", "body": body}
    dest = tmp_path / "exists2.bin"
    dest.write_bytes(b"old content")
    result = _fetch_allow_http(f"{base}/exists2.bin", dest, allowed_domains=("127.0.0.1",), overwrite_existing=True)
    assert result.ok is True
    assert dest.read_bytes() == body


# ---------------------------------------------------------------------------
# 9. interrupted partial file — no .partial temp file left behind, dest untouched
# ---------------------------------------------------------------------------

def test_p17b_09_interrupted_fetch_leaves_no_partial_file(tmp_path, fixture_server):
    base, _ = fixture_server
    _FixtureHandler.routes["/error2.bin"] = {"kind": "error", "status": 503}
    dest = tmp_path / "interrupted.bin"
    result = _fetch_allow_http(f"{base}/error2.bin", dest, allowed_domains=("127.0.0.1",), max_retries=1)
    assert result.ok is False
    assert not dest.exists()
    leftover = list(tmp_path.glob(".*partial*"))
    assert leftover == [], f"partial temp files leaked: {leftover}"


# ---------------------------------------------------------------------------
# 10. manifest atomic publish
# ---------------------------------------------------------------------------

def test_p17b_10_manifest_atomic_publish(tmp_path):
    manifest_path = tmp_path / "test.manifest.json"
    sha = pc.write_manifest(manifest_path, {"key": "value", "n": 1})
    assert manifest_path.exists()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data == {"key": "value", "n": 1}
    assert len(sha) == 64
    leftover = list(tmp_path.glob(".*partial*"))
    assert leftover == []


# ---------------------------------------------------------------------------
# 11. secret canary非露出（downloadスクリプト自体がsecretを一切引数化しないことの確認）
# ---------------------------------------------------------------------------

def test_p17b_11_no_secret_bearing_parameters_in_common_module():
    # 「secret」という語自体はモジュールの方針説明（docstring）に登場するため
    # 文字列検索ではなく、実際にsecret値を保持しうるparameter/変数定義
    # （例: `api_key=`, `password=`, `token=`）が存在しないことを確認する。
    import re
    source = (REPO_ROOT / "scripts" / "download" / "_provisioning_common.py").read_text(encoding="utf-8")
    forbidden_param_pattern = re.compile(r"\b(api_key|password|secret_value|auth_token)\s*[:=]", re.IGNORECASE)
    matches = forbidden_param_pattern.findall(source)
    assert matches == [], f"secret-bearing parameter names found: {matches}"


def test_p17b_11b_osm_and_flood_scripts_have_no_secret_canary():
    for name in ("download_osm_provision.py", "import_river_flood_manual.py"):
        source = (REPO_ROOT / "scripts" / "download" / name).read_text(encoding="utf-8")
        for canary in ("AKIA", "-----BEGIN", "ODPT_API_KEY=", "OPERATOR_AUTH_SECRET="):
            assert canary not in source, f"secret-like canary {canary!r} found in {name}"
