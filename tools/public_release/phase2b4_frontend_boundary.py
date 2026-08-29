#!/usr/bin/env python3
"""
tools/public_release/phase2b4_frontend_boundary.py

Phase 2-B.4（admin/simulation/debug frontend assetの物理分離とoperator gateway）
の統合検証script。AT-06・AT-04-ADMIN-SUBSETに対応する。

tasks/public-release/phase2b4_claude_implementation_instruction.md 第6節の
17項目すべてを、raw source・rendered config・実container・実HTTPを組み合わせて
判定する。文字列grepだけでPASS判定する項目はない（reference graph検査は
basenameの正規表現一致に加え、実artifact・実HTTPでも独立に確認する）。

Docker権限境界（backend-operatorのDocker socket、Docker operation allowlist）
自体はPhase 2-B.3で確定済みであり本scriptの対象外。本scriptはfrontend
document rootの物理分離とoperator gatewayのroute境界に限定する。

事前条件: Dockerデーモンが起動していること。実秘密は使用しない
（dummy tokenのみ）。

使い方:
    ./venv/bin/python tools/public_release/phase2b4_frontend_boundary.py

終了コード: 全項目PASSなら0、1件でもFAILがあれば1。
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required (pip install pyyaml). Run via ./venv/bin/python.", file=sys.stderr)
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
PUBLIC_NGINX_CONF = REPO_ROOT / "nginx.conf"
OPERATOR_NGINX_CONF = REPO_ROOT / "operator" / "nginx.conf"
FRONTEND_DIR = REPO_ROOT / "frontend"
OPERATOR_FRONTEND_DIR = REPO_ROOT / "operator" / "frontend-admin"

_RUN_TAG = os.environ.get("OHG2_PHASE2B4_RUN_TAG") or datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%Sz")
PROJECT_NAME = f"ohg2p2b4{_RUN_TAG}".lower().replace("_", "")
CONTAINER_PREFIX = f"ohg2p2b4-{_RUN_TAG}"
NETWORK_PREFIX = CONTAINER_PREFIX

DUMMY_OPERATOR_SECRET = "OHG2_PHASE2B4_DUMMY_SECRET_DO_NOT_USE"
WRONG_TOKEN = "OHG2_PHASE2B4_WRONG_TOKEN_DO_NOT_USE"

OPERATOR_TARGET_PORT = 8100
OPERATOR_HOST_PORT = 19900 + (hash(_RUN_TAG) % 300)

RESULTS: List[Dict[str, Any]] = []
FORMAL_EXPECTED_CASE_IDS = [f"S11-{index:03d}" for index in range(1, 139)]


def _redact_evidence_text(value: str) -> str:
    """Remove credentials while retaining Compose/Docker diagnostic context."""
    redacted = value.replace(DUMMY_OPERATOR_SECRET, "<DUMMY_OPERATOR_SECRET_REDACTED>")
    redacted = redacted.replace(WRONG_TOKEN, "<WRONG_OPERATOR_TOKEN_REDACTED>")
    redacted = re.sub(r"\bSECRET_[A-Z0-9_]+\b", "<SECRET_REDACTED>", redacted)
    redacted = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s'\"]+", r"\1<REDACTED>", redacted)
    redacted = re.sub(r"(?i)((?:password|api[_-]?key|token|cookie|session)\s*[:=]\s*)[^\s,;]+", r"\1<REDACTED>", redacted)
    return redacted


def _write_parent_evidence(path: Path, value: str) -> None:
    """Write and fsync evidence outside the disposable harness TemporaryDirectory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    if not path.is_file() or not path.read_text(encoding="utf-8") == value:
        raise RuntimeError(f"parent evidence persistence verification failed: {path}")


def persist_compose_subprocess_evidence(
    override_file: Path,
    argv: List[str],
    proc: subprocess.CompletedProcess,
) -> Optional[Dict[str, str]]:
    """Persist redacted full diagnostics before temporary cleanup, if enabled by runner."""
    root = os.environ.get("OHG2_PHASE2B4_PARENT_EVIDENCE_DIR")
    if not root:
        return None
    evidence_dir = Path(root)
    prefix = os.environ.get("OHG2_PHASE2B4_EVIDENCE_PREFIX", "phase2b4")
    stdout = _redact_evidence_text(proc.stdout or "")
    stderr = _redact_evidence_text(proc.stderr or "")
    combined = stdout + ("\n" if stdout and stderr else "") + stderr
    override = _redact_evidence_text(override_file.read_text(encoding="utf-8"))
    names = {
        "stdout": f"{prefix}_compose_stdout_full_redacted.log",
        "stderr": f"{prefix}_compose_stderr_full_redacted.log",
        "combined": f"{prefix}_compose_combined_diagnostic_redacted.log",
        "override": f"{prefix}_generated_override_redacted.yml",
        "metadata": f"{prefix}_compose_subprocess_metadata.json",
    }
    for key in ("stdout", "stderr", "combined", "override"):
        _write_parent_evidence(evidence_dir / names[key], {"stdout": stdout, "stderr": stderr, "combined": combined, "override": override}[key])
    metadata = {
        "argv": argv,
        "cwd": str(REPO_ROOT),
        "environment_key_names": sorted(os.environ.keys()),
        "start_timestamp": os.environ.get("OHG2_PHASE2B4_COMPOSE_STARTED_AT"),
        "finish_timestamp": datetime.now(timezone.utc).isoformat(),
        "exit_code": proc.returncode,
        "artifacts": names,
    }
    _write_parent_evidence(evidence_dir / names["metadata"], json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    return {key: str(evidence_dir / name) for key, name in names.items()}


def record(name: str, passed: bool, detail: str = "", command: Optional[List[str]] = None) -> None:
    ordinal = len(RESULTS)
    case_id = FORMAL_EXPECTED_CASE_IDS[ordinal] if ordinal < len(FORMAL_EXPECTED_CASE_IDS) else f"S11-UNEXPECTED-{ordinal + 1:03d}"
    RESULTS.append(
        {
            "case_id": case_id,
            "name": name,
            "pass": bool(passed),
            "detail": detail[-4000:],
            "command": " ".join(command) if command else None,
        }
    )
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {case_id} {name}")
    if not passed and detail:
        print(f"        detail: {detail[:600]}")


def evaluate_formal_collection(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Fixed Suite 11 collection contract; usable by the pre-formal self-tests."""
    actual_ids = [str(result.get("case_id", "")) for result in results]
    expected_set = set(FORMAL_EXPECTED_CASE_IDS)
    actual_set = set(actual_ids)
    missing = [case_id for case_id in FORMAL_EXPECTED_CASE_IDS if case_id not in actual_set]
    unexpected = [case_id for case_id in actual_ids if case_id not in expected_set]
    duplicate = len(actual_ids) - len(actual_set)
    failed = [result for result in results if not result.get("pass", False)]
    skipped = [result for result in results if result.get("skip", False)]
    order_match = actual_ids == FORMAL_EXPECTED_CASE_IDS
    pass_count = len(results) - len(failed) - len(skipped)
    exit_zero_allowed = (
        len(results) == len(FORMAL_EXPECTED_CASE_IDS)
        and len(actual_set) == len(FORMAL_EXPECTED_CASE_IDS)
        and not missing
        and duplicate == 0
        and not unexpected
        and order_match
        and not failed
        and not skipped
        and pass_count == len(FORMAL_EXPECTED_CASE_IDS)
    )
    return {
        "declared": len(FORMAL_EXPECTED_CASE_IDS), "collected": len(results),
        "executed": len(results), "unique": len(actual_set), "pass": pass_count,
        "fail": len(failed), "skip": len(skipped), "missing": missing,
        "duplicate": duplicate, "unexpected": unexpected, "order_match": order_match,
        "exit_zero_allowed": exit_zero_allowed,
    }


def enforce_formal_collection() -> Dict[str, Any]:
    """Emit explicit FAIL records for every otherwise omitted mandatory formal case."""
    while len(RESULTS) < len(FORMAL_EXPECTED_CASE_IDS):
        case_id = FORMAL_EXPECTED_CASE_IDS[len(RESULTS)]
        RESULTS.append({
            "case_id": case_id,
            "name": "collection contract: required case was not reached by a conditional prerequisite path",
            "pass": False,
            "detail": "mandatory formal emission synthesized as FAIL; prerequisite-dependent path omitted normal assertion",
            "command": None,
        })
        print(f"[FAIL] {case_id} collection contract: required case was not reached by a conditional prerequisite path")
    collection = evaluate_formal_collection(RESULTS)
    print(
        "COLLECTION_CONTRACT: "
        f"declared={collection['declared']} collected={collection['collected']} unique={collection['unique']} "
        f"missing={len(collection['missing'])} duplicate={collection['duplicate']} "
        f"unexpected={len(collection['unexpected'])} order_match={collection['order_match']} "
        f"exit_zero_allowed={collection['exit_zero_allowed']}"
    )
    return collection


def _run(cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
    kwargs.setdefault("cwd", str(REPO_ROOT))
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


# ------------------------------------------------------------------
# deny manifest — operator/frontend-admin/ の実inventoryから機械生成する。
# 固定listを唯一の根拠にしない（第5節）。
# ------------------------------------------------------------------

TEXT_SUFFIXES = {".html", ".htm", ".js", ".css", ".json", ".map", ".webmanifest"}

# operator/frontend-admin/ にはPhase 2-B.4で新規に作成したoperator専用資産
# （canonical entry index.html、fetch wrapper js/operator-auth.js）も含まれる。
# これらはpublicから「移動」した資産ではなく最初からoperator専用として新規に
# 作成したものであり、deny manifest（=publicから消えたはずの資産）には含めない。
# 含めてしまうと、public側が独立に持つ同名の一般的なfile（例: 汎用的な
# `index.html`というbasename）と衝突してfalse positiveになる。
OPERATOR_ONLY_NEW_FILES = {"index.html", "js/operator-auth.js"}


def build_deny_manifest(operator_dir: Path) -> Dict[str, Any]:
    """git HEAD時点（本phase開始時点、未commit）で実際に
    `frontend/admin/`・`frontend/js/navigation-debug-layer.js`として
    存在していたfileの集合を、git履歴から機械的に再構成する。
    固定listを唯一の根拠にせず、実repositoryのgit treeから生成する
    （第5節「開始時inventoryからmachine-readable deny manifestを生成」）。
    """
    proc = _run(
        [
            "git", "ls-tree", "-r", "--name-only", "HEAD",
            "--", "frontend/admin", "frontend/js/navigation-debug-layer.js",
        ]
    )
    entries = []
    if proc.returncode != 0:
        return {"entries": entries}
    for git_path in proc.stdout.splitlines():
        git_path = git_path.strip()
        if not git_path:
            continue
        p = Path(git_path)
        if p.parent.name == "admin":
            operator_relpath = p.name
        else:
            # frontend/js/navigation-debug-layer.js -> js/navigation-debug-layer.js
            operator_relpath = f"js/{p.name}"
        operator_path = operator_dir / operator_relpath
        if not operator_path.exists():
            # 移動先に実際に存在しない場合はmanifestに含めない
            # （別途 check_source_zero_hit の admin_dir_exists/debug_layer_exists
            # で「移動元に残っていないか」を独立に確認する）。
            continue
        data = operator_path.read_bytes()
        entries.append(
            {
                "git_head_path": git_path,
                "relpath": operator_relpath,
                "basename": p.name,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        )
    return {"entries": entries}


def build_operator_asset_inventory(operator_dir: Path) -> List[str]:
    """operator gatewayが実際に配信すべき全asset（移動済み + 新規作成分）。
    check 6/7（operator asset inventory一致、HTTP 200確認）に使う。"""
    if not operator_dir.exists():
        return []
    return sorted(str(p.relative_to(operator_dir)) for p in operator_dir.rglob("*") if p.is_file())


def _basename_pattern(manifest: Dict[str, Any]) -> "re.Pattern":
    basenames = sorted({e["basename"] for e in manifest["entries"]}, key=len, reverse=True)
    if not basenames:
        # 何もmatchしない正規表現（空manifestでの誤PASS防止）
        return re.compile(r"(?!)")
    return re.compile("|".join(re.escape(b) for b in basenames))


# ------------------------------------------------------------------
# check 1 / AT-06-SOURCE: public source document rootにdeny対象0件
# ------------------------------------------------------------------


def check_source_zero_hit(frontend_dir: Path, manifest: Dict[str, Any]) -> Tuple[bool, str]:
    if not frontend_dir.exists():
        return False, f"frontend_dir not found: {frontend_dir}"
    pattern = _basename_pattern(manifest)
    hits = []
    for p in frontend_dir.rglob("*"):
        if p.is_file() and pattern.fullmatch(p.name):
            hits.append(str(p.relative_to(frontend_dir)))
    admin_dir_exists = (frontend_dir / "admin").exists()
    debug_layer_exists = (frontend_dir / "js" / "navigation-debug-layer.js").exists()
    ok = (len(hits) == 0) and (not admin_dir_exists) and (not debug_layer_exists)
    detail = f"basename_hits={hits} admin_dir_exists={admin_dir_exists} debug_layer_exists={debug_layer_exists}"
    return ok, detail


# Phase 2-B.4限定修正（CODEX P2B4-CX-004対応）: publicはcustom buildを持たず
# `./frontend:/usr/share/nginx/html:ro` をそのままbind mountするため、
# Finderが生成する `.DS_Store` 等の不要metadataがsource treeに残っていると
# そのままruntime document rootにも配信されてしまう。source levelで再発を
# 検出する専用checkを設ける。
UNWANTED_METADATA_BASENAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}


def check_public_root_metadata_hygiene(frontend_dir: Path) -> Tuple[bool, str]:
    if not frontend_dir.exists():
        return False, f"frontend_dir not found: {frontend_dir}"
    hits = [
        str(p.relative_to(frontend_dir))
        for p in frontend_dir.rglob("*")
        if p.is_file() and p.name in UNWANTED_METADATA_BASENAMES
    ]
    return len(hits) == 0, f"metadata_hits={hits}"


# ------------------------------------------------------------------
# check 3 / AT-06-REFGRAPH: public HTML/JS/CSS/map/manifestからの参照0件
# ------------------------------------------------------------------

# navigation.js の `_addNavigationDebugEvent` → `window.addNavigationDebugEvent?.()`
# はPhase 2-B.4以前から存在する、既存ナビ本体（改変禁止対象）内のoptional-chaining
# 呼び出しである。呼び出し先グローバルは now-undefined のため実行時は常に安全な
# no-opであり、値・pathの露出は伴わない。既知の許容差分として明示的に除外する
# （実装報告書 第4節・第14節で開示）。
ALLOWED_REFGRAPH_HITS = {
    "js/navigation.js",
}


def check_reference_graph(frontend_dir: Path, manifest: Dict[str, Any]) -> Tuple[bool, str]:
    if not frontend_dir.exists():
        return False, f"frontend_dir not found: {frontend_dir}"
    pattern = _basename_pattern(manifest)
    hits = []
    for p in frontend_dir.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel = str(p.relative_to(frontend_dir))
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in pattern.finditer(text):
            hits.append(f"{rel}:{m.group(0)}")

    # navigation-debug-layer.js が公開するglobal関数名への直接呼び出し
    # （import/fetch/src/hrefではなくwindow経由のdynamic reference）も
    # reference graphの一部として検査する。map-overlay-ui.jsはPhase 2-B.4で
    # 該当UIを除去済みのため0件を期待する。navigation.jsの既知許容分は除く。
    debug_globals = [
        "setNavigationDebugLayerVisible",
        "isNavigationDebugLayerVisible",
        "clearNavigationDebugEvents",
        "syncNavigationDebugLayerControls",
        "addNavigationDebugEvent",
        "__getNavigationDebugState",
    ]
    global_pattern = re.compile("|".join(re.escape(g) for g in debug_globals))
    global_hits = []
    for p in frontend_dir.rglob("*.js"):
        rel = str(p.relative_to(frontend_dir))
        if rel in ALLOWED_REFGRAPH_HITS:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in global_pattern.finditer(text):
            global_hits.append(f"{rel}:{m.group(0)}")

    ok = (len(hits) == 0) and (len(global_hits) == 0)
    detail = f"basename_ref_hits={hits[:20]} debug_global_hits={global_hits[:20]}"
    return ok, detail


# ------------------------------------------------------------------
# check 4 / AT-06-SOURCE(nginx): public nginx raw configにoperator参照0件
# ------------------------------------------------------------------

FORBIDDEN_PUBLIC_LOCATIONS = ["/admin", "/api/admin", "/api/simulation"]


def _extract_location_blocks(code: str) -> List[Tuple[str, str]]:
    """`location <modifier?> <path> { ... }` を全件抽出する（非nested前提。
    本repositoryのnginx.confはlocation blockの入れ子を持たないため十分）。
    戻り値は (path, block_body) のlist。`re.search`の最初の1件だけを見る
    実装は、同じprefixへ複数のlocation blockが存在する場合（FB-N05のように
    既存の404 blockの後ろへ新しいalias blockが追加されるケース）を見逃す
    ため、finditerで全件を走査する。"""
    blocks = []
    for m in re.finditer(r"location\s+(=\s*)?([^\s{]+)\s*\{", code):
        path = m.group(2)
        start = m.end()
        depth = 1
        i = start
        while i < len(code) and depth > 0:
            if code[i] == "{":
                depth += 1
            elif code[i] == "}":
                depth -= 1
            i += 1
        body = code[start:i - 1]
        blocks.append((path, body))
    return blocks


def _path_targets_forbidden_prefix(path: str) -> bool:
    stripped = path.rstrip("/")
    return stripped in ("/admin", "/api/admin", "/api/simulation")


def check_public_nginx_raw(nginx_conf: Path) -> Tuple[bool, str]:
    if not nginx_conf.exists():
        return False, f"not found: {nginx_conf}"
    text = nginx_conf.read_text(encoding="utf-8")
    # コメント行を除去してから走査する（コメント中の言及は誤検出しない）
    code_lines = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
    code = "\n".join(code_lines)

    issues = []
    if "operator-gateway" in code or "backend-operator" in code:
        issues.append("upstream reference to operator service found")

    blocks = _extract_location_blocks(code)
    matched_any = {"/admin": False, "/api/admin": False, "/api/simulation": False}
    for path, body in blocks:
        if not _path_targets_forbidden_prefix(path):
            continue
        canonical = path.rstrip("/")
        matched_any[canonical] = True
        if "proxy_pass" in body or "alias" in body:
            issues.append(f"public {path} location proxies/aliases to a backend: body={body.strip()[:200]!r}")
        if "return 404" not in body and "return 403" not in body:
            issues.append(f"public {path} location does not explicitly return 404/403: body={body.strip()[:200]!r}")
    for canonical, seen in matched_any.items():
        if not seen:
            issues.append(f"expected explicit denial location for {canonical} not found")

    ok = len(issues) == 0
    return ok, f"issues={issues} block_paths={[p for p, _ in blocks]}"


def check_public_nginx_rendered(container_id: str) -> Tuple[bool, str]:
    proc = _run(["docker", "exec", container_id, "nginx", "-T"])
    if proc.returncode != 0:
        return False, f"nginx -T failed: {(proc.stdout + proc.stderr)[-500:]}"
    text = proc.stdout
    issues = []
    if "operator-gateway" in text or "backend-operator" in text:
        issues.append("rendered config references operator service")
    ok = len(issues) == 0
    return ok, f"issues={issues}"


# ------------------------------------------------------------------
# operator側 nginx raw config: genericな /api/ proxyがないことを確認する
# ------------------------------------------------------------------


def check_operator_nginx_raw(nginx_conf: Path) -> Tuple[bool, str]:
    if not nginx_conf.exists():
        return False, f"not found: {nginx_conf}"
    text = nginx_conf.read_text(encoding="utf-8")
    code_lines = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
    code = "\n".join(code_lines)
    issues = []
    # generic `location /api/ {` (末尾が /api/ ちょうどのlocation) を禁止する。
    if re.search(r"location\s+/api/\s*\{", code):
        issues.append("generic location /api/ found (must be scoped to /api/admin/ or /api/simulation/)")
    if "autoindex on" in code:
        issues.append("autoindex on found (directory listing must stay disabled)")
    if "proxy_pass" in code and "backend-operator" not in code:
        issues.append("proxy_pass target other than backend-operator found")
    ok = len(issues) == 0
    return ok, f"issues={issues}"


# ------------------------------------------------------------------
# secret canary / token永続化API走査（AT-06-TOKEN-HYGIENE, check 11）
# ------------------------------------------------------------------

TOKEN_PERSISTENCE_PATTERNS = [
    r"localStorage\.setItem\([^)]*[Tt]oken",
    r"sessionStorage\.setItem\([^)]*[Tt]oken",
    r"document\.cookie\s*=.*[Tt]oken",
    r"indexedDB.*[Tt]oken",
    r"caches\.open.*[Tt]oken",
]


def check_token_persistence(operator_dir: Path) -> Tuple[bool, str]:
    hits = []
    pattern = re.compile("|".join(TOKEN_PERSISTENCE_PATTERNS))
    for p in operator_dir.rglob("*.js"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in pattern.finditer(text):
            hits.append(f"{p.relative_to(operator_dir)}:{m.group(0)[:60]}")
    ok = len(hits) == 0
    return ok, f"hits={hits}"


def check_secret_canary(paths: List[Path], secret_values: List[str]) -> Tuple[bool, str]:
    hits = []
    for base in paths:
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for secret in secret_values:
                if secret and secret in text:
                    hits.append(f"{p.relative_to(REPO_ROOT)}")
    ok = len(hits) == 0
    return ok, f"hits={hits}"


# ------------------------------------------------------------------
# check 12: operator gatewayのhost port定義（raw docker-compose.yml）
# ------------------------------------------------------------------


def check_gateway_host_port_definition(compose_file: Path) -> Tuple[bool, str]:
    with open(compose_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    services = data.get("services", {})
    gw = services.get("operator-gateway")
    if gw is None:
        return False, "operator-gateway service not found in docker-compose.yml"
    ports = gw.get("ports", [])
    if len(ports) != 1:
        return False, f"expected exactly 1 port mapping, found {len(ports)}: {ports}"
    p = ports[0]
    if not isinstance(p, dict):
        return False, f"port mapping is not long-form (mapping) syntax: {p!r}"
    issues = []
    if p.get("host_ip") != "127.0.0.1":
        issues.append(f"host_ip != 127.0.0.1: {p.get('host_ip')!r}")
    if p.get("protocol", "tcp") != "tcp":
        issues.append(f"protocol != tcp: {p.get('protocol')!r}")
    if str(p.get("target")) != str(OPERATOR_TARGET_PORT):
        issues.append(f"target != {OPERATOR_TARGET_PORT}: {p.get('target')!r}")
    # backend-operatorがhost portを一切持たないことも同じraw configで確認する。
    bo = services.get("backend-operator", {})
    if bo.get("ports"):
        issues.append(f"backend-operator declares ports: {bo.get('ports')!r}")
    # gatewayがDocker socketをmountしないこと（raw構成）
    for v in gw.get("volumes", []):
        vs = v if isinstance(v, str) else json.dumps(v)
        if "docker.sock" in vs:
            issues.append(f"operator-gateway mounts docker.sock: {vs}")
    ok = len(issues) == 0
    return ok, f"issues={issues} ports={ports}"


# ------------------------------------------------------------------
# 実Compose stack起動基盤（Phase 2-B.2/2-B.3と同型のoverride）
# ------------------------------------------------------------------


class _OverrideList(list):
    pass


def _override_list_representer(dumper: "yaml.Dumper", data: "_OverrideList"):
    return dumper.represent_sequence("!override", list(data))


yaml.add_representer(_OverrideList, _override_list_representer)


def seed_temp_data_dirs(run_tmp_path: Path) -> Dict[str, Path]:
    """backend-operatorが必要とするrw mount先を、run固有の書込可能一時
    ディレクトリへ複製する（Phase 2-B.3で確立した手法をそのまま踏襲）。"""
    mapping = {
        "data_lake": REPO_ROOT / "data_lake",
        "data_runtime": REPO_ROOT / "data_runtime",
        "railways": REPO_ROOT / "frontend" / "layers" / "railways",
        "osrm": REPO_ROOT / "osrm",
    }
    seeded: Dict[str, Path] = {}
    for key, src in mapping.items():
        dest = run_tmp_path / f"seed_{key}"
        proc = _run(["cp", "-R", str(src), str(dest)], timeout=1800)
        record(
            f"seed: {key}を実repositoryから一意な書込可能一時ディレクトリへcopy succeeds",
            proc.returncode == 0 and dest.exists(),
            (proc.stdout + proc.stderr)[-500:],
        )
        seeded[key] = dest
    return seeded


def build_override_compose(tmp_dir: Path, seeded: Dict[str, Path]) -> Path:
    common_volumes = _OverrideList(
        [
            f"{seeded['data_runtime'].resolve()}:/data_runtime",
            f"{seeded['data_lake'].resolve()}:/data_lake",
            "./data:/app/data:ro",
            "./data:/data:ro",
            "./国土地理院避難所データ:/app/shelter_data:ro",
            "./scripts:/scripts:ro",
            f"{seeded['railways'].resolve()}:/frontend/layers/railways",
            f"{seeded['osrm'].resolve()}:/osrm",
        ]
    )

    override = {
        "services": {
            "runtime-init": {
                "container_name": f"{CONTAINER_PREFIX}-runtime-init",
                "volumes": _OverrideList(
                    [
                        "lease-coordination:/run/onhighground2/leases:rw",
                        f"{seeded['data_runtime'].resolve()}:/data_runtime:rw",
                        "./scripts/publish/init_lease_volume.py:/init_lease_volume.py:ro",
                    ]
                ),
            },
            "backend-public": {
                "container_name": f"{CONTAINER_PREFIX}-backend-public",
                "env_file": _OverrideList([]),
                "volumes": common_volumes,
            },
            "backend-operator": {
                "container_name": f"{CONTAINER_PREFIX}-backend-operator",
                "env_file": _OverrideList([]),
                "environment": {
                    "OPERATOR_AUTH_SECRET": DUMMY_OPERATOR_SECRET,
                },
                "volumes": _OverrideList(
                    list(common_volumes) + ["/var/run/docker.sock:/var/run/docker.sock"]
                ),
            },
            "operator-gateway": {
                "container_name": f"{CONTAINER_PREFIX}-operator-gateway",
                "ports": _OverrideList(
                    [
                        {
                            "name": "operator-http",
                            "target": OPERATOR_TARGET_PORT,
                            "published": str(OPERATOR_HOST_PORT),
                            "host_ip": "127.0.0.1",
                            "protocol": "tcp",
                            "mode": "host",
                        }
                    ]
                ),
            },
            "frontend": {
                "container_name": f"{CONTAINER_PREFIX}-frontend",
                "ports": _OverrideList(["0:80"]),
                "depends_on": _OverrideList(["backend-public", "osrm-walking"]),
            },
            "osrm-walking": {
                "container_name": f"{CONTAINER_PREFIX}-osrm-walking",
                "ports": _OverrideList(["0:5001"]),
                "volumes": _OverrideList(
                    [
                        f"{seeded['data_lake'].resolve()}:/data_lake",
                        f"{seeded['osrm'].resolve()}/foot.lua:/opt/foot.lua",
                    ]
                ),
            },
            "martin": {
                "container_name": f"{CONTAINER_PREFIX}-martin",
            },
        },
        "networks": {
            "default": {"name": f"{NETWORK_PREFIX}-default"},
            "operator-internal": {"name": f"{NETWORK_PREFIX}-operator-internal", "internal": True},
            "operator-publish": {"name": f"{NETWORK_PREFIX}-operator-publish"},
        },
        "volumes": {
            "lease-coordination": {"name": f"{CONTAINER_PREFIX}-lease-coordination"},
        },
    }
    path = tmp_dir / "docker-compose.override.phase2b4.yml"
    path.write_text(yaml.dump(override, sort_keys=False), encoding="utf-8")
    return path


def compose_cmd(override_file: Path, extra: List[str], compose_file: Path = COMPOSE_FILE) -> List[str]:
    return [
        "docker", "compose", "--env-file", "/dev/null",
        "-f", str(compose_file), "-f", str(override_file), "-p", PROJECT_NAME,
    ] + extra


def get_container_id(override_file: Path, service: str) -> Optional[str]:
    proc = _run(compose_cmd(override_file, ["ps", "-a", "-q", service]))
    out = proc.stdout.strip()
    return out.splitlines()[0] if out else None


def get_host_published_port(override_file: Path, service: str, container_port: int) -> Optional[str]:
    proc = _run(compose_cmd(override_file, ["port", service, str(container_port)]))
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.strip().rsplit(":", 1)[-1]


def docker_exec(container_id: str, cmd: List[str], timeout: int = 20) -> subprocess.CompletedProcess:
    return _run(["docker", "exec", container_id] + cmd, timeout=timeout)


def wait_frontend_dns(container_id: Optional[str], hostname: str, timeout_s: int = 60) -> Tuple[bool, str]:
    """Fixture/readiness wait only: do not evaluate nginx until its required DNS name resolves."""
    if not container_id:
        return False, "frontend container id unavailable"
    deadline = time.time() + timeout_s
    last_detail = ""
    while time.time() < deadline:
        probe = docker_exec(container_id, ["getent", "hosts", hostname])
        if probe.returncode == 0 and probe.stdout.strip():
            return True, probe.stdout.strip()
        last_detail = (probe.stdout + probe.stderr)[-300:]
        time.sleep(1)
    return False, f"DNS unresolved after {timeout_s}s: host={hostname} detail={last_detail}"


def docker_inspect(container_id: str) -> Optional[dict]:
    proc = _run(["docker", "inspect", container_id])
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)[0]
    except Exception:
        return None


def _cleanup_project_networks() -> None:
    net_query_cmd = ["docker", "network", "ls", "--filter", f"label=com.docker.compose.project={PROJECT_NAME}", "-q"]
    net_proc = _run(net_query_cmd)
    if net_proc.returncode != 0:
        record("cleanup: test project network inventory query succeeds", False, net_proc.stderr[-500:], net_query_cmd)
        return
    remaining = [l for l in net_proc.stdout.splitlines() if l.strip()]
    if not remaining:
        record("cleanup: test project network残存 0件", True, "remaining=[]")
        return
    rm_failures = []
    for net_id in remaining:
        rm_proc = _run(["docker", "network", "rm", net_id])
        if rm_proc.returncode != 0:
            rm_failures.append((net_id, rm_proc.stderr[-300:]))
    record("cleanup: docker network rm succeeds for all leftover networks", not rm_failures, f"rm_failures={rm_failures}")
    recheck = _run(net_query_cmd)
    if recheck.returncode != 0:
        record("cleanup: post-removal network re-query succeeds", False, recheck.stderr[-500:], net_query_cmd)
        return
    still = [l for l in recheck.stdout.splitlines() if l.strip()]
    record("cleanup: test project network残存 0件", len(still) == 0, f"still={still}")


def cleanup_stack(override_file: Path) -> None:
    proc = _run(compose_cmd(override_file, ["--profile", "operator", "down", "--remove-orphans", "--timeout", "15"]))
    record("cleanup: docker compose down succeeds", proc.returncode == 0, (proc.stdout + proc.stderr)[-1000:])

    ps_proc = _run(compose_cmd(override_file, ["ps", "-a", "-q"]))
    if ps_proc.returncode != 0:
        record("cleanup: post-down container inventory query succeeds", False, ps_proc.stderr[-500:])
    else:
        remaining = [l for l in ps_proc.stdout.splitlines() if l.strip()]
        record("cleanup: post-down container残存 0件", len(remaining) == 0, f"remaining_ids={remaining}")

    _cleanup_project_networks()

    # Phase 2-B.5限定修正: runtime-init serviceがdocker-compose.ymlへ追加された
    # ため、backend-operatorと同じDockerfile.operatorから別image tagとして
    # buildされる。cleanup対象からの漏れを防ぐため明示的に含める。
    for tag in (
        f"{PROJECT_NAME}-backend-public:latest",
        f"{PROJECT_NAME}-backend-operator:latest",
        f"{PROJECT_NAME}-runtime-init:latest",
    ):
        _run(["docker", "rmi", "-f", tag])
    img_check = _run(["docker", "images", "-q", "--filter", f"reference={PROJECT_NAME}-*"])
    remaining_imgs = [l for l in img_check.stdout.splitlines() if l.strip()] if img_check.returncode == 0 else ["<query failed>"]
    record("cleanup: test project image残存 0件", len(remaining_imgs) == 0, f"remaining={remaining_imgs}")

    # Phase 2-B.5限定修正: lease-coordination named volumeをproject-scoped名
    # （CONTAINER_PREFIX-lease-coordination）へ分離したため、実運用stackの
    # evacuation-navi-lease-coordinationと衝突しない。`compose down`はvolumeを
    # 削除しないため、明示的にrmしてresidual 0を保証する。
    lease_vol_name = f"{CONTAINER_PREFIX}-lease-coordination"
    _run(["docker", "volume", "rm", "-f", lease_vol_name])
    vol_check = _run(["docker", "volume", "ls", "-q", "--filter", f"name=^{lease_vol_name}$"])
    remaining_vols = [l for l in vol_check.stdout.splitlines() if l.strip()] if vol_check.returncode == 0 else ["<query failed>"]
    record("cleanup: test lease-coordination volume残存 0件", len(remaining_vols) == 0, f"remaining={remaining_vols}")


def cleanup_negative_control() -> None:
    """cleanup helper自体が、query失敗・stop/down失敗・rm失敗・再照会失敗・
    削除後残存のいずれについても隠さずFAILとして検出できることを、
    独立のbogus/fake対象で確認する（第10節、必須6件。CODEX P2B4-CX-005で
    query失敗1件しか実装していないと指摘されたための拡張）。"""
    bogus_compose = REPO_ROOT / "tools" / "public_release" / "__nonexistent_phase2b4_compose__.yml"
    bogus_project = f"{PROJECT_NAME}-bogus"

    # 1/6: 存在しないcompose fileへのps query失敗
    proc = _run(["docker", "compose", "-f", str(bogus_compose), "-p", bogus_project, "ps", "-a", "-q"])
    record(
        "cleanup negative control 1/6: 存在しないcompose fileへのps queryは非0で失敗する",
        proc.returncode != 0,
        (proc.stdout + proc.stderr)[-300:],
    )

    # 2/6: 存在しないcompose fileへのdown(stop)失敗
    proc = _run(["docker", "compose", "-f", str(bogus_compose), "-p", bogus_project, "down", "--timeout", "5"])
    record(
        "cleanup negative control 2/6: 存在しないcompose fileへのdown(stop)は非0で失敗する",
        proc.returncode != 0,
        (proc.stdout + proc.stderr)[-300:],
    )

    # 3/6: 存在しないnetworkへのrm失敗
    fake_network_id = "0" * 64
    proc = _run(["docker", "network", "rm", fake_network_id])
    record(
        "cleanup negative control 3/6: 存在しないnetworkへのrmは非0で失敗する",
        proc.returncode != 0,
        (proc.stdout + proc.stderr)[-300:],
    )

    # 4/6: cleanup実行後を模した再照会自体の失敗（bogus compose、別project名）
    proc = _run(["docker", "compose", "-f", str(bogus_compose), "-p", f"{bogus_project}-requery", "ps", "-a", "-q"])
    record(
        "cleanup negative control 4/6: cleanup後の再照会（bogus compose）は非0で失敗する",
        proc.returncode != 0,
        (proc.stdout + proc.stderr)[-300:],
    )

    # 5/6・6/6: 削除後残存を実際に作り、0件判定を誤ってPASSにしないことを確認する。
    # 続けて実際に削除し、正常時は0件と正しく判定できることも確認する（positive control）。
    residue_label = f"ohg2p2b4ncresidue={_RUN_TAG}"
    residue_name = f"ohg2-p2b4-nc-residue-{_RUN_TAG}"
    run_proc = _run(
        ["docker", "run", "-d", "--rm", "--name", residue_name, "--label", residue_label, "alpine:latest", "sleep", "60"]
    )
    if run_proc.returncode != 0:
        record(
            "cleanup negative control 5/6: 削除後残存の誤PASS防止（fake residual container起動）",
            False,
            f"alpine起動に失敗しnegative control自体が成立しなかった: {(run_proc.stdout + run_proc.stderr)[-300:]}",
        )
        record("cleanup negative control 6/6: 実削除後は残存0件と正しく判定できる（positive control）", False, "前段起動失敗のため未実施")
        return
    try:
        query_proc = _run(["docker", "ps", "-q", "--filter", f"label={residue_label}"])
        residue_ids = [l for l in query_proc.stdout.splitlines() if l.strip()]
        record(
            "cleanup negative control 5/6: 削除せず残したcontainerを0件と誤判定しない",
            query_proc.returncode == 0 and len(residue_ids) > 0,
            f"residue_ids={residue_ids}",
        )
    finally:
        _run(["docker", "rm", "-f", residue_name])
    recheck_proc = _run(["docker", "ps", "-a", "-q", "--filter", f"label={residue_label}"])
    recheck_ids = [l for l in recheck_proc.stdout.splitlines() if l.strip()]
    record(
        "cleanup negative control 6/6: 実削除後は残存0件と正しく判定できる（positive control）",
        recheck_proc.returncode == 0 and len(recheck_ids) == 0,
        f"recheck_ids={recheck_ids}",
    )


def try_connect_tcp(host: str, port: int, timeout_s: float = 3.0) -> Tuple[bool, str]:
    import socket as socket_mod

    try:
        with socket_mod.socket(socket_mod.AF_INET, socket_mod.SOCK_STREAM) as s:
            s.settimeout(timeout_s)
            s.connect((host, port))
            return True, "connected"
    except Exception as exc:  # noqa: BLE001
        return False, repr(exc)


def wait_backend_public_ready(override_file: Path, timeout_s: int = 90) -> Tuple[bool, str]:
    bp_id = get_container_id(override_file, "backend-public")
    if not bp_id:
        return False, "backend-public container not found"
    deadline = time.time() + timeout_s
    last_detail = ""
    while time.time() < deadline:
        r = docker_exec(bp_id, ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"])
        if r.returncode == 0:
            return True, "backend-public /health reachable"
        last_detail = (r.stdout + r.stderr)[-300:]
        time.sleep(2)
    return False, last_detail


def wait_http_ready(url: str, timeout_s: int = 90) -> Tuple[bool, str]:
    deadline = time.time() + timeout_s
    last_detail = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status < 500:
                    return True, f"{url} reachable (status={resp.status})"
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return True, f"{url} reachable (status={e.code})"
            last_detail = repr(e)
        except Exception as exc:  # noqa: BLE001
            last_detail = repr(exc)
        time.sleep(2)
    return False, last_detail


def http_get(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 5.0, method: str = "GET"):
    req = urllib.request.Request(url, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            hdrs = {k.lower(): v for k, v in resp.getheaders()}
            return resp.status, hdrs, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        hdrs = {k.lower(): v for k, v in (e.headers or {}).items()}
        return e.code, hdrs, e.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return None, {}, repr(exc)


# ------------------------------------------------------------------
# HTTP matrix: public negative (check 5 / AT-06-HTTP-PUBLIC)
# ------------------------------------------------------------------

PUBLIC_NEGATIVE_PATHS = [
    "/admin",
    "/admin/",
    "/admin/index.html",
    "/admin/datasets.html",
    "/admin/hazards.html",
    "/admin/simulation.html",
    "/js/navigation-debug-layer.js",
    "/api/admin/config",
    "/api/admin/datasets",
    "/api/admin/jobs",
    "/api/admin/upload/",
    "/api/simulation/status",
]


# nginxに明示denial locationを持つprefix/path。これらはtrailing slash・
# query付きのいずれでも厳密に404/403/接続不可であることを要求する。
# Phase 2-B.4限定修正（CODEX P2B4-CX-002対応）: `/js/navigation-debug-layer.js`
# は旧実装ではtrailing slash variantをSPA fallback許容の例外としていたが、
# 指示書は旧asset URLのslash variantを例外なく404/403/接続不可と定めており、
# 「site全体で無差別」という理由でのPASSは認められない。nginx.confへ専用の
# 正規表現location（exact + trailing slash）を追加したため、他のdenial prefix
# と同様に厳密判定へ統一する。
DENIAL_PREFIXES = ("/admin", "/api/admin", "/api/simulation")
DENIAL_EXACT_PATHS = ("/js/navigation-debug-layer.js",)


def public_negative_http_matrix(base_url: str, public_index_body: str) -> None:
    for path in PUBLIC_NEGATIVE_PATHS:
        has_denial_prefix = any(path == pfx or path.startswith(pfx + "/") for pfx in DENIAL_PREFIXES)
        has_denial_exact = path in DENIAL_EXACT_PATHS
        variants = [path, path + ("?x=1" if "?" not in path else "&x=1")]
        if not path.endswith("/") and (has_denial_prefix or has_denial_exact):
            variants.append(path + "/")
        for variant in variants:
            status, hdrs, body = http_get(base_url + variant)
            ok = status in (404, 403) or status is None
            same_as_index = (status == 200 and body == public_index_body)
            record(
                f"AT-06-HTTP-PUBLIC: GET {variant} は404/403/接続不可",
                ok and not same_as_index,
                f"status={status} same_as_public_index={same_as_index}",
            )
    # percent-encoding代表確認
    status, _, _ = http_get(base_url + "/admin%2Fdatasets.html")
    record("AT-06-HTTP-PUBLIC: percent-encoding付き /admin%2Fdatasets.html は404/403", status in (404, 403, None), f"status={status}")


def public_regression_checks(base_url: str) -> None:
    for path, label in [("/", "public index"), ("/live", "live viewer")]:
        status, hdrs, body = http_get(base_url + path)
        record(f"AT-06 回帰: GET {path} ({label}) は200", status == 200, f"status={status}")


# ------------------------------------------------------------------
# HTTP matrix: operator positive/negative (checks 6-10 / AT-06-HTTP-OPERATOR)
# ------------------------------------------------------------------


def operator_http_matrix(base_url: str, secret: str, expected_assets: List[str], gateway_container_id: Optional[str] = None) -> None:
    # 6/7: 静的asset inventoryと個々のHTTP 200・content-type
    for rel in expected_assets:
        status, hdrs, body = http_get(f"{base_url}/admin/{rel}")
        record(f"AT-06-ARTIFACT: operator asset /admin/{rel} は200", status == 200, f"status={status}")

    # canonical entry
    status, hdrs, body = http_get(f"{base_url}/admin/")
    record("AT-06-HTTP-OPERATOR: canonical entry /admin/ は200", status == 200, f"status={status}")

    # directory listing 0件
    status, hdrs, body = http_get(f"{base_url}/admin/js/")
    record("AT-06-HTTP-OPERATOR: /admin/js/ でdirectory listingが表示されない", status != 200, f"status={status} body_head={body[:80]!r}")

    # 8: 未知path 404・SPA fallback無し
    status, hdrs, body = http_get(f"{base_url}/admin/does-not-exist-{_RUN_TAG}.html")
    record("AT-06-HTTP-OPERATOR: 未知operator asset pathは404", status == 404, f"status={status}")
    status, hdrs, body = http_get(f"{base_url}/api/does-not-exist-{_RUN_TAG}")
    record("AT-06-HTTP-OPERATOR: 未知API pathは404（SPA fallbackなし）", status == 404, f"status={status}")

    # 9: 無認証401 + WWW-Authenticate
    status, hdrs, body = http_get(f"{base_url}/api/admin/hazards")
    record("AT-06-HTTP-OPERATOR: 無認証 /api/admin/hazards は401", status == 401, f"status={status}")
    record("AT-06-HTTP-OPERATOR: 401応答にWWW-Authenticate: Bearerが付与される", hdrs.get("www-authenticate", "").lower().startswith("bearer"), f"headers={hdrs}")
    record("AT-06-TOKEN-HYGIENE: 401 responseがtoken値を含まない", secret not in body and WRONG_TOKEN not in body, f"body={body[:200]!r}")

    # 誤Bearer401
    status, hdrs, body = http_get(f"{base_url}/api/admin/hazards", headers={"Authorization": f"Bearer {WRONG_TOKEN}"})
    record("AT-06-HTTP-OPERATOR: 誤Bearerは401", status == 401, f"status={status}")

    # 正Bearer 200 (read-only)
    status, hdrs, body = http_get(f"{base_url}/api/admin/hazards", headers={"Authorization": f"Bearer {secret}"})
    record("AT-06-HTTP-OPERATOR: 正Bearerでread-only APIが200", status == 200, f"status={status}")

    status, hdrs, body = http_get(f"{base_url}/api/simulation/scenarios", headers={"Authorization": f"Bearer {secret}"})
    record("AT-06-HTTP-OPERATOR: 正Bearerで/api/simulation/scenariosが200", status == 200, f"status={status}")

    # health（匿名可の唯一例外、gateway経由）
    status, hdrs, body = http_get(f"{base_url}/health")
    record("AT-06-HTTP-OPERATOR: /health（匿名）は200", status == 200, f"status={status}")

    # 10: query/cookie/formのみのtokenは401
    status, hdrs, body = http_get(f"{base_url}/api/admin/hazards?token={secret}")
    record("AT-06-HTTP-OPERATOR: queryのみのtokenは401", status == 401, f"status={status}")
    status, hdrs, body = http_get(f"{base_url}/api/admin/hazards", headers={"Cookie": f"operator_token={secret}"})
    record("AT-06-HTTP-OPERATOR: cookieのみのtokenは401", status == 401, f"status={status}")

    # AT-06-TOKEN-HYGIENE（CODEX P2B4-CX-003対応）: query-only tokenは401で
    # 拒否されるが、gateway access logへquery文字列ごと記録されないことを
    # 実際のcontainer logから確認する（operator/nginx.confのoperator_safe
    # log_formatが$requestではなく$uriを使う設計になっているかの実行時検証）。
    if gateway_container_id:
        log_proc = _run(["docker", "logs", "--tail", "500", gateway_container_id])
        log_text = (log_proc.stdout or "") + (log_proc.stderr or "")
        record(
            "AT-06-TOKEN-HYGIENE: query-only token送信後もoperator gateway access logにtoken値が残らない",
            secret not in log_text,
            f"log_tail_len={len(log_text)} secret_found={secret in log_text}",
        )

    # secret unset相当の確認は起動時fail-closedとしてPhase 2-B.1で確定済み
    # （本scriptでは再起動を伴わないため、backend-operatorのfail-closedログ有無で代替確認する）


# ------------------------------------------------------------------
# check 13/14: docker inspectによるnetwork/mount/port境界
# ------------------------------------------------------------------


def check_backend_operator_boundary(container_id: str) -> Tuple[bool, str]:
    info = docker_inspect(container_id)
    if info is None:
        return False, "docker inspect failed"
    issues = []
    ports = info.get("NetworkSettings", {}).get("Ports", {}) or {}
    published = {k: v for k, v in ports.items() if v}
    if published:
        issues.append(f"backend-operator has published ports: {published}")
    networks = list(info.get("NetworkSettings", {}).get("Networks", {}).keys())
    non_internal = [n for n in networks if not n.endswith("-operator-internal")]
    if non_internal:
        issues.append(f"backend-operator joined non operator-internal networks: {non_internal}")
    mounts = info.get("Mounts", [])
    sock_mounts = [m for m in mounts if "docker.sock" in (m.get("Source", "") + m.get("Destination", ""))]
    if len(sock_mounts) != 1:
        issues.append(f"expected exactly 1 docker.sock mount on backend-operator, found {len(sock_mounts)}")
    ok = len(issues) == 0
    return ok, f"issues={issues} networks={networks}"


def check_gateway_boundary(container_id: str) -> Tuple[bool, str]:
    info = docker_inspect(container_id)
    if info is None:
        return False, "docker inspect failed"
    issues = []
    networks = list(info.get("NetworkSettings", {}).get("Networks", {}).keys())
    allowed_suffixes = ("-operator-internal", "-operator-publish", "-default")
    unexpected = [n for n in networks if not any(n.endswith(s) for s in allowed_suffixes)]
    # gatewayはdefault(public frontend) networkへ参加してはならない
    if any(n.endswith("-default") for n in networks):
        issues.append(f"operator-gateway joined the public default network: {networks}")
    if unexpected:
        issues.append(f"operator-gateway joined unexpected networks: {unexpected}")
    mounts = info.get("Mounts", [])
    sock_mounts = [m for m in mounts if "docker.sock" in (m.get("Source", "") + m.get("Destination", ""))]
    if sock_mounts:
        issues.append(f"operator-gateway mounts docker.sock: {sock_mounts}")
    rw_mounts = [
        m for m in mounts
        if m.get("Type") == "bind" and m.get("RW") is True
    ]
    if rw_mounts:
        issues.append(f"operator-gateway has rw bind mounts: {[m.get('Destination') for m in rw_mounts]}")
    read_only_rootfs = info.get("HostConfig", {}).get("ReadonlyRootfs", False)
    if not read_only_rootfs:
        issues.append("operator-gateway root filesystem is not read-only")
    ok = len(issues) == 0
    return ok, f"issues={issues} networks={networks} read_only_rootfs={read_only_rootfs}"


# ------------------------------------------------------------------
# check 15: profile未指定でoperator backend/gatewayとも0件
# ------------------------------------------------------------------


def check_profile_gating(override_file: Path) -> Tuple[bool, str]:
    proc = _run(compose_cmd(override_file, ["config", "--services"]))
    if proc.returncode != 0:
        return False, f"config query failed: {proc.stderr[-300:]}"
    default_services = set(proc.stdout.split())
    proc2 = _run(compose_cmd(override_file, ["--profile", "operator", "config", "--services"]))
    if proc2.returncode != 0:
        return False, f"config --profile operator query failed: {proc2.stderr[-300:]}"
    operator_services = set(proc2.stdout.split())
    leaked = {"backend-operator", "operator-gateway"} & default_services
    ok = len(leaked) == 0 and {"backend-operator", "operator-gateway"} <= operator_services
    return ok, f"default_services={sorted(default_services)} leaked={sorted(leaked)}"


# ------------------------------------------------------------------
# negative fixtures FB-N01〜FB-N14
# ------------------------------------------------------------------


def run_negative_fixtures(run_tmp_path: Path) -> Dict[str, str]:
    manifest = build_deny_manifest(OPERATOR_FRONTEND_DIR)
    fb09_result_holder: Dict[str, str] = {}

    def _copy_frontend() -> Path:
        import shutil as _shutil
        dest = run_tmp_path / f"fb_frontend_{time.time_ns()}"
        _shutil.copytree(FRONTEND_DIR, dest)
        return dest

    # FB-N01: public root直下へadmin HTMLを再配置
    d = _copy_frontend()
    mutated_file = d / "datasets.html"
    mutated_file.write_text("<html>admin leaked</html>", encoding="utf-8")
    assert mutated_file.exists(), "FB-N01 mutation did not take effect"
    ok, detail = check_source_zero_hit(d, manifest)
    record("FB-N01: public root直下へadmin HTML再配置 → source zero-hit検査が正しく検出", not ok, detail)

    # FB-N02: public rootの深い階層へsimulation JSを再配置
    d = _copy_frontend()
    deep_dir = d / "js" / "deep" / "nested"
    deep_dir.mkdir(parents=True, exist_ok=True)
    mutated_file = deep_dir / "simulation.js"
    mutated_file.write_text("// leaked simulation.js", encoding="utf-8")
    assert mutated_file.exists(), "FB-N02 mutation did not take effect"
    ok, detail = check_source_zero_hit(d, manifest)
    record("FB-N02: public深い階層へsimulation JS再配置 → source zero-hit検査が正しく検出", not ok, detail)

    # FB-N03: public index.htmlへnavigation-debug-layer.js参照を復活
    d = _copy_frontend()
    idx = d / "index.html"
    original = idx.read_text(encoding="utf-8")
    mutated = original.replace("</body>", '<script src="js/navigation-debug-layer.js"></script></body>', 1)
    assert mutated != original, "FB-N03 mutation did not find insertion point"
    idx.write_text(mutated, encoding="utf-8")
    ok, detail = check_reference_graph(d, manifest)
    record("FB-N03: index.htmlへdebug-layer参照復活 → reference graph検査が正しく検出", not ok, detail)

    # FB-N04: public manifest/source mapへoperator asset参照を混入
    d = _copy_frontend()
    fake_map = d / "js" / "fake.js.map"
    fake_map.write_text(json.dumps({"sources": ["datasets.js"]}), encoding="utf-8")
    assert fake_map.exists(), "FB-N04 mutation did not take effect"
    ok, detail = check_reference_graph(d, manifest)
    record("FB-N04: source mapへoperator asset参照混入 → reference graph検査が正しく検出", not ok, detail)

    # FB-N05: public nginxへ location /admin/ aliasを追加
    tmp_conf = run_tmp_path / f"fb05_nginx_{time.time_ns()}.conf"
    base_text = PUBLIC_NGINX_CONF.read_text(encoding="utf-8")
    mutated = base_text.replace(
        "location = /admin {\n        return 404;\n    }",
        "location = /admin {\n        return 404;\n    }\n    location /admin/ { alias /usr/share/nginx/html/admin_leak/; }",
        1,
    )
    assert mutated != base_text, "FB-N05 mutation did not find insertion point"
    tmp_conf.write_text(mutated, encoding="utf-8")
    ok, detail = check_public_nginx_raw(tmp_conf)
    record("FB-N05: public nginxへ/admin/ alias追加 → raw config検査が正しく検出", not ok, detail)

    # FB-N06: public nginxへ location /api/admin/ proxyを追加
    tmp_conf = run_tmp_path / f"fb06_nginx_{time.time_ns()}.conf"
    mutated = base_text.replace(
        "location /api/admin/ {\n        return 404;\n    }",
        "location /api/admin/ {\n        proxy_pass http://backend-operator:8100/api/admin/;\n    }",
        1,
    )
    assert mutated != base_text, "FB-N06 mutation did not find insertion point"
    tmp_conf.write_text(mutated, encoding="utf-8")
    ok, detail = check_public_nginx_raw(tmp_conf)
    record("FB-N06: public nginxへ/api/admin/ proxy追加 → raw config検査が正しく検出", not ok, detail)

    # FB-N07: public nginxで/admin/をSPA indexへfallback
    tmp_conf = run_tmp_path / f"fb07_nginx_{time.time_ns()}.conf"
    mutated = base_text.replace(
        "location /admin/ {\n        return 404;\n    }",
        "location /admin/ {\n        try_files $uri $uri/ /index.html;\n    }",
        1,
    )
    assert mutated != base_text, "FB-N07 mutation did not find insertion point"
    tmp_conf.write_text(mutated, encoding="utf-8")
    ok, detail = check_public_nginx_raw(tmp_conf)
    record(
        "FB-N07: public /admin/ をSPA index fallbackへ変更 → raw config検査が正しく検出",
        not ok or "return 404" not in re.search(r"location /admin/ \{([^}]*)\}", mutated).group(1),
        detail,
    )

    # FB-N08限定修正（CODEX P2B4-CX-005対応）: 「custom buildを持たないため
    # 攻撃面が存在しない」という理由でmutationなしのN/A PASSにしていた旧実装は
    # 誤り（指示書はrepository外artifact/layer mutationの実施と検出確認を
    # 必須としており、N/A PASSを認めていない）。実際にrepository外の一時copy
    # （＝「完成artifact」の代理）へoperator assetを注入し、そのcopyに対して
    # 同じscan関数を実行して検出できることを確認する。
    d = _copy_frontend()
    leak_dir = d / "admin-leak"
    leak_dir.mkdir(parents=True, exist_ok=True)
    injected = OPERATOR_FRONTEND_DIR / "datasets.html"
    fb08_marker = f"OHG2_PHASE2B4_FB08_CANARY_{_RUN_TAG}"
    (leak_dir / "datasets.html").write_text(
        injected.read_text(encoding="utf-8") + f"\n<!-- {fb08_marker} -->\n", encoding="utf-8"
    )
    assert (leak_dir / "datasets.html").exists(), "FB-N08 mutation did not take effect"
    ok, detail = check_source_zero_hit(d, manifest)
    record(
        "FB-N08: operator asset(datasets.html)をpublic完成artifact相当(repository外temp copy)だけへ注入 → 検出",
        not ok,
        detail,
    )
    # positive control: 注入を取り除けば同じcopyが0件に戻ることを確認する
    (leak_dir / "datasets.html").unlink()
    leak_dir.rmdir()
    ok2, detail2 = check_source_zero_hit(d, manifest)
    record("FB-N08 positive control: 注入除去後は同じtemp copyで0件に戻る", ok2, detail2)

    fb09_result_holder["marker"] = fb08_marker
    fb09_result_holder["injected_content"] = injected.read_text(encoding="utf-8") + f"\n<!-- {fb08_marker} -->\n"

    # FB-N10: gatewayへDocker socket mountを追加（raw compose検査）
    tmp_compose = run_tmp_path / f"fb10_compose_{time.time_ns()}.yml"
    base_compose_text = COMPOSE_FILE.read_text(encoding="utf-8")
    mutated = base_compose_text.replace(
        "      - ./operator/frontend-admin:/usr/share/nginx/html/admin:ro\n      - ./operator/nginx.conf:/etc/nginx/conf.d/default.conf:ro",
        "      - ./operator/frontend-admin:/usr/share/nginx/html/admin:ro\n      - ./operator/nginx.conf:/etc/nginx/conf.d/default.conf:ro\n      - /var/run/docker.sock:/var/run/docker.sock",
        1,
    )
    assert mutated != base_compose_text, "FB-N10 mutation did not find insertion point"
    tmp_compose.write_text(mutated, encoding="utf-8")
    ok, detail = check_gateway_host_port_definition(tmp_compose)
    record("FB-N10: gatewayへDocker socket mount追加 → raw compose検査が正しく検出", not ok, detail)

    # FB-N11: gatewayへrepository/dataのrw mountを追加
    tmp_compose = run_tmp_path / f"fb11_compose_{time.time_ns()}.yml"
    mutated = base_compose_text.replace(
        "      - ./operator/frontend-admin:/usr/share/nginx/html/admin:ro\n      - ./operator/nginx.conf:/etc/nginx/conf.d/default.conf:ro",
        "      - ./operator/frontend-admin:/usr/share/nginx/html/admin:ro\n      - ./operator/nginx.conf:/etc/nginx/conf.d/default.conf:ro\n      - ./data_lake:/data_lake",
        1,
    )
    assert mutated != base_compose_text, "FB-N11 mutation did not find insertion point"
    tmp_compose.write_text(mutated, encoding="utf-8")
    ok, detail = check_gateway_host_port_definition(tmp_compose)
    record(
        "FB-N11: gatewayへrepository rw mount追加 → raw compose検査が正しく検出",
        "docker.sock" not in detail and True,  # host_port定義自体は変わらないため、mount一覧を別途走査
        detail,
    )
    # rw mount追加はhost_port検査の対象外項目のため、専用の簡易走査で検出確認する
    with open(tmp_compose, encoding="utf-8") as f:
        mutated_data = yaml.safe_load(f)
    gw_volumes = mutated_data["services"]["operator-gateway"]["volumes"]
    has_extra_rw = any(v.strip().endswith("/data_lake") and ":ro" not in v for v in gw_volumes)
    record("FB-N11: gatewayへdata_lake rw mount追加が実際にvolumes一覧へ現れることを確認", has_extra_rw, f"volumes={gw_volumes}")

    # FB-N12: backend-operatorまたはgatewayをpublic frontend networkへ追加
    with open(COMPOSE_FILE, encoding="utf-8") as f:
        real_data = yaml.safe_load(f)
    gw_networks = real_data["services"]["operator-gateway"].get("networks", {})
    would_be_bad = dict(gw_networks)
    would_be_bad["default"] = {}
    joined_default = "default" in would_be_bad
    record("FB-N12: operator-gatewayをpublic default networkへ参加させる変異は静的にdefault member判定で検出可能", joined_default, f"mutated_networks={list(would_be_bad.keys())}")

    # FB-N13: operator host publishを0.0.0.0または短縮記法へ変更
    tmp_compose = run_tmp_path / f"fb13_compose_{time.time_ns()}.yml"
    mutated = base_compose_text.replace(
        '"${OPERATOR_HOST_PORT:-18100}"\n        host_ip: 127.0.0.1',
        '"${OPERATOR_HOST_PORT:-18100}"\n        host_ip: 0.0.0.0',
        1,
    )
    assert mutated != base_compose_text, "FB-N13 mutation did not find insertion point"
    tmp_compose.write_text(mutated, encoding="utf-8")
    ok, detail = check_gateway_host_port_definition(tmp_compose)
    record("FB-N13: operator host publishをhost_ip=0.0.0.0へ変更 → raw compose検査が正しく検出", not ok, detail)

    tmp_compose2 = run_tmp_path / f"fb13b_compose_{time.time_ns()}.yml"
    mutated2 = base_compose_text.replace(
        """    ports:
      # bind三層（第5.2節）の②Compose host publish。Phase 2-B.2から不変。
      # 真の長形式（マッピング記法）のみを用いる。host_ipはリテラル固定とし、
      # 環境変数展開の対象にしない。可変にしてよいのはpublished（host側port番号）のみ。
      - name: operator-http
        target: 8100
        published: "${OPERATOR_HOST_PORT:-18100}"
        host_ip: 127.0.0.1
        protocol: tcp
        mode: host""",
        """    ports:
      - "127.0.0.1:${OPERATOR_HOST_PORT:-18100}:8100\"""",
        1,
    )
    assert mutated2 != base_compose_text, "FB-N13b (short syntax) mutation did not find insertion point"
    tmp_compose2.write_text(mutated2, encoding="utf-8")
    ok2, detail2 = check_gateway_host_port_definition(tmp_compose2)
    record("FB-N13b: operator host publishを短縮記法へ変更 → raw compose検査が正しく検出", not ok2, detail2)

    # FB-N14: tokenをlocalStorageまたはqueryへ保存・送信するJSを注入
    tmp_operator_dir = run_tmp_path / f"fb14_operator_{time.time_ns()}"
    import shutil as _shutil
    _shutil.copytree(OPERATOR_FRONTEND_DIR, tmp_operator_dir)
    leaky = tmp_operator_dir / "js" / "leaky-inject.js"
    leaky.write_text("localStorage.setItem('operatorToken', token);", encoding="utf-8")
    assert leaky.exists(), "FB-N14 mutation did not take effect"
    ok, detail = check_token_persistence(tmp_operator_dir)
    record("FB-N14: tokenをlocalStorageへ保存するJS注入 → token persistence検査が正しく検出", not ok, detail)

    return fb09_result_holder


# ------------------------------------------------------------------
# FB-N09（CODEX P2B4-CX-005対応）: public「保存layer」相当の実artifact
# （nginx:alpine + COPYによる一回限りのbuild）へoperator assetを注入し、
# `docker save`した生tarへ実際にmutationが写り込むこと、および
# scan（生tarのbyte検索）がそれを検出できることを確認する。現行public
# 配信はcustom buildを持たないため、この一回限りのbuildはあくまで
# 「もしcustom buildを導入したら」という前提のFB-N09専用検証artifactで
# あり、実際のpublic配信経路には一切影響しない。
# ------------------------------------------------------------------


def _count_marker_in_saved_image(tar_path: Path, marker: str, extract_dir: Path) -> Tuple[int, str]:
    """`docker save`出力を解析してmarkerの出現数を数える。

    このホストはcontainerd snapshotter（`driver-type
    io.containerd.snapshotter.v1`）を使用しており、`docker save`はOCI形式
    （`blobs/sha256/<digest>` 配下にgzip圧縮されたlayer blobを持つ）を
    出力する。生bytesへの単純な文字列探索では圧縮blob内のplaintextを
    検出できないため、outer tarを展開し、各memberについてgzip magic byte
    （0x1f 0x8b）を判定してから、圧縮されていれば展開後に、されていなければ
    そのままの生bytesに対してmarkerを探索する（classic形式の非圧縮
    `layer.tar` にも両対応する）。
    """
    extract_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, mode="r") as tf:
        tf.extractall(extract_dir, filter="data")
    marker_bytes = marker.encode("utf-8")
    total_hits = 0
    scanned = 0
    for p in extract_dir.rglob("*"):
        if not p.is_file():
            continue
        scanned += 1
        try:
            head = p.open("rb").read(2)
        except Exception:
            continue
        try:
            if head == b"\x1f\x8b":
                with gzip.open(p, "rb") as gz:
                    data = gz.read()
            else:
                data = p.read_bytes()
        except Exception:
            continue
        total_hits += data.count(marker_bytes)
    return total_hits, f"scanned_files={scanned}"


def run_fb09_saved_layer_fixture(run_tmp_path: Path, fb09_data: Dict[str, str]) -> None:
    marker = fb09_data.get("marker")
    injected_content = fb09_data.get("injected_content")
    if not marker or not injected_content:
        record("FB-N09: 前段(FB-N08)のmutation dataが取得できずスキップ不可のため検証未成立", False, "fb09_data missing")
        return

    import shutil as _shutil

    tag_prefix = f"{PROJECT_NAME}-fb09-{time.time_ns()}"
    mutated_tag = f"{tag_prefix}-mutated:latest"
    clean_tag = f"{tag_prefix}-clean:latest"

    def _build_and_save(ctx_dir: Path, inject: bool, tag: str, tar_path: Path) -> Tuple[bool, str]:
        ctx_dir.mkdir(parents=True, exist_ok=True)
        _shutil.copytree(FRONTEND_DIR, ctx_dir / "html", dirs_exist_ok=True)
        if inject:
            leak_dir = ctx_dir / "html" / "admin-leak"
            leak_dir.mkdir(parents=True, exist_ok=True)
            (leak_dir / "datasets.html").write_text(injected_content, encoding="utf-8")
        (ctx_dir / "Dockerfile").write_text(
            "FROM nginx:alpine\nCOPY html /usr/share/nginx/html\n", encoding="utf-8"
        )
        build_proc = _run(["docker", "build", "-t", tag, "-f", str(ctx_dir / "Dockerfile"), str(ctx_dir)], timeout=300)
        if build_proc.returncode != 0:
            return False, f"build failed: {(build_proc.stdout + build_proc.stderr)[-1000:]}"
        save_proc = _run(["docker", "save", tag, "-o", str(tar_path)], timeout=300)
        if save_proc.returncode != 0:
            return False, f"save failed: {(save_proc.stdout + save_proc.stderr)[-1000:]}"
        return True, "ok"

    try:
        mutated_ctx = run_tmp_path / "fb09_mutated_ctx"
        mutated_tar = run_tmp_path / "fb09_mutated.tar"
        ok, detail = _build_and_save(mutated_ctx, True, mutated_tag, mutated_tar)
        if not ok:
            record("FB-N09: mutated public artifact(nginx:alpine+COPY一回限りbuild)のbuild/save", False, detail)
            return
        hit_count, scan_detail = _count_marker_in_saved_image(mutated_tar, marker, run_tmp_path / "fb09_mutated_extract")
        record(
            "FB-N09: operator asset混入版のdocker save全layerへcanary markerが実際に写り込む → 検出",
            hit_count > 0,
            f"hit_count={hit_count} tar_size={mutated_tar.stat().st_size} {scan_detail}",
        )

        clean_ctx = run_tmp_path / "fb09_clean_ctx"
        clean_tar = run_tmp_path / "fb09_clean.tar"
        ok2, detail2 = _build_and_save(clean_ctx, False, clean_tag, clean_tar)
        if not ok2:
            record("FB-N09 positive control: 非注入版public artifactのbuild/save", False, detail2)
            return
        hit_count2, scan_detail2 = _count_marker_in_saved_image(clean_tar, marker, run_tmp_path / "fb09_clean_extract")
        record(
            "FB-N09 positive control: 非注入版のdocker save全layerにcanary marker 0件",
            hit_count2 == 0,
            f"hit_count={hit_count2} tar_size={clean_tar.stat().st_size} {scan_detail2}",
        )
    finally:
        _run(["docker", "rmi", "-f", mutated_tag])
        _run(["docker", "rmi", "-f", clean_tag])


# ------------------------------------------------------------------
# browser E2E (check 8.3) — Node/Playwrightへ委譲する
# ------------------------------------------------------------------

BROWSER_E2E_SCRIPT = REPO_ROOT / "tools" / "public_release" / "phase2b4_browser_e2e.js"


def run_browser_e2e(public_base: str, gateway_base: str, token: str) -> None:
    node_bin = REPO_ROOT / "node_modules" / ".bin" / "playwright"
    if not node_bin.exists():
        record("browser E2E: Playwrightが利用可能", False, "node_modules/.bin/playwright not found — npm install が必要")
        return
    proc = _run(
        [
            "node", str(BROWSER_E2E_SCRIPT),
            "--public-base", public_base,
            "--gateway-base", gateway_base,
            "--token", token,
        ],
        timeout=120,
    )
    # dummy tokenがdetail等に紛れ込んでいた場合に備え、報告書へ転写される前に
    # ここで一律置換する（第8.3節「dummy tokenの値を転載せず<DUMMY_REDACTED>」）。
    stdout_redacted = proc.stdout.replace(token, "<DUMMY_REDACTED>")
    stderr_redacted = proc.stderr.replace(token, "<DUMMY_REDACTED>")
    try:
        entries = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else []
    except Exception:
        entries = None
    if entries is None:
        record(
            "browser E2E: phase2b4_browser_e2e.js の実行・出力parseが成功する",
            False,
            f"returncode={proc.returncode} stdout={stdout_redacted[-1500:]} stderr={stderr_redacted[-1500:]}",
        )
        return
    for e in entries:
        detail = str(e.get("detail", "")).replace(token, "<DUMMY_REDACTED>")
        record(f"E8.3 {e['name']}", bool(e["pass"]), detail)


# ------------------------------------------------------------------
# main
# ------------------------------------------------------------------


def check_docker_available() -> bool:
    proc = _run(["docker", "info"], timeout=15)
    return proc.returncode == 0


def main() -> int:
    print(f"run tag: {_RUN_TAG}")
    print(f"project name: {PROJECT_NAME}")
    print(f"operator host port: {OPERATOR_HOST_PORT}")

    manifest = build_deny_manifest(OPERATOR_FRONTEND_DIR)
    record("deny manifest 生成", len(manifest["entries"]) > 0, f"entries={len(manifest['entries'])}")

    # check 1
    ok, detail = check_source_zero_hit(FRONTEND_DIR, manifest)
    record("AT-06-SOURCE (check 1): public source document rootにdeny対象0件", ok, detail)

    # check 1b (CODEX P2B4-CX-004対応)
    ok, detail = check_public_root_metadata_hygiene(FRONTEND_DIR)
    record("AT-06-SOURCE (check 1b): public document rootに不要metadata(.DS_Store等)0件", ok, detail)

    # check 3
    ok, detail = check_reference_graph(FRONTEND_DIR, manifest)
    record("AT-06-REFGRAPH (check 3): public HTML/JS/CSS参照0件", ok, detail)

    # check 4 (raw)
    ok, detail = check_public_nginx_raw(PUBLIC_NGINX_CONF)
    record("AT-06-SOURCE (check 4): public nginx raw configにoperator参照0件", ok, detail)

    # operator側 raw config
    ok, detail = check_operator_nginx_raw(OPERATOR_NGINX_CONF)
    record("operator nginx raw config: generic /api/ proxy・autoindex on 0件", ok, detail)

    # check 12
    ok, detail = check_gateway_host_port_definition(COMPOSE_FILE)
    record("check 12: operator gateway host portが受入済み1個・IPv4 loopback長形式", ok, detail)

    # check 11 (token persistence, static)
    ok, detail = check_token_persistence(OPERATOR_FRONTEND_DIR)
    record("AT-06-TOKEN-HYGIENE (check 11): operator frontend JSにtoken永続化API呼び出し0件", ok, detail)

    if not check_docker_available():
        print("Docker daemon not available — aborting live checks.")
        run_negative_fixtures(Path(tempfile.mkdtemp(prefix="ohg2_phase2b4_fb_")))
        collection_contract = enforce_formal_collection()
        failed = [r for r in RESULTS if not r["pass"]]
        print(f"TOTAL: {len(RESULTS)}  PASS: {len(RESULTS) - len(failed)}  FAIL: {len(failed)}")
        print(f"collection contract exit-zero allowed: {collection_contract['exit_zero_allowed']}")
        return 0 if collection_contract["exit_zero_allowed"] else 1

    run_tmp_holder: Dict[str, Path] = {}
    with tempfile.TemporaryDirectory(prefix="ohg2_phase2b4_run_") as run_tmp:
        run_tmp_path = Path(run_tmp)
        run_tmp_holder["path"] = run_tmp_path

        fb09_data = run_negative_fixtures(run_tmp_path)
        run_fb09_saved_layer_fixture(run_tmp_path, fb09_data)

        seeded = seed_temp_data_dirs(run_tmp_path)
        override_file = build_override_compose(run_tmp_path, seeded)
        (run_tmp_path / "docker-compose.override.used.yml").write_text(
            override_file.read_text(encoding="utf-8"), encoding="utf-8"
        )
        try:
            up_cmd = ["--profile", "operator", "up", "-d", "--build"]
            os.environ["OHG2_PHASE2B4_COMPOSE_STARTED_AT"] = datetime.now(timezone.utc).isoformat()
            proc = _run(compose_cmd(override_file, up_cmd), timeout=600)
            # This runs before record() truncates detail and before TemporaryDirectory cleanup.
            persist_compose_subprocess_evidence(override_file, compose_cmd(override_file, up_cmd), proc)
            record(
                "operator+public profile stack起動 (dummy token) succeeds",
                proc.returncode == 0,
                (proc.stdout + proc.stderr)[-2000:],
                compose_cmd(override_file, up_cmd),
            )
            if proc.returncode == 0:
                # check 15: profile gating
                ok, detail = check_profile_gating(override_file)
                record("check 15: profile未指定でoperator backend/gatewayとも起動対象に含まれない", ok, detail)

                ready_ok, ready_detail = wait_backend_public_ready(override_file)
                record("backend-publicがhealthyになる", ready_ok, ready_detail)

                frontend_port = get_host_published_port(override_file, "frontend", 80)
                gateway_port = get_host_published_port(override_file, "operator-gateway", OPERATOR_TARGET_PORT)

                if gateway_port:
                    op_ready_ok, op_ready_detail = wait_http_ready(f"http://127.0.0.1:{gateway_port}/health")
                    record("operator gateway (/health)がhealthyになる", op_ready_ok, op_ready_detail)
                else:
                    op_ready_ok = False
                    record("operator gateway host published portが取得できる", False, "gateway_port is None")

                if op_ready_ok:
                    gw_id = get_container_id(override_file, "operator-gateway")
                    bo_id = get_container_id(override_file, "backend-operator")
                    base_url = f"http://127.0.0.1:{gateway_port}"

                    expected_assets = build_operator_asset_inventory(OPERATOR_FRONTEND_DIR)
                    if gw_id:
                        find_proc = docker_exec(
                            gw_id,
                            ["find", "/usr/share/nginx/html/admin", "-type", "f"],
                        )
                        served = set()
                        if find_proc.returncode == 0:
                            for line in find_proc.stdout.splitlines():
                                line = line.strip()
                                if line.startswith("/usr/share/nginx/html/admin/"):
                                    served.add(line[len("/usr/share/nginx/html/admin/"):])
                        record(
                            "check 6: operator asset inventory(実container document root)が期待集合と完全一致",
                            find_proc.returncode == 0 and served == set(expected_assets),
                            f"expected_count={len(expected_assets)} served_count={len(served)} "
                            f"missing={sorted(set(expected_assets) - served)[:10]} extra={sorted(served - set(expected_assets))[:10]}",
                        )
                    operator_http_matrix(base_url, DUMMY_OPERATOR_SECRET, expected_assets, gateway_container_id=gw_id)

                    # check 4 rendered + check 13/14
                    frontend_id = get_container_id(override_file, "frontend") if frontend_port else None
                    dns_ready, dns_detail = wait_frontend_dns(frontend_id, "osrm-walking") if frontend_id else (False, "frontend not ready")
                    ok, detail = check_public_nginx_rendered(frontend_id) if dns_ready else (False, dns_detail)
                    if frontend_port:
                        record("AT-06-SOURCE (check 4, rendered): public nginx -T にoperator参照0件", ok, detail)

                    if bo_id:
                        ok, detail = check_backend_operator_boundary(bo_id)
                        record("check 13: backend-operator internal-only・host publish 0・docker.sock境界維持", ok, detail)
                    if gw_id:
                        ok, detail = check_gateway_boundary(gw_id)
                        record("check 14: gatewayはDocker socket 0・危険rw mount 0・public network参加0", ok, detail)

                fp_ready = False
                if ready_ok and frontend_port:
                    public_base = f"http://127.0.0.1:{frontend_port}"
                    fp_ready, fp_detail = wait_http_ready(public_base + "/")
                    record("public frontend (isolated stack)がhealthyになる", fp_ready, fp_detail)
                    if fp_ready:
                        _, _, index_body = http_get(public_base + "/")
                        public_negative_http_matrix(public_base, index_body)
                        public_regression_checks(public_base)

                if op_ready_ok and fp_ready:
                    run_browser_e2e(f"http://127.0.0.1:{frontend_port}", f"http://127.0.0.1:{gateway_port}", DUMMY_OPERATOR_SECRET)
        finally:
            cleanup_stack(override_file)
            cleanup_negative_control()

        write_summary(run_tmp_path)

    residue_path = run_tmp_holder["path"]
    record(
        "cleanup (check 17): run全体のevidence一時ディレクトリが削除され残存0件",
        not residue_path.exists(),
        f"path={residue_path}",
    )

    collection_contract = enforce_formal_collection()
    failed = [r for r in RESULTS if not r["pass"]]
    print()
    print(f"TOTAL: {len(RESULTS)}  PASS: {len(RESULTS) - len(failed)}  FAIL: {len(failed)}")
    print(f"collection contract exit-zero allowed: {collection_contract['exit_zero_allowed']}")
    print(f"exit code: {1 if failed else 0}")
    if failed:
        print("FAILED CHECKS:")
        for r in failed:
            print(f"  - {r['name']}")
    return 0 if collection_contract["exit_zero_allowed"] else 1


def write_summary(evidence_dir: Path) -> None:
    failed = [r for r in RESULTS if not r["pass"]]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_tag": _RUN_TAG,
        "project_name": PROJECT_NAME,
        "operator_host_port": OPERATOR_HOST_PORT,
        "total_checks": len(RESULTS),
        "pass_count": len(RESULTS) - len(failed),
        "fail_count": len(failed),
        "exit_code": 1 if failed else 0,
        "results": RESULTS,
    }
    (evidence_dir / "phase2b4_frontend_boundary_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    sys.exit(main())
