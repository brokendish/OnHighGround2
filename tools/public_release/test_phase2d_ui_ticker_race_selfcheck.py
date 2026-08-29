"""
test_phase2d_ui_ticker_race_selfcheck.py — `live-stream-weather-ticker.spec.js`
case 6のticker race回帰test（Phase 2-D Round 10、P2D-UI-TICKER-RACE対応、
指示書第7・第8節）。

CODEX Round 9独立検証は、300msページ送りintervalによる時間競合で
このcaseがflaky FAILすることを実測した（毎回ではなく約半数の頻度で発生）。
本fileは、修正後のcase 6を実際にPlaywrightで複数回連続実行し、1回も
raceが再現しないことを確認する（stress実行はformal denominatorへは
加算しない——指示書第8節）。

実行:
    venv/bin/python -m pytest tools/public_release/test_phase2d_ui_ticker_race_selfcheck.py -v
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TICKER_SPEC = "e2e/live-stream-weather-ticker.spec.js"
CASE_6_GREP = "北海道地点も含まれる"

# formal denominatorへは加算しない安定性確認専用のstress回数。
# 修正前（waitForFunction検知→別evaluateAllで再取得の2段階）は
# 30回中10回前後の頻度でflaky FAILしていたことを実測済み。
STRESS_REPEATS = 10


def _run_case_6() -> subprocess.CompletedProcess:
    return subprocess.run(
        ["npx", "playwright", "test", TICKER_SPEC, "-g", CASE_6_GREP, "--reporter=line"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_01_ticker_case_6_single_run_passes():
    result = _run_case_6()
    assert result.returncode == 0, result.stdout + result.stderr


def test_02_ticker_case_6_stress_repeat_zero_flake():
    """stress実行回数は安定性確認であり、formal denominatorへ加算しない
    （指示書第8節）。1回でもraceが再現すればfreezeしない、との方針に従い、
    ここでの1回でも失敗すればtest自体をFAILさせる。"""
    failures = []
    for i in range(STRESS_REPEATS):
        result = _run_case_6()
        if result.returncode != 0:
            failures.append({"iteration": i, "output": (result.stdout + result.stderr)[-2000:]})
    assert failures == [], f"ticker race reproduced in {len(failures)}/{STRESS_REPEATS} stress runs: {failures}"


def test_03_ticker_spec_total_case_count_unchanged():
    """race修正がtest数の増減（追加・削除・skip化）を伴っていないことを確認する。"""
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "list.json"
        import os

        env = dict(os.environ)
        result = subprocess.run(
            ["npx", "playwright", "test", "--list", "--reporter=json", TICKER_SPEC],
            cwd=REPO_ROOT,
            capture_output=True,
            env=env,
        )
        data = json.loads(result.stdout.decode("utf-8"))
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import phase2d_ui_formal_manifest as ui  # noqa: E402

        cases = ui.parse_list_json(data)
        assert len(cases) == 11
