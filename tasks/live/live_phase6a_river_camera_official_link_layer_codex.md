# Phase 6-A 河川ライブカメラ公式リンクレイヤー MVP 検証

## 目的

Phase 6-A 実装内容を検証する。

実装修正は禁止。

調査・検証・レポート作成のみ実施すること。

---

## 検証対象

* 河川ライブカメラレイヤー
* マーカー
* ポップアップ
* 外部リンク
* レイヤー切替
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

## 3. データ確認

確認:

* river_cameras.json 読み込み成功
* 件数確認
* lat/lng存在
* name存在
* url存在

---

## 4. レイヤー確認

URL:

```text
http://127.0.0.1:8080/live
```

確認:

* 河川ライブカメラレイヤー表示
* ON/OFF可能

---

## 5. マーカー確認

確認:

* マーカー表示
* 重複なし
* JSエラーなし

---

## 6. ポップアップ確認

確認:

* カメラ名
* 河川名
* 管理者
* 公式リンク

表示されること。

---

## 7. リンク確認

確認:

* target="_blank"
* noopener
* noreferrer

設定あり。

リンク押下で公式ページへ遷移できる。

---

## 8. エラー耐性確認

確認:

* URL欠損
* JSON欠損
* 空データ

で画面が壊れない。

JS errorなし。

---

## 9. false-safe確認

確認:

* dangerous_areas変化なし
* integrated_dangerous_regions変化なし
* 危険度集計変化なし

---

## 10. Console確認

確認:

* console errorなし
* page errorなし

---

## 11. 回帰確認

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
npx playwright test e2e/live-danger-focus.spec.js
```

追加E2Eがあれば実施する。

---

## 12. ナビ本体影響確認

URL:

```text
http://127.0.0.1:8080/
```

確認:

* 正常表示
* console errorなし
* page errorなし
* /live専用API自動呼び出しなし

---

## レポート

作成先:

```text
tasks/live/live_phase6a_river_camera_official_link_layer_codex_verification.md
```

記載内容:

* 実施日時
* Docker状態
* データ確認結果
* レイヤー確認結果
* マーカー確認結果
* ポップアップ確認結果
* リンク確認結果
* エラー耐性確認結果
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
