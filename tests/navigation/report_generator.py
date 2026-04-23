"""
Report generator for navigation parameter sweep results.
Called from conftest.pytest_sessionfinish after all tests complete.
"""

from pathlib import Path

REPORT_DIR = Path(__file__).resolve().parents[2] / "reports" / "parameter_sweep"

from sweep_config import (
    ARRIVAL_RADIUS_SWEEP,
    REROUTE_THRESHOLD_SWEEP,
    NOISE_SIGMA_SWEEP,
    CURRENT_ARRIVAL_RADIUS,
    CURRENT_REROUTE_THRESHOLD,
    CURRENT_CONSECUTIVE,
    CURRENT_DEBOUNCE_SEC,
    GPS_STEP_SEC,
    LOW_ACCURACY_ARRIVAL_RADIUS,
    LOW_ACCURACY_ARRIVAL_CONSECUTIVE,
    CURRENT_ARRIVAL_CONSECUTIVE,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get(results, **filters):
    for r in results:
        if all(r.get(k) == v for k, v in filters.items()):
            return r
    return None


def _pct(v):
    if v is None:
        return '—'
    return f'{v * 100:.0f}%'


def _fmt(v, decimals=1):
    if v is None:
        return '—'
    return f'{v:.{decimals}f}'


# ── accuracy/effectiveRadius paradox table ───────────────────────────────────

def _paradox_table(arrival_radius: float) -> str:
    rows = [
        '| GPS accuracy (m) | arrival radius (m) | required consecutive fixes | radius source |',
        '|---|---|---|---|',
    ]
    for acc in [5, 10, 15, 20, 30, 50, 80, 100]:
        if acc > 30:
            radius = LOW_ACCURACY_ARRIVAL_RADIUS
            required = LOW_ACCURACY_ARRIVAL_CONSECUTIVE
            src = 'low-accuracy conservative mode'
        else:
            radius = arrival_radius
            required = CURRENT_ARRIVAL_CONSECUTIVE
            src = f'arrival_radius={arrival_radius}m'
        rows.append(f'| {acc} | {radius:.0f} | {required} | {src} |')
    return '\n'.join(rows)


# ── arrival.md ───────────────────────────────────────────────────────────────

def generate_arrival_report(results: list) -> str:
    if not results:
        return '# Arrival sweep\n\n*No data collected.*\n'

    scenarios = sorted({r['scenario'] for r in results})

    lines = [
        '# Arrival Detection Parameter Sweep',
        '',
        '## GPS accuracy → arrival rule',
        '',
        f'Current `arrival_radius` = **{CURRENT_ARRIVAL_RADIUS} m**',
        '',
        _paradox_table(CURRENT_ARRIVAL_RADIUS),
        '',
        '> 低精度（accuracy > 30m）では半径を広げず、より小さい半径と',
        '> 多めの連続成立回数で保守的に確定する。',
        '',
        '## Detection rate by scenario',
        '',
        '`fired_rate`: fraction of trials where arrival fired.',
        '',
    ]

    for scenario in scenarios:
        lines.append(f'### {scenario}')
        lines.append('')

        # Header: arrival_radius columns
        header = '| σ (m) | ' + ' | '.join(f'r={r}m' for r in ARRIVAL_RADIUS_SWEEP) + ' |'
        sep    = '|---' * (len(ARRIVAL_RADIUS_SWEEP) + 1) + '|'
        lines.append(header)
        lines.append(sep)

        for sigma in NOISE_SIGMA_SWEEP:
            row_vals = []
            for r in ARRIVAL_RADIUS_SWEEP:
                rec = _get(results, scenario=scenario, arrival_radius=r, noise_sigma=sigma)
                row_vals.append(_pct(rec['fired_rate']) if rec else '—')
            lines.append(f'| {sigma:2d} | ' + ' | '.join(row_vals) + ' |')

        lines.append('')

    # Mean fire distance table for T1 at sigma=0
    lines += [
        '## Mean distance from destination at arrival (T1 direct, σ=0 m)',
        '',
        '| arrival_radius (m) | mean fire dist (m) |',
        '|---|---|',
    ]
    for r in ARRIVAL_RADIUS_SWEEP:
        rec = _get(results, scenario='T1_direct', arrival_radius=r, noise_sigma=0)
        lines.append(f'| {r} | {_fmt(rec["mean_fire_dist_m"]) if rec else "—"} |')

    lines.append('')
    return '\n'.join(lines)


# ── reroute.md ───────────────────────────────────────────────────────────────

def generate_reroute_report(results: list) -> str:
    if not results:
        return '# Reroute sweep\n\n*No data collected.*\n'

    scenarios = sorted({r['scenario'] for r in results})
    eff_delay = CURRENT_CONSECUTIVE * GPS_STEP_SEC + CURRENT_DEBOUNCE_SEC

    lines = [
        '# Reroute Detection Parameter Sweep',
        '',
        f'## Effective reroute delay (fixed parameters)',
        '',
        f'- `NAV_CONSECUTIVE` = {CURRENT_CONSECUTIVE} × GPS interval ({GPS_STEP_SEC} s) = {CURRENT_CONSECUTIVE * GPS_STEP_SEC:.0f} s',
        f'- `NAV_OFF_ROUTE_DEBOUNCE_MS` = {CURRENT_DEBOUNCE_SEC:.0f} s',
        f'- **Expected minimum delay from deviation to reroute: ~{eff_delay:.0f} s**',
        '',
        '> フィールドテスト観測項目: 逸脱から実際に再ルートが走るまでの秒数を計測し、',
        '> この期待値（~{:.0f}s）との差を記録すること。'.format(eff_delay),
        '',
        '## Detection rate by scenario',
        '',
        '`fired_rate`: fraction of trials where reroute triggered.',
        '',
    ]

    for scenario in scenarios:
        lines.append(f'### {scenario}')
        lines.append('')

        header = '| σ (m) | ' + ' | '.join(f't={t}m' for t in REROUTE_THRESHOLD_SWEEP) + ' |'
        sep    = '|---' * (len(REROUTE_THRESHOLD_SWEEP) + 1) + '|'
        lines.append(header)
        lines.append(sep)

        for sigma in NOISE_SIGMA_SWEEP:
            row_vals = []
            for t in REROUTE_THRESHOLD_SWEEP:
                rec = _get(results, scenario=scenario, reroute_threshold=t, noise_sigma=sigma)
                row_vals.append(_pct(rec['fired_rate']) if rec else '—')
            lines.append(f'| {sigma:2d} | ' + ' | '.join(row_vals) + ' |')

        lines.append('')

    return '\n'.join(lines)


# ── interaction.md ───────────────────────────────────────────────────────────

_ZONE_EMOJI = {
    'arrival_only':   '✅',
    'safe':           '✅',
    'reroute_then_arr': '⚠️',
    'reroute_only':   '❌',
    'neither':        '❌',
}

def generate_interaction_report(results: list) -> str:
    if not results:
        return '# Interaction matrix\n\n*No data collected.*\n'

    lines = [
        '# Arrival × Reroute Threshold Interaction Matrix',
        '',
        '**Scenario:** Walk toward destination, deviate 30 m off-route at 60% of route,',
        'do not return.  Tests whether reroute fires before arrival near destination.',
        '',
        'Legend: ✅ arrival fired (safe)  ⚠️ reroute before arrival  ❌ neither/reroute only',
        '',
    ]

    for sigma in [0, 10]:
        lines.append(f'## σ = {sigma} m noise')
        lines.append('')

        header = '| arrival_radius \\ reroute_threshold | ' + ' | '.join(f'{t}m' for t in REROUTE_THRESHOLD_SWEEP) + ' |'
        sep    = '|---' * (len(REROUTE_THRESHOLD_SWEEP) + 1) + '|'
        lines.append(header)
        lines.append(sep)

        for ar in ARRIVAL_RADIUS_SWEEP:
            row_vals = []
            for rt in REROUTE_THRESHOLD_SWEEP:
                rec = _get(results, arrival_radius=ar, reroute_threshold=rt, noise_sigma=sigma)
                if rec:
                    emoji = _ZONE_EMOJI.get(rec['classification'], '?')
                    row_vals.append(f'{emoji}')
                else:
                    row_vals.append('—')
            lines.append(f'| **{ar}m** | ' + ' | '.join(row_vals) + ' |')

        lines.append('')

        # Count safe cells
        safe_cells = sum(
            1 for r in results
            if r['noise_sigma'] == sigma
            and r['classification'] in ('arrival_only', 'safe')
        )
        total_cells = len(ARRIVAL_RADIUS_SWEEP) * len(REROUTE_THRESHOLD_SWEEP)
        lines.append(f'Safe cells (σ={sigma}m): **{safe_cells}/{total_cells}**')
        lines.append('')

    return '\n'.join(lines)


# ── RECOMMENDATION.md ────────────────────────────────────────────────────────

def generate_recommendation(arrival: list, reroute: list, interaction: list) -> str:
    lines = [
        '# Navigation Parameter Sweep — Recommendation Report',
        '',
        f'Generated by `pytest tests/navigation/`',
        '',
        '---',
        '',
        f'Current defaults: `arrival_radius={CURRENT_ARRIVAL_RADIUS}m`, '
        f'`reroute_threshold={CURRENT_REROUTE_THRESHOLD}m`',
        '',
    ]

    # ── Section 1: Safe zone ─────────────────────────────────────────────
    lines += ['## 1. Safe zone — arrival_radius', '']

    # Safe = T1 fired_rate >= 90% for all sigma <= 15m
    safe_arr = []
    for r in ARRIVAL_RADIUS_SWEEP:
        ok = all(
            (_get(arrival, scenario='T1_direct', arrival_radius=r, noise_sigma=s) or {}).get('fired_rate', 0) >= 0.9
            for s in [sig for sig in NOISE_SIGMA_SWEEP if sig <= 15]
        )
        if ok:
            safe_arr.append(r)

    if safe_arr:
        lines.append(f'Radii where T1 (direct approach) detection ≥ 90 % for all σ ≤ 15 m:')
        lines.append(f'**{safe_arr}**')
    else:
        lines.append('No radius achieves ≥ 90 % at all σ ≤ 15 m (check engine or traces).')
    lines.append('')

    lines += ['## 2. Safe zone — reroute_threshold', '']

    # Safe reroute = T4 (75m deviation) fired_rate >= 90% AND T1 false_positive = 0%
    safe_rt = []
    for t in REROUTE_THRESHOLD_SWEEP:
        det_ok = all(
            (_get(reroute, scenario='T4_dev_75m_no_ret', reroute_threshold=t, noise_sigma=s) or {}).get('fired_rate', 0) >= 0.9
            for s in [sig for sig in NOISE_SIGMA_SWEEP if sig <= 15]
        )
        fp_ok = all(
            (_get(reroute, scenario='T1_on_route', reroute_threshold=t, noise_sigma=s) or {}).get('fired_rate', 0) == 0.0
            for s in [sig for sig in NOISE_SIGMA_SWEEP if sig <= 15]
        )
        if det_ok and fp_ok:
            safe_rt.append(t)

    if safe_rt:
        lines.append(f'Thresholds where T4 detection ≥ 90 % AND T1 false-positive = 0 % for σ ≤ 15 m:')
        lines.append(f'**{safe_rt}**')
    else:
        lines.append('No threshold achieves both criteria simultaneously.')
    lines.append('')

    # ── Section 3: Risk zones ────────────────────────────────────────────
    lines += ['## 3. Risk zone — arrival false negative (missed detection)', '']

    fn_arr = []
    for r in ARRIVAL_RADIUS_SWEEP:
        rec = _get(arrival, scenario='T3_overshoot_30m', arrival_radius=r, noise_sigma=0)
        if rec and rec['fired_rate'] < 1.0:
            fn_arr.append((r, rec['fired_rate']))

    if fn_arr:
        lines.append('arrival_radius values where T3 (30m overshoot) misses at σ=0:')
        for r, rate in fn_arr:
            lines.append(f'- {r}m: {_pct(rate)} detection')
    else:
        lines.append('No false negatives detected in T3 at σ=0.')
    lines.append('')

    lines += ['## 4. Risk zone — reroute false positive (jitter)', '']

    fp_rt = []
    for t in REROUTE_THRESHOLD_SWEEP:
        for s in NOISE_SIGMA_SWEEP:
            rec = _get(reroute, scenario='T6_jitter', reroute_threshold=t, noise_sigma=s)
            if rec and rec['fired_rate'] > 0:
                fp_rt.append((t, s, rec['fired_rate']))

    if fp_rt:
        lines.append('(threshold, σ) pairs with false-positive reroute on jitter trace:')
        for t, s, rate in fp_rt:
            lines.append(f'- threshold={t}m, σ={s}m: {_pct(rate)} false-positive rate')
    else:
        lines.append('No false positives on jitter trace (T6) at any threshold/noise combination.')
    lines.append('')

    # ── Section 5: Sensitive zone ────────────────────────────────────────
    lines += ['## 5. Sensitive zone (noise-sensitive behaviour)', '']
    lines.append('arrival_radius values where T1 fired_rate drops below 100 % at σ=20m:')
    sensitive = []
    for r in ARRIVAL_RADIUS_SWEEP:
        rec = _get(arrival, scenario='T1_direct', arrival_radius=r, noise_sigma=20)
        if rec and rec['fired_rate'] < 1.0:
            sensitive.append((r, rec['fired_rate']))
    if sensitive:
        for r, rate in sensitive:
            lines.append(f'- {r}m: {_pct(rate)} (σ=20m)')
    else:
        lines.append('All tested radii detect T1 at σ=20m.')
    lines.append('')

    # ── Section 6: Recommended starting values ───────────────────────────
    lines += ['## 6. Recommended starting values for field test', '']

    rec_arr = safe_arr[0] if safe_arr else CURRENT_ARRIVAL_RADIUS
    rec_rt  = safe_rt[0]  if safe_rt  else CURRENT_REROUTE_THRESHOLD

    lines += [
        '| Pattern | arrival_radius | reroute_threshold | Notes |',
        '|---|---|---|---|',
        f'| A (conservative) | {rec_arr}m | {rec_rt}m | Lowest safe values |',
        f'| B (current)      | {CURRENT_ARRIVAL_RADIUS}m | {CURRENT_REROUTE_THRESHOLD}m | Current defaults |',
        f'| C (loose)        | {min(75, rec_arr + 15)}m | {min(100, rec_rt + 15)}m | Wider margin |',
        '',
    ]

    # ── Section 7: What field test must answer ───────────────────────────
    eff_delay = CURRENT_CONSECUTIVE * GPS_STEP_SEC + CURRENT_DEBOUNCE_SEC
    lines += [
        '## 7. What field test must answer',
        '',
        '1. **実際のGPS accuracy 分布**: 都市歩行中の accuracy 値（中央値・95パーセンタイル）',
        '   → 机上スイープの σ 仮定が合っているか確認',
        '2. **到着判定の実効半径**: 目的地通過時の dist_to_dest ログを記録し、',
        f'   現行 arrival_radius={CURRENT_ARRIVAL_RADIUS}m で検出できるか確認',
        '3. **再ルート実効遅延の実測値**: 逸脱開始から再ルート発動まで何秒かかったか。',
        f'   机上予測値 ≈ {eff_delay:.0f}s との差を記録',
        '4. **GPS loss 発生頻度**: トンネル・高架下での signal loss 時間を記録',
        '5. **到着直前の逸脱判定誤発火**: 目的地 50m 圏内で reroute が発動した回数',
        '',
        '---',
        '',
        '*このレポートは `pytest tests/navigation/` により自動生成されます。*',
        '',
    ]

    return '\n'.join(lines)


# ── Main entry point ─────────────────────────────────────────────────────────

def generate_all_reports(arrival: list, reroute: list, interaction: list) -> None:
    """Write all four markdown reports to reports/parameter_sweep/."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    reports = {
        'arrival.md':        generate_arrival_report(arrival),
        'reroute.md':        generate_reroute_report(reroute),
        'interaction.md':    generate_interaction_report(interaction),
        'RECOMMENDATION.md': generate_recommendation(arrival, reroute, interaction),
    }

    for filename, content in reports.items():
        path = REPORT_DIR / filename
        path.write_text(content, encoding='utf-8')
        print(f'\n  [sweep] Report written: {path}')
