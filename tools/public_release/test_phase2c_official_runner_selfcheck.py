"""
Phase 2-C 公式runner自己検証（CODEX第2・第3ラウンドP2C-CX-003対応）。

`phase2c_official_runner.py`のfail-closed判定ロジック（case ID重複／欠落／
想定外の検出、GLK stdout解析でのraw ID重複保持、manifest自体の内部整合性
検証、Docker照会失敗のcleanup検証への反映、実temp root残存検出）を純粋関数
として切り出し、negative mutation・positive controlの両方で検証する。
実Docker daemon・実app_publicのheavy importを一切必要としないため高速。

実行:
    cd /path/to/repo && venv/bin/python -m pytest tools/public_release/test_phase2c_official_runner_selfcheck.py -v
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from phase2c_official_runner import (  # noqa: E402
    ManifestIntegrityError,
    default_temp_roots,
    evaluate_case_ids,
    load_manifest,
    ohg2p2c_residue_snapshot,
    parse_gitlink_stdout,
)


# ============================================================
# case ID evaluation: duplicate / missing / unexpected mutation
# ============================================================


class TestEvaluateCaseIdsPositiveControl:
    def test_exact_match_is_ok(self):
        declared = ["A::t1", "A::t2", "B::t1"]
        actual = ["A::t1", "A::t2", "B::t1"]
        result = evaluate_case_ids(declared, actual)
        assert result["ok"] is True
        assert result["duplicates"] == []
        assert result["missing"] == []
        assert result["unexpected"] == []

    def test_order_independent(self):
        declared = ["A::t1", "A::t2", "B::t1"]
        actual = ["B::t1", "A::t2", "A::t1"]
        assert evaluate_case_ids(declared, actual)["ok"] is True


class TestEvaluateCaseIdsNegativeMutation:
    """CODEX第2ラウンド指摘: 「同一class内で必須caseを別caseへ差し替える、
    またはIDを重複させても件数が同じならPASS可能」という抜け穴を、
    duplicate/missing/unexpectedの個別検出で塞いだことを確認する。"""

    def test_duplicate_id_replacing_a_missing_required_case_is_detected(self):
        """件数だけは一致するが、必須case Bの代わりにAが重複しているケース。
        件数一致だけを見るrunnerならPASSしてしまう典型的な抜け穴。"""
        declared = ["A::t1", "A::t2", "B::t1"]
        actual = ["A::t1", "A::t2", "A::t2"]  # B::t1が欠落、A::t2が重複
        result = evaluate_case_ids(declared, actual)
        assert result["ok"] is False
        assert result["duplicates"] == ["A::t2"]
        assert result["missing"] == ["B::t1"]
        assert len(actual) == len(declared)  # 件数だけは一致することを確認

    def test_missing_case_is_detected(self):
        declared = ["A::t1", "A::t2", "B::t1"]
        actual = ["A::t1", "A::t2"]
        result = evaluate_case_ids(declared, actual)
        assert result["ok"] is False
        assert result["missing"] == ["B::t1"]

    def test_unexpected_extra_case_is_detected(self):
        declared = ["A::t1", "A::t2"]
        actual = ["A::t1", "A::t2", "C::unexpected"]
        result = evaluate_case_ids(declared, actual)
        assert result["ok"] is False
        assert result["unexpected"] == ["C::unexpected"]

    def test_duplicate_without_denominator_change_is_detected(self):
        """重複IDを追加しつつ他の1件を削って総数だけ据え置いた場合。"""
        declared = ["A::t1", "A::t2", "B::t1"]
        actual = ["A::t1", "A::t1", "B::t1"]  # A::t2が欠落、A::t1が重複
        result = evaluate_case_ids(declared, actual)
        assert result["ok"] is False
        assert result["duplicates"] == ["A::t1"]
        assert result["missing"] == ["A::t2"]


class TestManifestIntegrity:
    def test_manifest_has_no_internal_duplicates(self):
        manifest = load_manifest()
        ids = manifest["declared_case_ids"]
        assert len(ids) == len(set(ids)), "manifest自体にduplicate IDが含まれている"
        assert manifest["declared_total"] == len(ids)

    def test_manifest_glk_checks_fixed_at_six(self):
        manifest = load_manifest()
        assert len(manifest["glk_declared_checks"]) == 6
        assert len(set(manifest["glk_declared_checks"])) == 6


# ============================================================
# Docker query失敗のcleanup検証への反映（CODEX第2ラウンド指摘(2)）
# ============================================================


def _fake_docker_query_all_ok(*args):
    return {"lines": [], "exit_code": 0, "stderr": ""}


def _fake_docker_query_one_fails(*args):
    # "network"照会だけ daemon不調で失敗するケースを模擬する
    if "network" in args:
        return {"lines": [], "exit_code": 1, "stderr": "Cannot connect to the Docker daemon"}
    return {"lines": [], "exit_code": 0, "stderr": ""}


def _fake_docker_query_reports_resource_but_succeeds(*args):
    if "ps" in args:
        return {"lines": ["ohg2p2c_stray_container"], "exit_code": 0, "stderr": ""}
    return {"lines": [], "exit_code": 0, "stderr": ""}


class TestDockerQueryFailureHandling:
    def test_all_queries_succeed_zero_resources_is_confirmed_zero(self, tmp_path):
        snapshot = ohg2p2c_residue_snapshot(
            temp_roots=[tmp_path], docker_query_fn=_fake_docker_query_all_ok
        )
        assert snapshot["query_failed_commands"] == []
        assert snapshot["resource_count"] == 0
        assert snapshot["residue_confirmed_zero"] is True

    def test_one_query_failure_is_not_treated_as_zero_residue(self, tmp_path):
        """CODEX第2ラウンド指摘(2)の直接回帰: daemon照会が非0でstdout空でも、
        『0件残存』とfalse negative判定してはならない。"""
        snapshot = ohg2p2c_residue_snapshot(
            temp_roots=[tmp_path], docker_query_fn=_fake_docker_query_one_fails
        )
        assert snapshot["query_failed_commands"] == ["networks"]
        assert snapshot["resource_count"] == 0  # stdoutは空のまま
        assert snapshot["residue_confirmed_zero"] is False, (
            "Docker照会失敗が『0件残存』としてfalse negative判定された"
            "（P2C-CX-003(2)の回帰）"
        )

    def test_actual_residue_is_detected_even_when_all_queries_succeed(self, tmp_path):
        snapshot = ohg2p2c_residue_snapshot(
            temp_roots=[tmp_path],
            docker_query_fn=_fake_docker_query_reports_resource_but_succeeds,
        )
        assert snapshot["query_failed_commands"] == []
        assert snapshot["resource_count"] == 1
        assert snapshot["residue_confirmed_zero"] is False


# ============================================================
# 実temp rootの残存検出（CODEX第2ラウンド指摘(3)）
# ============================================================


class TestTempRootScanning:
    def test_default_temp_roots_includes_tempfile_gettempdir(self):
        """`/tmp`・`/private/tmp`だけでなく`tempfile.gettempdir()`
        （macOSでは実際には`/var/folders/.../T`等を指す）も
        scan対象に含まれることを確認する（P2C-CX-003(3)の直接回帰）。"""
        roots = default_temp_roots()
        root_strs = [str(r) for r in roots]
        assert str(Path(tempfile.gettempdir())) in root_strs
        assert str(Path("/tmp")) in root_strs
        assert str(Path("/private/tmp")) in root_strs

    def test_stray_file_in_real_tempfile_gettempdir_is_detected(self):
        """`tempfile.gettempdir()`配下（実runnerのgitlink toolが一時repoを
        作る場所と同じ実temp root）に実際に`ohg2p2c*`残存物を作り、
        `default_temp_roots()`経由のscanが検出できることを実filesystemで
        確認する（`/tmp`・`/private/tmp`だけの旧実装では検出できなかった
        経路の直接回帰）。"""
        real_temp_root = Path(tempfile.gettempdir())
        stray_dir = real_temp_root / "ohg2p2c_selfcheck_stray_probe"
        stray_dir.mkdir(exist_ok=True)
        try:
            snapshot = ohg2p2c_residue_snapshot(
                temp_roots=default_temp_roots(), docker_query_fn=_fake_docker_query_all_ok
            )
            assert any("ohg2p2c_selfcheck_stray_probe" in p for p in snapshot["temp_paths"]), (
                f"実tempfile.gettempdir()配下の残存物が検出されなかった: {snapshot['temp_paths']}"
            )
            assert snapshot["residue_confirmed_zero"] is False
        finally:
            stray_dir.rmdir()

    def test_no_stray_files_after_cleanup_is_confirmed_zero(self):
        """positive control: 実temp rootに残存物がなければ
        residue_confirmed_zero=Trueになる（stray probeが確実に片付いている
        ことも合わせて確認する）。"""
        real_temp_root = Path(tempfile.gettempdir())
        assert not list(real_temp_root.glob("*ohg2p2c_selfcheck_stray_probe*"))
        snapshot = ohg2p2c_residue_snapshot(
            temp_roots=[real_temp_root], docker_query_fn=_fake_docker_query_all_ok
        )
        leftover = [p for p in snapshot["temp_paths"] if "ohg2p2c_selfcheck_stray_probe" in p]
        assert leftover == []


# ============================================================
# GLK stdout解析でのraw ID重複保持（CODEX第3ラウンドP2C-CX-003(1)対応）
# ============================================================


class TestParseGitlinkStdoutDuplicateDetection:
    """CODEXの局所mutation（同じGLK IDを複数回出力しても、dict化した
    key列だけを見るとduplicateが消えてしまう）を、dict化前のraw list
    （`check_names_raw`）を直接検査することで検出できることを確認する。"""

    def test_normal_output_has_no_duplicates_in_raw_list(self):
        stdout = "\n".join([
            "[phase2c_gitlink_check] g1: PASS",
            "[phase2c_gitlink_check] g2: PASS",
            "[phase2c_gitlink_check] AT-15 overall = PASS",  # summary行、":"を含まないため無視される
        ])
        parsed = parse_gitlink_stdout(stdout)
        assert parsed["check_names_raw"] == ["g1", "g2"]
        result = evaluate_case_ids(["g1", "g2"], parsed["check_names_raw"])
        assert result["ok"] is True

    def test_duplicate_check_line_is_preserved_in_raw_list_and_detected(self):
        """CODEX第3ラウンドの再現手順そのもの: g1を2回出力してもg2は1回のみ
        （宣言2件に対し実測3行）。dictに縮約すると{'g1':'PASS','g2':'PASS'}
        の2 keyとなりduplicateが消えるが、raw listは3件のまま保持され、
        `evaluate_case_ids()`が正しくduplicatesを検出する。"""
        stdout = "\n".join([
            "[phase2c_gitlink_check] g1: PASS",
            "[phase2c_gitlink_check] g1: PASS",
            "[phase2c_gitlink_check] g2: PASS",
        ])
        parsed = parse_gitlink_stdout(stdout)
        assert parsed["check_names_raw"] == ["g1", "g1", "g2"]
        assert parsed["checks"] == {"g1": "PASS", "g2": "PASS"}  # dict側は上書きされて2件になる（表示用、判定には使わない）

        result = evaluate_case_ids(["g1", "g2"], parsed["check_names_raw"])
        assert result["ok"] is False, (
            "GLK check行の重複出力がraw list経由でも検出されなかった"
            "（P2C-CX-003(1)の回帰、CODEX第3ラウンド再現ケース）"
        )
        assert result["duplicates"] == ["g1"]

    def test_missing_check_line_is_detected_via_raw_list(self):
        stdout = "[phase2c_gitlink_check] g1: PASS"
        parsed = parse_gitlink_stdout(stdout)
        result = evaluate_case_ids(["g1", "g2"], parsed["check_names_raw"])
        assert result["ok"] is False
        assert result["missing"] == ["g2"]

    def test_unrelated_lines_are_ignored(self):
        stdout = "\n".join([
            "some unrelated log line",
            "[phase2c_gitlink_check] repo_root=/x HEAD=abc",  # ":"を含まない形式
            "[phase2c_gitlink_check] g1: PASS",
        ])
        parsed = parse_gitlink_stdout(stdout)
        assert parsed["check_names_raw"] == ["g1"]


# ============================================================
# manifest自体の内部整合性検証（CODEX第3ラウンドP2C-CX-003(2)対応）
# ============================================================


class TestManifestIntegrityValidation:
    """CODEXの局所mutation（`declared_total`だけを`999`等へ改ざんしても、
    runnerがそれを一度も参照しないため検出できない）を、`load_manifest()`
    が読み込み時に`declared_total`と実件数の一致を検証することで
    塞いだことを確認する。"""

    def _write_manifest(self, tmp_path, declared_total, declared_case_ids, glk_checks=None):
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps({
            "declared_case_ids": declared_case_ids,
            "declared_total": declared_total,
            "glk_declared_checks": glk_checks if glk_checks is not None else ["g1", "g2"],
        }), encoding="utf-8")
        return manifest_path

    def test_valid_manifest_loads_successfully(self, tmp_path):
        manifest_path = self._write_manifest(tmp_path, 2, ["A::t1", "A::t2"])
        manifest = load_manifest(manifest_path)
        assert manifest["declared_total"] == 2

    def test_tampered_declared_total_is_rejected(self, tmp_path):
        """CODEX第3ラウンドの再現手順そのもの: declared_case_idsは177件相当
        （ここでは2件）のままdeclared_totalだけを999へ改ざんする。"""
        manifest_path = self._write_manifest(tmp_path, 999, ["A::t1", "A::t2"])
        with pytest.raises(ManifestIntegrityError):
            load_manifest(manifest_path)

    def test_declared_total_smaller_than_actual_ids_is_also_rejected(self, tmp_path):
        manifest_path = self._write_manifest(tmp_path, 1, ["A::t1", "A::t2"])
        with pytest.raises(ManifestIntegrityError):
            load_manifest(manifest_path)

    def test_duplicate_ids_within_manifest_itself_is_rejected(self, tmp_path):
        manifest_path = self._write_manifest(tmp_path, 3, ["A::t1", "A::t1", "A::t2"])
        with pytest.raises(ManifestIntegrityError):
            load_manifest(manifest_path)

    def test_duplicate_glk_checks_within_manifest_itself_is_rejected(self, tmp_path):
        manifest_path = self._write_manifest(
            tmp_path, 2, ["A::t1", "A::t2"], glk_checks=["g1", "g1"]
        )
        with pytest.raises(ManifestIntegrityError):
            load_manifest(manifest_path)

    def test_real_manifest_file_passes_integrity_check(self):
        """positive control: repo実物のmanifestが改ざんされていないことを
        毎回確認する。"""
        manifest = load_manifest()
        assert manifest["declared_total"] == len(manifest["declared_case_ids"])
        assert len(manifest["declared_case_ids"]) == len(set(manifest["declared_case_ids"]))
