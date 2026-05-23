# キキクル Phase 3-A Claude Code向け実装指示書

## 目的

キキクル Phase 2 で実装済みの「現在地周辺」「目的地周辺」の危険度要約に続き、Phase 3-A では「ルート周辺キキクル要約」を追加する。

重要: Phase 3-A では、ルート危険度スコア、ルート順位、ナビ中の再ルート判定には一切反映しない。

目的は、選択中ルートの周辺にリアルタイム危険度が存在するかを情報タブへ表示し、Phase 3-B のスコア連携前に安全な観測・表示レイヤーとして固めること。

---

## 前提

既存実装:

- `frontend/js/kikikuru-layer.js`
  - 浸水 `inund`
  - 洪水 `flood_mesh`
  - 土砂 `land`
  - targetTimes.json 共有 Promise
  - 現在地周辺要約
  - 目的地周辺要約
  - unknown / 取得失敗を safe / none 扱いしない防御
  - async sampling version 管理

既存検証:

- Phase 2 は PASS with notes
- 実データで危険色が取れない場合があるため、透明 tile 中心の確認は notes 可

---

## 実装対象

### 1. ルート周辺キキクル要約を情報タブへ追加

情報タブのキキクルカード内に、選択中ルートがある場合のみ「ルート周辺」を表示する。

表示例:

```text
ルート周辺
浸水: なし　洪水: なし　土砂: なし
```

危険がある場合:

```text
ルート周辺
洪水: 注意あり
浸水: なし
土砂: なし
```

取得失敗時:

```text
ルート周辺
取得不可
```

---

### 2. 選択中ルートの周辺サンプリング

選択中ルートの geometry を使って、ルート上の代表点をサンプリングする。

推奨:

- 最大サンプル数: 12点程度
- 間隔目安: 150〜300m
- 現在地から先のルートが判定できる場合は前方優先
- 判定できない場合はルート全体を均等サンプリング

注意:

- route polyline 全点をそのまま判定しない
- map move ごとに再サンプリングしない
- ナビ進行中の current_segment_index 等が存在する場合も、Phase 3-A では表示要約にだけ使う

---

### 3. 危険度集約ルール

種類ごとに、サンプル点の最大危険度を採用する。

対象:

- 浸水
- 洪水
- 土砂

判定優先度:

```text
取得不可 > 危険 > 注意 > なし
```

ただし、1点だけ取得不可で他が危険のような場合は、UI表示で「一部取得不可」を表現してもよい。

最低限必要な状態:

- なし
- 注意
- 危険
- 取得不可
- 確認中
- ルート未選択

unknown / 未知色 / tile fetch failure は絶対に `なし` に倒さない。

---

### 4. UI仕様

情報タブの既存キキクルカードに追加する。

既存:

- 現在地周辺
- 目的地周辺

追加:

- ルート周辺

目的地未設定でも、ルートが存在すればルート周辺は表示してよい。

ルート未選択時は非表示、または控えめに以下を表示する。

```text
ルート周辺: ルート未選択
```

どちらでもよいが、情報タブが騒がしくならない方を優先。

---

### 5. 更新トリガー

ルート作成・変更・クリア時に更新する。

候補:

- route selected
- route displayed
- navigation route set
- route clear
- reroute result accepted

既存コードの責務に合わせて、最小変更で接続すること。

禁止:

- map move ごとの再判定
- tile layer ON/OFF ごとの過剰再判定
- setInterval での常時再判定

---

### 6. stale / async 防御

Phase2 の version 管理をルート要約にも適用する。

必須:

- route clear 後に古い async 結果が表示を上書きしない
- targetTimes 更新失敗後に古い `なし` を残さない
- destination clear と route clear を混同しない
- ルート変更前の結果が新ルートに表示されない

---

### 7. 既存ルート危険度への影響禁止

Phase 3-A では絶対に変更しない:

- route-risk API
- safety_score
- risk_level
- route ranking
- navigation reroute
- 推奨/注意/最短/安全優先ラベル
- hazard segment visualization

このフェーズは「表示だけ」。

---

### 8. デバッグ

debug 有効時のみ以下を出してよい。

- route sample count
- sampled lat/lng
- kind別集約結果
- unavailable reason

通常時に console を汚さない。

---

## 実装候補ファイル

主に確認・変更する可能性があるファイル:

- `frontend/js/kikikuru-layer.js`
- `frontend/js/navigation.js`
- `frontend/js/destination.js`
- `frontend/js/map-overlay-ui.js`
- `frontend/index.html`
- `e2e/kikikuru-layer.spec.js`

ただし、実際の既存構造に合わせて最小変更にすること。

---

## 完了条件

- 選択中ルートがある場合、情報タブにルート周辺キキクル要約が表示される
- 浸水・洪水・土砂の3種が要約される
- ルート変更で要約が更新される
- ルート clear で要約が非表示または未選択表示になる
- unknown / 取得失敗を `なし` 扱いしない
- targetTimes.json 重複 fetch が増えない
- map move 連打で request が暴走しない
- モバイル幅で横はみ出ししない
- ルート危険度スコア、順位、ナビ判定に影響しない
- 既存 E2E が PASS
