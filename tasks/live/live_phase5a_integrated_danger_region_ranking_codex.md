# Phase 5-A 危険地域統合ランキング MVP 検証

## 目的

Phase 5-A の実装内容を検証する。

実装修正は禁止。

調査・検証・レポート作成のみ実施すること。

---

## 検証対象

- /live
- /api/live/summary
- dangerous_areas
- integrated_dangerous_regions
- 危険地域カード
- 回帰影響

---

## 1. 構文確認

実施:

```bash
python3 -m compileall backend/app
node --check frontend/js/live/*.js
```

確認:

- SyntaxErrorなし
- ImportErrorなし
- JS構文エラーなし

---

## 2. Docker起動確認

実施:

```bash
docker compose build
docker compose up -d
docker compose ps
```

確認:

- backend healthy
- frontend Up
- martin healthy

---

## 3. API確認

確認対象:

```text
/api/live/summary
```

確認:

- HTTP 200
- dangerous_areas が存在する
- integrated_dangerous_regions が存在する
- JSON構造が妥当

---

## 4. 統合確認

mock または実データで以下を確認する。

入力例:

```text
高知県付近 rain
高知県付近 kikikuru
沖縄県付近 rain
```

期待:

```text
高知県付近
  rain
  kikikuru

沖縄県付近
  rain
```

確認:

- 同一 label が1地域に統合される
- events 配列に複数イベントが入る
- types に複数 type が入る

---

## 5. 優先順位確認

確認:

```text
tsunami
storm_surge
earthquake
kikikuru
rain
```

の優先順位になっていること。

複数イベントを持つ地域は、最も優先度の高いイベントで並ぶこと。

---

## 6. 表示件数確認

確認:

- 地域単位で最大10件
- イベント単位10件ではない
- 10件超過時に画面が崩れない

---

## 7. UI確認

URL:

```text
http://127.0.0.1:8080/live.html
```

確認:

- 危険地域カードが表示される
- 同一地域が重複表示されない
- 地域内に複数イベントが表示される
- rain / kikikuru / tsunami / storm_surge / earthquake の表記が分かる
- スクロール表示が崩れない

---

## 8. フォールバック確認

確認:

- integrated_dangerous_regions がない場合、既存 dangerous_areas 表示へフォールバックする
- JSエラーなし
- page errorなし

---

## 9. false-safe確認

確認:

- unknown が danger 扱いされない
- unavailable が danger 扱いされない
- threshold未満の雨雲が表示されない
- tide / sun_moon が dangerous region に入らない

---

## 10. Console確認

確認:

- console errorなし
- page errorなし

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
```

追加E2Eがある場合は実施する。

---

## 12. ナビ本体影響確認

URL:

```text
http://127.0.0.1:8080/
```

確認:

- 正常表示
- console errorなし
- page errorなし
- /live 用APIの不要な自動呼び出しなし

---

## レポート

作成先:

```text
tasks/live/live_phase5a_integrated_danger_region_ranking_codex_verification.md
```

記載内容:

- 実施日時
- Docker状態
- API確認結果
- 統合確認結果
- 優先順位確認結果
- 表示件数確認結果
- UI確認結果
- フォールバック確認結果
- false-safe確認結果
- Console確認結果
- 回帰確認結果
- ナビ本体影響確認
- スクリーンショット
- 最終判定

判定:

```text
PASS
PASS with notes
FAIL
```

のいずれかを明記すること。