#!/usr/bin/env python3
"""OSRM provenance guard / rebuild helper の契約を host 上の一時 fixture で検証する。

pytest 非依存。直接実行する:
    python3 tools/public_release/test_osrm_provenance_guard.py

検証対象:
  1. scripts/osrm_provenance.sh — provenance guard の fail-closed 契約
     （version / image / digest / profile / input name / input hash mismatch、
       required field 個別欠落、malformed JSON、missing provenance）
  2. scripts/rebuild_osrm_artifacts.sh — rebuild helper の静的契約
     （osrm-provenance write の 5 引数、retain 前 verify、verify FAIL 時に retain
       しない、walking/driving 両対称）
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "osrm_provenance.sh"
REBUILD = ROOT / "scripts" / "rebuild_osrm_artifacts.sh"
REQUIRED_SUFFIXES = ("", ".partition", ".mldgr", ".cells", ".fileIndex", ".ramIndex")
REQUIRED_FIELDS = (
    "schema_version",
    "osrm_version",
    "image",
    "image_digest",
    "profile",
    "input_pbf",
    "input_pbf_sha256",
)


def run(action: str, prefix: Path, profile: str = "foot", input_pbf: str = "input.osm.pbf") -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as bin_dir:
        binary = Path(bin_dir) / "osrm-routed"
        binary.write_text("#!/bin/sh\necho 'v5.25.0'\n", encoding="utf-8")
        binary.chmod(0o755)
        env = os.environ | {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "OSRM_IMAGE_REF": "osrm/osrm-backend:v5.25.0@sha256:bdfa60e64ae1376bff6ff5605991be50600132a27469a4a9e77c23afd3a6d555",
        }
        return subprocess.run(
            ["sh", str(SCRIPT), action, str(prefix), profile, input_pbf, str(prefix.with_suffix(".osm.pbf"))],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )


# ---------------------------------------------------------------------------
# 1. provenance guard の fail-closed 契約
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as temp_dir:
    prefix = Path(temp_dir) / "tokyo.osrm"
    pbf = prefix.with_suffix(".osm.pbf")
    for suffix in REQUIRED_SUFFIXES:
        Path(f"{prefix}{suffix}").write_text("artifact\n", encoding="utf-8")
    pbf.write_text("pbf\n", encoding="utf-8")
    metadata = Path(f"{prefix}.provenance.json")

    def rewrite(**changes: object) -> None:
        """正しい provenance を書き直したうえで changes を適用する。"""
        assert run("write", prefix).returncode == 0
        doc = json.loads(metadata.read_text(encoding="utf-8"))
        for key, value in changes.items():
            if value is None:
                doc.pop(key, None)
            else:
                doc[key] = value
        metadata.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    # --- 既存 coverage（保持）---
    assert run("write", prefix).returncode == 0
    assert run("verify", prefix).returncode == 0, "matching version must be reusable"

    rewrite(osrm_version="5.26.0")
    assert run("verify", prefix).returncode != 0, "mismatched version must be rejected"

    rewrite(image_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    assert run("verify", prefix).returncode != 0, "digest mismatch must be rejected"

    assert run("write", prefix).returncode == 0
    assert run("verify", prefix, profile="car").returncode != 0, "profile mismatch must be rejected"

    assert run("write", prefix).returncode == 0
    metadata.unlink()
    assert run("verify", prefix).returncode != 0, "missing provenance must be rejected"

    metadata.write_text("{not json}\n", encoding="utf-8")
    assert run("verify", prefix).returncode != 0, "malformed provenance must be rejected"

    metadata.write_text('{"schema_version": 1}\n', encoding="utf-8")
    assert run("verify", prefix).returncode != 0, "sparse provenance must be rejected"

    # --- 追加 negative coverage ---
    rewrite(image="osrm/osrm-backend:v9.99.9")
    assert run("verify", prefix).returncode != 0, "image mismatch must be rejected"

    assert run("write", prefix).returncode == 0
    assert run("verify", prefix, input_pbf="other-region.osm.pbf").returncode != 0, \
        "input PBF name mismatch must be rejected"

    assert run("write", prefix).returncode == 0
    pbf.write_text("pbf-tampered\n", encoding="utf-8")  # write 後に入力を差し替える
    assert run("verify", prefix).returncode != 0, "input PBF content/hash mismatch must be rejected"
    pbf.write_text("pbf\n", encoding="utf-8")

    # 7 fields を 1 つずつ欠落させて fail-closed を確認
    for field in REQUIRED_FIELDS:
        rewrite(**{field: None})
        rc = run("verify", prefix).returncode
        assert rc != 0, f"missing required field must be rejected: {field}"

    # --- CODEX MEDIUM finding の再現: 7 field 名 + 期待値相当文字列を
    #     すべて含むが JSON 構文として不正な非 JSON。sed/grep 抽出では
    #     exit 0 になっていた。構文検証で fail-closed であること。 ---
    assert run("write", prefix).returncode == 0
    good = json.loads(metadata.read_text(encoding="utf-8"))
    all_field_blob = " ".join(f"{k} {v}" for k, v in good.items())
    for text in (
        all_field_blob,                       # 全 field 文字列を含む非 JSON
        all_field_blob.join(("<<", ">>")),     # 前後にノイズ
        json.dumps(good)[:-1],                 # 途中で切れた JSON
        json.dumps(good) + "}",                # 余分な閉じ括弧
        json.dumps(good).replace(",", ";"),    # 区切りが不正
    ):
        metadata.write_text(text + "\n", encoding="utf-8")
        assert run("verify", prefix).returncode != 0, \
            f"syntactically invalid metadata must be rejected: {text[:40]!r}"

    # --- top-level が object でない valid JSON は reject ---
    for doc in ("[]", '["schema_version", 1]', '"a string"', "null", "12345", "true"):
        metadata.write_text(doc + "\n", encoding="utf-8")
        assert run("verify", prefix).returncode != 0, \
            f"non-object top-level JSON must be rejected: {doc}"

    # --- 型不一致（valid JSON だが field の型が契約外）---
    rewrite(schema_version="1")
    assert run("verify", prefix).returncode != 0, "schema_version as string must be rejected"

    rewrite(schema_version=2)
    assert run("verify", prefix).returncode != 0, "schema_version != 1 must be rejected"

    rewrite(osrm_version=5.25)
    assert run("verify", prefix).returncode != 0, "osrm_version as number must be rejected"

    rewrite(image=["osrm/osrm-backend:v5.25.0"])
    assert run("verify", prefix).returncode != 0, "image as array must be rejected"

    rewrite(profile="")
    assert run("verify", prefix).returncode != 0, "empty profile string must be rejected"

    # --- nominal は引き続き PASS（既存 contract 維持）---
    assert run("write", prefix).returncode == 0
    assert run("verify", prefix).returncode == 0, "well-formed 7-field provenance must still verify"

print("PASS: OSRM provenance guard "
      "matching/version/image/digest/profile/input-name/input-hash/"
      "per-field-missing/malformed-all-fields/non-object/type-mismatch/nominal")


# ---------------------------------------------------------------------------
# 2. rebuild helper の静的契約
# ---------------------------------------------------------------------------
helper = REBUILD.read_text(encoding="utf-8")

# 2-1. osrm-provenance write は 5 引数（action + prefix + profile + input-name + input-path）
write_lines = [ln.strip() for ln in helper.splitlines() if "osrm-provenance write" in ln]
assert write_lines, "osrm-provenance write call not found"
for ln in write_lines:
    assert ".osm.pbf'" in ln, f"osrm-provenance write missing input PBF path arg: {ln}"
    assert "${container_prefix}.osm.pbf" in ln, f"input PBF path must be the container path: {ln}"

# 2-2. retain の前に osrm-provenance verify を実行し、その成功時のみ return する
assert "osrm-provenance verify" in helper, "retain path must run osrm-provenance verify"
retain_block = re.search(
    r"if\s*\(\(\s*required\s*==\s*1\s*\)\);\s*then(.*?)\n\s*fi\n\s*fi",
    helper,
    re.DOTALL,
)
assert retain_block, "retain block (required == 1) not found"
block = retain_block.group(1)
assert "osrm-provenance verify" in block, "verify must run inside the retain decision"
assert re.search(r"if\s+docker compose[^\n]*osrm-provenance verify", block, re.DOTALL) or \
    re.search(r"if\s+docker compose.*?\n[^\n]*osrm-provenance verify", block, re.DOTALL), \
    "verify result must gate retain (if docker compose ... verify; then ... return)"
# verify を通った時だけ return する（無条件 return が残っていない）
assert re.search(r"osrm-provenance verify.*?then\s*\n\s*echo[^\n]*\n\s*return", block, re.DOTALL), \
    "return must be reached only on verify success"
# verify FAIL 時は return せず rebuild 経路へ（fail-closed のログがある）
assert re.search(r"failed verification", block), "verify failure must log and fall through to rebuild"

# 2-3. walking / driving 両方が同じ rebuild 関数を通る
assert re.search(r"^rebuild osrm-walking\b", helper, re.MULTILINE), "walking rebuild invocation missing"
assert re.search(r"^rebuild osrm-driving\b", helper, re.MULTILINE), "driving rebuild invocation missing"

print("PASS: OSRM rebuild helper static contract "
      "write-5-args/retain-verify/verify-fail-no-retain/walking+driving")
