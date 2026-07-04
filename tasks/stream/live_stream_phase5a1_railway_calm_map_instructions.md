# /live/stream Stream Phase 5-A.1 指示書
## 鉄道小画面 平常時路線図表示範囲修正

---

# Claude用実装指示書

## 目的

`/live/stream` の右上「鉄道情報」小画面について、障害・運行影響が発生していない平常時でも、首都圏のODPT対応路線が収まる範囲で路線図を表示するように修正してください。

Phase 5-A bundle では、以下は完了済みです。

- 地震情報 子画面 本番地図化・詳細表示同期
- 鉄道情報 子画面 詳細化
- メイン地図 鉄道路線カラー反映

ただし、現状では以下の仕様が未達です。

> 障害が発生していないときは、鉄道小画面の地図が「首都圏の路線が収まる範囲で路線図を表示」する。

この対応を完了してから、次工程の Phase 5-B: OBS soak / 長時間安定性確認 に進みます。

---

## 1. 対象範囲

今回の対象は `/live/stream` の鉄道情報小画面のみです。

対象:

- `/live/stream` 鉄道情報小画面
- 平常時の路線図表示
- 首都圏ODPT対応路線の表示範囲
- 影響あり / 影響なし / API失敗時の表示分岐
- ODPT対応路線のみ表示の明記

対象外:

- メイン地図の鉄道路線PMTiles再設計
- 地震小画面
- キキクル・豪雨小画面
- 潮位小画面
- OBS soak
- 新規鉄道データソース追加
- ODPT期間限定路線対応
- 鉄道小画面の完全デフォルメ路線図生成
- 駅名ラベル表示

---

## 2. 重要方針

鉄道情報は、引き続き ODPT の恒常的・安定取得できる対応路線のみを対象にしてください。

- ODPT対応路線のみ
- 期間限定ODPT路線は対象外
- 小田急・京王・東急など、期間限定/別枠公開の私鉄には追随しない
- 全国鉄道完全監視を目指さない

鉄道小画面には、以下の趣旨の文言を明記してください。

- `ODPT対応路線のみ`

または、既存UIに馴染む場合は以下でも構いません。

- `ODPT対応路線`

「全国鉄道」「首都圏全路線」など、対象範囲を誤解させる表現は避けてください。

---

## 3. 平常時も路線図を表示する

現在、影響路線が0件または平常時に、鉄道小画面の右側地図が以下の状態になることがあります。

- 路線図が空に見える
- 背景だけになる
- 「影響路線なし」の文字だけになる
- 首都圏路線が収まる範囲にならない

これを修正してください。

期待する平常時表示:

左側:

- 影響路線なし
- 平常運転

右側:

- 首都圏のODPT対応路線図
- 平常路線は細線・低輝度
- 影響路線の強調はなし

重要なのは、以下の2つを分離することです。

- 路線図を表示するかどうか
- 影響路線を強調するかどうか

つまり、影響路線が0件でも railway map / railway layer は初期化し、route layer を表示してください。

---

## 4. 平常時の表示範囲

平常時は、対象路線から毎回 bounds を算出するより、まずは固定 bounds で安定表示してください。

候補:

```js
const STREAM_RAILWAY_DEFAULT_BOUNDS = [
  [35.50, 139.45],
  [35.90, 140.05]
];
```

目的:

- 東京メトロ・都営地下鉄など、首都圏ODPT対応路線が小画面内に収まる
- 地図が全国や海だけに飛ばない
- 影響0件でも安定した見た目になる

実際の画面に合わせて bounds は微調整して構いません。

この小画面では、地理的な完全性よりも「路線図として見えること」を優先してください。

---

## 5. 状態別表示仕様

### A. 影響あり

既存 Phase 5-A の仕様を維持してください。

左側:

- 影響路線カード
- 路線名
- 状態
- 事業者
- 更新時刻
- 詳細本文
- 出典

右側:

- ODPT対応路線図
- 影響路線を太線・高輝度で強調
- 平常路線は細線・低輝度

既存の鉄道詳細 overlay、detail hold、auto-scroll を壊さないでください。

### B. 影響なし / 平常時

今回の主対象です。

左側:

- 影響路線なし
- 平常運転

右側:

- 首都圏ODPT対応路線図を表示
- 全路線を細線・低輝度表示
- 影響路線強調なし

ヘッダーは既存仕様に合わせつつ、影響件数として扱う場合は以下にしてください。

- `鉄道 0`

### C. 取得失敗

API失敗時は、平常と断定しないでください。

左側:

- 鉄道情報を取得できません
- または
- 一時的に取得不可

右側:

- 可能なら路線図背景は維持
- ただし影響路線強調はしない

禁止:

- 取得失敗なのに「影響路線なし」
- 取得失敗なのに「平常運転」
- 取得失敗なのに「鉄道 0」と断定

取得失敗と影響0件は明確に分けてください。

---

## 6. railway layer 初期化条件の見直し

現状で railway layer が影響路線ありの場合だけ初期化されている場合は、修正してください。

期待:

railway layer 初期化:

- 鉄道小画面の初期化時に行う

affected lines:

- layer初期化条件にはしない
- 強調対象としてのみ使う

つまり、`affectedCount === 0` でも、鉄道路線図は表示される必要があります。

---

## 7. 平常路線の描画スタイル

平常時のODPT対応路線は、見えるが主張しすぎない表示にしてください。

平常路線の例:

- stroke: routeColor または muted routeColor
- width: 1.0〜1.5
- opacity: 0.35〜0.55

影響あり路線の例:

- stroke: routeColor
- width: 3.0〜4.0
- opacity: 0.9〜1.0
- glow / outline ありでも可

注意:

- 平常路線を完全に非表示にしない
- 平常路線を暗くしすぎて見えなくしない
- 影響あり路線の色を別色へ置換しない
- 路線色は既存 route color table を尊重する

---

## 8. 「ODPT対応路線のみ」の明記

鉄道小画面内のどこかに、対象範囲を明記してください。

候補文言:

- `ODPT対応路線のみ`

表示位置候補:

- 鉄道小画面ヘッダー右上
- 鉄道小画面フッター
- 路線図下部

既存の `平常監視` や `影響 n路線` 表示と重ならないようにしてください。

---

## 9. 詳細地図ではなく「路線図」として扱う

鉄道小画面は、詳細地図ではなく、配信用の路線図的表示を目指します。

不要:

- 道路名
- 建物
- 地名ラベル
- 駅名
- ポップアップ

背景地図を使っている場合でも、地図要素は控えめにし、路線が主役になるようにしてください。

- 路線が主役
- 背景は暗く控えめ
- ODPT対応路線が見えることを優先

---

## 10. data-testid / diagnostics

既存 testid は維持してください。

既存候補:

- `live-stream-panel-rail`
- `live-stream-rail-map`
- `live-stream-rail-route`
- `live-stream-rail-list`
- `live-stream-rail-empty`
- `live-stream-rail-unavailable`

追加推奨:

- `live-stream-railway-default-map`
- `live-stream-railway-scope-label`
- `live-stream-railway-normal-route`
- `live-stream-railway-highlight-route`

Diagnostics に以下があると望ましいです。

```js
railwayMiniMap: {
  loaded: true,
  defaultBoundsApplied: true,
  routeCount: 12,
  affectedCount: 0,
  highlightedCount: 0,
  lastError: null
}
```

既存 `railwayDetail` / `railwayLayer` diagnostics がある場合は、自然に追加してください。

---

## 11. demo / calm / real の扱い

### demo=1

影響ありデモを維持してください。

- 影響路線カード表示
- 該当路線を強調
- 路線図表示

### state=calm

今回の主確認対象です。

- 影響路線なし
- 平常運転
- 首都圏ODPT対応路線図を表示
- ヘッダー 鉄道 0
- ODPT対応路線のみ表示を明記

### 通常表示

実データに応じて分岐してください。

影響あり:

- 影響路線強調

影響なし:

- 首都圏ODPT対応路線図を平常表示

取得失敗:

- 取得不可表示
- 可能なら路線図背景は維持

---

## 12. 今回やらないこと

- 鉄道小画面の完全デフォルメ路線図生成
- OSMからの新規路線図生成スクリプト作成
- ODPT期間限定路線対応
- 駅名ラベル表示
- 乗換駅表示
- 路線図編集UI
- メイン地図の鉄道レイヤー再設計
- OBS soak

今回は「平常時の鉄道小画面に首都圏ODPT対応路線図を表示すること」に絞ってください。

---

## 13. 受け入れ条件

以下を満たしてください。

- `state=calm` で鉄道小画面に首都圏ODPT対応路線図が表示される
- 影響路線なし / 平常運転の表示がある
- 右側路線図が空白にならない
- 右側路線図が首都圏ODPT対応路線の収まる範囲になる
- ODPT対応路線のみであることが明記される
- `demo=1` の影響路線強調が壊れない
- 通常表示で影響あり / 影響なしが正しく切り替わる
- API失敗時に平常と断定しない
- 既存E2EがPASSする
- 重大なconsole/page errorがない
- `/live` が壊れない
- `/` が壊れない

---

## 14. 実装後の報告

以下を報告してください。

- 変更ファイル
- 追加ファイル
- 平常時の路線図表示修正内容
- railway layer 初期化条件の見直し内容
- 平常時 default bounds
- ODPT対応路線のみ表示ラベルの追加位置
- 影響あり / 影響なし / 取得失敗の表示分岐
- 追加/更新したE2E
- 未対応項目
- 次フェーズ候補

---

# CODEX用検証指示書

## 目的

Claude Code が実装した `/live/stream` 鉄道小画面の平常時路線図表示修正を検証してください。

主な検証対象:

- 障害・影響路線がない平常時でも、鉄道小画面に首都圏ODPT対応路線図が表示される
- 路線図が空白にならない
- 首都圏路線が収まる範囲になる
- ODPT対応路線のみ表示していることが明記される
- 影響あり時の既存詳細表示が壊れない
- API失敗時に平常と断定しない
- 既存E2Eが壊れていない

レポート保存先:

```text
tasks/live/live_stream_phase5a1_railway_calm_map_codex_verification.md
```

---

## 1. 静的確認

以下を確認してください。

```bash
git status --short
git diff --stat
```

確認観点:

- `/live/stream` 鉄道小画面関連の変更である
- railway layer / railway mini map の初期化条件が確認できる
- 影響路線0件でも路線図を描画する変更がある
- ODPT対応路線のみ表示ラベルが追加されている
- 通常 `/live` への影響が最小限である
- 通常 `/` への影響がない

---

## 2. スコープ逸脱確認

以下へ広がっていないことを確認してください。

- 鉄道小画面の完全デフォルメ路線図生成
- OSMからの新規路線図生成スクリプト
- ODPT期間限定路線対応
- 駅名ラベル表示
- メイン地図鉄道レイヤー再設計
- OBS soak
- DB追加

今回の範囲は「鉄道小画面の平常時路線図表示修正」のみです。

---

## 3. 構文チェック

対象JSに `node --check` を実行してください。

```bash
node --check frontend/js/live-stream/live-stream-runtime.js
node --check frontend/js/live-stream/live-stream-main.js
node --check frontend/js/live-stream/live-stream-panels.js
node --check frontend/js/live-stream/live-stream-railway-adapter.js
node --check frontend/js/live-stream/live-stream-railway-layer.js
node --check frontend/js/live-stream/live-stream-map-view.js
node --check frontend/js/live-stream/live-stream-focus-policy.js
node --check frontend/js/live-stream/live-stream-focus-controller.js
```

E2E:

```bash
node --check e2e/live-stream.spec.js
node --check e2e/live-stream-railway-detail.spec.js
node --check e2e/live-stream-railway-color-layer.spec.js
node --check e2e/rail-mock-verify.spec.js
```

追加E2Eがある場合:

```bash
node --check e2e/live-stream-railway-calm-map.spec.js
```

---

## 4. Docker状態確認

```bash
docker compose ps
```

確認対象:

- frontend
- backend
- martin
- osrm-walking

既存サービスが壊れていないことを確認してください。

---

## 5. HTTP確認

以下が 200 で返ることを確認してください。

```text
/live/stream
/live/stream?chrome=off
/live/stream?state=calm&chrome=off
/live/stream?demo=1&chrome=off
/live/stream?demo=1&focusSpeed=test&runtimeSpeed=test
/live
/
```

---

## 6. calm / 平常時の鉄道小画面確認

対象URL:

```text
/live/stream?state=calm&chrome=off
```

確認項目:

- 鉄道小画面が表示される
- 影響路線なし / 平常運転が表示される
- 右側に首都圏ODPT対応路線図が表示される
- 路線図が空白にならない
- 路線が小画面内に収まっている
- 路線が暗すぎて見えない状態ではない
- ODPT対応路線のみ表示であることが明記されている

DOM / diagnostics確認候補:

- `live-stream-panel-rail`
- `live-stream-rail-map`
- `live-stream-rail-empty`
- `live-stream-railway-scope-label`
- `live-stream-railway-normal-route`

Diagnostics があれば以下を確認してください。

- loaded = true
- routeCount > 0
- affectedCount = 0
- highlightedCount = 0
- defaultBoundsApplied = true
- lastError = null

---

## 7. 実データ影響0件時の確認

実データで影響路線が0件の場合、通常表示で確認してください。

対象URL:

```text
/live/stream?chrome=off
```

期待:

- 鉄道小画面に首都圏ODPT対応路線図が表示される
- 影響路線なし / 平常運転が表示される
- ヘッダー鉄道件数が0または既存仕様通り平常表示
- デモ路線が混入しない

検証時点で実データに影響路線がある場合は、この項目は mock で確認してください。

---

## 8. 影響あり / demo確認

対象URL:

```text
/live/stream?demo=1&chrome=off
```

または既存の demo URL:

```text
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00
```

確認項目:

- 鉄道小画面に影響路線カードが表示される
- 右側路線図が表示される
- 影響路線が太線・高輝度で強調される
- 平常路線は細線・低輝度で表示される
- 既存の鉄道詳細 overlay が壊れていない
- detail hold / auto-scroll が壊れていない

---

## 9. API失敗時の確認

可能であれば Playwright route で `/api/live/trains/summary` などを 500 にしてください。

期待:

- 鉄道情報を取得できません / 一時的に取得不可
- 平常運転と断定しない
- 影響路線なしと断定しない
- 画面全体が壊れない
- console/page error がない

右側路線図について:

- 可能なら路線図背景を維持
- 維持できない場合でも、取得失敗表示を出し、空白放置しない

---

## 10. ODPT対応路線のみ表示ラベル確認

鉄道小画面内に以下の趣旨の文言があることを確認してください。

- `ODPT対応路線のみ`
- `ODPT対応路線`

確認項目:

- 文字が小さすぎて読めない状態ではない
- 既存の平常監視/影響件数表示と重ならない
- 全国鉄道監視のような誤解を招く文言ではない

---

## 11. 路線図表示範囲確認

calm または影響0件 mock で、右側路線図が首都圏路線の範囲になっていることを目視確認してください。

FAIL例:

- 日本全国表示になって路線が豆粒
- 東京中心から外れて海だけ
- 路線が画面外に出ている
- 一部の太線だけで全体が見えない
- 空白背景だけ

PASS例:

- 首都圏のODPT対応路線が小画面内に収まる
- 平常路線が薄く見える
- 影響0件でも路線図として成立している

---

## 12. 既存E2E実行

既存E2Eを実行してください。

```bash
npx playwright test \
  e2e/live-stream.spec.js \
  e2e/live-stream-main-map.spec.js \
  e2e/live-stream-main-map-real-data.spec.js \
  e2e/live-stream-event-sync.spec.js \
  e2e/live-stream-status-sync.spec.js \
  e2e/live-stream-auto-focus.spec.js \
  e2e/live-stream-stability.spec.js \
  e2e/live-stream-earthquake-detail.spec.js \
  e2e/live-stream-earthquake-detail-map-sync.spec.js \
  e2e/live-stream-railway-detail.spec.js \
  e2e/live-stream-railway-color-layer.spec.js \
  e2e/eq-mock-verify.spec.js \
  e2e/rain-mock-verify.spec.js \
  e2e/tide-mock-verify.spec.js \
  e2e/rail-mock-verify.spec.js
```

追加E2Eがある場合:

```bash
npx playwright test e2e/live-stream-railway-calm-map.spec.js
```

期待:

- 全テスト PASS

---

## 13. 表示欠損確認

以下が画面に出ていないことを確認してください。

- undefined
- null
- NaN
- Invalid Date
- [object Object]

鉄道小画面で特に確認してください。

- 路線名不明が大量表示されていない
- 状態不明が平常表示と混同されていない
- 取得失敗時に空欄放置されていない

---

## 14. スクリーンショット保存

以下を保存してください。

```text
test-results/live-stream-phase5a1-railway-calm-1920.png
test-results/live-stream-phase5a1-railway-normal-1920.png
test-results/live-stream-phase5a1-railway-demo-1920.png
test-results/live-stream-phase5a1-railway-failure-1920.png
```

failure は可能なら保存してください。難しければ Notes に記載してください。

---

## 15. `/live` 回帰確認

通常 `/live` を開いて確認してください。

確認項目:

- HTTP 200
- console/page error なし
- 地図表示が壊れていない
- 地震表示が壊れていない
- キキクル・豪雨表示が壊れていない
- 潮位表示が壊れていない
- 鉄道表示が壊れていない

---

## 16. `/` 回帰確認

ナビ本体 `/` を開いて確認してください。

確認項目:

- HTTP 200
- console/page error なし
- 基本地図表示が壊れていない
- `/live/stream` CSS/JS が漏れていない

---

## 17. レポートに含める内容

- 判定: PASS / PASS with notes / FAIL
- 検証日時
- 対象ブランチ/コミット
- 変更ファイル
- 構文チェック結果
- Docker状態
- HTTP確認結果
- calm / 平常時鉄道小画面確認
- 実データ影響0件確認、またはmock確認
- demo / 影響あり確認
- API失敗時確認
- ODPT対応路線のみ表示ラベル確認
- 路線図表示範囲確認
- E2E結果
- スクリーンショット保存先
- `/live` 回帰
- `/` 回帰
- Notes
- 修正推奨事項

---

## PASS条件

以下を満たせば PASS としてください。

- `state=calm` で鉄道小画面に首都圏ODPT対応路線図が表示される
- 影響路線なし / 平常運転が表示される
- 路線図が空白にならない
- 路線図が首都圏ODPT対応路線の収まる範囲になる
- ODPT対応路線のみ表示であることが明記される
- `demo=1` で影響路線強調が維持される
- API失敗時に平常と断定しない
- 既存E2EがPASS
- console/page error なし
- `/live` が壊れていない
- `/` が壊れていない

---

## PASS with notes条件

以下は PASS with notes としてください。

- 実データで影響0件を確認できず mock 確認になった
- API失敗時に路線図背景維持までは未対応だが取得不可表示はできる
- 路線図表示範囲が固定boundsで暫定
- ODPT対応路線の一部のみ表示
- 表示範囲確認が目視中心

---

## FAIL条件

以下の場合は FAIL としてください。

- `state=calm` で鉄道小画面の路線図が空白
- 影響0件時に路線図レイヤーが初期化されない
- 首都圏路線が収まる範囲にならない
- ODPT対応路線のみの明記がない
- API失敗時に平常運転と断定する
- `demo=1` の影響路線強調が壊れる
- 既存E2Eが壊れる
- 重大なconsole/page error
- `/live` が壊れる
- `/` が壊れる

---

## 最終コメント例

判定: PASS

`/live/stream` Phase 5-A.1 鉄道小画面 平常時路線図表示範囲修正は、`state=calm` および影響0件相当の状態で、鉄道小画面に首都圏ODPT対応路線図が表示されることを確認しました。

影響ありデモでは既存の鉄道詳細表示・路線強調も維持され、API失敗時も平常とは断定しません。

既存E2E、通常 `/live`、`/` への回帰影響はありません。

次フェーズでは Phase 5-B: OBS soak / 長時間安定性確認へ進めます。
