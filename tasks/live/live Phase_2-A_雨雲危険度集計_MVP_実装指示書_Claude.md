````md
# /live Phase 2-A 雨雲危険度集計 MVP 実装指示書（Claude Code向け）

## 最重要

作業前に必ず以下を読むこと。

- AGENTS.md
- CLAUDE.md
- docs/live/DEVELOPMENT_GUARDRAILS.md
- frontend/js/live/README.md
- tasks/live/live_mvp_codex_verification.md
- tasks/live/live_phase1b_danger_cards_codex_verification.md
- tests/test_live_summary_api.py

既存ナビ本体には触らないこと。

---

# 目的

Phase 2-A では、`/api/live/summary` の rain セクションを、現在の

```text
evaluated=false
雨雲: 未判定（タイル表示のみ）
````

から、MVP レベルで

```text
evaluated=true
強雨域あり / 強雨域なし
```

へ進める。

ただし、最初から高精度な全国解析を目指さない。

目的は以下。

```text
既存の雨雲タイル / nowcast 資産を使って、軽量な強雨域サマリーを作る
```

---

# 絶対に守ること

以下は禁止。

* frontend/index.html を変更する
* frontend/js/navigation.js を変更する
* frontend/js/state.js に依存追加する
* frontend/js/hazard-layers.js を変更する
* nav / reroute / OSRM に触る
* frontend 側で全国ラスタを重く解析する
* タイル取得成功だけで `強雨域なし` と表示する
* 解析失敗を `強雨域なし` と表示する
* ダミーの危険地域を本物のように表示する

---

# 基本方針

雨雲危険度集計は backend 側で行う。

frontend は `/api/live/summary` の rain 契約を見るだけにする。

```text
backend が判定する
frontend は表示する
```

---

# 既存資産の確認

まず既存の nowcast / rain 実装を調査すること。

想定確認対象:

```text
backend/app/services/*nowcast*
backend/app/services/*rain*
backend/app/api/*weather*
frontend/js/live/live-layers.js
frontend/js/rain-layer.js
tests/*rain*
tests/*nowcast*
```

既存の JMA nowcast タイル取得・色判定・降水強度判定ロジックがある場合、それを再利用する。

新規実装で重複させない。

---

# Phase 2-A のスコープ

## やること

* backend で雨雲危険度を簡易集計する
* `/api/live/summary.rain.evaluated=true` を返せるようにする
* `strong_rain_detected` を true / false で返す
* `warning_area_count` / `danger_area_count` を返す
* `areas` に代表的な強雨域を最大数件返す
* `dangerous_areas` に rain 由来の地域を追加する
* frontend は summary API を使って `強雨域あり / なし` を表示する
* API 失敗時は offline / 未判定に戻す
* E2E / pytest を追加・更新する

## やらないこと

* 高精度な全国雨雲ポリゴン化
* 全ピクセル解析
* ブラウザ側ラスタ解析
* 台風解析
* キキクル危険度集計
* OSRM 利用
* ナビ本体への反映

---

# MVP 判定方式

最初は粗くてよい。

## 推奨

全国を代表するサンプリング地点で雨雲強度を確認する。

例:

```text
全国主要地域 / 都道府県代表点 / 既存観測対象地点
```

MVP では以下のような地点セットでよい。

```text
札幌
仙台
東京
新潟
名古屋
大阪
広島
高知
福岡
鹿児島
那覇
```

または既存の都道府県代表点データがあればそれを利用する。

---

# 降水強度レベル

既存 nowcast ロジックに合わせる。

なければ以下の暫定基準でよい。

```text
none      降雨なし
weak      弱い雨
moderate  やや強い雨
strong    強雨
severe    非常に強い雨
unknown   判定不能
```

Phase 2-A では:

```text
strong / severe が1地点以上 → strong_rain_detected=true
```

とする。

---

# summary 契約

`/api/live/summary` の rain を以下のように拡張する。

## 強雨なし

```json
{
  "status": "ok",
  "evaluated": true,
  "reason": "sampled_nowcast",
  "summary": {
    "strong_rain_detected": false,
    "warning_area_count": 0,
    "danger_area_count": 0,
    "sample_count": 11,
    "unknown_count": 0
  },
  "areas": []
}
```

## 強雨あり

```json
{
  "status": "ok",
  "evaluated": true,
  "reason": "sampled_nowcast",
  "summary": {
    "strong_rain_detected": true,
    "warning_area_count": 2,
    "danger_area_count": 1,
    "sample_count": 11,
    "unknown_count": 0
  },
  "areas": [
    {
      "id": "rain-tokyo-20260527-2240",
      "label": "東京都付近",
      "prefecture": "東京都",
      "area_name": "東京",
      "level": "warning",
      "type": "rain",
      "source": "jma_nowcast",
      "lat": 35.681,
      "lng": 139.767,
      "observed_at": "2026-05-27T22:40:00+09:00",
      "description": "強雨域を検出"
    }
  ]
}
```

---

# level 判定

```text
moderate → watch
strong   → warning
severe   → danger
```

`dangerous_areas` には `warning` 以上のみ追加する。

---

# unknown の扱い

重要。

```text
unknown_count が多い場合に強雨なしと断定しない
```

目安:

```text
sample_count > 0
unknown_count / sample_count >= 0.5
```

の場合:

```json
{
  "status": "unknown",
  "evaluated": false,
  "reason": "too_many_unknown_samples"
}
```

または `status=ok, evaluated=false` でもよい。

ただし:

```text
strong_rain_detected=false
```

にしてはいけない。

---

# frontend 表示ルール

Phase 1-C の evaluated 契約を守る。

## rain.evaluated=true

```text
strong_rain_detected=true
→ 強雨域あり

strong_rain_detected=false
→ 強雨域なし
```

## rain.evaluated=false

```text
雨雲: 未判定（タイル表示のみ）
```

または reason に応じて:

```text
雨雲: 判定不能
```

## rain.status=offline

```text
雨雲情報: 取得失敗
```

---

# 危険地域ランキング

rain.areas のうち `level=warning` / `danger` を危険地域ランキングに追加する。

優先順位:

```text
津波警報 > 津波注意報 > M6以上地震 > rain danger > rain warning > M5以上地震
```

または既存ランキング設計に自然に統合する。

---

# backend 実装候補

新規または拡張:

```text
backend/app/services/live_rain_summary_service.py
```

役割:

* サンプリング地点を定義
* 既存 nowcast intensity 判定を呼び出す
* summary を作る
* areas を返す
* failure / unknown を正しく返す

`live_summary_service.py` から呼び出す。

---

# サンプリング地点

MVP ではコード内定義でよい。

例:

```python
LIVE_RAIN_SAMPLE_POINTS = [
    {"id": "sapporo", "label": "札幌", "prefecture": "北海道", "lat": 43.0618, "lng": 141.3545},
    {"id": "sendai", "label": "仙台", "prefecture": "宮城県", "lat": 38.2682, "lng": 140.8694},
    {"id": "tokyo", "label": "東京", "prefecture": "東京都", "lat": 35.6812, "lng": 139.7671},
    {"id": "nagoya", "label": "名古屋", "prefecture": "愛知県", "lat": 35.1709, "lng": 136.8815},
    {"id": "osaka", "label": "大阪", "prefecture": "大阪府", "lat": 34.6937, "lng": 135.5023},
    {"id": "fukuoka", "label": "福岡", "prefecture": "福岡県", "lat": 33.5902, "lng": 130.4017},
    {"id": "kagoshima", "label": "鹿児島", "prefecture": "鹿児島県", "lat": 31.5966, "lng": 130.5571},
    {"id": "naha", "label": "那覇", "prefecture": "沖縄県", "lat": 26.2124, "lng": 127.6792}
]
```

可能なら 47都道府県代表点にしてもよいが、Phase 2-A では重さ優先で少数でも可。

---

# キャッシュ

雨雲判定は短時間キャッシュする。

例:

```text
TTL 120秒
```

目的:

* `/live` 更新時に JMA へ過剰アクセスしない
* サーバ負荷を抑える

---

# API failure

外部取得失敗時:

```json
"rain": {
  "status": "offline",
  "evaluated": false,
  "reason": "source_unavailable",
  "summary": {
    "strong_rain_detected": null,
    "warning_area_count": null,
    "danger_area_count": null,
    "sample_count": 0,
    "unknown_count": null
  },
  "areas": []
}
```

---

# pytest 追加

`tests/test_live_summary_api.py` を拡張する。

追加確認:

* rain.evaluated=true のとき strong_rain_detected は boolean
* rain.evaluated=false のとき strong_rain_detected は null
* strong / severe サンプルで areas が返る
* severe は level=danger
* strong は level=warning
* unknown 過多では false-safe にならない
* dangerous_areas に rain warning/danger が追加される
* source failure は status=offline

必要なら `live_rain_summary_service` 単体テストを追加。

```text
tests/test_live_rain_summary_service.py
```

---

# E2E 追加

`e2e/live-basic.spec.js` に追加する。

## mock summary API

* rain evaluated=true + strong_rain_detected=false

  * `強雨域なし` 表示
* rain evaluated=true + strong_rain_detected=true

  * `強雨域あり` 表示
  * 危険地域ランキングに rain area 表示
* rain evaluated=false

  * `強雨域なし` を表示しない
* rain offline

  * `雨雲情報: 取得失敗`
  * 安全断定しない

---

# 完了条件

以下を満たすこと。

* `/api/live/summary.rain.evaluated=true` を返せる
* 強雨域あり / なし が evaluated に基づいて表示される
* strong/severe サンプルが危険地域ランキングに追加される
* unknown / failure で false-safe しない
* backend pytest PASS
* `/live` E2E PASS
* 既存ナビ代表 E2E PASS
* 禁止ファイル未変更
* navigation/state/reroute/OSRM 依存なし

---

# 検証コマンド

```bash
node --check frontend/js/live/live-map.js
node --check frontend/js/live/live-layers.js
node --check frontend/js/live/live-alert-panel.js
node --check frontend/js/live/live-ui.js
node --check frontend/js/live/live-main.js
node --check frontend/js/live/live-danger-summary.js

pytest tests/test_live_summary_api.py
test -f tests/test_live_rain_summary_service.py && pytest tests/test_live_rain_summary_service.py || true

npx playwright test e2e/live-basic.spec.js

npx playwright test e2e/info-tab-card-ui.spec.js e2e/weather-rain-radar-card.spec.js e2e/tide-sun-moon-timeline.spec.js e2e/simulation-mode.spec.js
```

---

# 報告内容

完了後、以下を報告すること。

* 追加ファイル
* 変更ファイル
* 雨雲危険度集計方式
* サンプリング地点数
* `/api/live/summary.rain` のレスポンス例
* false-safe 防止仕様
* pytest 結果
* `/live` E2E 結果
* 既存ナビ代表 E2E 結果
* 禁止ファイル差分有無

```
```
