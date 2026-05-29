````md
# /live Phase 2-D 雨雲面スキャン方式 MVP 実装指示書（Claude Code向け）

## 最重要

作業前に必ず以下を読むこと。

- AGENTS.md
- CLAUDE.md
- docs/live/DEVELOPMENT_GUARDRAILS.md
- frontend/js/live/README.md
- tasks/live/live_observation_notes.md
- tasks/live/live_phase2a_rain_summary_codex_verification.md
- tasks/live/live_phase2b_rain_sampling_codex_verification.md
- tasks/live/live_phase2c_regional_sampling_codex_verification.md
- tests/test_live_rain_summary_service.py
- tests/test_live_summary_api.py

既存ナビ本体には触らないこと。

---

# 背景

Phase 2-A/B/C では、雨雲危険度集計を地点サンプリング方式で実装した。

```text
Phase 2-A: 11地点
Phase 2-B: 47都道府県代表点
Phase 2-C: 76地域代表点
````

この方式により、`/api/live/summary.rain` の契約、false-safe 防止、危険地域カード、E2E は整備できた。

しかし観察の結果、千葉県沿岸のような帯状・局地的な強雨が、サンプリング地点に当たらず `強雨域なし` になる可能性が確認された。

そのため Phase 2-D では、地点サンプリングから雨雲面スキャン方式へ移行する。

---

# 目的

雨雲タイルそのものを軽量にスキャンし、地点サンプリングに依存せず strong / severe の領域を検出する。

目的:

```text
雨雲の「点」ではなく「面」を見る
```

ただし、MVP では高精度解析や全ピクセル解析は行わない。

---

# 絶対に守ること

以下は禁止。

* frontend/index.html を変更する
* frontend/js/navigation.js を変更する
* frontend/js/state.js に依存追加する
* frontend/js/hazard-layers.js を変更する
* nav / reroute / OSRM に触る
* frontend 側でラスタ解析する
* 全国全タイル・全ピクセル解析をする
* JMA へ過剰アクセスする
* 解析失敗を `強雨域なし` と表示する
* unknown / failure を `strong_rain_detected=false` にする
* false-safe 契約を壊す
* UI を大きく作り直す

---

# 基本方針

雨雲面スキャンは backend 側で実装する。

既存の `/api/live/summary.rain` 契約は維持する。

frontend はこれまで通り summary を表示するだけにする。

---

# 実装対象

主な変更対象:

```text
backend/app/services/live_rain_summary_service.py
tests/test_live_rain_summary_service.py
tests/test_live_summary_api.py
e2e/live-basic.spec.js
```

必要に応じて新規ファイル可:

```text
backend/app/services/live_rain_tile_scan_service.py
```

frontend は原則変更不要。

既存表示:

```text
強雨域あり
強雨域なし
雨雲情報: 取得失敗
雨雲: 判定不能
```

がそのまま使えるようにする。

---

# Phase 2-D での方針転換

## 旧方式

```text
76地点サンプリング
```

## 新方式

```text
雨雲タイル面スキャン
```

ただし、既存の地点サンプリングコードを完全削除する必要はない。

推奨:

```text
面スキャンを主方式
地点サンプリングは fallback またはテスト資産として残す
```

---

# スキャン対象範囲

MVP では全国全域を対象にしつつ、低ズーム・タイル数制限で軽くする。

推奨:

```text
zoom = 6
```

または既存 JMA nowcast 仕様に合う最小現実ズーム。

対象範囲:

```text
日本周辺 bbox
```

目安:

```text
lat: 24.0 〜 46.5
lng: 122.0 〜 146.5
```

これは南西諸島〜北海道までを含む。

---

# タイル数制限

必ず最大タイル数を設ける。

例:

```text
MAX_SCAN_TILES = 64
```

または実際の zoom / bbox で必要なタイル数を計算し、過剰なら FAIL-safe にする。

過剰な場合:

```text
evaluated=false
reason=too_many_tiles
strong_rain_detected=null
```

---

# ピクセル間引き

全ピクセル走査は禁止。

必ず間引きする。

例:

```text
PIXEL_STRIDE = 4
```

または:

```text
8
```

MVPでは stride 4〜8 程度でよい。

---

# 色判定

既存の JMA nowcast 色判定・降水強度判定を再利用する。

確認対象:

```text
backend/app/services/jma_rain_tile_service.py
backend/app/services/*rain*
tests/*rain*
```

既存の:

```text
none / weak / moderate / strong / severe / unknown
```

分類を使うこと。

新規で別色テーブルを作らない。

---

# 検出対象

Phase 2-D では以下を検出する。

```text
strong
severe
```

判定:

```text
strong → warning
severe → danger
```

moderate は以下。

```text
watch 集計のみ
dangerous_areas には入れない
```

---

# クラスタリング MVP

高精度なポリゴン化は不要。

以下程度でよい。

## 方法A: タイル単位クラスタ

各タイル内で strong / severe ピクセルが一定数以上あれば、そのタイルを1つの area とする。

例:

```text
strong_or_severe_pixel_count >= threshold
```

area の lat/lng は該当ピクセルの重心またはタイル中心。

## 方法B: 簡易グリッドクラスタ

検出ピクセルを粗いグリッドに丸めて集計する。

例:

```text
0.25度グリッド
```

Phase 2-D では方法Aでよい。

---

# area 生成

area は最大5件。

```json
{
  "id": "rain-scan-20260529-001",
  "label": "千葉県付近",
  "prefecture": "千葉県",
  "area_name": "千葉県付近",
  "level": "warning",
  "type": "rain",
  "source": "jma_nowcast_scan",
  "lat": 35.4,
  "lng": 140.0,
  "observed_at": "2026-05-29T21:10:00+09:00",
  "description": "雨雲面スキャンで強雨域を検出"
}
```

---

# prefecture / label 推定

MVPでは厳密な行政界判定は不要。

以下のいずれかでよい。

## 推奨

既存の都道府県代表点との最近傍で推定する。

```text
検出重心
↓
最寄り代表点
↓
prefecture / label
```

## 代替

都道府県不明:

```text
日本周辺
```

ただし可能なら最近傍推定を入れる。

---

# summary 契約

既存 `/api/live/summary.rain` 契約を維持する。

## 強雨あり

```json
{
  "status": "ok",
  "evaluated": true,
  "reason": "tile_scan",
  "summary": {
    "strong_rain_detected": true,
    "warning_area_count": 2,
    "danger_area_count": 1,
    "sample_count": null,
    "unknown_count": 0,
    "scan_tile_count": 36,
    "scan_pixel_stride": 4
  },
  "areas": []
}
```

## 強雨なし

```json
{
  "status": "ok",
  "evaluated": true,
  "reason": "tile_scan",
  "summary": {
    "strong_rain_detected": false,
    "warning_area_count": 0,
    "danger_area_count": 0,
    "sample_count": null,
    "unknown_count": 0,
    "scan_tile_count": 36,
    "scan_pixel_stride": 4
  },
  "areas": []
}
```

## 判定不能

```json
{
  "status": "unknown",
  "evaluated": false,
  "reason": "too_many_tiles",
  "summary": {
    "strong_rain_detected": null,
    "warning_area_count": null,
    "danger_area_count": null,
    "sample_count": null,
    "unknown_count": null,
    "scan_tile_count": null,
    "scan_pixel_stride": 4
  },
  "areas": []
}
```

---

# sample_count について

地点サンプリングではなくなるため、`sample_count=76` にこだわらない。

推奨:

```json
"sample_count": null
```

または後方互換が必要なら:

```json
"sample_count": 0
```

ただし tests を契約に合わせて更新すること。

新規項目:

```json
"scan_tile_count": 36
"scan_pixel_stride": 4
```

を追加する。

---

# false-safe 防止

以下を守る。

## OK

```json
"evaluated": true,
"strong_rain_detected": false
```

これはスキャン完了し、strong/severe が無かった場合のみ。

## NG

```json
"evaluated": false,
"strong_rain_detected": false
```

判定不能なら必ず null。

---

# fallback 方針

タイル面スキャンが失敗した場合、地点サンプリング fallback を使うかどうかは実装判断でよい。

ただし、fallback を使う場合は reason を明示する。

例:

```text
tile_scan_failed_fallback_sampled_nowcast
```

fallback でも判定不能なら:

```text
evaluated=false
strong_rain_detected=null
```

---

# キャッシュ

TTL は維持。

```text
120秒
```

ただし、タイルスキャン結果もキャッシュする。

---

# 並列数

タイル取得も制限する。

```text
max_workers = 8
```

---

# timeout

全体 timeout を設定する。

目安:

```text
30秒以内
```

---

# areas 統合

`live_summary_service.py` の dangerous_areas へ rain areas を統合する。

既存と同じ。

```text
warning / danger のみ
最大5件
```

---

# backend test 更新

`tests/test_live_rain_summary_service.py` を更新する。

追加確認:

* tile_scan reason が返る
* scan_tile_count が返る
* scan_pixel_stride が返る
* strong pixel で warning area が返る
* severe pixel で danger area が返る
* strong/severe なしで strong_rain_detected=false
* too_many_tiles で evaluated=false
* tile fetch failure で evaluated=false または fallback reason
* evaluated=false 時 strong_rain_detected=null
* areas 最大5件
* dangerous_areas へ warning/danger のみ統合
* frontend 契約に合う

---

# summary API test 更新

`tests/test_live_summary_api.py` を更新。

確認:

* `/api/live/summary.rain.reason` が `tile_scan` または fallback reason
* `sample_count` への固定期待を外す
* evaluated=true 時 strong_rain_detected は boolean
* evaluated=false 時 strong_rain_detected は null
* scan metadata が含まれる

---

# E2E 更新

`e2e/live-basic.spec.js` を必要に応じて更新。

確認:

* rain tile_scan evaluated=true + no strong

  * `強雨域なし`
* rain tile_scan evaluated=true + strong

  * `強雨域あり`
  * 危険地域ランキングに rain area
* rain evaluated=false

  * `強雨域なし` を表示しない
* rain offline / unknown

  * 非断定表示
* page error なし

---

# 観察メモ更新

今回の判断理由を記録する。

`tasks/live/live_observation_notes.md` に追記:

```text
2026-05-29 千葉県沿岸の強雨取り逃し
地点サンプリング方式の限界を確認
Phase 2-D で雨雲面スキャン方式へ移行
```

---

# 完了条件

以下を満たすこと。

* 雨雲サマリーの主方式が tile scan になる
* 地点サンプリングに当たらない強雨も拾える構造になる
* false-safe 防止を維持
* areas 最大5件維持
* scan metadata が summary に入る
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

pytest tests/test_live_rain_summary_service.py
pytest tests/test_live_summary_api.py
pytest tests/test_live_kikikuru_summary_service.py

npx playwright test e2e/live-basic.spec.js

npx playwright test \
e2e/info-tab-card-ui.spec.js \
e2e/weather-rain-radar-card.spec.js \
e2e/tide-sun-moon-timeline.spec.js \
e2e/simulation-mode.spec.js
```

---

# 報告内容

完了後、以下を報告すること。

* 変更ファイル
* tile scan 対象 zoom / bbox / tile count
* pixel stride
* cluster / area 生成方式
* fallback 有無
* `/api/live/summary.rain` レスポンス例
* false-safe 防止仕様
* 観察メモ追記内容
* pytest 結果
* `/live` E2E 結果
* 既存ナビ代表 E2E 結果
* 禁止ファイル差分有無

```
```
