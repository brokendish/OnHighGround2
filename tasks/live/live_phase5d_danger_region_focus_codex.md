# Phase 5-D 危険地域フォーカス機能 検証

## 目的

Phase 5-D 実装内容を検証する。

実装修正は禁止。

調査・検証・レポート作成のみ実施すること。

---

## 検証対象

* 危険地域カード
* 地図フォーカス
* ズーム移動
* 強調表示
* ポップアップ
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

## 3. 危険地域カード確認

URL:

```text
http://127.0.0.1:8080/live
```

確認:

* 危険地域カード表示
* クリック可能
* cursor変更

---

## 4. 地図フォーカス確認

確認:

* 地域クリック
* 地図移動
* flyTo実行
* JSエラーなし

---

## 5. ズーム確認

確認:

* 対象地域へ移動
* zoom 変更
* 過度なズームアウトなし

---

## 6. 強調表示確認

確認:

* highlight表示
* pulse表示
* ring表示

いずれか確認。

---

## 7. ポップアップ確認

確認:

* 地域名
* イベント一覧

表示される。

例:

```text
高知県付近

キキクル（洪水）
雨雲
```

---

## 8. false-safe確認

確認:

* dangerous_areas変化なし
* integrated_dangerous_regions変化なし
* ランキング変化なし
* 集計変化なし

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
npx playwright test e2e/live-rain-timeline.spec.js
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
* /live専用機能の自動呼び出しなし

---

## レポート

作成先:

```text
tasks/live/live_phase5d_danger_region_focus_codex_verification.md
```

記載内容:

* 実施日時
* Docker状態
* カード確認結果
* フォーカス確認結果
* ズーム確認結果
* 強調表示確認結果
* ポップアップ確認結果
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
