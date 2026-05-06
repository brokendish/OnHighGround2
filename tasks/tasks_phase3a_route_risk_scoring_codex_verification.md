# OnHighGround2 Phase3A ルート危険度スコアリング検証

検証日: 2026-05-06  
最終判定: **PASS with notes**

## 1. API確認

判定: PASS

確認対象:

- `POST /api/route-risk`
- `safety_score`
- `risk_level`
- `risk_summary`

実行コマンド:

```bash
curl -s -X POST http://127.0.0.1:8000/api/route-risk \
  -H 'Content-Type: application/json' \
  -d '{"coordinates":[[35.63743961235805,139.52226429878073],[35.63743961235805,139.52226429878073],[35.63743961235805,139.52226429878073],[35.63743961235805,139.52226429878073],[35.63743961235805,139.52226429878073]],"sample_count":5}'
```

結果:

```json
{
  "safety_score": 92.0,
  "risk_level": "safe",
  "risk_summary": {
    "total_penalty": 8.0,
    "hazards": [
      {
        "type": "lowland_poor_drainage",
        "label": "低地・排水困難エリア",
        "exposure_ratio": 1.0,
        "penalty": 8.0,
        "role": "supplementary"
      }
    ],
    "notes": ["低地・排水困難エリアを一部通過します（100%）"]
  }
}
```

確認:

- `safety_score` が数値で返る。
- `risk_level` が返る。
- `risk_summary.total_penalty`, `risk_summary.hazards`, `risk_summary.notes` が返る。
- frontend proxy 経由 `http://127.0.0.1:8080/api/route-risk` でも同等のレスポンスを確認。

Note:

- 検証開始時、起動済み backend は `POST /api/route-risk` に `404 Not Found` を返した。
- `docker exec evacuation-navi-backend python -c "import main; ..."` では `/api/route-risk` が route 登録済みだったため、backend 再起動後に再確認したところ 200 OK になった。

## 2. safety_score範囲

判定: PASS

コード確認:

- `backend/app/services/route_risk_scoring.py`
- `safety_score = max(0.0, min(100.0, 100.0 - total_penalty))`

実測:

```text
危険なし: safety_score=100.0
低地単独: safety_score=92.0
洪水+低地+高潮: safety_score=45.2
複合最大例: safety_score=1.0
```

確認:

- すべて `0 <= safety_score <= 100`。
- 明示的に clamp される実装。

## 3. risk_level

判定: PASS

コード確認:

```python
if score >= 75:
    return "safe"
if score >= 50:
    return "caution"
return "danger"
```

確認結果:

```text
100.0 -> safe
92.0  -> safe
70.0  -> caution
45.2  -> danger
```

しきい値:

- `>=75`: `safe`
- `50〜74`: `caution`
- `<50`: `danger`

## 4. lowland単独

判定: PASS

実行結果:

```json
{
  "safety_score": 92.0,
  "risk_level": "safe",
  "risk_summary": {
    "total_penalty": 8.0,
    "hazards": [
      {
        "type": "lowland_poor_drainage",
        "penalty": 8.0,
        "role": "supplementary"
      }
    ]
  }
}
```

補足確認:

```bash
curl -i 'http://127.0.0.1:8000/api/hazard-check?lat=35.63743961235805&lon=139.52226429878073'
```

結果:

- `hazard_assessment.lowland_poor_drainage = "inside"`
- `is_danger = false`
- `hazards = []`

確認:

- lowland 単独 penalty は 8.0 と小さい。
- lowland 単独では `danger` にならない。
- `role` は `supplementary`。

## 5. flood + lowland

判定: PASS

関数レベル確認:

```text
flood 50% only:
  safety_score=80.0
  risk_level=safe
  total_penalty=20.0

flood 50% + lowland 50%:
  safety_score=70.0
  risk_level=caution
  total_penalty=30.0
```

API確認:

```json
{
  "safety_score": 68.0,
  "risk_level": "caution",
  "risk_summary": {
    "total_penalty": 32.0,
    "hazards": [
      {"type": "lowland_poor_drainage", "exposure_ratio": 1.0, "penalty": 8.0},
      {"type": "flood", "exposure_ratio": 0.2, "penalty": 24.0}
    ]
  }
}
```

確認:

- flood に lowland が重なると `LOWLAND_OVERLAP_BONUS.flood = 6` が加算される。
- penalty が増加する。
- `risk_level` が低下するケースを確認。

## 6. inland + lowland

判定: PASS

関数レベル確認:

```text
inland_flood 50% only:
  safety_score=90.0
  risk_level=safe
  total_penalty=10.0

inland_flood 50% + lowland 50%:
  safety_score=81.0
  risk_level=safe
  total_penalty=19.0
```

確認:

- inland_flood に lowland が重なると `LOWLAND_OVERLAP_BONUS.inland_flood = 5` が加算される。
- lowland は主危険ではなく補助として penalty を強化する。
- このケースでは `risk_level` は `safe` のままだが、score は 90.0 から 81.0 に低下する。

## 7. ルート比較

判定: PASS

API確認:

```text
危険なしルート:
  safety_score=100.0
  risk_level=safe
  total_penalty=0.0

lowland単独:
  safety_score=92.0
  risk_level=safe
  total_penalty=8.0

lowland + flood + storm_surge:
  safety_score=45.2
  risk_level=danger
  total_penalty=54.8
```

確認:

- 危険少 → score 高。
- 危険多 → score 低。
- 複合 hazard で `danger` まで低下する。

## 8. UI確認

判定: PASS with notes

コード確認:

- `frontend/js/routing.js`
  - `_assessRouteHazardRisk(route)` が `/api/route-risk` へ route coordinates を送信。
  - `_appendRouteRiskBlock(panel, route)` が `risk_summary.notes` と `risk_level` を表示。
- `frontend/index.html`
  - `.route-risk-block.safe`
  - `.route-risk-block.caution`
  - `.route-risk-block.danger`

実行コマンド:

```bash
node --check frontend/js/routing.js
node --check frontend/js/navigation.js
curl -i -X GET http://127.0.0.1:8080/
node -e "... Playwrightで http://127.0.0.1:8080/ を表示 ..."
```

結果:

- `routing.js` 構文 OK。
- `navigation.js` 構文 OK。
- frontend root は 200 OK。
- Playwright:
  - title: `避難ナビゲーション OnHighGround - 津波・高潮・洪水対策`
  - viewport body: `1280 x 900`
  - route risk CSS rules: `4`
  - `pageerror`: なし

Notes:

- Playwright console warning として位置情報拒否が出た。
  - `[lip] 初回位置取得失敗: User denied Geolocation`
  - `[GPS] 位置情報取得失敗: User denied Geolocation`
- headless browser の geolocation 未許可による想定警告であり、今回の route risk 表示崩れや JS 構文エラーではない。

## 9. 回帰確認

判定: PASS

実行コマンド:

```bash
docker compose ps
curl -i http://127.0.0.1:8000/health
curl -s 'http://127.0.0.1:5501/route/v1/walking/139.7905,35.6415;139.8000,35.6500?overview=false'
curl -s 'http://127.0.0.1:8000/api/emergency-shelters?limit=5'
curl -s 'http://127.0.0.1:8000/api/hazards/active'
```

結果:

- backend: healthy。
- frontend: container up、root 200 OK、API proxy 200 OK。
- Martin: healthy。
- OSRM walking: `code=Ok`, `distance=2030.8m`。
- shelters API: `count=5`, `total_count=6939`。
- active hazards:
  - `flood`
  - `tsunami`
  - `storm_surge`
  - `inland_flood`
  - `landslide`
  - `pseudo_inland_flood`

## 10. 最終判定

**PASS with notes**

理由:

- `safety_score`, `risk_level`, `risk_summary` の API 返却を確認。
- `safety_score` は 0〜100 に収まる。
- `risk_level` しきい値は指示どおり。
- lowland 単独は小 penalty で `danger` にならない。
- flood + lowland は penalty が増え、`risk_level` が低下する。
- inland + lowland は補助 hazard として penalty を強化する。
- 危険が少ないルートほど score が高く、危険が多いルートほど score が低い。
- frontend 表示用 CSS / JS 構文 / Playwright 起動確認は OK。
- backend / frontend / Martin / OSRM / shelters API の回帰確認は OK。

Notes:

- 検証中、backend の起動済みプロセスが古い route 状態を保持しており、`/api/route-risk` が一時的に 404 になった。backend 再起動後は 200 OK。
- Playwright では geolocation 拒否の warning が出たが、今回対象の route risk JS エラーではない。
