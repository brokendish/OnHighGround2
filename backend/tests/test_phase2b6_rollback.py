"""
Phase 2-B.6 受入試験 — rollback manifest schema／validator（第7節）。

構成:
  1. RBM-P001（valid）／RBM-N001〜N009（9カテゴリの独立negative fixture）を
     `tools/public_release/phase2b6_rollback_validate.py`へ通す静的試験。
  2. 実運用VPSではなく、isolated scratch root上で
     `backend/app/services/runtime_publish.py::AtomicPublisher`を直接使い、
     (a) invalid manifestによるrollback入口の状態変更前拒否、
     (b) valid manifestによるrollback後、新規readerが完全な旧versionだけを
         観測し部分混在しないこと、
     を実際に実行して確認する（第7節「local isolated fixtureだけを用いる」）。

実行:
    cd backend && ../venv/bin/python -m pytest tests/test_phase2b6_rollback.py -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.runtime_atomic import generate_version_id  # noqa: E402
from app.services.runtime_publish import AtomicPublisher, VERSION_DIR_MODE, VERSION_FILE_MODE  # noqa: E402

VALIDATOR = REPO_ROOT / "tools/public_release/phase2b6_rollback_validate.py"
FIXTURE_BASE = REPO_ROOT / "tests/fixtures/public_release/rollback"

RBM_CASES = [
    ("RBM-P001", 0, "VALID"),
    ("RBM-N001", 2, "E_ROLLBACK_SCHEMA_INVALID"),
    ("RBM-N002", 2, "E_ROLLBACK_SCHEMA_UNSUPPORTED"),
    ("RBM-N003", 2, "E_ROLLBACK_REQUIRED_MISSING"),
    ("RBM-N004", 2, "E_ROLLBACK_ADDITIONAL_FIELD"),
    ("RBM-N005", 2, "E_ROLLBACK_HASH_MALFORMED"),
    ("RBM-N006", 2, "E_ROLLBACK_CHECKSUM_MISMATCH"),
    ("RBM-N007", 2, "E_ROLLBACK_REFERENCE_INCONSISTENT"),
    ("RBM-N008", 2, "E_ROLLBACK_PATH_ESCAPE"),
    ("RBM-N009", 2, "E_ROLLBACK_SECRET_VALUE_LEAK"),
]
assert len(RBM_CASES) == 10
assert len({fid for fid, _, _ in RBM_CASES}) == 10


@pytest.mark.parametrize("fixture_id,expected_exit,expected_code", RBM_CASES)
def test_rollback_manifest_fixture(tmp_path, fixture_id, expected_exit, expected_code):
    manifest = FIXTURE_BASE / f"{fixture_id}.json"
    assert manifest.is_file(), f"{fixture_id} manifest missing"
    result_path = tmp_path / f"{fixture_id}.json"
    cmd = [sys.executable, str(VALIDATOR), "--manifest", str(manifest), "--result", str(result_path)]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
    assert proc.returncode == expected_exit, f"{fixture_id}: stdout={proc.stdout!r} stderr={proc.stderr!r}"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["primary_code"] == expected_code


# ---------------------------------------------------------------------------
# Live isolated-root rollback behavior
# ---------------------------------------------------------------------------

UID = os.geteuid()
GID = os.getegid()


def _write_version(staging_path: Path, marker: str) -> None:
    import hashlib

    staging_path.mkdir(mode=VERSION_DIR_MODE, exist_ok=True)
    os.chmod(staging_path, VERSION_DIR_MODE)
    marker_file = staging_path / "marker.txt"
    marker_file.write_text(marker, encoding="utf-8")
    os.chmod(marker_file, VERSION_FILE_MODE)

    # runtime_publish.rollback() re-verifies version content against
    # _manifest.json (runtime_dataset_validate.verify_manifest_matches_disk)
    # before allowing a rollback target; this isolated fixture must provide
    # one even though it uses a no-op publish-time validate_fn.
    marker_sha256 = hashlib.sha256(marker.encode("utf-8")).hexdigest()
    manifest_file = staging_path / "_manifest.json"
    manifest_file.write_text(json.dumps({"files": {"marker.txt": marker_sha256}}), encoding="utf-8")
    os.chmod(manifest_file, VERSION_FILE_MODE)


def _noop_validate(staging_path: Path, previous_version_path):
    return None


@pytest.fixture
def isolated_publisher(tmp_path):
    root = tmp_path / "data_runtime_isolated"
    (root / ".staging").mkdir(parents=True)
    (root / "versions").mkdir(parents=True)
    lock_path = root / ".publish.lock"
    lock_path.touch(mode=0o600)
    publisher = AtomicPublisher(root, expect_uid=UID, expect_gid=GID)
    yield publisher, root


def test_rollback_isolated_setup_and_reader_observation(isolated_publisher):
    publisher, root = isolated_publisher

    version_a = generate_version_id()
    staging_a = publisher.new_staging_path(version_a)
    _write_version(staging_a, "VERSION-A-CONTENT")
    result_a = publisher.publish(version_a, _noop_validate)
    assert result_a.version_id == version_a
    assert result_a.previous_version_id is None

    version_b = generate_version_id()
    staging_b = publisher.new_staging_path(version_b)
    _write_version(staging_b, "VERSION-B-CONTENT")
    result_b = publisher.publish(version_b, _noop_validate)
    assert result_b.version_id == version_b
    assert result_b.previous_version_id == f"versions/{version_a}"

    current_target_before = os.readlink(root / "current")
    assert current_target_before == f"versions/{version_b}"
    versions_before = set(publisher.list_versions())
    assert versions_before == {version_a, version_b}

    # --- (a) invalid manifest must be rejected BEFORE any state change ---
    invalid_manifest_path = root / "invalid-rollback-manifest.json"
    valid = FIXTURE_BASE / "RBM-N006.json"  # checksum mismatch
    invalid_manifest_path.write_text(valid.read_text(encoding="utf-8"), encoding="utf-8")

    validate_result_path = root / "invalid-validate-result.json"
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), "--manifest", str(invalid_manifest_path), "--result", str(validate_result_path)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 2
    validate_result = json.loads(validate_result_path.read_text())
    assert validate_result["primary_code"] == "E_ROLLBACK_CHECKSUM_MISMATCH"

    # Because the manifest was rejected, the rollback entry point must never
    # have been invoked. Confirm no state changed.
    assert os.readlink(root / "current") == current_target_before
    assert set(publisher.list_versions()) == versions_before
    reader_after_rejected = (root / "current" / "marker.txt").read_text(encoding="utf-8")
    assert reader_after_rejected == "VERSION-B-CONTENT"

    # --- (b) valid manifest referencing the real A/B version ids ---
    valid_manifest = json.loads((FIXTURE_BASE / "RBM-P001.json").read_text(encoding="utf-8"))
    valid_manifest["version_id"] = version_b
    valid_manifest["previous_version_id"] = version_a
    valid_manifest["data"]["before_runtime_version_id"] = version_a
    valid_manifest["data"]["after_runtime_version_id"] = version_b
    import hashlib

    def canonical_checksum(m):
        body = {k: v for k, v in m.items() if k != "manifest_checksum"}
        text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    valid_manifest["manifest_checksum"] = canonical_checksum(valid_manifest)
    valid_manifest_path = root / "valid-rollback-manifest.json"
    valid_manifest_path.write_text(json.dumps(valid_manifest, indent=2), encoding="utf-8")

    validate_result_path2 = root / "valid-validate-result.json"
    proc2 = subprocess.run(
        [sys.executable, str(VALIDATOR), "--manifest", str(valid_manifest_path), "--result", str(validate_result_path2)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc2.returncode == 0
    validate_result2 = json.loads(validate_result_path2.read_text())
    assert validate_result2["primary_code"] == "VALID"

    # Only now, after the manifest is validated, invoke the actual rollback.
    rollback_result = publisher.rollback(version_a)
    assert rollback_result.version_id == version_a
    assert rollback_result.previous_version_id == f"versions/{version_b}"

    # New readers must observe ONLY the complete old version, never a mix.
    assert os.readlink(root / "current") == f"versions/{version_a}"
    reader_after_rollback = (root / "current" / "marker.txt").read_text(encoding="utf-8")
    assert reader_after_rollback == "VERSION-A-CONTENT"
    assert set(os.listdir(root / "current")) == {"marker.txt", "_manifest.json"}
