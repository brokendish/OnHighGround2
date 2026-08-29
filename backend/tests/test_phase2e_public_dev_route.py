"""P2E-R51-SEC-001: public earthquake debug publish route must fail closed."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.api import earthquakes_stream  # noqa: E402
from app.services.earthquake_event_bus import get_earthquake_event_bus  # noqa: E402

DEV_PUBLISH_PATH = "/api/dev/earthquakes/publish"
NORMAL_SSE_PATH = "/api/earthquakes/stream"
NORMAL_STATUS_PATH = "/api/earthquakes/realtime/status"


@pytest.fixture(scope="module")
def public_app():
    """Import the heavy public app only for tests that exercise its boundary."""
    import app_public

    return app_public.app


def _public_route_lines(public_app) -> set[str]:
    return {
        f"{','.join(sorted(route.methods))} {route.path}"
        for route in public_app.routes
        if getattr(route, "methods", None)
    }


def _dev_flag_value(env_value: str | None) -> bool:
    """Import only the dev module in a fresh process to verify its env default."""
    env = os.environ.copy()
    if env_value is None:
        env.pop("DEV_EARTHQUAKE_PUBLISH", None)
    else:
        env["DEV_EARTHQUAKE_PUBLISH"] = env_value
    proc = subprocess.run(
        [sys.executable, "-c", "import json; from app.api.earthquakes_stream import _DEV_PUBLISH_ENABLED; print(json.dumps(_DEV_PUBLISH_ENABLED))"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip())


def test_public_route_inventory_excludes_debug_publish_and_retains_normal_earthquake_routes(public_app):
    routes = _public_route_lines(public_app)
    assert f"POST {DEV_PUBLISH_PATH}" not in routes
    assert f"GET {NORMAL_SSE_PATH}" in routes
    assert f"GET {NORMAL_STATUS_PATH}" in routes


def test_default_unset_and_false_flag_are_disabled():
    assert _dev_flag_value(None) is False
    assert _dev_flag_value("false") is False


def test_explicit_true_cannot_enable_public_debug_route(monkeypatch, public_app):
    monkeypatch.setenv("DEV_EARTHQUAKE_PUBLISH", "true")
    assert _dev_flag_value("true") is True  # dev module requires explicit opt-in
    assert f"POST {DEV_PUBLISH_PATH}" not in _public_route_lines(public_app)


def test_rejected_public_publish_has_no_event_bus_side_effect(public_app):
    bus = get_earthquake_event_bus()
    before = bus.recent_events()
    payload = {
        "event_id": "p2e-r52-rejected-public-injection",
        "occurred_at": "2026-08-29T00:00:00Z",
        "epicenter_name": "negative-test",
    }
    response = TestClient(public_app).post(DEV_PUBLISH_PATH, json=payload)
    assert response.status_code == 404
    assert bus.recent_events() == before


def test_normal_status_and_sse_handler_remain_available(public_app):
    response = TestClient(public_app).get(NORMAL_STATUS_PATH)
    assert response.status_code == 200

    async def _check_sse_handler() -> None:
        response = await earthquakes_stream.earthquake_stream()
        assert response.media_type == "text/event-stream"
        first_chunk = await anext(response.body_iterator)
        assert first_chunk == ": ping\n\n"
        await response.body_iterator.aclose()

    asyncio.run(_check_sse_handler())
