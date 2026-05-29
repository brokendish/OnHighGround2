# Claude用 Phase 2-C 地域ブロック代表点 受入検証指示書（CODEX向け）

# Phase 2-C 地域ブロック代表点 受入検証

## 目的

Phase 2-C で追加した「地域ブロック代表点（76地点サンプリング）」が正しく機能し、既存機能へ回帰を発生させていないことを検証する。

実装修正は禁止。

検証・レポート作成のみ実施すること。

---

# 検証対象

## 雨雲サマリ

backend/app/services/live_rain_summary_service.py

## 集約API

/api/live/summary

## live画面

/live

---

# 必須確認項目

## 1. サンプル地点数

LIVE_RAIN_SAMPLE_POINTS を確認。

期待値:

* 総数 76
* 都道府県代表点 47
* 地域ブロック代表点 29

確認項目:

* 重複座標がない
* 明らかな県外誤配置がない
* kind が存在する

期待:

```python
kind in (
    "prefecture_capital",
    "regional"
)
```

---

## 2. API契約確認

実環境で:

```bash
curl http://localhost:8000/api/live/summary
```

確認項目:

```json
rain.status
rain.evaluated
rain.reason
rain.summary.sample_count
rain.summary.unknown_count
```

期待:

sample_count == 76

---

## 3. false-safe防止確認

以下を確認。

### ケースA

warning_area_count=0
danger_area_count=0
unknown_count>=38

期待:

```json
evaluated=false
```

### ケースB

warning_area_count>0

期待:

```json
evaluated=true
```

unknown が多数あっても
warning/danger を優先すること。

---

## 4. areas件数上限

確認項目:

```json
rain.areas
```

期待:

```text
最大5件
```

超過しないこと。

---

## 5. danger優先順位

areas の並び順確認。

期待:

```text
danger
↓
warning
```

危険度順。

---

## 6. タイムアウト確認

コード確認。

期待:

```python
timeout == 30秒
```

近辺であること。

極端な値でないこと。

---

## 7. 並列数確認

期待:

```python
max_workers == 8
```

または同等。

---

## 8. TTL確認

期待:

```text
120秒
```

維持されていること。

---

# live画面確認

## 9. 通常表示

/live を開く。

確認:

* 地図表示
* JSエラーなし
* カード表示
* レイヤー切替動作

---

## 10. 雨雲正常時

期待:

```text
強雨域なし
```

または

```text
強雨域あり
```

いずれか。

表示崩れなし。

---

## 11. 危険地域ランキング

強雨 mock を用意できる場合。

期待:

```text
危険地域
1 ○○県付近
```

表示。

---

## 12. API失敗時

rain API を 503 化。

期待:

```text
雨雲情報: 取得失敗
```

表示。

さらに:

* map操作継続
* レイヤー切替継続
* page errorなし
* 未処理Promise rejectionなし

---

# 回帰確認

## 13. live E2E

実行:

```bash
npx playwright test e2e/live-basic.spec.js
```

期待:

PASS

---

## 14. backendテスト

実行:

```bash
pytest tests/test_live_rain_summary_service.py
pytest tests/test_live_summary_api.py
```

期待:

PASS

---

## 15. 既存ナビ回帰

実行:

代表E2E一式

期待:

PASS

---

# 禁止事項確認

差分確認。

以下へ変更が無いこと。

* frontend/index.html
* frontend/js/navigation.js
* frontend/js/nav-*
* frontend/js/state.js
* frontend/js/hazard-layers.js

---

# 依存関係確認

live 系コードから以下への新規依存追加が無いこと。

* navigation
* reroute
* state
* OSRM

---

# 成果物

以下を作成。

tasks/live/live_phase2c_regional_sampling_codex_verification.md

記載内容:

* 判定（PASS / PASS with notes / FAIL）
* 実施コマンド
* API確認結果
* sample_count確認結果
* areas件数確認結果
* E2E結果
* 回帰結果
* 問題点

スクリーンショット保存:

tasks/live/verification_screenshots/

* phase2c-live-normal.png
* phase2c-live-rain-warning.png
* phase2c-live-rain-offline.png
* phase2c-navigation-root.png

実装修正は禁止。
検証・レポート作成のみ実施すること。
