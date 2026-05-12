"""
normalize_tide_jma.py — 気象庁潮位表テキスト → JSONL 変換

raw ディレクトリ (h{code}.txt) を読み込み、
正規化した JSONL を output-dir へ書き出す。

生成ファイル:
    tide_hourly_{year}.jsonl   — 毎時潮位レコード
    tide_extremes_{year}.jsonl — 日別満潮・干潮レコード

使用方法 (pipeline_service から呼び出す):
    python3 scripts/normalize/normalize_tide_jma.py \
        --input data_lake/raw/japan/tide/jma/2026 \
        --output-dir data_lake/normalized/japan/tide/jma/2026
"""
import argparse
import json
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "backend"))

from app.services.tide_parser import iter_hourly, find_extremes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

_STATION_MASTER = _PROJECT_ROOT / "data_lake" / "registry" / "station_master.json"
_LEGACY_STATION_MASTER = _PROJECT_ROOT / "data_lake" / "registry" / "tide_station_master.json"


def _load_station_codes() -> set[str]:
    station_master = _STATION_MASTER if _STATION_MASTER.exists() else _LEGACY_STATION_MASTER
    if not station_master.exists():
        logger.error("station_master not found: %s", _STATION_MASTER)
        sys.exit(1)
    with station_master.open(encoding="utf-8") as f:
        stations = json.load(f)
    return {s["station_code"] for s in stations}


def _year_from_dir(raw_dir: Path) -> str:
    """ディレクトリパスから年を推定する (例: .../2026 → "2026")。"""
    for part in reversed(raw_dir.parts):
        if part.isdigit() and len(part) == 4:
            return part
    return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize JMA tide table text to JSONL")
    parser.add_argument("--input", required=True, help="raw ディレクトリパス")
    parser.add_argument("--output-dir", required=True, help="JSONL 出力ディレクトリ")
    args = parser.parse_args()

    raw_dir = Path(args.input)
    out_dir = Path(args.output_dir)

    if not raw_dir.exists():
        logger.error("input directory not found: %s", raw_dir)
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)

    year = _year_from_dir(raw_dir)
    valid_codes = _load_station_codes()

    txt_files = sorted(raw_dir.glob("h*.txt"))
    if not txt_files:
        logger.error("no h*.txt files found in %s", raw_dir)
        sys.exit(1)

    logger.info("normalize start: %d files year=%s", len(txt_files), year)

    hourly_path = out_dir / f"tide_hourly_{year}.jsonl"
    extremes_path = out_dir / f"tide_extremes_{year}.jsonl"

    hourly_count = 0
    station_count = 0
    error_count = 0

    with hourly_path.open("w", encoding="utf-8") as fh, \
         extremes_path.open("w", encoding="utf-8") as fe:

        for txt_file in txt_files:
            # ファイル名から地点コードを取得: h{CODE}.txt
            stem = txt_file.stem  # "hTK"
            if not stem.startswith("h"):
                continue
            code = stem[1:]

            if code not in valid_codes:
                logger.warning("unknown station code=%s file=%s — skip", code, txt_file.name)
                continue

            try:
                text = txt_file.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                logger.error("read error station=%s: %s", code, e)
                error_count += 1
                continue

            try:
                hourly = iter_hourly(code, text, log_errors=True)
            except Exception as e:
                logger.error("invalid tide format station=%s: %s", code, e)
                error_count += 1
                continue

            if not hourly:
                logger.warning("no records station=%s", code)
                continue

            for rec in hourly:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            hourly_count += len(hourly)

            try:
                extremes = find_extremes(code, hourly)
            except Exception as e:
                logger.error("extremes error station=%s: %s", code, e)
                error_count += 1
                continue

            for rec in extremes:
                fe.write(json.dumps(rec, ensure_ascii=False) + "\n")

            station_count += 1
            logger.info("station=%s records=%d", code, len(hourly))

    logger.info(
        "normalize completed stations=%d hourly_records=%d errors=%d",
        station_count, hourly_count, error_count,
    )
    logger.info("  hourly  → %s", hourly_path)
    logger.info("  extremes → %s", extremes_path)

    if station_count == 0:
        logger.error("normalize failed: no stations processed")
        sys.exit(1)


if __name__ == "__main__":
    main()
