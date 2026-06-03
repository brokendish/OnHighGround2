# Phase 5-B 雨雲予測タイムライン MVP 検証

## 目的

Phase 5-B 実装内容を検証する。

実装修正は禁止。

調査・検証・レポート作成のみ実施すること。

---

## 検証対象

* 雨雲予測タイムライン
* スライダー
* 再生機能
* 停止機能
* タイル更新
* 回帰影響

---

## 1. 構文確認

実施:

```bash
python3 -m compileall backend/app
node --check frontend/js/live/*.js
```

確認:

* SyntaxErrorなし
* ImportErrorなし
* JS構文エラーなし

---

## 2. Docker起動確認

実施:

```bash
docker compose build
docker compose up -d
docker compose ps
```

確認:

* backend healthy
* frontend Up
* martin healthy

---

## 3. タイムライン確認

URL:

```text
http://127.0.0.1:8080/live
```

確認:

* タイムライン表示
* スライダー表示
* 現在時刻表示
* 予測時刻表示

---

## 4. フレーム確認

確認:

```text
現在
+5
+10
+15
+20
+25
+30
+35
+40
+45
+50
+55
+60
```

13ステップ存在すること。

---

## 5. スライダー確認

確認:

* 手動移動可能
* 各時刻へ移動可能
* タイル更新される
* JSエラーなし

---

## 6. 再生確認

確認:

* 再生開始
* フレーム進行
* +60到達
* 停止可能

---

## 7. タイル更新確認

確認:

* 現在と予測でタイルURLが変化する
* 表示更新される
* Console Errorなし

---

## 8. false-safe確認

確認:

* dangerous_areas変化なし
* integrated_dangerous_regions変化なし
* キキクル変化なし
* 地震変化なし

---

## 9. Console確認

確認:

* console errorなし
* page errorなし

---

## 10. 回帰確認

実施:

```bash
git diff --check

npx playwright test e2e/live-basic.spec.js
npx playwright test e2e/live-earthquake-layer.spec.js
npx playwright test e2e/live-sun-moon-card.spec.js
npx playwright test e2e/live-tide-layer.spec.js
npx playwright test e2e/live-storm-surge.spec.js
npx playwright test e2e/live-integrated-regions.spec.js
```

追加E2Eがあれば実施する。

---

## 11. ナビ本体影響確認

URL:

```text
http://127.0.0.1:8080/
```

確認:

* 正常表示
* console errorなし
* page errorなし
* 雨雲タイムラインAPI自動呼び出しなし

---

## レポート

作成先:

```text
tasks/live/live_phase5b_rain_forecast_timeline_codex_verification.md
```

記載内容:

* 実施日時
* Docker状態
* タイムライン確認結果
* スライダー確認結果
* 再生確認結果
* タイル更新確認結果
* false-safe確認結果
* Console確認結果
* 回帰確認結果
* ナビ本体影響確認
* スクリーンショット
* 最終判定

判定:

```text
PASS
PASS with notes
FAIL
```

のいずれかを明記すること。

```
```
