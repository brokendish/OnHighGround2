"""
admin_isolation.py — テスト実行中の実 data_lake/admin 保護（tests/ と backend/tests の conftest が読み込む）。

背景（2026-10-07 実害）: host 上のテストが実 data_lake/admin/state を削除・再推定・上書きした。
data_lake/admin は gitignore 対象で復元手段が無い。

1. 隔離: OHG2_ADMIN_DIR を session 専用 tmp に設定する（app の import より前）。job_manager /
   active_mapping_service / dataset_state_service（acquisitions・cache はその parent 基準）が従う。
   tmp は実 admin の state / history / active_mappings.json / boot_state.json のコピーで初期化する
   （実データは読むだけ）。subprocess も環境変数を継承する。
2. guard: 実 data_lake/admin 配下への write / delete / rename / chmod / 新規 mkdir を audit hook で
   拒否して記録し、そのテストを FAIL させる（例外が握り潰されても記録で検出する）。
   collection（import）時の違反は session を失敗させる。
3. 終了時検査: 実 data_lake/admin の (path, size, mtime_ns) snapshot を開始時と比較し、
   1 件でも変化があれば session を失敗させる（audit hook が届かない subprocess 等も検出）。
   ただし logs/ は除外する: 稼働中の backend-operator container が data_lake を bind mount し、
   operator_audit.log に healthcheck を追記し続けるため（テスト由来の logs/ 書込は 2. の hook で検出）。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

import pytest

REAL_ADMIN = (Path(__file__).resolve().parents[1] / "data_lake" / "admin").resolve()
_SEED_FILES = ("active_mappings.json", "boot_state.json")
_SEED_DIRS = ("state", "history")
_SNAPSHOT_EXCLUDE = ("logs",)

_hits: list = []
_current = {"nodeid": None}


def _snapshot() -> dict:
    snap = {}
    if not REAL_ADMIN.is_dir():
        return snap
    for root, dirs, files in os.walk(REAL_ADMIN):
        if Path(root) == REAL_ADMIN:
            dirs[:] = [d for d in dirs if d not in _SNAPSHOT_EXCLUDE]
        for name in dirs + files:
            p = Path(root) / name
            try:
                st = p.lstat()
            except OSError:
                continue
            snap[str(p)] = (st.st_size if p.is_file() else -1, st.st_mtime_ns if p.is_file() else 0)
    return snap


def _setup_isolated_admin() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="ohg2-admin-test-"))
    for name in _SEED_FILES:
        src = REAL_ADMIN / name
        if src.is_file():
            shutil.copy2(src, tmp / name)
    for name in _SEED_DIRS:
        src = REAL_ADMIN / name
        if src.is_dir():
            shutil.copytree(src, tmp / name)
    for name in ("jobs", "logs", "cache", "acquisitions"):
        (tmp / name).mkdir(exist_ok=True)
    return tmp


def _under_real_admin(raw) -> bool:
    try:
        p = Path(os.fsdecode(raw))
    except (TypeError, ValueError):
        return False
    if not p.is_absolute():
        p = Path.cwd() / p
    try:
        p = Path(os.path.realpath(p))
    except (OSError, ValueError):
        return False
    return p == REAL_ADMIN or REAL_ADMIN in p.parents


def _audit(event, args):
    if event in ("os.remove", "os.rmdir", "os.chmod", "os.chown", "os.truncate", "os.utime"):
        targets = [args[0]]
    elif event in ("os.rename", "os.replace", "os.link", "os.symlink"):
        targets = [args[0], args[1]]
    elif event == "os.mkdir":
        try:
            if Path(os.fsdecode(args[0])).exists():
                return  # 既存 directory の mkdir(exist_ok) は変更ではない
        except (TypeError, ValueError, OSError):
            pass
        targets = [args[0]]
    elif event == "open" and len(args) >= 2 and args[1] is not None and any(c in str(args[1]) for c in "wax+"):
        targets = [args[0]]
    elif event == "open" and len(args) >= 3 and isinstance(args[2], int) and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
        targets = [args[0]]
    else:
        return
    for t in targets:
        if isinstance(t, int) or t is None:
            continue
        if _under_real_admin(t):
            _hits.append({"test": _current["nodeid"], "event": event, "path": os.fsdecode(t),
                          "stack": "".join(traceback.format_stack(limit=14)[:-2])})
            raise PermissionError(f"[admin_isolation] 実 data_lake/admin への変更は禁止: {event} {os.fsdecode(t)}")


# ── 初期化（conftest import 時 = app の import より前）──────────────────────────
if os.environ.get("OHG2_ADMIN_DIR") is None:
    os.environ["OHG2_ADMIN_DIR"] = str(_setup_isolated_admin())
_SNAPSHOT_BEFORE = _snapshot()
if not getattr(sys, "_ohg2_admin_audit_installed", False):
    sys.addaudithook(_audit)
    sys._ohg2_admin_audit_installed = True


def pytest_runtest_setup(item):
    _current["nodeid"] = item.nodeid


@pytest.fixture(autouse=True)
def _real_admin_guard(request):
    start = len(_hits)
    yield
    mine = _hits[start:]
    if mine:
        detail = "\n".join(f"{h['event']} {h['path']}\n{h['stack']}" for h in mine[:3])
        pytest.fail(f"実 data_lake/admin への書込・削除が {len(mine)} 件検出されました（tmp へ隔離してください）:\n{detail}",
                    pytrace=False)


def pytest_sessionfinish(session, exitstatus):
    problems = []
    unattributed = [h for h in _hits if h["test"] is None]
    if unattributed:
        problems.append("collection / import 時の実 data_lake/admin 変更: "
                        + ", ".join(f"{h['event']} {h['path']}" for h in unattributed))
    after = _snapshot()
    changed = sorted(k for k in set(_SNAPSHOT_BEFORE) | set(after) if _SNAPSHOT_BEFORE.get(k) != after.get(k))
    if changed:
        problems.append(f"実 data_lake/admin の snapshot が変化（{len(changed)} 件）: " + ", ".join(changed[:10]))
    tr = session.config.pluginmanager.get_plugin("terminalreporter")
    if problems:
        session.exitstatus = 1
        if tr:
            tr.write_line("")
            for p in problems:
                tr.write_line(f"[admin_isolation] FAIL: {p}", red=True)
    elif tr:
        tr.write_line(f"[admin_isolation] 実 data_lake/admin への変更 0 件（isolated: {os.environ['OHG2_ADMIN_DIR']}）")
