# /live Phase 3-B キキクル複数種別化 実装指示書（Claude Code向け）

## 最重要

作業前に必ず以下を読むこと。

* AGENTS.md
* CLAUDE.md
* docs/live/DEVELOPMENT_GUARDRAILS.md
* frontend/js/live/README.md
* tasks/live/live_phase2c_regional_sampling_codex_verification.md
* tasks/live/live_observation_notes.md
* tests/test_live_kikikuru_summary_service.py
* tests/test_live_summary_api.py

既存ナビ本体には触らないこと。

---

# 目的

Phase 3-A ではキキクルの

```text
land（土砂災害）
```

のみを対象としていた。

Phase 3-B では以下を追加する。

```text
land        （土砂災害）
inund       （浸水害）
flood_mesh  （洪水害）
```

全国監視ビューアとして、キキクル危険度をより実態に近づける。

---

# 基本方針

Phase 3-A の契約は維持する。

以下を壊さないこと。

```text
evaluated
status
reason
areas
danger_detected
false-safe 防止
```

---

# 絶対禁止事項

以下は禁止。

* frontend/index.html の変更
* navigation.js の変更
* reroute 関連変更
* state.js 変更
* OSRM 関連変更
* 全面ラスタ解析
* タイル全走査
* 危険判定不能を危険なし扱い
* watch を dangerous_areas に入れる

---

# 対象 hazard

## 追加対象

### inund

浸水害

表示例:

```json
{
  "hazard": "inund"
}
```

---

### flood_mesh

洪水害

表示例:

```json
{
  "hazard": "flood_mesh"
}
```

---

### land

既存

```json
{
  "hazard": "land"
}
```

---

# 集計方式

Phase 2-C の 76地点サンプリングを再利用する。

```text
sample_count = 76
```

維持。

---

# 危険度レベル

内部で以下へ正規化。

```text
normal
watch
warning
danger
unknown
```

---

# 危険判定

以下のいずれかが warning 以上なら

```text
danger_detected = true
```

---

# summary 契約

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

---

## 危険あり

```json
{
  "status": "ok",
  "evaluated": true,
  "reason": "sampled_kikikuru",
  "summary": {
    "danger_detected": true,
    "watch_area_count": 2,
    "warning_area_count": 1,
    "danger_area_count": 1,
    "sample_count": 76,
    "unknown_count": 2
  },
  "areas": [
    {
      "type": "kikikuru",
      "hazard": "land",
      "level": "danger"
    },
    {
      "type": "kikikuru",
      "hazard": "inund",
      "level": "warning"
    }
  ]
}
```

---

# area オブジェクト

areas に hazard 種別を保持する。

例:

```json
{
  "hazard": "land"
}
```

```json
{
  "hazard": "inund"
}
```

```json
{
  "hazard": "flood_mesh"
}
```

---

# dangerous_areas 統合

dangerous_areas に統合する。

優先順位:

```text
津波
↓
地震
↓
キキクル danger
↓
雨雲 danger
↓
キキクル warning
↓
雨雲 warning
```

既存ロジック維持。

---

# UI

危険地域カードに hazard 名を表示する。

例:

```text
高知県 四万十付近
キキクル（土砂）
```

```text
宮崎県付近
キキクル（浸水）
```

```text
福岡県付近
キキクル（洪水）
```

---

# 表示名称

推奨:

```text
land       → 土砂
inund      → 浸水
flood_mesh → 洪水
```

---

# false-safe 防止

以下は禁止。

```json
{
  "evaluated": false,
  "danger_detected": false
}
```

未判定なら:

```json
{
  "evaluated": false,
  "danger_detected": null
}
```

---

# unknown の扱い

Phase 3-A と同じ。

```text
unknown >= 50%
かつ warning/danger なし
↓
evaluated=false
danger_detected=null
```

---

```text
warning/danger が存在
↓
evaluated=true
danger_detected=true
```

---

# areas 上限

維持。

```text
5件
```

danger 優先。

---

# キャッシュ

維持。

```text
TTL 120秒
```

---

# 並列数

維持。

```text
max_workers = 8
```

---

# timeout

維持。

```text
30秒以内
```

---

# backend

新規ファイル追加は不要。

既存

```text
backend/app/services/live_kikikuru_summary_service.py
```

を拡張する。

---

# pytest

更新対象:

```text
tests/test_live_kikikuru_summary_service.py
tests/test_live_summary_api.py
```

追加確認項目:

* land
* inund
* flood_mesh

それぞれ danger/warning/watch 判定

---

確認:

* sample_count=76
* false-safe 防止
* evaluated契約維持
* areas最大5件
* hazard種別保持
* dangerous_areas統合

---

# E2E

更新:

```text
e2e/live-basic.spec.js
```

確認:

* キキクル（土砂）
* キキクル（浸水）
* キキクル（洪水）

表示確認。

---

# 回帰確認

実行:

```bash
pytest tests/test_live_kikikuru_summary_service.py
pytest tests/test_live_rain_summary_service.py
pytest tests/test_live_summary_api.py

npx playwright test e2e/live-basic.spec.js

npx playwright test \
e2e/info-tab-card-ui.spec.js \
e2e/weather-rain-radar-card.spec.js \
e2e/tide-sun-moon-timeline.spec.js \
e2e/simulation-mode.spec.js
```

---

# 完了条件

以下を満たすこと。

* land / inund / flood_mesh 集計可能
* hazard名が保持される
* 危険地域カードに表示される
* false-safe しない
* sample_count=76
* TTL 120秒維持
* areas最大5件維持
* backend pytest PASS
* /live E2E PASS
* 既存ナビ代表 E2E PASS
* 禁止ファイル未変更
* navigation/state/reroute/OSRM依存なし

---

# 報告内容

完了後、以下を報告すること。

* 変更ファイル
* 追加対応 hazard
* 集計方式
* sample_count
* TTL / max_workers / timeout
* false-safe 防止仕様
* areas 最大件数
* summary レスポンス例
* pytest 結果
* /live E2E 結果
* 既存ナビ代表 E2E 結果
* 禁止ファイル差分有無

```
```
