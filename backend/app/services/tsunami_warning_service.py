"""
tsunami_warning_service.py — 津波警報・注意報情報サービス

一次ソース: 気象庁防災情報XML (VTSE41)
fallback: P2P地震情報API /v2/jma/tsunami

環境変数:
  TSUNAMI_WARNING_SOURCE_PRIORITY=jma_xml,p2p
  TSUNAMI_WARNING_TTL_SECONDS=60
  TSUNAMI_WARNING_ENABLE_FALLBACK=true
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

_JMA_EQVOL_FEED_URL = "https://www.data.jma.go.jp/developer/xml/feed/eqvol.xml"
_JMA_EQVOL_LONG_FEED_URL = "https://www.data.jma.go.jp/developer/xml/feed/eqvol_l.xml"
_P2P_TSUNAMI_URL = "https://api.p2pquake.net/v2/jma/tsunami?limit=1"
_JST = timezone(timedelta(hours=9))


def _load_properties() -> Dict[str, str]:
    path = Path(os.getenv("APP_PROPERTIES_FILE", Path(__file__).resolve().parents[2] / "app.properties"))
    props: Dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            props[key.strip()] = value.strip()
    except OSError:
        pass
    return props


_PROPERTIES = _load_properties()


def _config_value(env_name: str, property_name: str, default: str) -> str:
    return os.getenv(env_name) or _PROPERTIES.get(property_name) or default


def _env_csv(name: str, default: str) -> List[str]:
    prop_name = {
        "TSUNAMI_WARNING_SOURCE_PRIORITY": "tsunami.warning.source_priority",
    }.get(name, name.lower().replace("_", "."))
    value = _config_value(name, prop_name, default)
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def _env_bool(name: str, default: bool) -> bool:
    prop_name = {
        "TSUNAMI_WARNING_ENABLE_FALLBACK": "tsunami.warning.enable_fallback",
    }.get(name, name.lower().replace("_", "."))
    value = _config_value(name, prop_name, "true" if default else "false")
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_float(name: str, default: float) -> float:
    prop_name = {
        "TSUNAMI_WARNING_TTL_SECONDS": "tsunami.warning.ttl_seconds",
    }.get(name, name.lower().replace("_", "."))
    try:
        return float(_config_value(name, prop_name, str(default)))
    except (TypeError, ValueError):
        return default


_CACHE_TTL = _env_float("TSUNAMI_WARNING_TTL_SECONDS", 60.0)
_SOURCE_PRIORITY = _env_csv("TSUNAMI_WARNING_SOURCE_PRIORITY", "jma_xml,p2p")
_ENABLE_FALLBACK = _env_bool("TSUNAMI_WARNING_ENABLE_FALLBACK", True)

_GRADE_TO_LEVEL: Dict[str, str] = {
    "MajorWarning": "major_warning",
    "Warning": "warning",
    "Watch": "advisory",
    "Unknown": "forecast",
}

_JMA_KIND_TO_LEVEL: Dict[str, str] = {
    "大津波警報": "major_warning",
    "津波警報": "warning",
    "津波注意報": "advisory",
    "津波予報": "forecast",
}

_LEVEL_LABEL: Dict[str, str] = {
    "major_warning": "大津波警報",
    "warning": "津波警報",
    "advisory": "津波注意報",
    "forecast": "津波予報",
}

_LEVEL_PRIORITY: Dict[str, int] = {
    "major_warning": 4,
    "warning": 3,
    "advisory": 2,
    "forecast": 1,
}

_cache: Optional[Dict[str, Any]] = None
_cache_at: float = 0.0


def _monotonic() -> float:
    return time.monotonic()


def _now_jst_iso() -> str:
    return datetime.now(_JST).isoformat()


def _http_get_bytes(url: str, timeout: float = 10.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "OnHighGround2/1.0 (disaster evacuation navigation)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _http_get_json(url: str) -> Any:
    return json.loads(_http_get_bytes(url).decode("utf-8"))


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _children_by_local(elem: ET.Element, name: str) -> List[ET.Element]:
    return [child for child in list(elem) if _local_name(child.tag) == name]


def _first_child(elem: ET.Element, name: str) -> Optional[ET.Element]:
    for child in list(elem):
        if _local_name(child.tag) == name:
            return child
    return None


def _first_text(elem: Optional[ET.Element], path: Iterable[str]) -> Optional[str]:
    current = elem
    for name in path:
        if current is None:
            return None
        current = _first_child(current, name)
    if current is None or current.text is None:
        return None
    text = current.text.strip()
    return text or None


def _all_text(elem: Optional[ET.Element]) -> str:
    if elem is None:
        return ""
    return "".join(part.strip() for part in elem.itertext() if part and part.strip())


def _find_first_desc(elem: ET.Element, name: str) -> Optional[ET.Element]:
    for node in elem.iter():
        if _local_name(node.tag) == name:
            return node
    return None


def _find_child_desc(elem: ET.Element, path: Iterable[str]) -> Optional[ET.Element]:
    current = elem
    for name in path:
        found = None
        for node in current.iter():
            if node is current:
                continue
            if _local_name(node.tag) == name:
                found = node
                break
        current = found
        if current is None:
            return None
    return current


def _parse_iso_to_jst(time_str: Optional[str]) -> Optional[str]:
    if not time_str:
        return None
    try:
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        return dt.astimezone(_JST).isoformat()
    except ValueError:
        return time_str


def _parse_p2p_time(time_str: Optional[str]) -> Optional[str]:
    """P2P 時刻文字列 "YYYY/MM/DD HH:MM:SS" → JST ISO8601"""
    if not time_str:
        return None
    try:
        dt = datetime.strptime(time_str.strip()[:19], "%Y/%m/%d %H:%M:%S")
        return dt.replace(tzinfo=_JST).isoformat()
    except ValueError:
        return None


def _build_message(max_level: Optional[str]) -> str:
    if max_level == "major_warning":
        return "大津波警報が発表されています。直ちに高台へ避難してください。"
    if max_level == "warning":
        return "津波警報が発表されています。海岸・河口付近から離れてください。"
    if max_level == "advisory":
        return "津波注意報が発表されています。海岸・河口付近から離れてください。"
    if max_level == "forecast":
        return "津波予報が発表されています。"
    return ""


def _make_none_response(source: str) -> Dict[str, Any]:
    return {
        "source": source,
        "status": "none",
        "observed_at": None,
        "updated_at": _now_jst_iso(),
        "ttl_seconds": int(_CACHE_TTL),
        "areas": [],
        "message": "",
    }


def _make_error_response(reason: str) -> Dict[str, Any]:
    return {
        "source": "error",
        "status": "error",
        "observed_at": None,
        "updated_at": _now_jst_iso(),
        "ttl_seconds": int(_CACHE_TTL),
        "areas": [],
        "message": "",
        "error": reason,
    }


class JmaXmlTsunamiWarningClient:
    """気象庁PULL型Atomフィードから VTSE41 を取得して正規化する。"""

    source = "jma_xml"

    def __init__(self, feed_urls: Optional[List[str]] = None) -> None:
        self.feed_urls = feed_urls or [_JMA_EQVOL_FEED_URL, _JMA_EQVOL_LONG_FEED_URL]

    def fetch(self) -> Dict[str, Any]:
        hrefs = self._find_vtse41_hrefs()
        if not hrefs:
            return _make_none_response(self.source)

        last_error: Optional[Exception] = None
        for href in hrefs:
            try:
                return self._parse_report(_http_get_bytes(href), href)
            except Exception as exc:
                last_error = exc
                logger.warning("JMA XML VTSE41 parse failed (%s): %s", href, exc)

        if last_error:
            raise last_error
        return _make_none_response(self.source)

    def _find_vtse41_hrefs(self) -> List[str]:
        hrefs: List[str] = []
        for feed_url in self.feed_urls:
            feed = ET.fromstring(_http_get_bytes(feed_url))
            for entry in [n for n in feed.iter() if _local_name(n.tag) == "entry"]:
                title = _first_text(entry, ["title"]) or ""
                content = _first_text(entry, ["content"]) or ""
                if "VTSE41" not in title and "津波警報・注意報・予報" not in title and "津波警報・注意報・予報" not in content:
                    continue
                for link in [n for n in entry.iter() if _local_name(n.tag) == "link"]:
                    href = link.attrib.get("href")
                    if href:
                        hrefs.append(href)
                        break
            if hrefs:
                break
        return hrefs[:5]

    def _parse_report(self, xml_bytes: bytes, href: str) -> Dict[str, Any]:
        root = ET.fromstring(xml_bytes)
        title = _first_text(_find_first_desc(root, "Control"), ["Title"]) or ""
        head_title = _first_text(_find_first_desc(root, "Head"), ["Title"]) or ""
        info_type = _first_text(_find_first_desc(root, "Head"), ["InfoType"]) or ""

        if "津波警報・注意報・予報" not in title and "津波警報・注意報・予報" not in head_title:
            raise ValueError(f"not VTSE41 tsunami warning report: {href}")
        if "取消" in info_type:
            return _make_none_response(self.source)

        observed_at = _parse_iso_to_jst(_first_text(_find_first_desc(root, "Head"), ["ReportDateTime"]))
        areas: List[Dict[str, Any]] = []
        max_level: Optional[str] = None

        for item in [n for n in root.iter() if _local_name(n.tag) == "Item"]:
            area = _first_child(item, "Area")
            kind = _find_child_desc(item, ["Kind"])
            kind_name = _first_text(kind, ["Name"])
            if area is None or not kind_name:
                continue
            if "解除" in kind_name:
                continue

            level = _JMA_KIND_TO_LEVEL.get(kind_name)
            if level is None:
                if "大津波警報" in kind_name:
                    level = "major_warning"
                elif "津波警報" in kind_name:
                    level = "warning"
                elif "津波注意報" in kind_name:
                    level = "advisory"
                elif "津波予報" in kind_name:
                    level = "forecast"
                else:
                    continue

            if _LEVEL_PRIORITY.get(level, 0) > _LEVEL_PRIORITY.get(max_level or "", 0):
                max_level = level

            first_height = _first_child(item, "FirstHeight")
            max_height = _first_child(item, "MaxHeight")
            areas.append({
                "code": _first_text(area, ["Code"]),
                "name": _first_text(area, ["Name"]) or "",
                "level": level,
                "level_label": _LEVEL_LABEL.get(level, kind_name),
                "expected_height": _all_text(max_height) or None,
                "arrival_time": _all_text(first_height) or None,
                "is_target": False,
            })

        if not areas or max_level is None:
            return _make_none_response(self.source)

        return {
            "source": self.source,
            "status": "active",
            "observed_at": observed_at,
            "updated_at": _now_jst_iso(),
            "ttl_seconds": int(_CACHE_TTL),
            "areas": areas,
            "message": _build_message(max_level),
        }


class P2PTsunamiWarningClient:
    """P2P地震情報APIを fallback として正規化する。"""

    source = "p2p_fallback"

    def fetch(self) -> Dict[str, Any]:
        data = _http_get_json(_P2P_TSUNAMI_URL)

        if not isinstance(data, list) or len(data) == 0:
            return _make_none_response(self.source)

        item = data[0]

        if item.get("cancelled", False):
            return _make_none_response(self.source)

        issue = item.get("issue", {})
        observed_at = _parse_p2p_time(issue.get("time"))

        areas: List[Dict[str, Any]] = []
        max_level: Optional[str] = None

        for area in item.get("areas", []):
            grade = area.get("grade", "Unknown")
            level = _GRADE_TO_LEVEL.get(grade, "forecast")

            if _LEVEL_PRIORITY.get(level, 0) > _LEVEL_PRIORITY.get(max_level or "", 0):
                max_level = level

            areas.append({
                "code": None,
                "name": area.get("name", ""),
                "level": level,
                "level_label": _LEVEL_LABEL.get(level, level),
                "expected_height": None,
                "arrival_time": None,
                "is_target": False,
            })

        if not areas or max_level is None:
            return _make_none_response(self.source)

        return {
            "source": self.source,
            "status": "active",
            "observed_at": observed_at,
            "updated_at": _now_jst_iso(),
            "ttl_seconds": int(_CACHE_TTL),
            "areas": areas,
            "message": _build_message(max_level),
        }


def _clients_for_priority() -> List[Any]:
    clients: List[Any] = []
    for source in _SOURCE_PRIORITY:
        if source == "jma_xml":
            clients.append(JmaXmlTsunamiWarningClient())
        elif source in {"p2p", "p2p_fallback"}:
            clients.append(P2PTsunamiWarningClient())
        else:
            logger.warning("unknown tsunami warning source ignored: %s", source)
    return clients or [JmaXmlTsunamiWarningClient(), P2PTsunamiWarningClient()]


async def get_tsunami_warnings(
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> Dict[str, Any]:
    """
    最新の津波警報情報を返す。
    - 既定は気象庁防災情報XML VTSE41 → P2P fallback
    - TTL キャッシュ
    - 取得失敗時は status="error" を返す（既存機能を止めない）
    """
    global _cache, _cache_at

    now = _monotonic()
    if _cache is not None and (now - _cache_at) < _CACHE_TTL:
        return dict(_cache)

    errors: List[str] = []
    clients = _clients_for_priority()
    if not _ENABLE_FALLBACK:
        clients = clients[:1]

    for client in clients:
        try:
            result = client.fetch()
            _cache = result
            _cache_at = now
            return dict(result)
        except Exception as exc:
            logger.warning("津波警報情報の取得に失敗しました (%s): %s", client.source, exc)
            errors.append(f"{client.source}: {exc}")

    return _make_error_response("; ".join(errors) or "no tsunami warning source configured")
