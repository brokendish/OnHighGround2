#!/usr/bin/env python3
"""
Phase 2-C 公式runner（CODEX第1〜第3ラウンドP2C-CX-003対応）。

DOC/OBS/HLT/CRS（pytest, backend/tests/test_phase2c_public_hardening.py）と
GLK（tools/public_release/phase2c_gitlink_check.py）を実行し、固定宣言
manifest（`phase2c_case_manifest.json`）・command・exit・expected/actual・
SHA-256付きraw evidenceを`tasks/public-release/evidence/phase2c/`へ出力する。

CODEX第2ラウンドで指摘された4件への対応:
  1. class別件数だけでなく、`phase2c_case_manifest.json`に固定した177件の
     exact unique case ID集合を正本とし、実測（junit xml）のraw ID列に対して
     duplicate／missing／unexpectedを個別に判定する（`evaluate_case_ids()`）。
  2. Docker資源照会（container/network/volume/image）はexit codeを必須で
     検査し、いずれか非0の場合は「0件」ではなく`query_failed_commands`を
     報告してcleanup検証をfail-closedにする（`ohg2p2c_residue_snapshot()`）。
  3. 一時directory残存検査を`/tmp`・`/private/tmp`に加え
     `tempfile.gettempdir()`（macOSの実tempfile root、`/var/folders/.../T`等）
     も対象にする。
  4. 上記3点の判定ロジックを純粋関数として切り出し、
     `test_phase2c_official_runner_selfcheck.py`がduplicate ID注入・
     missing ID注入・Docker query失敗injection・実temp root残存という
     negative mutationで、本runner自身がfail-closedになることを検証する。

CODEX第3ラウンドで指摘された2件（`evaluate_case_ids()`自体は正しく実装
されていたが、その手前の集約経路にfail-closed不足が残っていた）への対応:
  5. `_run_gitlink_check()`がGLK check行を`checks[name] = verdict`という
     dictへ格納してから`evaluate_case_ids()`へ渡していたため、rawで同じID
     が複数回出力されてもdict化の時点で上書きされ、duplicate判定へ
     到達する前に消えていた（`parse_gitlink_stdout()`を新設し、dictとは
     別に重複を保持したままのraw list `check_names_raw` を返すよう分離）。
  6. manifest内の`declared_total`フィールド自体をrunner本体が一度も検証
     しておらず、`declared_case_ids`の実件数と食い違っていても
     （例: manifestを直接改ざんして`declared_total=999`にする）検出
     できなかった（`load_manifest()`が読み込み時に整合性を検証し、
     不一致なら`ManifestIntegrityError`でfail-closedにする）。

実行:
    python3 tools/public_release/phase2c_official_runner.py

終了コード: 0 = manifestどおり全case PASS・cleanup確認OK、1 = 何らかの
不一致/FAIL、2 = junit xml生成失敗・manifest不整合等の致命的実行時エラー。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
EVIDENCE_DIR = REPO_ROOT / "tasks" / "public-release" / "evidence" / "phase2c"
PYTEST_TARGET = "tests/test_phase2c_public_hardening.py"
GITLINK_TOOL = REPO_ROOT / "tools" / "public_release" / "phase2c_gitlink_check.py"
MANIFEST_PATH = Path(__file__).resolve().parent / "phase2c_case_manifest.json"


class ManifestIntegrityError(ValueError):
    """`phase2c_case_manifest.json`自体の内部整合性が崩れている場合に送出する
    （CODEX第3ラウンドP2C-CX-003(2)対応: `declared_total`フィールドと
    `declared_case_ids`の実件数が食い違う、または宣言ID自体に重複がある等）。
    manifestを直接改ざんしても`declared_total`だけを見た浅い検証をすり抜け
    られないよう、読み込み時点でfail-closedにする。"""


def load_manifest(manifest_path: Path = MANIFEST_PATH) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    declared_ids = manifest.get("declared_case_ids", [])
    declared_total_field = manifest.get("declared_total")
    if declared_total_field != len(declared_ids):
        raise ManifestIntegrityError(
            f"manifest declared_total={declared_total_field!r} が "
            f"declared_case_idsの実件数={len(declared_ids)}と一致しない"
            f"（manifest改ざん・編集ミスの疑い）"
        )
    if len(declared_ids) != len(set(declared_ids)):
        raise ManifestIntegrityError("manifest declared_case_ids自体に重複IDが含まれている")

    glk_checks = manifest.get("glk_declared_checks", [])
    if len(glk_checks) != len(set(glk_checks)):
        raise ManifestIntegrityError("manifest glk_declared_checks自体に重複IDが含まれている")

    return manifest


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


# ============================================================
# 純粋関数（CODEX第2ラウンド対応、self-check testの直接対象）
# ============================================================


def evaluate_case_ids(declared_ids: List[str], actual_ids: List[str]) -> dict:
    """宣言case ID集合と実測case ID列（重複を保持したままのraw list）を突合する。

    件数だけの比較ではなく、次の3種を個別に検出する:
      - duplicates: actual_ids内で2回以上出現するID（分母をすり替えて
        件数だけ帳尻を合わせる手口を検出する）
      - missing: declaredにあるがactualに一度も現れないID
      - unexpected: actualにあるがdeclaredにないID
    """
    actual_set = set(actual_ids)
    declared_set = set(declared_ids)
    duplicates = sorted({case_id for case_id in actual_ids if actual_ids.count(case_id) > 1})
    missing = sorted(declared_set - actual_set)
    unexpected = sorted(actual_set - declared_set)
    ok = (
        not duplicates
        and not missing
        and not unexpected
        and len(actual_ids) == len(declared_ids)
    )
    return {
        "declared_total": len(declared_ids),
        "actual_total": len(actual_ids),
        "duplicates": duplicates,
        "missing": missing,
        "unexpected": unexpected,
        "ok": ok,
    }


def docker_query(*args: str) -> dict:
    """`docker <args>`を実行し、行配列とexit codeの両方を返す
    （exit codeを握りつぶさない、CODEX第2ラウンドP2C-CX-003(2)対応）。"""
    proc = subprocess.run(["docker", *args], capture_output=True, text=True)
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    return {"lines": lines, "exit_code": proc.returncode, "stderr": proc.stderr}


def default_temp_roots() -> List[Path]:
    """`/tmp`・`/private/tmp`に加え、`tempfile.gettempdir()`
    （macOSでは実際には`/var/folders/.../T`等を指す、CODEX第2ラウンド
    P2C-CX-003(3)対応）も一時残存検査の対象root集合とする。"""
    roots: List[Path] = []
    for raw in ("/tmp", "/private/tmp", tempfile.gettempdir()):
        candidate = Path(raw)
        if candidate not in roots:
            roots.append(candidate)
    return roots


def ohg2p2c_residue_snapshot(
    temp_roots: Optional[List[Path]] = None,
    docker_query_fn: Callable[..., dict] = docker_query,
) -> dict:
    """`ohg2p2c*` prefix資源の残存snapshotを取る。

    `docker_query_fn`と`temp_roots`をdependency injectionできるようにし、
    self-check testがDocker query失敗や実temp root残存をmutationとして
    注入できるようにする。
    """
    query_specs = {
        "containers": ["ps", "-a", "--filter", "name=ohg2p2c", "--format", "{{.Names}}"],
        "networks": ["network", "ls", "--filter", "name=ohg2p2c", "--format", "{{.Name}}"],
        "volumes": ["volume", "ls", "--filter", "name=ohg2p2c", "--format", "{{.Name}}"],
        "images": ["images", "--filter", "reference=ohg2p2c*", "--format", "{{.Repository}}"],
    }
    query_results = {name: docker_query_fn(*args) for name, args in query_specs.items()}
    query_failed_commands = sorted(
        name for name, result in query_results.items() if result["exit_code"] != 0
    )

    roots = temp_roots if temp_roots is not None else default_temp_roots()
    tmp_hits: List[str] = []
    for base in roots:
        if base.is_dir():
            tmp_hits.extend(str(p) for p in base.glob("*ohg2p2c*"))

    resource_count = sum(len(result["lines"]) for result in query_results.values()) + len(tmp_hits)

    return {
        "containers": query_results["containers"]["lines"],
        "networks": query_results["networks"]["lines"],
        "volumes": query_results["volumes"]["lines"],
        "images": query_results["images"]["lines"],
        "temp_paths": tmp_hits,
        "temp_roots_scanned": [str(root) for root in roots],
        "docker_query_exit_codes": {
            name: result["exit_code"] for name, result in query_results.items()
        },
        "query_failed_commands": query_failed_commands,
        "resource_count": resource_count,
        # query失敗時はresource_count==0であっても「確認できていない」
        # ため必ずFalseにする（query失敗をfalse negativeの0件残存として
        # 扱わない、CODEX第2ラウンドP2C-CX-003(2)対応）。
        "residue_confirmed_zero": (not query_failed_commands) and resource_count == 0,
    }


def _run_pytest(junit_xml_path: Path, stdout_log_path: Path) -> dict:
    command = [
        sys.executable, "-m", "pytest", PYTEST_TARGET,
        "-v", f"--junit-xml={junit_xml_path}",
    ]
    proc = subprocess.run(command, cwd=str(BACKEND_DIR), capture_output=True, text=True)
    stdout_log_path.write_text(proc.stdout + "\n---STDERR---\n" + proc.stderr, encoding="utf-8")
    return {"command": " ".join(command), "exit_code": proc.returncode}


def _parse_junit(junit_xml_path: Path) -> list:
    tree = ET.parse(junit_xml_path)
    root = tree.getroot()
    cases = []
    for case_el in root.iter("testcase"):
        classname = case_el.get("classname", "")
        name = case_el.get("name", "")
        short_classname = classname.rsplit(".", 1)[-1] if classname else ""
        failure = case_el.find("failure")
        error = case_el.find("error")
        skipped = case_el.find("skipped")
        if failure is not None:
            actual, message = "FAIL", failure.get("message", "")
        elif error is not None:
            actual, message = "ERROR", error.get("message", "")
        elif skipped is not None:
            actual, message = "SKIPPED", skipped.get("message", "")
        else:
            actual, message = "PASS", ""
        case_xml_fragment = ET.tostring(case_el, encoding="unicode")
        cases.append({
            "unique_id": f"{short_classname}::{name}",
            "class": short_classname,
            "name": name,
            "expected": "PASS",
            "actual": actual,
            "message": message,
            "replay_command": (
                f"{sys.executable} -m pytest {PYTEST_TARGET}::{short_classname}::{name} -v"
            ),
            "artifact_sha256": _sha256_text(case_xml_fragment),
        })
    return cases


def parse_gitlink_stdout(stdout: str) -> dict:
    """`phase2c_gitlink_check.py`のstdoutから`<name>: PASS/FAIL`形式の行を
    抽出する（CODEX第3ラウンドP2C-CX-003(1)対応の純粋関数、self-check testの
    直接対象）。

    `check_names_raw`は出現順そのまま・重複を保持したlist（duplicate判定は
    これを`evaluate_case_ids()`へそのまま渡すことで行う）。`checks`は
    name→最新verdictのdict（表示・non-pass検査用の便宜的な集計であり、
    duplicate判定の入力には使わない——dict化した時点で重複が上書きされ
    検出不能になるため、判定用のraw listと表示用のdictを明確に分離する）。
    """
    marker = "[phase2c_gitlink_check] "
    check_names_raw: List[str] = []
    checks: Dict[str, str] = {}
    for line in stdout.splitlines():
        if not line.startswith(marker):
            continue
        body = line[len(marker):]
        name, sep, verdict = body.rpartition(": ")
        if sep and verdict in ("PASS", "FAIL"):
            check_names_raw.append(name)
            checks[name] = verdict
    return {"check_names_raw": check_names_raw, "checks": checks}


def _run_gitlink_check() -> dict:
    command = [sys.executable, str(GITLINK_TOOL)]
    proc = subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, text=True)
    parsed = parse_gitlink_stdout(proc.stdout)
    return {
        "command": " ".join(command),
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "check_names_raw": parsed["check_names_raw"],
        "checks": parsed["checks"],
        "stdout_sha256": _sha256_text(proc.stdout),
    }


def main() -> int:
    manifest = load_manifest()
    declared_case_ids = manifest["declared_case_ids"]
    glk_declared_checks = manifest["glk_declared_checks"]

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    run_started_at = datetime.now(timezone.utc).isoformat()

    residue_before = ohg2p2c_residue_snapshot()

    junit_xml_path = EVIDENCE_DIR / "phase2c_junit.xml"
    stdout_log_path = EVIDENCE_DIR / "phase2c_pytest_stdout.log"
    pytest_meta = _run_pytest(junit_xml_path, stdout_log_path)

    if not junit_xml_path.exists():
        print("[phase2c_official_runner] FATAL: junit xml not produced, cannot verify denominators")
        return 2

    cases = _parse_junit(junit_xml_path)
    actual_ids_raw = [c["unique_id"] for c in cases]
    id_evaluation = evaluate_case_ids(declared_case_ids, actual_ids_raw)
    non_pass_cases = [c for c in cases if c["actual"] != "PASS"]

    gitlink_result = _run_gitlink_check()
    glk_actual_checks = gitlink_result["checks"]
    # CODEX第3ラウンドP2C-CX-003(1)対応: dict化済みのkey列ではなく、
    # 重複を保持したままのraw list（check_names_raw）をduplicate判定へ渡す。
    glk_id_evaluation = evaluate_case_ids(
        glk_declared_checks, gitlink_result["check_names_raw"]
    )
    glk_non_pass = [k for k, v in glk_actual_checks.items() if v != "PASS"]

    residue_after = ohg2p2c_residue_snapshot()

    overall_pass = (
        pytest_meta["exit_code"] == 0
        and id_evaluation["ok"]
        and not non_pass_cases
        and gitlink_result["exit_code"] == 0
        and glk_id_evaluation["ok"]
        and not glk_non_pass
        and residue_before["residue_confirmed_zero"]
        and residue_after["residue_confirmed_zero"]
    )

    (EVIDENCE_DIR / "phase2c_case_results.json").write_text(
        json.dumps({
            "batch_command": pytest_meta["command"],
            "batch_exit_code": pytest_meta["exit_code"],
            "manifest_path": str(MANIFEST_PATH),
            "id_evaluation": id_evaluation,
            "cases": cases,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (EVIDENCE_DIR / "phase2c_gitlink_check.json").write_text(
        json.dumps({
            "command": gitlink_result["command"],
            "exit_code": gitlink_result["exit_code"],
            "id_evaluation": glk_id_evaluation,
            "actual_checks": glk_actual_checks,
            "non_pass_checks": glk_non_pass,
            "stdout_sha256": gitlink_result["stdout_sha256"],
            "stdout": gitlink_result["stdout"],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    junit_xml_sha256 = _sha256_bytes(junit_xml_path.read_bytes())
    stdout_log_sha256 = _sha256_bytes(stdout_log_path.read_bytes())
    repo_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), capture_output=True, text=True
    ).stdout.strip()

    summary = {
        "run_started_at_utc": run_started_at,
        "run_finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_head": repo_head,
        "manifest_sha256": _sha256_bytes(MANIFEST_PATH.read_bytes()),
        "pytest": {
            "command": pytest_meta["command"],
            "exit_code": pytest_meta["exit_code"],
            "junit_xml_sha256": junit_xml_sha256,
            "stdout_log_sha256": stdout_log_sha256,
        },
        "case_id_evaluation": id_evaluation,
        "non_pass_cases": [
            {"unique_id": c["unique_id"], "actual": c["actual"], "message": c["message"]}
            for c in non_pass_cases
        ],
        "gitlink_check": {
            "exit_code": gitlink_result["exit_code"],
            "id_evaluation": glk_id_evaluation,
            "non_pass_checks": glk_non_pass,
        },
        "cleanup_control": {
            "ohg2p2c_residue_before": residue_before,
            "ohg2p2c_residue_after": residue_after,
        },
        "overall_result": "PASS" if overall_pass else "FAIL",
    }
    summary["summary_sha256_excluding_self"] = _sha256_bytes(
        json.dumps(summary, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    (EVIDENCE_DIR / "phase2c_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"[phase2c_official_runner] case_id_evaluation={id_evaluation}")
    print(f"[phase2c_official_runner] non_pass_cases={len(non_pass_cases)}")
    print(
        f"[phase2c_official_runner] gitlink exit={gitlink_result['exit_code']} "
        f"id_evaluation={glk_id_evaluation} non_pass={glk_non_pass}"
    )
    print(
        f"[phase2c_official_runner] residue_before={residue_before['residue_confirmed_zero']} "
        f"(failed_queries={residue_before['query_failed_commands']}, count={residue_before['resource_count']}) "
        f"residue_after={residue_after['residue_confirmed_zero']} "
        f"(failed_queries={residue_after['query_failed_commands']}, count={residue_after['resource_count']})"
    )
    print(f"[phase2c_official_runner] evidence written to {EVIDENCE_DIR}")
    print(f"[phase2c_official_runner] OVERALL RESULT: {summary['overall_result']}")

    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
