````md
# /live Phase 1-C 雨雲・キキクル危険度集計データ契約設計 実装指示書（Claude Code向け）

## 最重要

作業前に必ず以下を読むこと。

- AGENTS.md
- CLAUDE.md
- docs/live/DEVELOPMENT_GUARDRAILS.md
- frontend/js/live/README.md
- tasks/live/live_mvp_codex_verification.md
- tasks/live/live_phase1b_danger_cards_codex_verification.md

既存ナビ本体には触らないこと。

---

# 目的

Phase 1-C では、雨雲・キキクルについて、

```text
タイルが表示できた
````

ではなく、

```text
危険度を集計・判定できた
```

と扱えるための **データ契約** を設計・実装する。

今回の目的は、全国監視ビューア `/live` が将来的に

```text
強雨域あり / なし
キキクル危険地域あり / なし
危険地域ランキング
```

を正しく表示できる土台を作ること。

---

# 重要な前提

Phase 1-B では、雨雲・キキクルは以下の状態になっている。

```text
雨雲: 未判定（タイル表示のみ）
キキクル: 未判定（タイル表示のみ）
```

これは正しい。

Phase 1-C では、この「未判定」を将来「判定済み」にできるようにする。

ただし、無理に危険判定を捏造してはいけない。

---

# 絶対に守ること

以下は禁止。

* frontend/index.html を変更する
* frontend/js/navigation.js を変更する
* frontend/js/state.js に依存追加する
* frontend/js/hazard-layers.js を変更する
* nav / reroute / OSRM に触る
* タイル取得成功を危険なし扱いする
* 未判定を安全表示に戻す
* ダミーの危険判定を本物のように表示する

---

# 今回の実装範囲

Phase 1-C は「契約設計」が主目的。

最低限、以下を実装する。

## backend

新規追加候補:

```text
backend/app/api/live_summary.py
backend/app/services/live_summary_service.py
```

または既存 live API 構成に合わせた live 専用 API。

## frontend

変更候補:

```text
frontend/js/live/live-main.js
frontend/js/live/live-alert-panel.js
frontend/js/live/live-danger-summary.js
frontend/js/live/live-layers.js
frontend/js/live/live-ui.js
```

## test

変更・追加候補:

```text
e2e/live-basic.spec.js
tests/test_live_summary_api.py
```

---

# API 契約

以下のような live summary API を追加する。

```text
GET /api/live/summary
```

レスポンス例:

```json
{
  "updated_at": "2026-05-27T22:40:00+09:00",
  "status": "ok",
  "rain": {
    "status": "ok",
    "evaluated": false,
    "reason": "tile_only",
    "summary": {
      "strong_rain_detected": null,
      "warning_area_count": null,
      "danger_area_count": null
    },
    "areas": []
  },
  "kikikuru": {
    "status": "ok",
    "evaluated": false,
    "reason": "tile_only",
    "summary": {
      "danger_detected": null,
      "warning_area_count": null,
      "danger_area_count": null
    },
    "areas": []
  },
  "earthquake": {
    "status": "ok",
    "evaluated": true,
    "summary": {
      "count_24h": 1,
      "m5_count": 1,
      "m6_count": 0
    },
    "areas": []
  },
  "tsunami": {
    "status": "ok",
    "evaluated": true,
    "summary": {
      "active": false,
      "warning_area_count": 0
    },
    "areas": []
  },
  "dangerous_areas": []
}
```

---

# 重要な契約ルール

## evaluated

必ず `evaluated` を持たせる。

```json
"evaluated": true
```

は、危険あり / なし を判定できる状態。

```json
"evaluated": false
```

は、表示や取得はできているが危険度は判定できない状態。

---

# rain 契約

## 現時点

雨雲はタイル表示のみ。

そのため初期実装では以下でよい。

```json
"rain": {
  "status": "ok",
  "evaluated": false,
  "reason": "tile_only",
  "summary": {
    "strong_rain_detected": null,
    "warning_area_count": null,
    "danger_area_count": null
  },
  "areas": []
}
```

重要:

```text
strong_rain_detected: false
```

にしてはいけない。

未判定なら `null`。

---

# kikikuru 契約

## 現時点

キキクルもタイル表示のみ。

そのため初期実装では以下でよい。

```json
"kikikuru": {
  "status": "ok",
  "evaluated": false,
  "reason": "tile_only",
  "summary": {
    "danger_detected": null,
    "warning_area_count": null,
    "danger_area_count": null
  },
  "areas": []
}
```

重要:

```text
danger_detected: false
```

にしてはいけない。

未判定なら `null`。

---

# 将来の areas 契約

将来、雨雲・キキクルの危険地域集計ができるようになった場合は、以下の形式にする。

```json
{
  "id": "rain-20260527-001",
  "label": "鹿児島県 奄美地方",
  "prefecture": "鹿児島県",
  "area_name": "奄美地方",
  "level": "warning",
  "type": "rain",
  "source": "jma_nowcast",
  "lat": 28.37,
  "lng": 129.49,
  "observed_at": "2026-05-27T22:35:00+09:00",
  "description": "強雨域を検出"
}
```

level は以下に統一する。

```text
normal
watch
warning
danger
unknown
```

---

# status 契約

各カテゴリの status は以下に統一する。

```text
ok
offline
stale
unknown
```

意味:

```text
ok       API取得成功
offline 取得失敗
stale   取得できたが古い
unknown 未確認・未初期化
```

---

# frontend 表示ルール

frontend は `/api/live/summary` を利用する。

## rain

```text
status=ok, evaluated=false
→ 雨雲: 未判定（タイル表示のみ）
```

```text
status=ok, evaluated=true, strong_rain_detected=false
→ 強雨域なし
```

```text
status=ok, evaluated=true, strong_rain_detected=true
→ 強雨域あり
```

## kikikuru

```text
status=ok, evaluated=false
→ キキクル: 未判定（タイル表示のみ）
```

```text
status=ok, evaluated=true, danger_detected=false
→ キキクル危険地域なし
```

```text
status=ok, evaluated=true, danger_detected=true
→ キキクル危険地域あり
```

---

# false-safe 防止

以下は禁止。

```js
if (rain.status === 'ok') {
  show('強雨域なし');
}
```

必ず以下のように判定する。

```js
if (rain.status === 'ok' && rain.evaluated === true && rain.summary.strong_rain_detected === false) {
  show('強雨域なし');
}
```

---

# 危険地域ランキング

`dangerous_areas` は backend summary が返す。

frontend は基本的に `dangerous_areas` を表示する。

ただし Phase 1-C 時点では、雨雲・キキクルが未判定なら dangerous_areas に含めない。

既存の津波・M5以上地震ランキングは維持する。

---

# backend 実装方針

最初は既存 API の集約でよい。

## やること

* `/api/live/summary` を追加
* rain / kikikuru は `evaluated=false` として返す
* earthquake / tsunami は既存 API を利用して可能な範囲で summary 化する
* dangerous_areas は既存 Phase 1-B 相当のロジックを維持
* API 失敗時は該当カテゴリを `offline` にする
* API 全体はできるだけ 200 を返し、カテゴリ単位で status を表現する

## やらないこと

* 雨雲ラスタ解析
* キキクルタイル解析
* 全国メッシュ集計
* 重い画像解析
* OSRM 利用
* nav 既存 API への変更

---

# frontend 実装方針

* 可能であれば `/api/live/summary` を優先利用する
* summary API が失敗した場合でも画面を壊さない
* 雨雲・キキクルのタイル表示機能は維持する
* 危険カードは summary API の `evaluated` を見て表示する
* 未判定は未判定として表示する

---

# E2E 追加

`e2e/live-basic.spec.js` に以下を追加する。

## 追加確認

* `/api/live/summary` が使われる
* rain evaluated=false で `強雨域なし` を表示しない
* kikikuru evaluated=false で `キキクル危険地域なし` を表示しない
* rain evaluated=true + strong_rain_detected=false なら `強雨域なし`
* kikikuru evaluated=true + danger_detected=false なら `キキクル危険地域なし`
* summary API failure でも page error なし
* offline 時に「安全」と断定しない

---

# backend test

可能であれば pytest を追加する。

```text
tests/test_live_summary_api.py
```

確認項目:

* `/api/live/summary` が 200
* rain.evaluated が boolean
* rain.summary.strong_rain_detected は未判定時 null
* kikikuru.evaluated が boolean
* kikikuru.summary.danger_detected は未判定時 null
* status が契約値内
* dangerous_areas が配列

---

# 完了条件

以下を満たすこと。

* `/api/live/summary` が追加される
* rain / kikikuru に `evaluated` がある
* 未判定時に false を返さない
* frontend が `evaluated` を見て表示を切り替える
* false-safe 表示が復活しない
* `/live` E2E PASS
* backend pytest PASS
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

npx playwright test e2e/live-basic.spec.js

npx playwright test e2e/info-tab-card-ui.spec.js e2e/weather-rain-radar-card.spec.js e2e/tide-sun-moon-timeline.spec.js e2e/simulation-mode.spec.js
```

---

# 報告内容

完了後、以下を報告すること。

* 追加ファイル
* 変更ファイル
* `/api/live/summary` のレスポンス例
* rain / kikikuru の evaluated 表示仕様
* false-safe 防止内容
* backend pytest 結果
* `/live` E2E 結果
* 既存ナビ代表 E2E 結果
* 禁止ファイル差分有無

```
```
