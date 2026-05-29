````md
# /live Phase 3-A キキクル危険度集計 MVP 実装指示書（Claude Code向け）

## 最重要

作業前に必ず以下を読むこと。

- AGENTS.md
- CLAUDE.md
- docs/live/DEVELOPMENT_GUARDRAILS.md
- frontend/js/live/README.md
- tasks/live/live_mvp_codex_verification.md
- tasks/live/live_phase1b_danger_cards_codex_verification.md
- tasks/live/live_phase2a_rain_summary_codex_verification.md
- tasks/live/live_phase2b_rain_sampling_codex_verification.md
- tasks/live/live_phase2c_regional_sampling_codex_verification.md
- tests/test_live_summary_api.py
- tests/test_live_rain_summary_service.py

既存ナビ本体には触らないこと。

---

# 目的

Phase 3-A では、`/api/live/summary` の `kikikuru` セクションを、現在の

```text
evaluated=false
キキクル: 未判定（タイル表示のみ）
````

から、MVP レベルで

```text
evaluated=true
キキクル危険地域あり / なし
```

へ進める。

目的は以下。

```text
全国監視ビューアとして、雨雲だけでなくキキクル危険度も危険地域カード・ランキングへ反映する
```

---

# 重要な前提

キキクルは、単にタイルが表示できるだけでは「危険なし」とは言えない。

必ず以下を分けること。

```text
タイル取得成功
≠
危険度判定済み
```

Phase 3-A では、危険度判定に使える集計契約を backend 側で作る。

---

# 絶対に守ること

以下は禁止。

* frontend/index.html を変更する
* frontend/js/navigation.js を変更する
* frontend/js/state.js に依存追加する
* frontend/js/hazard-layers.js を変更する
* nav / reroute / OSRM に触る
* frontend 側で全国タイル・ラスタを重く解析する
* 全タイル・全ピクセル解析を行う
* タイル取得成功だけで `キキクル危険地域なし` と表示する
* 判定不能・取得失敗を `危険なし` と表示する
* ダミー危険地域を本物のように表示する
* 既存ナビのキキクル表示ロジックを壊す

---

# Phase 3-A の基本方針

MVP では、以下のどちらか現実的な方法を採用する。

## 方針A: 既存キキクル取得・表示ロジックを再利用する

既存 backend / frontend にキキクル関連の取得ロジックがある場合、それを調査し、live 専用 summary に再利用する。

確認候補:

```text
backend/app/services/*kikikuru*
backend/app/api/*kikikuru*
frontend/js/*kikikuru*
frontend/js/live/live-layers.js
tests/*kikikuru*
```

## 方針B: サンプリング方式で危険度を集計する

既存のキキクルタイル / risk tile から、雨雲と同様に代表点サンプリングで危険度を判定する。

Phase 3-A では全面解析ではなく、軽量サンプリングでよい。

---

# 推奨実装

雨雲と同様に、backend 側で軽量サンプリングする。

```text
backend/app/services/live_kikikuru_summary_service.py
```

を追加し、`live_summary_service.py` から呼び出す。

---

# サンプリング地点

Phase 2-C の雨雲サンプリング地点を再利用してよい。

推奨:

```text
LIVE_RAIN_SAMPLE_POINTS と同等の 76 地点
```

ただし、名称は将来の共通化を見据えて以下へ分離してもよい。

```text
backend/app/services/live_sample_points.py
```

この場合:

* rain
* kikikuru

の両方から使う。

ただし、既存テストが壊れないようにすること。

---

# 対象キキクル種別

Phase 3-A では最小限でよい。

優先順位:

```text
1. 土砂災害
2. 浸水害
3. 洪水害
```

既存タイルや API が扱いやすいものから始めてよい。

MVP では1種別だけでも可。

ただし UI/summary 契約は複数種別へ拡張できる形にする。

---

# 危険度レベル契約

キキクルの危険度を `/live` 内では以下へ正規化する。

```text
normal
watch
warning
danger
unknown
```

JMA 側の色・値・階級は、既存実装があればそれに合わせる。

MVP の対応例:

```text
注意      → watch
警戒      → warning
危険      → danger
災害切迫  → danger
```

厳密な名称は既存ロジックに合わせてよい。

---

# summary 契約

`/api/live/summary` の `kikikuru` を以下のように拡張する。

## 危険なし

```json
{
  "status": "ok",
  "evaluated": true,
  "reason": "sampled_kikikuru",
  "summary": {
    "danger_detected": false,
    "watch_area_count": 0,
    "warning_area_count": 0,
    "danger_area_count": 0,
    "sample_count": 76,
    "unknown_count": 0
  },
  "areas": []
}
```

## 危険あり

```json
{
  "status": "ok",
  "evaluated": true,
  "reason": "sampled_kikikuru",
  "summary": {
    "danger_detected": true,
    "watch_area_count": 3,
    "warning_area_count": 2,
    "danger_area_count": 1,
    "sample_count": 76,
    "unknown_count": 2
  },
  "areas": [
    {
      "id": "kikikuru-kochi-shimanto-landslide-20260529-2230",
      "label": "高知県 四万十付近",
      "prefecture": "高知県",
      "area_name": "四万十付近",
      "level": "danger",
      "type": "kikikuru",
      "hazard": "landslide",
      "source": "jma_kikikuru",
      "lat": 32.9916,
      "lng": 132.9339,
      "observed_at": "2026-05-29T22:30:00+09:00",
      "description": "キキクル危険度を検出"
    }
  ]
}
```

---

# important: false-safe 防止

以下は禁止。

```json
"evaluated": false,
"danger_detected": false
```

未判定なら:

```json
"evaluated": false,
"danger_detected": null
```

取得失敗も:

```json
"status": "offline",
"evaluated": false,
"danger_detected": null
```

---

# unknown の扱い

雨雲と同じ考え方を採用する。

```text
unknown_count / sample_count >= 0.5
かつ warning/danger なし
→ evaluated=false
→ danger_detected=null
```

ただし:

```text
warning/danger が1件でもある
→ evaluated=true
→ danger_detected=true
```

理由:

```text
一部 unknown でも危険検出は表示する
```

---

# areas の上限

雨雲と同じ。

```text
areas 最大5件
```

優先順位:

```text
danger > warning
```

`watch` はカードの集計には含めてもよいが、`dangerous_areas` には入れない。

---

# dangerous_areas 統合

`live_summary_service.py` の dangerous_areas に kikikuru areas を統合する。

優先順位案:

```text
津波警報
津波注意報
M6以上地震
キキクル danger
雨雲 danger
キキクル warning
雨雲 warning
M5以上地震
```

厳密には既存設計に合わせてよいが、キキクル danger は雨雲 danger と同等以上に扱う。

---

# frontend 表示ルール

Phase 1-C の evaluated 契約を守る。

## kikikuru.evaluated=true

```text
danger_detected=true
→ キキクル危険地域あり

danger_detected=false
→ キキクル危険地域なし
```

## kikikuru.evaluated=false

```text
キキクル: 未判定
```

または reason に応じて:

```text
キキクル: 判定不能
```

## kikikuru.status=offline

```text
キキクル情報: 取得失敗
```

---

# UI

危険地域カードにキキクルを反映する。

例:

```text
現在の状況
キキクル危険地域あり

危険地域
1 高知県 四万十付近 / キキクル（土砂）
2 鹿児島県 奄美付近 / 雨雲
```

hazard 表示:

```text
土砂
浸水
洪水
```

のいずれかを出せるとよい。

---

# backend 実装候補

新規:

```text
backend/app/services/live_kikikuru_summary_service.py
tests/test_live_kikikuru_summary_service.py
```

変更:

```text
backend/app/services/live_summary_service.py
tests/test_live_summary_api.py
frontend/js/live/live-alert-panel.js
frontend/js/live/live-danger-summary.js
e2e/live-basic.spec.js
```

---

# 既存キキクル仕様の調査

必ず最初に既存キキクル関連実装を確認すること。

確認対象例:

```bash
rg -n "kikikuru|危険度|土砂|浸水|洪水" backend frontend tests
```

既存の tile URL / targetTimes / color mapping / intensity mapping があるなら再利用する。

---

# パフォーマンス制約

## TTL

```text
120秒
```

でよい。

雨雲と別キャッシュでよい。

## 並列数

```text
max_workers=8
```

程度。

## timeout

雨雲と同等または少し長め。

```text
30秒以内
```

---

# API failure

取得失敗時:

```json
{
  "status": "offline",
  "evaluated": false,
  "reason": "source_unavailable",
  "summary": {
    "danger_detected": null,
    "watch_area_count": null,
    "warning_area_count": null,
    "danger_area_count": null,
    "sample_count": 76,
    "unknown_count": 76
  },
  "areas": []
}
```

---

# pytest 追加

`tests/test_live_kikikuru_summary_service.py` を追加する。

確認項目:

* sample_count が 76
* status 契約値
* evaluated boolean
* evaluated=false 時 danger_detected=null
* danger / warning / watch のレベル変換
* watch は dangerous_areas に入らない
* danger/warning は areas に入る
* areas 最大5件
* unknown 50%以上で evaluated=false
* warning/danger ありなら unknown 多数でも evaluated=true
* source failure は offline
* false-safe しない

---

# summary API test 更新

`tests/test_live_summary_api.py` を更新。

確認:

* `/api/live/summary.kikikuru` に evaluated がある
* evaluated=false 時 danger_detected は null
* evaluated=true 時 danger_detected は boolean
* kikikuru areas が dangerous_areas に統合される
* false-safe しない

---

# E2E 追加

`e2e/live-basic.spec.js` に追加。

確認:

* kikikuru evaluated=true + danger_detected=false

  * `キキクル危険地域なし`
* kikikuru evaluated=true + danger_detected=true

  * `キキクル危険地域あり`
  * 危険地域ランキングにキキクル area 表示
* kikikuru evaluated=false

  * `キキクル危険地域なし` を表示しない
* kikikuru offline

  * `キキクル情報: 取得失敗`
* page error なし
* 既存 rain 表示が壊れない

---

# 完了条件

以下を満たすこと。

* `/api/live/summary.kikikuru.evaluated=true` を返せる
* キキクル危険地域あり / なし が evaluated に基づいて表示される
* warning/danger が危険地域ランキングに追加される
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

pytest tests/test_live_kikikuru_summary_service.py
pytest tests/test_live_rain_summary_service.py
pytest tests/test_live_summary_api.py

npx playwright test e2e/live-basic.spec.js

npx playwright test e2e/info-tab-card-ui.spec.js e2e/weather-rain-radar-card.spec.js e2e/tide-sun-moon-timeline.spec.js e2e/simulation-mode.spec.js
```

---

# 報告内容

完了後、以下を報告すること。

* 追加ファイル
* 変更ファイル
* 既存キキクル実装の調査結果
* キキクル危険度集計方式
* 対象 hazard 種別
* サンプリング地点数
* TTL / max_workers / timeout
* unknown の扱い
* areas 最大件数
* `/api/live/summary.kikikuru` のレスポンス例
* false-safe 防止仕様
* pytest 結果
* `/live` E2E 結果
* 既存ナビ代表 E2E 結果
* 禁止ファイル差分有無

```
```
