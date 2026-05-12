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
from collections import defaultdict
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── インライン潮汐パーサー（tide_parser.py から移植、外部依存なし） ─────────

TIDE_FORMAT = {
    "line_start": 0,
    "value_width": 3,
    "hourly_count": 24,
    "date_start": 72,
    "station_start": 78,
}

_MISSING_VALUE = 999
_JST = timezone(timedelta(hours=9))


class TideFormatError(ValueError):
    pass


def _parse_century(yy: int) -> int:
    return 2000 + yy if yy < 50 else 1900 + yy


def _parse_line(line: str, *, strict: bool = False) -> tuple[Optional[date], list[Optional[int]]]:
    required_len = TIDE_FORMAT["station_start"] + 2
    if len(line) < required_len:
        if strict:
            raise TideFormatError(f"fixed length short: expected>={required_len} actual={len(line)}")
        return None, []

    date_field = line[TIDE_FORMAT["date_start"]:TIDE_FORMAT["station_start"]]
    try:
        yy = int(date_field[0:2])
        mm = int(date_field[2:4])
        dd = int(date_field[4:6])
    except ValueError:
        if strict and line[:72].strip():
            raise TideFormatError(f"invalid date field: {date_field!r}")
        return None, []
    try:
        year = _parse_century(yy)
        day = date(year, mm, dd)
    except ValueError:
        if strict:
            raise TideFormatError(f"invalid date: {date_field!r}")
        return None, []

    start = TIDE_FORMAT["line_start"]
    width = TIDE_FORMAT["value_width"]
    count = TIDE_FORMAT["hourly_count"]
    values: list[Optional[int]] = []
    for i in range(count):
        chunk = line[start + i * width : start + (i + 1) * width]
        if len(chunk) < width:
            if strict:
                raise TideFormatError(f"short hourly field hour={i}")
            return day, []
        try:
            val = int(chunk)
            values.append(None if val == _MISSING_VALUE else val)
        except ValueError:
            if strict:
                raise TideFormatError(f"invalid hourly field hour={i} value={chunk!r}")
            values.append(None)

    return day, values


def iter_hourly(station_code: str, text: str, *, log_errors: bool = False) -> list[dict]:
    records = []
    for lineno, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.rstrip()
        if not line:
            continue
        try:
            day, values = _parse_line(line, strict=log_errors)
        except TideFormatError as exc:
            logger.error("invalid tide format station=%s line=%d: %s", station_code, lineno, exc)
            continue
        if day is None:
            continue
        if len(values) != TIDE_FORMAT["hourly_count"]:
            if log_errors:
                logger.error(
                    "invalid tide format station=%s line=%d: hourly_count=%d",
                    station_code, lineno, len(values),
                )
            continue
        for hour, cm in enumerate(values):
            dt = datetime(day.year, day.month, day.day, hour, 0, 0, tzinfo=_JST)
            records.append({
                "station": station_code,
                "datetime": dt.isoformat(),
                "tide_cm": cm,
            })
    return records


def find_extremes(station_code: str, hourly: list[dict]) -> list[dict]:
    by_date: dict[str, list[dict]] = defaultdict(list)
    for rec in hourly:
        by_date[rec["datetime"][:10]].append(rec)

    result = []
    for day_str in sorted(by_date):
        day_recs = by_date[day_str]
        valid = [(i, r) for i, r in enumerate(day_recs) if r["tide_cm"] is not None]

        highs: list[dict] = []
        lows: list[dict] = []

        for idx, (i, rec) in enumerate(valid):
            cm = rec["tide_cm"]
            prev_cm = valid[idx - 1][1]["tide_cm"] if idx > 0 else None
            next_cm = valid[idx + 1][1]["tide_cm"] if idx < len(valid) - 1 else None

            if prev_cm is not None and next_cm is not None:
                if cm >= prev_cm and cm >= next_cm:
                    highs.append({"time": rec["datetime"], "tide_cm": cm})
                elif cm <= prev_cm and cm <= next_cm:
                    lows.append({"time": rec["datetime"], "tide_cm": cm})

        result.append({
            "station": station_code,
            "date": day_str,
            "high_tides": highs,
            "low_tides": lows,
        })

    return result


# ── ロギング設定 ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ── ステーションマスター ─────────────────────────────────────────────────────

def _find_station_master() -> Optional[Path]:
    """スクリプト位置を基点に station_master.json を探す。

    ローカル: scripts/normalize/ → 2階層上 = プロジェクトルート
    VPS (Docker): /scripts/normalize/ → 2階層上 = / → /data_lake/registry/
    """
    script_dir = Path(__file__).resolve().parent
    candidates_roots = [
        script_dir.parents[1],  # プロジェクトルート or / (VPS)
        script_dir.parents[0],  # scripts/normalize
        Path("/app"),           # 一般的な Docker マウント点
    ]
    for root_candidate in candidates_roots:
        for name in ("station_master.json", "tide_station_master.json"):
            candidate = root_candidate / "data_lake" / "registry" / name
            if candidate.exists():
                return candidate
    return None


def _load_station_codes() -> set[str]:
    master = _find_station_master()
    if master is None:
        logger.error("station_master not found")
        sys.exit(1)
    logger.info("station_master: %s", master)
    with master.open(encoding="utf-8") as f:
        stations = json.load(f)
    return {s["station_code"] for s in stations}


def _year_from_dir(raw_dir: Path) -> str:
    for part in reversed(raw_dir.parts):
        if part.isdigit() and len(part) == 4:
            return part
    return "unknown"


# ── メイン ───────────────────────────────────────────────────────────────────

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
