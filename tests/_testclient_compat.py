"""
_testclient_compat.py — httpx 非推奨 'app' shortcut を使わない TestClient

背景:
  fastapi==0.104.1 が依存する starlette 0.27 の TestClient.__init__ は、
  transport=_TestClientTransport(app) に加えて非推奨の app= も httpx.Client へ渡す。
  httpx 0.27 はこれに DeprecationWarning（"The 'app' shortcut is now deprecated.
  Use the explicit style 'transport=...' instead."）を出し、0.28 で app 引数自体が廃止された
  （requirements-dev.txt の httpx<0.28 固定の理由）。

対応:
  httpx.Client は transport が指定されていれば app を使わない（_init_transport は
  transport を最優先し、env proxy 判定も transport 指定で無効になる）。
  そこで MRO 上 starlette TestClient と httpx.Client の間に本 mixin を挟み、
  TestClient が常に渡す explicit transport のみで httpx.Client を初期化する。
  starlette の private API は使わず、TestClient の挙動（transport・lifespan・例外伝播・
  cookies・headers）は変わらない。warning の抑制（filterwarnings 等）ではない。

  fastapi/starlette を更新して TestClient 自体が app= を渡さなくなれば本 module は不要。
  backend/tests/_testclient_compat.py と同内容（tests/ と backend/tests/ は import root が別のため）。
"""
from __future__ import annotations

import httpx
from fastapi.testclient import TestClient as _StarletteTestClient


class _ExplicitTransportClient(httpx.Client):
    def __init__(self, *args, app=None, **kwargs):
        if kwargs.get("transport") is None:
            # app だけが渡る経路は想定外（ここで app を捨てると挙動が変わる）ため明示的に失敗させる
            raise TypeError("TestClient compat: explicit transport is required")
        super().__init__(*args, **kwargs)


class TestClient(_StarletteTestClient, _ExplicitTransportClient):
    __test__ = False
