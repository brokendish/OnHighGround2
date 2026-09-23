"""
Phase 2-C 受入試験 — public docs/OpenAPI無効化・metrics/diagnostics/admin/simulation
二層遮断・public /health最小schema・CORS exact-origin allowlist
（AT-04, AT-07, AT-08、tasks/public-release/phase2c_claude_implementation_instruction.md）。

test class ↔ case ID prefixの対応:
    TestCorsOriginParserUnit          CRS-U-*  (parse_cors_origins単体、app import不要)
    TestCorsFailClosedIntegration     CRS-I-*  (実app_publicの起動時fail-closed、subprocess)
    TestCorsRuntimeFourPatterns       CRS-R-*  (実CORSMiddlewareを使った4基本パターン+negative)
    TestDocsProductionDefault         DOC-P-*  (production既定でdocs 0件、実app_public TestClient)
    TestDocsDevelopmentModeToggle     DOC-D-*  (development二重条件のpositive/negative、subprocess)
    TestNginxStaticConfig             DOC/OBS/HLT-N-* (nginx.confの静的内容検査)
    TestObservabilityRouteDenylist    OBS-*    (metrics/diagnostics/admin/simulation、実app_public)
    TestHealthMinimalSchema           HLT-*    (実app_public /health)
    TestComposeDevFlagsAbsent         DOC-C-*  (docker-compose.ymlにdev flag 0件の静的検査)

実行:
    cd backend && ../venv/bin/python -m pytest tests/test_phase2c_public_hardening.py -v

注意: app_public のmodule importは実ハザードデータを読み込むため数十秒かかる
（test_phase2b1_entrypoint_boundary.pyの既存コメントと同一事情）。本ファイルは
app_operator/test_phase2b3_operator_security.pyと同じ方針で、1プロセス内で
一度だけimportし、複数testで使い回す（DOC-D-*のみ、development flagの検証に
別プロセスでの再importを要するためsubprocessを使う）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
INTROSPECT_SCRIPT = Path(__file__).resolve().parent / "_phase2b1_introspect_app_public.py"
SUBPROCESS_TIMEOUT_SECONDS = 180

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app_public  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from ._testclient_compat import TestClient  # noqa: E402

from app_config_properties import (  # noqa: E402
    CorsConfigError,
    parse_cors_origins,
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app_public.app)


def _run_introspect(env_overrides: Dict[str, str]) -> Dict[str, Any]:
    env = os.environ.copy()
    env.update(env_overrides)
    proc = subprocess.run(
        [sys.executable, str(INTROSPECT_SCRIPT)],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    assert proc.returncode == 0, (
        f"app_public introspection subprocess failed (exit={proc.returncode}).\n"
        f"stdout(tail)={proc.stdout[-2000:]}\nstderr(tail)={proc.stderr[-4000:]}"
    )
    last_line = proc.stdout.strip().splitlines()[-1]
    return json.loads(last_line)


def _run_import_only(env_overrides: Dict[str, str]) -> subprocess.CompletedProcess:
    """app_public を `python -c "import app_public"` で別プロセスimportする。

    起動時fail-closed（CorsConfigErrorがそのまま伝播してexit != 0になる）を
    検証するためだけに使う（route一覧は不要）。
    """
    env = os.environ.copy()
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", "import app_public; print('IMPORT_OK')"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )


# ============================================================
# CRS-U: parse_cors_origins() 単体検証（app import不要、高速）
# ============================================================


class TestCorsOriginParserUnit:
    """AT-08 第6.1節: exact-origin allowlist parserのpositive/negative。"""

    def test_crs_u_p01_unset_is_empty_allowlist(self):
        assert parse_cors_origins(None) == []

    def test_crs_u_p02_empty_string_is_empty_allowlist(self):
        assert parse_cors_origins("") == []

    def test_crs_u_p03_whitespace_only_is_empty_allowlist(self):
        assert parse_cors_origins("   ") == []

    def test_crs_u_p04_single_valid_origin(self):
        assert parse_cors_origins("https://example.com") == ["https://example.com"]

    def test_crs_u_p05_valid_origin_with_port(self):
        assert parse_cors_origins("http://localhost:5173") == ["http://localhost:5173"]

    def test_crs_u_p06_multiple_valid_origins(self):
        assert parse_cors_origins("https://a.example.com,https://b.example.com") == [
            "https://a.example.com",
            "https://b.example.com",
        ]

    def test_crs_u_p07_scheme_and_host_normalized_lowercase(self):
        assert parse_cors_origins("HTTPS://Example.COM") == ["https://example.com"]

    def test_crs_u_p08_ipv4_and_ipv6_hosts_allowed(self):
        assert parse_cors_origins("http://127.0.0.1:8080") == ["http://127.0.0.1:8080"]
        assert parse_cors_origins("http://[::1]:8080") == ["http://[::1]:8080"]

    @pytest.mark.parametrize(
        "raw,case_id",
        [
            ("*", "wildcard_only"),
            ("https://*.example.com", "wildcard_subdomain"),
            ("https://example.com/*", "wildcard_path"),
            ("null", "literal_null"),
            ("NULL", "literal_null_uppercase"),
            ("example.com", "no_scheme"),
            ("//example.com", "no_scheme_protocol_relative"),
            ("ftp://example.com", "non_http_scheme"),
            ("ws://example.com", "non_http_scheme_ws"),
            ("https://", "no_host"),
            ("https://example.com/path", "with_path"),
            ("https://example.com?x=1", "with_query"),
            ("https://example.com#frag", "with_fragment"),
            ("https://user@example.com", "with_userinfo"),
            ("https://user:pass@example.com", "with_userinfo_password"),
            (" https://example.com", "leading_whitespace"),
            ("https://example.com ", "trailing_whitespace"),
            ("https://exam ple.com", "internal_whitespace"),
            ("https://example.com\t", "trailing_tab"),
            ("https://example.com\r\nX-Injected: 1", "crlf_injection"),
        ],
    )
    def test_crs_u_n_single_invalid_origin_rejected(self, raw, case_id):
        # 単体要素として不正な構文（wildcard/null/scheme欠落/path付き等）を
        # 検証する。"" や空白のみの値そのものは（parse_cors_origins全体への
        # 入力として見た場合）空allowlistという正当な意味を持つため、ここでは
        # 単体要素の構文チェック（wildcard・null・path等の構造違反）だけを
        # 対象にする（空要素はtest_crs_u_n_empty_element_in_list_rejectedで
        # リスト内要素として別途検証する）。
        with pytest.raises(CorsConfigError):
            parse_cors_origins(raw)

    def test_crs_u_n_prefix_match_not_silently_accepted(self):
        # "https://example.com" 単体は valid だが、prefix/substring一致を
        # 許可する実装ではないことを、別ホストとして拒否されない=正しい形で確認する。
        assert parse_cors_origins("https://example.com") == ["https://example.com"]
        # "https://example.com.evil.com" は example.com の suffix一致ではなく、
        # 別の正当なexact originとして扱われる（構文上は妥当だが example.com とは別値）。
        parsed = parse_cors_origins("https://example.com.evil.com")
        assert parsed == ["https://example.com.evil.com"]
        assert "https://example.com" not in parsed or parsed == ["https://example.com.evil.com"]

    def test_crs_u_n_empty_element_in_list_rejected(self):
        with pytest.raises(CorsConfigError):
            parse_cors_origins("https://a.example.com,,https://b.example.com")

    def test_crs_u_n_trailing_slash_rejected_not_silently_stripped(self):
        with pytest.raises(CorsConfigError):
            parse_cors_origins("https://example.com/")

    def test_crs_u_n_duplicate_origin_rejected(self):
        with pytest.raises(CorsConfigError):
            parse_cors_origins("https://example.com,https://example.com")

    def test_crs_u_n_duplicate_origin_after_normalization_rejected(self):
        with pytest.raises(CorsConfigError):
            parse_cors_origins("https://example.com,HTTPS://EXAMPLE.COM")

    def test_crs_u_n_control_character_rejected(self):
        with pytest.raises(CorsConfigError):
            parse_cors_origins("https://example.com\x00")

    def test_crs_u_n_second_element_invalid_rejects_whole_value(self):
        """1件だけ不正でも読み飛ばさず全体をfail-closedにする（黙示補正の禁止）。"""
        with pytest.raises(CorsConfigError):
            parse_cors_origins("https://good.example.com,not-a-valid-origin")


# ============================================================
# CRS-I: 実app_public起動時のfail-closed統合検証（subprocess）
# ============================================================


class TestCorsFailClosedIntegration:
    """AT-08: 実際のapp_public importが、不正なcors.allow_origins設定で
    緩いfallbackへ倒れず起動そのものをfail-closedで停止することを確認する。"""

    def _run_with_cors_env(self, tmp_path, cors_value: str) -> subprocess.CompletedProcess:
        # 既存app.propertiesをコピーしてcors.allow_originsだけを上書きした
        # 一時propertiesを作り、APP_PROPERTIES_FILEで差し替える
        # （app_config_properties.resolve_config_pathの既存契約を利用）。
        original = (BACKEND_DIR / "app.properties").read_text(encoding="utf-8")
        lines = [
            line for line in original.splitlines()
            if not line.startswith("cors.allow_origins=")
        ]
        lines.append(f"cors.allow_origins={cors_value}")
        temp_props = tmp_path / "app.properties"
        temp_props.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return _run_import_only({"APP_PROPERTIES_FILE": str(temp_props)})

    def test_crs_i_n01_wildcard_config_fails_closed(self, tmp_path):
        proc = self._run_with_cors_env(tmp_path, "*")
        assert proc.returncode != 0, "cors.allow_origins=* でapp_publicのimportが成功してしまった"
        assert "IMPORT_OK" not in proc.stdout

    def test_crs_i_n02_path_suffix_config_fails_closed(self, tmp_path):
        proc = self._run_with_cors_env(tmp_path, "https://example.com/admin")
        assert proc.returncode != 0
        assert "IMPORT_OK" not in proc.stdout

    def test_crs_i_n03_leading_whitespace_via_real_properties_file_fails_closed(self, tmp_path):
        """CODEX第1ラウンドP2C-CX-002回帰: `load_properties()`の`.strip()`が
        原因で、前後空白付きoriginが実配線ではfail-closedへ到達しなかった
        （parser単体testだけがPASSし、production config読み込み経路は
        素通りしていた）。`load_raw_property_value()`導入後は実file経由でも
        必ずfail-closedになることを確認する。"""
        proc = self._run_with_cors_env(tmp_path, " https://example.com")
        assert proc.returncode != 0, (
            "cors.allow_origins= https://example.com（先頭に空白）で"
            "app_publicのimportが成功してしまった（P2C-CX-002の回帰）"
        )
        assert "IMPORT_OK" not in proc.stdout

    def test_crs_i_n04_trailing_tab_via_real_properties_file_fails_closed(self, tmp_path):
        proc = self._run_with_cors_env(tmp_path, "https://example.com\t")
        assert proc.returncode != 0, (
            "cors.allow_origins=https://example.com\\t（末尾tab）で"
            "app_publicのimportが成功してしまった（P2C-CX-002の回帰）"
        )
        assert "IMPORT_OK" not in proc.stdout

    def test_crs_i_p01_valid_explicit_origin_starts_successfully(self, tmp_path):
        proc = self._run_with_cors_env(tmp_path, "https://example.com")
        assert proc.returncode == 0, proc.stderr[-2000:]
        assert "IMPORT_OK" in proc.stdout

    def test_crs_i_p02_empty_config_starts_successfully(self, tmp_path):
        proc = self._run_with_cors_env(tmp_path, "")
        assert proc.returncode == 0, proc.stderr[-2000:]
        assert "IMPORT_OK" in proc.stdout


# ============================================================
# CRS-R: 実CORSMiddlewareを使った4基本パターン + negative
#
# app_public.py と全く同じ配線（parse_cors_origins → CORSMiddleware）を
# 最小のprobe appへ適用し、実HTTPレベルで検証する。実app_public.app
# （実ハザードデータを読み、CORS設定を書き換えられない）を毎回再importする
# 代わりにこの構成を使う——production配線と検証対象のmiddleware実装は
# app_public.pyと完全に同一であり、差分はhandlerの中身だけである。
# ============================================================


def _build_probe_app(
    origins: List[str],
    methods: List[str] = None,
    headers: List[str] = None,
    credentials: bool = False,
) -> FastAPI:
    probe = FastAPI()
    probe.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=credentials,
        allow_methods=methods or ["GET", "POST", "OPTIONS"],
        allow_headers=headers or ["Content-Type"],
    )

    @probe.get("/probe")
    def _get_probe():
        return {"ok": True}

    @probe.post("/probe")
    def _post_probe():
        return {"ok": True}

    return probe


ALLOWED_ORIGIN = "https://allowed.example.com"
DISALLOWED_ORIGIN = "https://not-allowed.example.com"


@pytest.fixture()
def probe_client_with_allowlist() -> TestClient:
    app_instance = _build_probe_app(parse_cors_origins(ALLOWED_ORIGIN))
    return TestClient(app_instance)


@pytest.fixture()
def probe_client_empty_allowlist() -> TestClient:
    app_instance = _build_probe_app(parse_cors_origins(""))
    return TestClient(app_instance)


class TestCorsRuntimeFourPatterns:
    """AT-08 第6.3節: 4基本パターンの期待値をprobe appで実測する。"""

    # --- パターン1: same-origin / Originなし ---
    def test_crs_r_pattern1_no_origin_header_succeeds_without_cors_headers(
        self, probe_client_with_allowlist
    ):
        r = probe_client_with_allowlist.get("/probe")
        assert r.status_code == 200
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers.keys()}

    # --- パターン2: 明示許可origin ---
    def test_crs_r_pattern2_preflight_from_allowed_origin_succeeds(
        self, probe_client_with_allowlist
    ):
        r = probe_client_with_allowlist.options(
            "/probe",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
        assert "*" not in (r.headers.get("access-control-allow-origin") or "")
        assert r.headers.get("vary") is not None and "origin" in r.headers["vary"].lower()

    def test_crs_r_pattern2_actual_request_from_allowed_origin_has_exact_acao(
        self, probe_client_with_allowlist
    ):
        r = probe_client_with_allowlist.get("/probe", headers={"Origin": ALLOWED_ORIGIN})
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN

    # --- パターン3: 非許可origin ---
    def test_crs_r_pattern3_preflight_from_disallowed_origin_is_not_successful(
        self, probe_client_with_allowlist
    ):
        r = probe_client_with_allowlist.options(
            "/probe",
            headers={
                "Origin": DISALLOWED_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert r.status_code != 200
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers.keys()}

    def test_crs_r_pattern3_simple_request_from_disallowed_origin_processed_but_no_acao(
        self, probe_client_with_allowlist
    ):
        # サーバー自体はrequestを処理する（simple GETなのでpreflight不要）が、
        # ACAOを付与しないためbrowser側は結果を読み取れない、という区別を確認する。
        r = probe_client_with_allowlist.get("/probe", headers={"Origin": DISALLOWED_ORIGIN})
        assert r.status_code == 200  # サーバーは処理している
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers.keys()}

    # --- パターン4: allowlist未設定/空 ---
    def test_crs_r_pattern4_empty_allowlist_preflight_not_successful(
        self, probe_client_empty_allowlist
    ):
        r = probe_client_empty_allowlist.options(
            "/probe",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert r.status_code != 200
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers.keys()}

    def test_crs_r_pattern4_empty_allowlist_same_origin_style_request_still_succeeds(
        self, probe_client_empty_allowlist
    ):
        r = probe_client_empty_allowlist.get("/probe")
        assert r.status_code == 200

    # --- 追加negative（第6.3節末尾）---
    def test_crs_r_neg_origin_null_literal_not_matched(self, probe_client_with_allowlist):
        r = probe_client_with_allowlist.get("/probe", headers={"Origin": "null"})
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers.keys()}

    def test_crs_r_neg_prefix_of_allowed_origin_not_matched(self, probe_client_with_allowlist):
        r = probe_client_with_allowlist.get(
            "/probe", headers={"Origin": "https://allowed.example.com.evil.com"}
        )
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers.keys()}

    def test_crs_r_neg_suffix_of_allowed_origin_not_matched(self, probe_client_with_allowlist):
        r = probe_client_with_allowlist.get(
            "/probe", headers={"Origin": "https://evil-allowed.example.com"}
        )
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers.keys()}

    def test_crs_r_neg_different_scheme_not_matched(self, probe_client_with_allowlist):
        r = probe_client_with_allowlist.get(
            "/probe", headers={"Origin": "http://allowed.example.com"}
        )
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers.keys()}

    def test_crs_r_neg_different_port_not_matched(self, probe_client_with_allowlist):
        r = probe_client_with_allowlist.get(
            "/probe", headers={"Origin": "https://allowed.example.com:8443"}
        )
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers.keys()}

    def test_crs_r_neg_case_difference_not_matched_verbatim(self, probe_client_with_allowlist):
        # ブラウザは常に正規化済み小文字schemeでOriginヘッダを送るため、この
        # テストは「configの正規化」ではなく「middleware側は大文字小文字を
        # 区別してexact matchする」ことの確認（fail-openでないことの傍証）。
        r = probe_client_with_allowlist.get(
            "/probe", headers={"Origin": "https://ALLOWED.EXAMPLE.COM"}
        )
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers.keys()}

    def test_crs_r_neg_multiple_origin_headers_not_matched(self, probe_client_with_allowlist):
        # httpxではheadersは単一値指定のみ可能なため、複数Originを1つの
        # comma区切り値として送りexact matchしないことを確認する
        # （実サーバーがCRLF等で複数Originヘッダを受理してもfail-openしない
        # ことの近似的検証）。
        r = probe_client_with_allowlist.get(
            "/probe",
            headers={"Origin": f"{ALLOWED_ORIGIN}, {DISALLOWED_ORIGIN}"},
        )
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers.keys()}

    def test_crs_r_credentials_false_by_default_no_acac_header(
        self, probe_client_with_allowlist
    ):
        r = probe_client_with_allowlist.get("/probe", headers={"Origin": ALLOWED_ORIGIN})
        assert r.headers.get("access-control-allow-credentials") is None

    def test_crs_r_wildcard_and_credentials_combination_not_used_in_production_wiring(self):
        # production配線（app_public.py）はwildcard originを構造的に受け付けない
        # （parse_cors_originsがCorsConfigErrorを送出する）ため、
        # 「allow_credentials有効時にwildcard origin」という組合せ自体が
        # 発生し得ないことをCRS-U側のnegativeテストと合わせて構造的に保証する。
        with pytest.raises(CorsConfigError):
            parse_cors_origins("*")


class TestCorsProductionWiringMatchesRealApp:
    """実app_public.appの実際の設定値が、production既定契約
    （空allowlist・credentials=false・GET,POST,OPTIONS・Content-Type）と
    一致することを確認する（probe appでの検証が本物の配線とずれていないか
    の橋渡し）。"""

    def test_real_app_default_cors_config_values(self):
        assert app_public.CORS_ALLOW_ORIGINS == []
        assert app_public.CORS_ALLOW_CREDENTIALS is False
        assert set(app_public.CORS_ALLOW_METHODS) == {"GET", "POST", "OPTIONS"}
        assert app_public.CORS_ALLOW_HEADERS == ["Content-Type"]

    def test_real_app_same_origin_request_unaffected(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_real_app_cross_origin_preflight_not_successful_with_default_empty_allowlist(
        self, client
    ):
        r = client.options(
            "/api/evacuation",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert r.status_code != 200
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers.keys()}


# ============================================================
# DOC-P: production既定でdocs/OpenAPIがpublic route table 0件（実app_public）
# ============================================================


class TestDocsProductionDefault:
    """AT-04: production既定でFastAPI docs系4routeが登録されない。"""

    DOC_PATHS = ["/docs", "/docs/", "/redoc", "/redoc/", "/openapi.json", "/openapi.json/",
                 "/docs/oauth2-redirect"]

    def test_doc_p01_docs_url_disabled_on_app_instance(self):
        assert app_public.app.docs_url is None
        assert app_public.app.redoc_url is None
        assert app_public.app.openapi_url is None

    def test_doc_p02_no_docs_paths_in_route_table(self):
        paths = {getattr(r, "path", None) for r in app_public.app.routes}
        for doc_path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
            assert doc_path not in paths, f"{doc_path} が production route tableに存在する"

    @pytest.mark.parametrize("path", DOC_PATHS)
    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
    def test_doc_p03_docs_paths_return_404_for_get_head(self, client, path, method):
        if method == "OPTIONS":
            # 素のOPTIONS（Originヘッダなし = preflightではない）は通常routing
            # を通るため404になる。CORS preflight自体の挙動はCRS-Rで別途検証する。
            r = client.options(path)
        else:
            r = client.request(method, path)
        assert r.status_code == 404, f"{method} {path} が404ではない: {r.status_code}"


class TestDocsDevelopmentModeToggle:
    """AT-04 第3.2節: development限定の二重条件positive/negative（subprocess）。"""

    def test_doc_d_p01_both_flags_true_enables_docs(self):
        introspection = _run_introspect(
            {"OHG2_DEV_MODE": "true", "OHG2_DEV_DOCS_ENABLED": "true"}
        )
        paths = {p for p, _m in introspection["routes"]}
        for doc_path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
            assert doc_path in paths, f"development flag有効時に{doc_path}が登録されていない"
        # docs以外のadmin/simulation/operator routeは増えない
        modules = set(introspection["modules"])
        forbidden = {
            "app.api.admin", "app.api.admin_config", "app.api.admin_datasets",
            "app.api.admin_upload", "app.api.layer_types_api", "app.api.simulation",
            "app.services.pipeline_service", "app.services.job_manager", "app_operator",
        }
        assert not (modules & forbidden), f"development docs有効化で禁止moduleが増えた: {modules & forbidden}"

    @pytest.mark.parametrize(
        "env,case_id",
        [
            ({}, "both_unset"),
            ({"OHG2_DEV_MODE": "true"}, "only_dev_mode"),
            ({"OHG2_DEV_DOCS_ENABLED": "true"}, "only_dev_docs"),
            ({"OHG2_DEV_MODE": "", "OHG2_DEV_DOCS_ENABLED": ""}, "both_empty"),
            ({"OHG2_DEV_MODE": "   ", "OHG2_DEV_DOCS_ENABLED": "   "}, "both_whitespace"),
            ({"OHG2_DEV_MODE": "false", "OHG2_DEV_DOCS_ENABLED": "true"}, "dev_mode_false_conflict"),
            ({"OHG2_DEV_MODE": "TRUE", "OHG2_DEV_DOCS_ENABLED": "1"}, "docs_flag_wrong_value_not_literal_true"),
            ({"OHG2_DEV_MODE": "yes", "OHG2_DEV_DOCS_ENABLED": "yes"}, "bool_like_but_not_literal_true"),
        ],
    )
    def test_doc_d_n_incomplete_or_invalid_flags_keep_docs_disabled(self, env, case_id):
        introspection = _run_introspect(env)
        paths = {p for p, _m in introspection["routes"]}
        for doc_path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
            assert doc_path not in paths, (
                f"case={case_id} env={env} でdocsが意図せず有効化された: {doc_path}"
            )


# ============================================================
# OBS: metrics/diagnostics/admin/simulation 経路の遮断（実app_public route table）
# ============================================================


class TestObservabilityRouteDenylist:
    """AT-04（docsと合わせた広義のobservability遮断）第4節。

    固定期待表（本テストが検証する契約）:
      GET/HEAD 各pathへの素のrequest              -> 404（route table 0件のため通常routing miss）
      OPTIONS（Originヘッダなし、非preflight）    -> 404（同上）
      OPTIONS（Origin+ACRMヘッダ付き、preflight） -> CORSMiddlewareが横取りし、
                                                       既定空allowlistのため必ず非成功（400）。
                                                       path自体の存在有無に関わらず一律の挙動であり
                                                       route存在を区別する情報を漏らさない。
    """

    DENY_PATHS = [
        "/metrics", "/metrics/", "/diagnostics", "/diagnostics/",
        "/api/metrics", "/api/metrics/", "/api/diagnostics", "/api/diagnostics/",
        "/admin", "/admin/", "/api/admin", "/api/admin/",
        "/simulation", "/simulation/", "/api/simulation", "/api/simulation/",
    ]

    def test_obs_route_table_has_zero_matches(self):
        registered_paths = {getattr(r, "path", None) for r in app_public.app.routes}
        for deny_path in self.DENY_PATHS:
            normalized = deny_path.rstrip("/") or "/"
            assert normalized not in registered_paths, f"{deny_path} がpublic route tableに存在する"

    @pytest.mark.parametrize("path", DENY_PATHS)
    @pytest.mark.parametrize("method", ["GET", "HEAD"])
    def test_obs_deny_paths_return_404(self, client, path, method):
        r = client.request(method, path)
        assert r.status_code == 404, f"{method} {path} が404ではない: {r.status_code}"

    @pytest.mark.parametrize("path", DENY_PATHS)
    def test_obs_deny_paths_plain_options_return_404(self, client, path):
        r = client.options(path)
        assert r.status_code == 404, f"OPTIONS {path}（非preflight）が404ではない: {r.status_code}"

    @pytest.mark.parametrize("path", DENY_PATHS)
    def test_obs_deny_paths_preflight_options_not_successful_and_uninformative(self, client, path):
        r = client.options(
            path,
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "GET",
            },
        )
        # production既定はcors.allow_origins空のため、pathの実在有無に関わらず
        # 常に非成功（一様な挙動 = route存在を区別する情報を漏らさない）。
        assert r.status_code != 200
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers.keys()}

    def test_obs_response_bodies_do_not_leak_internal_details(self, client):
        for path in self.DENY_PATHS:
            r = client.get(path)
            body_text = r.text.lower()
            for leak_marker in ("traceback", "/app/", "/backend/", str(BACKEND_DIR).lower()):
                assert leak_marker not in body_text, f"{path} のresponseに内部情報が含まれる: {leak_marker}"


# ============================================================
# HLT: public /health 最小schema
# ============================================================


class TestHealthMinimalSchema:
    """AT-07: public /health が厳密に {"status"} 1-keyだけを返す。"""

    def test_hlt_p01_get_returns_200_json(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/json")

    def test_hlt_p02_exact_key_set_is_status_only(self, client):
        body = client.get("/health").json()
        assert set(body.keys()) == {"status"}

    def test_hlt_p03_status_value_is_enumerated_fixed_value(self, client):
        body = client.get("/health").json()
        assert body["status"] in ("ok", "degraded")
        assert isinstance(body["status"], str)

    def test_hlt_p04_cache_disabled(self, client):
        r = client.get("/health")
        cache_control = r.headers.get("cache-control", "")
        assert "no-store" in cache_control.lower()

    def test_hlt_p05_head_matches_get_status_no_body(self, client):
        get_response = client.get("/health")
        head_response = client.head("/health")
        assert head_response.status_code == get_response.status_code
        assert head_response.content == b""

    def test_hlt_n01_post_method_not_allowed_no_internal_leak(self, client):
        r = client.post("/health")
        assert r.status_code == 405
        body_text = r.text.lower()
        for leak_marker in ("traceback", "dem_path", "/app/", "/backend/"):
            assert leak_marker not in body_text

    def test_hlt_n02_no_forbidden_fields_present(self, client):
        body = client.get("/health").json()
        forbidden_fields = {
            "role", "service", "app", "version", "commit", "branch", "build_timestamp",
            "hostname", "container_id", "pid", "process_id",
            "dataset", "datasets", "dem_loaded", "dem_path", "hazard_loaded",
            "hazard_polygon_counts", "hazard_sources", "tsunami_coverage",
            "shelters_loaded", "exception", "stack_trace", "config", "environment",
        }
        assert not (set(body.keys()) & forbidden_fields)

    def test_hlt_n03_operator_health_contract_untouched(self):
        """operator専用の`/operator/health`（{"status","role"}契約）は
        本節の対象外であり、public appにも登録されていないことを確認する
        （混同防止）。"""
        paths = {getattr(r, "path", None) for r in app_public.app.routes}
        assert "/operator/health" not in paths


# ============================================================
# 静的検査: nginx.conf / docker-compose.yml
# ============================================================


class TestNginxStaticConfig:
    """DOC-N/OBS-N/HLT-N: nginx.confへ二層目の遮断・healthのexact proxyが
    実際に記述されていることを静的に検証する（実nginxプロセスの起動は
    heavy regression gate側の責務であり、本testはconfig内容の存在検査のみ）。"""

    @pytest.fixture(scope="class")
    def nginx_conf_text(self) -> str:
        return (REPO_ROOT / "nginx.conf").read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "exact_path",
        ["/docs", "/redoc", "/openapi.json", "/metrics", "/diagnostics",
         "/api/metrics", "/api/diagnostics"],
    )
    def test_doc_obs_n_explicit_404_block_present(self, nginx_conf_text, exact_path):
        marker = f"location = {exact_path} {{"
        assert marker in nginx_conf_text, f"nginx.confに `{marker}` の明示blockが見つからない"
        # 同一block内で404を返していることを大まかに確認
        idx = nginx_conf_text.index(marker)
        block = nginx_conf_text[idx: idx + 120]
        assert "return 404" in block

    def test_hlt_n_health_exact_proxy_present(self, nginx_conf_text):
        assert "location = /health {" in nginx_conf_text
        idx = nginx_conf_text.index("location = /health {")
        block = nginx_conf_text[idx: idx + 200]
        assert "proxy_pass http://backend:8000/health" in block

    def test_crs_n_api_location_has_no_nginx_level_cors_header(self, nginx_conf_text):
        """CODEX第1ラウンドP2C-CX-001回帰: `location /api/`がnginx独自の
        wildcard CORS header・OPTIONS短絡を持たず、backendのCORSMiddleware
        （第6節）へ全requestを委譲していることを確認する。"""
        marker = "location /api/ {"
        assert marker in nginx_conf_text, "nginx.confに `location /api/` が見つからない"
        idx = nginx_conf_text.index(marker)
        # 次のlocation blockが始まる直前までを対象にする
        next_location_idx = nginx_conf_text.index("\n    location ", idx + len(marker))
        block = nginx_conf_text[idx:next_location_idx]
        assert "Access-Control-Allow-Origin" not in block, (
            "location /api/ がnginx独自のCORS headerを付与している（P2C-CX-001の回帰）"
        )
        assert "request_method = 'OPTIONS'" not in block, (
            "location /api/ がOPTIONSを短絡してbackendへ到達させていない（P2C-CX-001の回帰）"
        )
        assert "proxy_pass http://backend:8000/api/;" in block

    def test_doc_obs_n_admin_simulation_blocks_still_present_unmodified(self, nginx_conf_text):
        # Phase 2-B accepted設計を再オープンしないことの確認（回帰チェック）。
        for path in ("/admin", "/api/admin", "/api/simulation"):
            assert f"location = {path} {{" in nginx_conf_text


class TestComposeDevFlagsAbsent:
    """DOC-C: public/operator既定profileにdevelopment指定が0件（第3.2節）。"""

    def test_compose_has_no_dev_docs_flags(self):
        compose_text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        assert "OHG2_DEV_MODE" not in compose_text
        assert "OHG2_DEV_DOCS_ENABLED" not in compose_text
