"""
tide_parser.py — 気象庁潮位表テキスト 固定長フォーマットパーサー

気象庁が公開する潮位表テキスト (h{code}.txt) を解析し、
毎時潮位と極値（満潮・干潮）を抽出する。

フォーマット仕様:
    各行 = 1日分のデータ
    先頭 72 文字 = 24 時間 × 3 文字 (cm 単位の整数、欠損は 999)
    以降 8 文字 = YY MM DD station_code

    TIDE_FORMAT["line_start"]    = 0   毎時潮位の開始位置
    TIDE_FORMAT["value_width"]   = 3   1 時間あたりの文字幅
    TIDE_FORMAT["hourly_count"]  = 24  1 行あたりの時間数

欠損値:
    999 → None（欠損扱い）

出力単位:
    cm（整数）
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

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
    """Raised when a line looks like tide data but violates the fixed-width format."""


def _parse_century(yy: int) -> int:
    return 2000 + yy if yy < 50 else 1900 + yy


def parse_line(line: str, *, strict: bool = False) -> tuple[Optional[date], list[Optional[int]]]:
    """
    1 行を解析して (date, [hour_0..23]) を返す。

    date: 解析できた場合は date オブジェクト、できない場合は None。
    list: 24 要素。欠損値は None。
    """
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


def parse_file(text: str) -> list[dict]:
    """
    テキスト全体を解析して hourly レコードのリストを返す。

    返却スキーマ:
        {"station": str, "datetime": ISO8601+09:00, "tide_cm": int | None}
    """
    raise NotImplementedError(
        "station context が必要なため normalize_tide_jma.py 側で呼び出す"
    )


def iter_hourly(
    station_code: str,
    text: str,
    *,
    log_errors: bool = False,
) -> list[dict]:
    """
    テキストを行ごとに解析し、毎時レコードを生成する。

    Parameters
    ----------
    station_code : JMA 地点コード（例: "TK"）
    text         : h{code}.txt の生テキスト

    Yields
    ------
    dict:
        station   : str
        datetime  : str (ISO8601, JST +09:00)
        tide_cm   : int | None
    """
    records = []
    for lineno, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.rstrip()
        if not line:
            continue
        try:
            day, values = parse_line(line, strict=log_errors)
        except TideFormatError as exc:
            logger.error(
                "invalid tide format station=%s line=%d: %s",
                station_code,
                lineno,
                exc,
            )
            continue
        if day is None:
            continue
        if len(values) != TIDE_FORMAT["hourly_count"]:
            if log_errors:
                logger.error(
                    "invalid tide format station=%s line=%d: hourly_count=%d",
                    station_code,
                    lineno,
                    len(values),
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


def find_extremes(
    station_code: str,
    hourly: list[dict],
) -> list[dict]:
    """
    毎時データから極値（満潮・干潮）を日付別に集計する。

    Parameters
    ----------
    station_code : JMA 地点コード
    hourly       : iter_hourly() の出力

    Returns
    -------
    list of dict:
        station    : str
        date       : "YYYY-MM-DD"
        high_tides : [{"time": ISO8601, "tide_cm": int}, ...]
        low_tides  : [{"time": ISO8601, "tide_cm": int}, ...]
    """
    from collections import defaultdict

    by_date: dict[str, list[dict]] = defaultdict(list)
    for rec in hourly:
        d = rec["datetime"][:10]
        by_date[d].append(rec)

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
