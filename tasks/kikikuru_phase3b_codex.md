# キキクル Phase 3-B CODEX向け検証指示書

## 目的

Phase 3-B で実装された「キキクルによるルート危険度のリアルタイム補正」が、安全に動作しているか検証する。

最重要:

- キキクルは判断の主役ではなく、固定ハザードへのリアルタイム補正であること
- キキクル単独で `danger` にしないこと
- 取得不可 / unknown を `safe` にしないこと
- 取得不可 / unknown を `danger` にもしないこと
- 自動 reroute に接続していないこと

---

## 検証対象

- `/api/route-risk`
- `safety_score`
- `risk_level`
- `risk_summary`
- キキクル補正 summary
- frontend の route risk 表示
- route ranking / reroute への非影響

---

## 必須検証

### 1. キキクルなしで既存挙動不変

確認:

- キキクル無効時、既存 route-risk の `safety_score` が従来通り
- `risk_level` が従来通り
- `risk_summary` が壊れない
- sampled_points 形式が壊れない

---

### 2. キキクル単独 danger 禁止

mock で確認。

#### ケースA

```text
固定ハザードなし
キキクル洪水: 危険
```

期待:

- penalty は入ってよい
- `safe -> caution` は許可
- `danger` にはしない

#### ケースB

```text
固定ハザードなし
キキクル浸水: 注意
```

期待:

- danger にはしない
- 自動 reroute しない

---

### 3. 固定ハザード + キキクルで補正強化

#### ケースC

```text
固定洪水ハザードあり
キキクル洪水: 注意
```

期待:

- キキクル補正 summary に表示
- score が控えめに低下
- 必要に応じて `safe -> caution`

#### ケースD

```text
固定洪水ハザードあり
キキクル洪水: 危険
```

期待:

- 通常より強い penalty
- 既存が caution 相当なら danger へ下がってよい
- summary に「固定ハザードと重なるため補正」など説明がある

---

### 4. penalty 上限

複数種キキクルを mock。

```text
浸水 危険
洪水 危険
土砂 危険
```

期待:

- penalty 合計が上限を超えない
- score が 0 未満にならない
- summary が過剰に長くならない

---

### 5. unknown / 取得不可

#### ケースE

```text
キキクル取得不可
```

期待:

- penalty 0
- safe 扱いしない
- danger 扱いしない
- summary に `取得不可`

#### ケースF

```text
未知の不透明 tile 色
```

期待:

- `none` にしない
- penalty 0 または unavailable 扱い
- summary に取得不可または判定不可

---

### 6. 自動 reroute 非接続

必ず確認:

- キキクル補正だけで reroute が発火しない
- navigation の reroute 判定にキキクル補正が入っていない
- route candidate がキキクルだけで破棄されない
- route ranking が極端に変わらない

---

### 7. UI確認

確認:

- ルート危険度表示に `キキクル補正` または `リアルタイム補正` が見える
- 「固定ハザードも見ている、キキクルも見ている」ことが伝わる
- キキクルだけで断定しているように見えない
- mobile で横はみ出しなし
- 取得不可時に `危険なし` と誤読しない

---

### 8. ネットワーク・パフォーマンス

確認:

- targetTimes.json 重複 fetch なし
- route-risk request が map move で暴走しない
- sampling tile request が map move で増え続けない
- 25回程度 `map.fire('move')` して request count を確認

---

## 推奨テスト

### Backend pytest

追加推奨:

- キキクルなし
- キキクル単独 caution
- キキクル単独 danger でも risk_level danger 禁止
- 固定ハザード + キキクル caution
- 固定ハザード + キキクル danger
- penalty cap
- unavailable penalty 0
- unknown penalty 0

### E2E

追加推奨:

- ルート表示中にキキクル補正 summary が出る
- 取得不可時に safe 表示しない
- キキクル単独 danger mock で UI が danger 断定しない
- reroute が発火しない
- mobile 表示

---

## 実行コマンド例

```bash
node --check frontend/js/kikikuru-layer.js
node --check frontend/js/navigation.js
node --check frontend/js/map-overlay-ui.js
node --check e2e/kikikuru-layer.spec.js
python3 -m compileall backend/app backend/main.py
git diff --check

pytest tests -q

npx playwright test e2e/kikikuru-layer.spec.js
npx playwright test e2e/weather-rain-radar-card.spec.js e2e/info-tab-card-ui.spec.js e2e/hazard-state-consistency.spec.js
```

Docker:

```bash
docker compose up -d --build
docker compose ps
curl -I http://127.0.0.1:8080
curl -s http://127.0.0.1:8000/health
```

---

## Docker 実ブラウザ確認

確認する画面:

- 通常ルート
- 固定ハザードありルート
- キキクル補正あり mock
- 取得不可 mock
- mobile 390px

スクリーンショット例:

- `tasks/screenshots/kikikuru_phase3b_adjustment_desktop.png`
- `tasks/screenshots/kikikuru_phase3b_adjustment_mobile.png`
- `tasks/screenshots/kikikuru_phase3b_unavailable.png`

---

## 判定基準

### PASS

- キキクル補正が控えめに入る
- キキクル単独で danger にならない
- 固定ハザード + キキクルで補正強化される
- unknown / 取得不可を safe にしない
- unknown / 取得不可を danger にしない
- penalty 上限あり
- 自動 reroute なし
- 既存回帰 PASS
- console error / pageerror なし

### PASS with notes

許容:

- 実 JMA データで危険色を目視できない
- mock 中心の確認
- UI文言の微調整余地

### FAIL

- キキクル単独で danger
- 取得不可を `なし` 表示
- unknown を safe 扱い
- 自動 reroute 発火
- penalty 上限なし
- route-risk 既存形式破壊
- request 暴走
