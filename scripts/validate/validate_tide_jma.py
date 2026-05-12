"""
validate_tide_jma.py — 気象庁潮位表 JSONL バリデーション

正規化済み JSONL (tide_hourly_{year}.jsonl) を検証し、
validation_report.json と検証済み JSONL を output-dir へ出力する。

検証項目:
    - 年間日数 (365 / 366 日)
    - 各日 24 時間レコード数
    - 欠損率（20% 超でエラー）
    - station 存在確認（station_master.json との照合）
    - datetime 重複禁止

使用方法 (pipeline_service から呼び出す):
    python3 scripts/validate/validate_tide_jma.py \
        --input-dir data_lake/normalized/japan/tide/jma/2026 \
        --output-dir data_lake/validated/japan/tide/jma/2026
"""
import argparse
import calendar
import json
import logging
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STATION_MASTER = _PROJECT_ROOT / "data_lake" / "registry" / "station_master.json"
_LEGACY_STATION_MASTER = _PROJECT_ROOT / "data_lake" / "registry" / "tide_station_master.json"

_MAX_MISSING_RATE = 0.20
_HOURS_PER_DAY = 24
_JST = timezone(timedelta(hours=9))
_REQUIRED_HOURLY_FIELDS = {"station", "datetime", "tide_cm"}


def _load_valid_codes() -> set[str]:
    station_master = _STATION_MASTER if _STATION_MASTER.exists() else _LEGACY_STATION_MASTER
    if not station_master.exists():
        logger.error("station_master not found: %s", _STATION_MASTER)
        sys.exit(1)
    with station_master.open(encoding="utf-8") as f:
        return {s["station_code"] for s in json.load(f)}


def _year_from_dir(path: Path) -> str:
    for part in reversed(path.parts):
        if part.isdigit() and len(part) == 4:
            return part
    return "unknown"


def _year_from_hourly_file(path: Path) -> str:
    stem = path.stem
    suffix = stem.removeprefix("tide_hourly_")
    return suffix if suffix.isdigit() and len(suffix) == 4 else "unknown"


def validate(input_dir: Path, output_dir: Path) -> bool:
    valid_codes = _load_valid_codes()

    hourly_files = sorted(input_dir.glob(f"tide_hourly_*.jsonl"))
    if not hourly_files:
        logger.error("missing tide_hourly file in %s", input_dir)
        return False

    hourly_file = hourly_files[0]
    year = _year_from_dir(input_dir)
    if year == "unknown":
        year = _year_from_hourly_file(hourly_file)
    errors: list[str] = []
    warnings: list[str] = []

    # ── 読み込み ─────────────────────────────────────────────────────────────
    records: list[dict] = []
    try:
        with hourly_file.open(encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as e:
                    errors.append(f"invalid tide format line={lineno}: {e}")
                    continue
                records.append(rec)
    except Exception as e:
        logger.error("read error: %s", e)
        return False

    if not records:
        errors.append("hourly file is empty")
        _write_report(output_dir, year, False, errors, warnings)
        return False

    # ── schema / station 存在確認 ────────────────────────────────────────────
    for idx, rec in enumerate(records, 1):
        if not isinstance(rec, dict):
            errors.append(f"invalid tide format record={idx}: JSON value must be object")
            continue
        missing_fields = _REQUIRED_HOURLY_FIELDS - set(rec)
        if missing_fields:
            errors.append(f"invalid tide format record={idx}: missing {sorted(missing_fields)}")
            continue
        if not isinstance(rec.get("station"), str) or not rec.get("station"):
            errors.append(f"invalid tide format record={idx}: invalid station")
        try:
            dt = datetime.fromisoformat(rec.get("datetime", ""))
            if dt.tzinfo is None or dt.utcoffset() != _JST.utcoffset(None):
                errors.append(f"invalid tide format record={idx}: datetime must be JST ISO8601")
        except ValueError:
            errors.append(f"invalid tide format record={idx}: invalid datetime")
        tide_cm = rec.get("tide_cm")
        if tide_cm is not None and not isinstance(tide_cm, int):
            errors.append(f"invalid tide format record={idx}: tide_cm must be int or null")

    seen_stations = {r.get("station") for r in records if r.get("station")}
    unknown = seen_stations - valid_codes
    if unknown:
        for code in sorted(unknown):
            errors.append(f"missing tide station: {code}")

    # ── datetime 重複禁止 ────────────────────────────────────────────────────
    seen_dts: set[tuple] = set()
    for rec in records:
        key = (rec.get("station"), rec.get("datetime"))
        if key in seen_dts:
            errors.append(f"duplicate datetime station={key[0]} dt={key[1]}")
        seen_dts.add(key)

    # ── 地点別 集計 ──────────────────────────────────────────────────────────
    from collections import defaultdict
    by_station: dict[str, dict] = defaultdict(lambda: {"dates": set(), "total": 0, "missing": 0})

    for rec in records:
        code = rec.get("station", "")
        dt_str = rec.get("datetime", "")
        day = dt_str[:10] if len(dt_str) >= 10 else ""
        by_station[code]["dates"].add(day)
        by_station[code]["total"] += 1
        if rec.get("tide_cm") is None:
            by_station[code]["missing"] += 1

    try:
        yr = int(year)
        expected_days = 366 if calendar.isleap(yr) else 365
    except ValueError:
        expected_days = 365

    for code, stats in sorted(by_station.items()):
        day_count = len(stats["dates"])
        if day_count < expected_days:
            errors.append(
                f"station={code} days={day_count} expected={expected_days}"
            )

        total = stats["total"]
        missing = stats["missing"]
        if total > 0:
            per_day = total / max(day_count, 1)
            if abs(per_day - _HOURS_PER_DAY) > 2:
                errors.append(
                    f"station={code} avg_hours_per_day={per_day:.1f} expected={_HOURS_PER_DAY}"
                )
            missing_rate = missing / total
            if missing_rate > _MAX_MISSING_RATE:
                errors.append(
                    f"station={code} missing_rate={missing_rate:.1%} exceeds {_MAX_MISSING_RATE:.0%}"
                )

    passed = len(errors) == 0
    _write_report(output_dir, year, passed, errors, warnings)

    if not passed:
        for msg in errors:
            logger.error(msg)
        return False

    for msg in warnings:
        logger.warning(msg)

    # ── 検証済み JSONL を output-dir へコピー ────────────────────────────────
    output_dir.mkdir(parents=True, exist_ok=True)
    for src in input_dir.glob("tide_*.jsonl"):
        dest = output_dir / src.name
        shutil.copy2(src, dest)
        logger.info("copied: %s → %s", src.name, dest)

    manifest = {
        "dataset": "TIDE-JMA-JAPAN",
        "year": year,
        "source": "jma_tide_table",
        "generated_at": datetime.now(_JST).isoformat(),
        "station_count": len(by_station),
        "hourly_records": len(records),
        "missing_records": sum(1 for r in records if r.get("tide_cm") is None),
        "files": sorted(p.name for p in output_dir.glob("tide_*.jsonl")),
    }
    manifest_path = output_dir / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    logger.info("manifest → %s", manifest_path)

    logger.info(
        "validate_tide_jma passed: stations=%d records=%d warnings=%d",
        len(by_station), len(records), len(warnings),
    )
    return True


def _write_report(
    output_dir: Path,
    year: str,
    passed: bool,
    errors: list,
    warnings: list,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "year": year,
        "passed": passed,
        "errors": errors,
        "warnings": warnings,
    }
    report_path = output_dir / "validation_report.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info("validation report → %s (passed=%s)", report_path, passed)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate JMA tide JSONL")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    if not input_dir.exists():
        logger.error("input-dir not found: %s", input_dir)
        sys.exit(1)

    ok = validate(input_dir, output_dir)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
