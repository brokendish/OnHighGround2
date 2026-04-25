import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services import reverse_geocode_service as rgs
from app.services.reverse_geocode_service import ReverseGeocodeService


class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_reverse_geocode_uses_cache_hit_without_provider_call(tmp_path, monkeypatch):
    cache_path = tmp_path / "reverse_geocode_cache.json"
    cache_path.write_text(json.dumps({
        "35.6812,139.7671": {
            "address": "東京都千代田区丸の内",
            "postcode": "100-0005",
            "provider": "nominatim",
            "fetched_at": "2099-01-01T00:00:00+00:00",
        }
    }), encoding="utf-8")
    service = ReverseGeocodeService(cache_path=cache_path)

    monkeypatch.setattr(rgs, "_get_config_value", lambda key, default: {
        "geocode.enabled": True,
        "geocode.coordinate_precision": 4,
        "geocode.cache_ttl_hours": 24,
        "geocode.provider": "nominatim",
    }.get(key, default))

    def _unexpected_provider(*args, **kwargs):
        raise AssertionError("provider should not be called on cache hit")

    monkeypatch.setattr(rgs, "urlopen", _unexpected_provider)

    result = service.reverse_geocode(35.681236, 139.767125)

    assert result["source"] == "cache"
    assert result["address"] == "東京都千代田区丸の内"
    assert result["postcode"] == "100-0005"
    assert result["lat"] == 35.6812
    assert result["lon"] == 139.7671


def test_reverse_geocode_fetches_provider_and_persists_cache(tmp_path, monkeypatch):
    cache_path = tmp_path / "reverse_geocode_cache.json"
    service = ReverseGeocodeService(cache_path=cache_path)
    calls = {"count": 0}
    request_headers = {}

    monkeypatch.setattr(rgs, "_get_config_value", lambda key, default: {
        "geocode.enabled": True,
        "geocode.coordinate_precision": 4,
        "geocode.cache_ttl_hours": 24,
        "geocode.provider": "nominatim",
    }.get(key, default))

    def _fake_urlopen(request, timeout=0):
        calls["count"] += 1
        request_headers["User-Agent"] = request.headers.get("User-agent")
        return _FakeResponse({
            "display_name": "神奈川県横浜市中区本町",
            "address": {"postcode": "231-0005"},
        })

    monkeypatch.setattr(rgs, "urlopen", _fake_urlopen)

    result = service.reverse_geocode(35.447753, 139.642514)

    assert calls["count"] == 1
    assert request_headers["User-Agent"] == "OnHighGround2/0.1 (https://ohg.brokendish.org/)"
    assert result["source"] == "provider"
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache["35.4478,139.6425"]["address"] == "神奈川県横浜市中区本町"
    assert cache["35.4478,139.6425"]["postcode"] == "231-0005"


def test_reverse_geocode_returns_stale_cache_when_provider_fails(tmp_path, monkeypatch):
    cache_path = tmp_path / "reverse_geocode_cache.json"
    cache_path.write_text(json.dumps({
        "35.6812,139.7671": {
            "address": "東京都千代田区丸の内",
            "postcode": "100-0005",
            "provider": "nominatim",
            "fetched_at": "2000-01-01T00:00:00+00:00",
        }
    }), encoding="utf-8")
    service = ReverseGeocodeService(cache_path=cache_path)

    monkeypatch.setattr(rgs, "_get_config_value", lambda key, default: {
        "geocode.enabled": True,
        "geocode.coordinate_precision": 4,
        "geocode.cache_ttl_hours": 1,
        "geocode.provider": "nominatim",
    }.get(key, default))

    def _failing_urlopen(request, timeout=0):
        raise RuntimeError("provider down")

    monkeypatch.setattr(rgs, "urlopen", _failing_urlopen)

    result = service.reverse_geocode(35.681236, 139.767125)

    assert result["source"] == "cache"
    assert result["address"] == "東京都千代田区丸の内"
    assert result["postcode"] == "100-0005"
