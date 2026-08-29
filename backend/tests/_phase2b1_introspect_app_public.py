"""
tests/_phase2b1_introspect_app_public.py

test_phase2b1_entrypoint_boundary.py から別プロセスで実行される introspection
helper。app_public をimportし、登録済みroute一覧とsys.modulesのスナップショットを
JSONでstdoutへ出力する。

別プロセスで実行する理由:
  - app_public.py はモジュールレベルでハザードデータ（数十万ポリゴン）を実際に
    読み込むため、同一pytestプロセス内で複数バリエーション（環境変数あり/なし）を
    importし直すことができない（2回目以降のimportはPythonの sys.modules
    キャッシュにより実行されず、真の再現試験にならない）。
  - operator関連環境変数を与えた場合の副作用を、テストプロセス自身の環境から
    隔離するため。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import app_public  # noqa: E402

_routes = []
for _route in app_public.app.routes:
    _path = getattr(_route, "path", None)
    if _path is None:
        continue
    _methods = sorted(getattr(_route, "methods", None) or [])
    _routes.append([_path, _methods])

_modules = sorted(
    name for name in sys.modules
    if name == "app_operator" or name.startswith("app.api.") or name.startswith("app.services.")
)

print(json.dumps({"routes": _routes, "modules": _modules}))
