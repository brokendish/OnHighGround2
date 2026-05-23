# キキクル Phase 3-A CODEX向け検証指示書

## 目的

Phase 3-A で追加された「ルート周辺キキクル要約」が、安全に表示専用として実装されているか検証する。

最重要観点:

- ルート危険度スコアへ混入していないこと
- ルート順位・ナビ再ルートへ影響していないこと
- unknown / 取得失敗を `なし` / safe 扱いしないこと
- map move や route 更新で request が暴走しないこと

---

## 前提

Phase 2 では以下が確認済み。

- 現在地周辺要約
- 目的地周辺要約
- 目的地 clear 後の非表示
- 未知色 / tile fetch failure / targetTimes failure の safe 誤判定防止
- 代表回帰 PASS

Phase 3-A では、これに「ルート周辺要約」を追加する。

---

## 必須検証

### 1. ルート周辺要約の表示

確認:

- ルート未選択時にルート周辺要約が表示されない、または `ルート未選択` と表示される
- ルート選択後に `ルート周辺` が表示される
- 浸水 / 洪水 / 土砂 の3種が読める
- 情報タブ内に収まり、既存の現在地/目的地要約を壊さない

---

### 2. ルート変更時の更新

確認:

- 目的地変更またはルート再作成でルート周辺要約が更新される
- 古いルートの async sampling 結果が新ルートに上書き表示されない
- route clear 後に古い要約が残らない

---

### 3. 取得不可・unknown の扱い

必須:

- tile fetch failure 時に `なし` と表示しない
- unknown / 未知色を `なし` 扱いしない
- targetTimes.json 更新失敗後に古い `なし` 要約を残さない
- 一部取得不可の場合に safe 側へ倒れない

E2E で mock / route interception を使って確認すること。

---

### 4. ルート危険度スコアへの非影響

必ず確認:

- `/api/route-risk` のレスポンス形式・値にキキクル由来の項目が混入していない
- `safety_score` がキキクル要約の有無で変化しない
- `risk_level` がキキクル要約の有無で変化しない
- route ranking ラベルがキキクル要約だけで変化しない
- ナビ再ルート判定がキキクル要約だけで発火しない

これは Phase 3-A の最重要検証。

---

### 5. ネットワーク・パフォーマンス

確認:

- 3種 ON + ルート要約ありでも `targetTimes.json` が重複 fetch されない
- map move 連続で sampling tile request が増え続けない
- route 更新時のみ必要最小限の sampling request が発生する
- 25回程度 `map.fire('move')` して request count が暴走しない

---

### 6. UI / モバイル

確認:

- desktop で情報タブ表示が崩れない
- mobile viewport 390px 前後で横 overflow が増えない
- ルート周辺要約が長文で押し広げない
- 凡例・既存キキクルカード・雨量カードとの表示競合がない

---

## 推奨E2E追加

`e2e/kikikuru-layer.spec.js` に追加推奨:

1. ルート未選択時のルート周辺表示
2. ルート選択後のルート周辺要約表示
3. ルート clear 後の非表示
4. ルート変更時に古い async 結果が残らない
5. tile fetch failure 時に `なし` にならない
6. unknown color が `なし` にならない
7. map move 連続で request が暴走しない
8. ルート危険度スコアへ影響しない

---

## 代表回帰

最低限実行:

```bash
node --check frontend/js/kikikuru-layer.js
node --check frontend/js/navigation.js
node --check frontend/js/destination.js
node --check frontend/js/map-overlay-ui.js
node --check e2e/kikikuru-layer.spec.js
python3 -m compileall backend/app backend/main.py
git diff --check
npx playwright test e2e/kikikuru-layer.spec.js
npx playwright test e2e/weather-rain-radar-card.spec.js e2e/info-tab-card-ui.spec.js e2e/hazard-state-consistency.spec.js
```

可能なら route-risk 系の既存テストも実行する。

---

## Docker実ブラウザ確認

Docker 起動後、実ブラウザで確認する。

```bash
docker compose up -d --build
docker compose ps
curl -I http://127.0.0.1:8080
curl -s http://127.0.0.1:8000/health
```

確認項目:

- ルート作成前
- ルート作成後
- 目的地変更後
- ルート clear 後
- desktop screenshot
- mobile screenshot
- unavailable screenshot

スクリーンショット保存例:

- `tasks/screenshots/kikikuru_phase3a_route_summary_desktop.png`
- `tasks/screenshots/kikikuru_phase3a_route_summary_mobile.png`
- `tasks/screenshots/kikikuru_phase3a_route_summary_unavailable.png`

---

## 判定基準

### PASS

- ルート周辺要約が表示される
- ルート変更/clear に追従する
- safe 誤判定がない
- ルート危険度スコア・順位・ナビ判定に影響しない
- request 暴走なし
- E2E / 代表回帰 PASS
- console error / pageerror なし

### PASS with notes

許容 notes:

- 実 JMA データが透明 tile 中心で危険色の目視が限定的
- 実災害時でないため `危険` / `注意` の実データ確認が限定的
- 既存UI文言差分など、Phase 3-A 外の軽微な既存問題

### FAIL

- 取得失敗を `なし` と表示
- unknown を safe 扱い
- route clear 後に古い要約が残る
- route-risk / safety_score / ranking / reroute に影響
- request が map move で増え続ける
- console error / pageerror
