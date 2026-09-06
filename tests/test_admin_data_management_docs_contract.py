"""
test_admin_data_management_docs_contract.py —
Dual Storage Remediation Phase C3-B のdocumentation更新（
docs/admin-data-management.md）が、意図した重要な契約説明を
含んでいることを確認する軽量testcontract。

脆い全文一致は避け、「この概念が説明されているか」という観点の
キーワード存在確認に留める（本文の言い回し変更に対して過度に
壊れないようにするため）。
"""
from __future__ import annotations

from pathlib import Path

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "admin-data-management.md"


def _read() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_doc_exists_and_is_readable():
    assert DOC_PATH.is_file()
    assert len(_read()) > 0


def test_doc_explains_admin_deploy_step_exists():
    """従来ドキュメントの図には存在しなかった"deploy"（flatへの反映）
    ステップが明記されていること。"""
    content = _read()
    assert "deploy" in content
    assert "flat runtime" in content


def test_doc_explains_admin_deploy_not_equal_current_activation():
    content = _read()
    assert "current が切り替わった" in content or "current/versioned" in content


def test_doc_explains_flat_is_not_official_recovery():
    content = _read()
    assert "recovery" in content or "復旧" in content
    assert "activate_version.py --rollback" in content


def test_doc_explains_active_mappings_not_flat_only_state():
    content = _read()
    assert "flat 専用の state" in content or "flat専用" in content


def test_doc_explains_runtime_path_points_to_flat_not_current():
    content = _read()
    assert "runtime_path" in content
    assert "current_runtime_path" in content


def test_doc_explains_transient_inconsistency_is_not_corruption():
    content = _read()
    assert "破損ではなく" in content or "corruption" in content
