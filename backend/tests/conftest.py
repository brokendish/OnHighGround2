"""backend/tests 共通設定: 実 data_lake/admin をテストから隔離・保護する（tests/admin_isolation.py）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))

from admin_isolation import _real_admin_guard, pytest_runtest_setup, pytest_sessionfinish  # noqa: E402,F401
