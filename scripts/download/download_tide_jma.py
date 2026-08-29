"""
download_tide_jma.py — 気象庁潮位表テキストデータ 全国一括ダウンロード

気象庁公式サイトから全観測地点の潮位表テキスト (h{code}.txt) を取得し、
指定された raw ディレクトリへ保存する。

使用方法:
    python3 scripts/download/download_tide_jma.py --raw-dir data_lake/raw/japan/tide/jma/2026 --year 2026

URL パターン:
    https://www.data.jma.go.jp/gmd/kaiyou/data/db/tide/suisan/txt/{year}/h{code}.txt

注意:
    HTMLスクレイピングは行わない。station_master.json に定義された地点コードのみを使用する。
"""
import argparse
import json
import logging
import sys
import time
import urllib.error
import urllib.request
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

_JMA_URL_PATTERN = (
    "https://www.data.jma.go.jp/kaiyou/data/db/tide/suisan/txt/{year}/{code}.txt"
)
_REQUEST_INTERVAL_SECONDS = 0.5
_TIMEOUT_SECONDS = 30
_USER_AGENT = "OnHighGround2/1.0 (disaster-escape-navigation)"


def _load_stations() -> list:
    station_master = _STATION_MASTER if _STATION_MASTER.exists() else _LEGACY_STATION_MASTER
    if not station_master.exists():
        logger.error("station_master not found: %s", _STATION_MASTER)
        sys.exit(1)
    with station_master.open(encoding="utf-8") as f:
        return json.load(f)


def _fetch(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            if resp.status != 200:
                return None
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        logger.warning("HTTP %s for %s", e.code, url)
        return None
    except Exception as e:
        logger.warning("fetch error %s: %s", url, e)
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="JMA tide table batch downloader")
    parser.add_argument("--raw-dir", required=True, help="raw 保存先ディレクトリ")
    parser.add_argument("--year", default="2026", help="対象年度 (例: 2026)")
    args = parser.parse_args()

    year = args.year
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    stations = _load_stations()
    logger.info("tide dataset download start year=%s stations=%d", year, len(stations))

    success = 0
    skipped = 0
    failed = 0

    for station in stations:
        code = station["station_code"]
        name = station.get("station_name") or station.get("name", code)
        url = _JMA_URL_PATTERN.format(year=year, code=code)
        dest = raw_dir / f"h{code}.txt"

        if dest.exists() and dest.stat().st_size > 0:
            logger.info("skip (exists) station=%s name=%s", code, name)
            skipped += 1
            continue

        data = _fetch(url)
        time.sleep(_REQUEST_INTERVAL_SECONDS)

        if data is None:
            logger.warning("missing station=%s name=%s url=%s", code, name, url)
            failed += 1
            continue

        dest.write_bytes(data)
        logger.info("saved station=%s name=%s bytes=%d", code, name, len(data))
        success += 1

    logger.info(
        "download complete year=%s success=%d skipped=%d failed=%d total=%d",
        year, success, skipped, failed, len(stations),
    )

    if success + skipped == 0:
        logger.error("no files downloaded")
        sys.exit(1)


if __name__ == "__main__":
    main()
