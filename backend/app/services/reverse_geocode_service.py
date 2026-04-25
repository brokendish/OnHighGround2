"""
reverse_geocode_service.py — 逆ジオコーディングと座標丸めキャッシュ
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.services.admin_log_service import write_app_log
from app.services.config_definition_service import get_config_definition_service
from app.services.config_state_service import get_config_state_service

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CACHE_PATH = _PROJECT_ROOT / "data_runtime" / "cache" / "reverse_geocode_cache.json"
_DEFAULT_TTL_HOURS = 24
_DEFAULT_PRECISION = 4
_DEFAULT_PROVIDER = "nominatim"
_DEFAULT_ENABLED = True
_MIN_PROVIDER_INTERVAL_SEC = 1.0
_NOMINATIM_USER_AGENT = "OnHighGround2/0.1 (https://ohg.brokendish.org/)"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _get_config_value(key: str, default: Any) -> Any:
    try:
        defn = get_config_definition_service().get(key)
        if defn is None:
            return default
        return get_config_state_service().resolve_value(defn)
    except Exception:
        return default


class ReverseGeocodeService:
    def __init__(self, cache_path: Optional[Path] = None) -> None:
        self._cache_path = cache_path or _CACHE_PATH
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last_provider_call_monotonic = 0.0

    def reverse_geocode(self, lat: float, lon: float) -> Dict[str, Any]:
        enabled = bool(_get_config_value("geocode.enabled", _DEFAULT_ENABLED))
        provider = str(_get_config_value("geocode.provider", _DEFAULT_PROVIDER) or _DEFAULT_PROVIDER).lower()
        precision = self._normalize_precision(_get_config_value("geocode.coordinate_precision", _DEFAULT_PRECISION))
        rounded_lat = round(float(lat), precision)
        rounded_lon = round(float(lon), precision)
        key = self._build_cache_key(rounded_lat, rounded_lon, precision)

        if not enabled:
            return self._build_response(None, None, "disabled", rounded_lat, rounded_lon)

        with self._lock:
            cache = self._load_cache()
            entry = cache.get(key)
            if self._is_cache_fresh(entry):
                return self._build_response(
                    entry.get("address"),
                    entry.get("postcode"),
                    "cache",
                    rounded_lat,
                    rounded_lon,
                )

            try:
                result = self._fetch_from_provider(rounded_lat, rounded_lon, provider)
                cache[key] = {
                    "address": result.get("address"),
                    "postcode": result.get("postcode"),
                    "provider": provider,
                    "fetched_at": _utc_now_iso(),
                    "raw": result.get("raw"),
                }
                self._save_cache(cache)
                return self._build_response(
                    result.get("address"),
                    result.get("postcode"),
                    "provider",
                    rounded_lat,
                    rounded_lon,
                )
            except Exception as exc:
                logger.warning("reverse geocode provider failed: %s", exc)
                try:
                    write_app_log(
                        f"reverse geocode failed lat={rounded_lat} lon={rounded_lon} provider={provider} error={exc}",
                        level="WARNING",
                    )
                except Exception:
                    pass
                if entry:
                    return self._build_response(
                        entry.get("address"),
                        entry.get("postcode"),
                        "cache",
                        rounded_lat,
                        rounded_lon,
                    )
                return self._build_response(None, None, "unknown", rounded_lat, rounded_lon)

    def _fetch_from_provider(self, lat: float, lon: float, provider: str) -> Dict[str, Any]:
        if provider != "nominatim":
            raise ValueError(f"unsupported provider: {provider}")

        self._rate_limit_provider_call()
        params = urlencode({
            "lat": lat,
            "lon": lon,
            "format": "jsonv2",
            "addressdetails": 1,
            "accept-language": "ja",
        })
        url = f"https://nominatim.openstreetmap.org/reverse?{params}"
        request = Request(
            url,
            headers={
                "User-Agent": _NOMINATIM_USER_AGENT,
                "Accept": "application/json",
            },
        )
        with urlopen(request, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))

        address = data.get("display_name")
        postcode = None
        if isinstance(data.get("address"), dict):
            postcode = data["address"].get("postcode")

        return {
            "address": address,
            "postcode": postcode,
            "raw": data,
        }

    def _rate_limit_provider_call(self) -> None:
        now = time.monotonic()
        wait = _MIN_PROVIDER_INTERVAL_SEC - (now - self._last_provider_call_monotonic)
        if wait > 0:
            time.sleep(wait)
        self._last_provider_call_monotonic = time.monotonic()

    def _load_cache(self) -> Dict[str, Any]:
        if not self._cache_path.exists():
            return {}
        try:
            with self._cache_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_cache(self, cache: Dict[str, Any]) -> None:
        with self._cache_path.open("w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)

    def _is_cache_fresh(self, entry: Optional[Dict[str, Any]]) -> bool:
        if not entry or not entry.get("fetched_at"):
            return False
        try:
            fetched_at = datetime.fromisoformat(entry["fetched_at"])
        except Exception:
            return False
        ttl_hours = int(_get_config_value("geocode.cache_ttl_hours", _DEFAULT_TTL_HOURS))
        return fetched_at >= (_utc_now() - timedelta(hours=ttl_hours))

    @staticmethod
    def _normalize_precision(value: Any) -> int:
        try:
            precision = int(value)
        except Exception:
            precision = _DEFAULT_PRECISION
        return max(2, min(6, precision))

    @staticmethod
    def _build_cache_key(lat: float, lon: float, precision: int) -> str:
        return f"{lat:.{precision}f},{lon:.{precision}f}"

    @staticmethod
    def _build_response(address: Optional[str], postcode: Optional[str], source: str, lat: float, lon: float) -> Dict[str, Any]:
        return {
            "address": address,
            "postcode": postcode,
            "source": source,
            "lat": lat,
            "lon": lon,
        }


_instance: Optional[ReverseGeocodeService] = None


def get_reverse_geocode_service() -> ReverseGeocodeService:
    global _instance
    if _instance is None:
        _instance = ReverseGeocodeService()
    return _instance
