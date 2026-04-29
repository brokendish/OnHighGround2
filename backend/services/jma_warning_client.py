"""
気象庁警報・注意報クライアント。

エンドポイント:
  /bosai/warning/data/warning/{office_code}.json（120s キャッシュ）

アクティブ判定:
  area.warnings[] の各エントリに code フィールドがあり、
  status が "解除" でないものを「発表中」とみなす。
  status "発表警報・注意報はなし" のエントリは code なし → 警報なし。

警報コード:
  01-07: 警報（警報）
  10-25: 注意報（注意報）
"""
import time
import logging
import urllib.request
import json
from typing import Optional

logger = logging.getLogger(__name__)

_JMA_WARNING_URL = "https://www.jma.go.jp/bosai/warning/data/warning/{office_code}.json"
_WARNING_CACHE: dict[str, tuple[dict, float]] = {}  # office_code → (data, fetched_at)
_WARNING_TTL = 120.0  # 2 分

# 警報コード → (名称, レベル)
WARNING_CODE_MAP: dict[str, tuple[str, str]] = {
    "01": ("暴風雪警報",   "警報"),
    "02": ("大雪警報",     "警報"),
    "03": ("暴風警報",     "警報"),
    "04": ("波浪警報",     "警報"),
    "05": ("高潮警報",     "警報"),
    "06": ("大雨警報",     "警報"),
    "07": ("洪水警報",     "警報"),
    "10": ("暴風雪注意報", "注意報"),
    "11": ("風雪注意報",   "注意報"),
    "12": ("大雪注意報",   "注意報"),
    "13": ("強風注意報",   "注意報"),
    "14": ("波浪注意報",   "注意報"),
    "15": ("高潮注意報",   "注意報"),
    "16": ("大雨注意報",   "注意報"),
    "17": ("洪水注意報",   "注意報"),
    "18": ("濃霧注意報",   "注意報"),
    "19": ("雷注意報",     "注意報"),
    "20": ("乾燥注意報",   "注意報"),
    "21": ("なだれ注意報", "注意報"),
    "22": ("低温注意報",   "注意報"),
    "23": ("霜注意報",     "注意報"),
    "24": ("着氷注意報",   "注意報"),
    "25": ("着雪注意報",   "注意報"),
}

# 発表中とみなすステータス値（空文字 or フィールドなしも含む）
_ACTIVE_STATUSES = {"発表中", "継続", ""}


def _http_get(url: str, timeout: int = 10) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "OnHighGround2/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_warning_data(office_code: str) -> Optional[dict]:
    """警報・注意報 JSON を返す（120s キャッシュ）。"""
    now = time.monotonic()
    if office_code in _WARNING_CACHE:
        data, fetched_at = _WARNING_CACHE[office_code]
        if now - fetched_at < _WARNING_TTL:
            logger.debug("jma warning: cache hit office=%s", office_code)
            return data

    url = _JMA_WARNING_URL.format(office_code=office_code)
    try:
        raw = _http_get(url)
        data = json.loads(raw)
        _WARNING_CACHE[office_code] = (data, now)
        logger.info("jma warning: cache miss — fetched office=%s", office_code)
        return data
    except Exception as exc:
        logger.warning("jma warning fetch failed office=%s: %s", office_code, exc)
        cached = _WARNING_CACHE.get(office_code)
        return cached[0] if cached else None


def parse_area_warnings(warning_data: dict, class10_code: str) -> list[dict]:
    """
    警報 JSON から指定 class10 エリアのアクティブ警報リストを返す。

    Returns:
        [{"code": "06", "name": "大雨警報", "level": "警報"}, ...]
        警報なしの場合は空リスト。
    """
    result: list[dict] = []
    for atype in warning_data.get("areaTypes", []):
        for area in atype.get("areas", []):
            if area.get("code") != class10_code:
                continue
            for w in area.get("warnings", []):
                code = w.get("code")
                status = w.get("status", "")
                if not code:
                    continue
                if status == "解除":
                    continue
                # アクティブ: code あり & 解除でない
                name, level = WARNING_CODE_MAP.get(code, (f"警報コード{code}", "不明"))
                result.append({"code": code, "name": name, "level": level})
    return result


def get_highest_level(warnings: list[dict]) -> str:
    """警報リストから最高レベルを返す。"""
    if not warnings:
        return "なし"
    if any(w["level"] == "警報" for w in warnings):
        return "警報"
    if any(w["level"] == "注意報" for w in warnings):
        return "注意報"
    return "なし"
