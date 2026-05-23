# キキクル Phase 2 検証指示書

## 目的

Phase2 の

- 現在地危険度要約
- 目的地危険度要約

が安全に実装されているか検証する。

---

# 必須確認

## 1. 現在地要約

確認:

- 情報タブへ表示
- 浸水/洪水/土砂反映
- loading → 正常遷移
- unavailable 表示

---

## 2. 目的地要約

確認:

- 目的地設定時のみ表示
- 目的地変更で更新
- destination clear で消える

---

## 3. safe 誤判定禁止

最重要:

取得失敗:
- safe 表示しない

unknown:
- none 扱いしない

---

## 4. ネットワーク

確認:

- targetTimes.json 重複 fetch なし
- Tile request 暴走なし

---

## 5. パフォーマンス

確認:

- map move 連続で request flood しない
- mobile browser で破綻なし

---

## 6. 回帰

実施:

- weather-rain-radar-card
- info-tab-card-ui
- hazard-state-consistency
- kikikuru-layer

---

## 7. Docker確認

実ブラウザで:

- current location summary
- destination summary
- unavailable state
- mobile width

確認。

---

# 判定条件

PASS 条件:

- safe 誤判定なし
- console error なし
- pageerror なし
- E2E PASS
- 回帰 PASS

notes:

- 実データが透明 tile 中心
- 危険色目視が限定的

は notes 可。