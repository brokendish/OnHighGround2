# キキクル Phase 3-B Claude Code向け実装指示書

## 目的

キキクル Phase 3-B では、Phase 3-A の「ルート周辺キキクル要約」を、ルート危険度評価へ控えめに反映する。

キキクルは判断の主役ではなく、固定ハザードへのリアルタイム補正として扱う。

最重要方針:

- キキクル単独で `danger` にしない
- キキクル単独で自動 reroute しない
- 固定ハザード、地形、低地、既存 route-risk を主判定とする
- キキクルは補助 penalty / summary として扱う
- unknown / 取得不可を safe 扱いしない
- unknown / 取得不可を danger 扱いもしない

---

## 前提

既存:

- Phase 1: 浸水・洪水・土砂キキクル TileLayer 表示
- Phase 2: 現在地・目的地周辺の要約
- Phase 3-A: ルート周辺要約
- Phase 3-A では `/api/route-risk`、`safety_score`、`risk_level`、route ranking、reroute へ非影響であることを確認済み

Phase 3-B では、初めて route-risk 系へキキクル補正を入れる。

---

## 実装方針

### 1. キキクルは「リアルタイム補正」

固定ハザードを主判定とする。

対象例:

- 洪水浸水想定
- 内水浸水
- 土砂災害
- 低地・排水困難エリア
- その他既存 hazard

キキクルは以下のリアルタイム補正として扱う。

- 浸水
- 洪水
- 土砂

---

### 2. キキクル単独 danger 禁止

禁止:

```text
固定ハザードなし + キキクル危険 = danger
固定ハザードなし + キキクル注意 = danger
```

キキクル単独では最大でも `caution` 方向の補正までに留める。

---

### 3. 固定ハザードとの重なりで補正強化

以下の場合は penalty を強めてよい。

```text
固定洪水ハザード + 洪水キキクル注意/危険
低地・排水困難 + 浸水キキクル注意/危険
土砂ハザード + 土砂キキクル注意/危険
```

この場合は `risk_level` を `safe -> caution`、または既存 `caution -> danger` へ押し下げることを許可する。

ただし、固定 hazard とキキクルの重なり根拠が明確な場合のみ。

---

## penalty 案

### キキクル単独

```text
浸水 注意: -3
浸水 危険: -6

洪水 注意: -4
洪水 危険: -8

土砂 注意: -4
土砂 危険: -8
```

### 固定ハザードと重なる場合

```text
浸水 注意: -6
浸水 危険: -12

洪水 注意: -8
洪水 危険: -16

土砂 注意: -8
土砂 危険: -16
```

### 上限

```text
通常上限: -20
固定ハザード重なりあり: -30
```

必ず penalty cap を設けること。

---

## risk_level 方針

既存しきい値がある場合は既存を優先する。

追加ルール:

- キキクル単独では `danger` にしない
- キキクル単独で `safe -> caution` は許可
- 固定ハザード + キキクル危険なら `caution -> danger` は許可
- unknown / 取得不可では risk_level を下げない
- unknown / 取得不可では summary に注意喚起だけ出す

---

## route-risk API への追加

`/api/route-risk` のレスポンスに、キキクル補正情報を追加する。

例:

```json
{
  "kikikuru_adjustment": {
    "enabled": true,
    "status": "normal",
    "penalty": -8,
    "max_level": "caution",
    "matched_hazards": ["flood"],
    "summary": [
      "洪水キキクル注意を検出",
      "固定洪水ハザードと重なるため補正"
    ]
  }
}
```

既存互換を壊さないこと。

必須維持:

- `safety_score`
- `risk_level`
- `risk_summary`
- `sampled_points`

---

## sampled_points への追加

可能であれば、各 sampled point にキキクル判定を追加する。

```json
{
  "lat": 35.0,
  "lng": 139.0,
  "hazards": [],
  "kikikuru": {
    "inund": "none",
    "flood": "caution",
    "land": "none"
  }
}
```

フロント既存描画が壊れる場合は top-level summary のみでもよい。

---

## フロント表示

情報タブまたはルート危険度表示へ、キキクル補正を明示する。

例:

```text
リアルタイム補正: 洪水注意 -8
固定洪水ハザードと重なっています
```

重要:

- ユーザーに「固定ハザードも見ている、キキクルも見ている」と伝わること
- キキクルだけで断定しているように見せないこと

---

## 取得不可・unknown

必須:

- `取得不可` は safe にしない
- `取得不可` は danger にもしない
- `取得不可` は penalty 0
- summary に `キキクル取得不可` を出す
- 古い `なし` を残さない

---

## 自動 reroute 禁止

Phase 3-B では禁止:

- キキクル補正だけで自動 reroute
- キキクル補正だけで route candidate を破棄
- キキクル補正だけでナビ中の強制変更
- route label を過剰に変える

許可:

- safety_score への控えめな penalty
- risk_summary への説明追加
- route list / info panel への補正表示

---

## 実装候補

確認・変更候補:

- `backend/app/api/route_risk.py`
- `backend/app/services/route_risk_service.py`
- `frontend/js/kikikuru-layer.js`
- `frontend/js/navigation.js`
- `frontend/js/map-overlay-ui.js`
- `frontend/index.html`
- `e2e/kikikuru-layer.spec.js`
- route-risk 系 pytest / E2E

実際の構造に合わせて最小変更にすること。

---

## 実装上の注意

キキクル tile sampling がフロント完結の場合、backend route-risk へ直接反映するには設計が必要。

選択肢:

### A. フロント側補正

- backend の `safety_score` はそのまま
- frontend でキキクル penalty を加味した表示用 score を作る
- Phase 3-B 初期として安全

### B. backend へキキクル判定を渡す

- frontend が route sampling 結果を backend route-risk request に含める
- backend で penalty 計算
- API とテストの責務が明確

推奨は B。大きくなる場合は A で表示補正から始めてもよい。

ただし、表示 score と backend score の混乱を避けること。

---

## 完了条件

- キキクル補正が route risk summary に表示される
- キキクル penalty が控えめに score へ反映される
- キキクル単独で danger にならない
- 固定ハザード + キキクル危険でのみ強めの補正が入る
- unknown / 取得不可を safe 扱いしない
- unknown / 取得不可を danger 扱いしない
- penalty 上限がある
- 自動 reroute しない
- route ranking を過剰に変えない
- 既存 E2E / pytest が PASS
- mobile 表示が崩れない
