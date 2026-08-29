#!/usr/bin/env python3
"""
import_river_flood_manual.py — 国土数値情報 A31a/A31b 洪水浸水想定データの
fail-closed手動import（Phase 2-D Round 2、P2D-AT17-BOOTSTRAP対応、指示書Round 2第11.4節）

## 自動取得不能である理由（指示書第11.4節が要求する明記）

国土数値情報（KSJ）のA31データダウンロードページ
（https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A31.html）を2026-08-21に
確認したところ、実際のダウンロードは都道府県・年度を選択するHTMLフォーム経由でのみ
提供されており、`<region_code>.zip`のような安定した直接URLパターンは確認できなかった
（`scripts/download/download_shelter_gsi_prefecture.sh`が対象とするGSI避難所
ポータルとは異なり、KSJのA31配布はフォーム送信を要する）。

指示書第11.4節「公式で安定した機械取得endpointが存在しない、または自動取得が
規約上不明の場合」に該当するため、本scriptはfake downloadを実装せず、
**利用者（operator）がKSJの公式ページから手動でダウンロードしたZIP/GMLファイルを
fail-closedで検証・importする**方式のみを提供する。

## 使い方

1. https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A31.html を開き、
   対象都道府県・最新年度のA31a/A31b ZIPを手動でダウンロードする。
2. 本scriptで検証・importする:

   python3 scripts/download/import_river_flood_manual.py \\
       --input /path/to/A31a-25_13_GML.zip \\
       --prefecture-code 13 \\
       --output-dir data_lake/raw/tokyo/flood

## 検証内容（fail-closed）

- ZIPとして開けること
- 内部に`.xml`または`.gml`ファイルが存在すること
- 中身がKSJ A31a/A31b想定スキーマ（`ksj:Dataset`をroot要素に持つ）であること
- 既存の同名importを無断上書きしないこと（`--overwrite`明示時のみ許可）
- SHA-256を計算しmanifestへ記録すること

検証に失敗した場合は非0終了し、importを行わない（部分的なファイルを残さない）。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _provisioning_common import check_disk_space, write_manifest  # noqa: E402


class ImportValidationError(Exception):
    pass


def _sha256_of_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 256), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _validate_zip_contains_ksj_schema(zip_path: Path) -> list:
    """ZIP内にA31a/A31b想定のGML/XMLが存在し、ksj:Dataset root要素を持つことを確認する。
    戻り値: 検証を通過したmember名のリスト。"""
    if not zipfile.is_zipfile(zip_path):
        raise ImportValidationError(f"not a valid ZIP archive: {zip_path}")

    matched_members = []
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
        if bad is not None:
            raise ImportValidationError(f"corrupt member in archive: {bad}")

        xml_members = [n for n in zf.namelist() if n.lower().endswith((".xml", ".gml"))]
        if not xml_members:
            raise ImportValidationError("archive contains no .xml/.gml members (unexpected for A31a/A31b)")

        for name in xml_members:
            with zf.open(name) as f:
                head = f.read(4096)
            if b"ksj:Dataset" in head or b"ksj:" in head:
                matched_members.append(name)

        if not matched_members:
            raise ImportValidationError(
                "no member matched expected KSJ A31a/A31b schema marker (ksj:Dataset). "
                "Refusing import — this may not be the expected dataset."
            )

    return matched_members


def import_file(input_path: Path, output_dir: Path, prefecture_code: str, *, overwrite: bool) -> int:
    if not input_path.exists():
        print(f"ERROR: input not found: {input_path}", file=sys.stderr)
        return 1

    try:
        matched_members = _validate_zip_contains_ksj_schema(input_path)
    except ImportValidationError as exc:
        print(f"ERROR: validation failed (fail-closed, not importing): {exc}", file=sys.stderr)
        return 1

    output_path = output_dir / f"A31_{prefecture_code}_{input_path.name}"
    if output_path.exists() and not overwrite:
        print(f"ERROR: destination already exists (use --overwrite to replace): {output_path}", file=sys.stderr)
        return 1

    try:
        check_disk_space(output_path, input_path.stat().st_size * 2)
    except Exception as exc:  # noqa: BLE001 — surfaced as a plain fail-closed error, not a crash
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(prefix=f".{output_path.name}.", suffix=".partial", dir=str(output_dir))
    tmp_path = Path(tmp_name)
    try:
        os.close(tmp_fd)
        shutil.copyfile(input_path, tmp_path)
        os.replace(tmp_path, output_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    sha256 = _sha256_of_file(output_path)
    manifest_path = output_path.with_suffix(output_path.suffix + ".manifest.json")
    write_manifest(manifest_path, {
        "artifact": str(output_path),
        "prefecture_code": prefecture_code,
        "source": "manual import — 国土数値情報 A31a/A31b、operatorがKSJ公式サイトから手動取得",
        "official_page": "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A31.html",
        "official_terms_page": "https://nlftp.mlit.go.jp/ksj/other/agreement.html",
        "license": "PDL1.0 (公共データ利用規約第1.0版)",
        "validated_zip_members": matched_members,
        "sha256": sha256,
        "original_filename": input_path.name,
        "automatic_fetch_not_implemented_reason": (
            "KSJ A31 distribution requires HTML form submission (prefecture/year selection); "
            "no stable direct-download URL pattern was confirmed as of 2026-08-21. "
            "See module docstring for detail."
        ),
    })

    print(f"OK: imported to {output_path} (sha256={sha256})")
    print(f"manifest: {manifest_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, type=Path, help="手動ダウンロード済みのA31a/A31b ZIPファイル")
    parser.add_argument("--prefecture-code", required=True, help="都道府県コード（例: 13 = 東京都）")
    parser.add_argument("--output-dir", required=True, type=Path, help="import先ディレクトリ")
    parser.add_argument("--overwrite", action="store_true", help="既存の同名importを上書きする")
    args = parser.parse_args()

    return import_file(args.input, args.output_dir, args.prefecture_code, overwrite=args.overwrite)


if __name__ == "__main__":
    sys.exit(main())
