# /live/stream Phase Stream-2-C 下部テロップ統合・実データ化 — 検証レポート

## 判定: PASS with notes

---

## 検証日時

2026-07-02 22:36 JST

## 対象ブランチ / コミット

- branch: main (untracked 新規ファイル群)
- base commit: ba6f7bd

---

## 変更ファイル

| ファイル | 区分 | 内容 |
|---|---|---|
| `frontend/js/live-stream/live-stream-scene.js` | 更新 | `buildTickerItems()` / `buildTickerText()` 追加。地震・大雨・鉄道・潮位 scene から ticker item 生成 |
| `frontend/js/live-stream/live-stream-panels.js` | 更新 | ticker本文が変わった時のみDOM更新する処理を追加 |
| `e2e/live-stream.spec.js` | 更新 | Phase 2-C ticker テスト 7件追加 |

既存 `/live` ファイル変更: **ゼロ**  
既存 `/` ファイル変更: **ゼロ**  
backend 変更: **ゼロ**  
DB追加: **ゼロ**

---

## 1. 静的確認

- `/live/stream` 専用ファイル中心の変更 ✅
- 通常 `/live` への影響なし ✅
- 通常 `/` への影響なし ✅
- ticker生成関数あり ✅
- 地震・大雨・鉄道・潮位の scene / ViewModel を利用 ✅
- `render()` 側は `_lastTickerText` で本文差分更新し、毎秒ticker全体を再生成しない ✅

スコープ逸脱なし。音声読み上げ、YouTube API連携、DB追加、テロップ編集UI、`/live` 本体大規模改修までは広げていない。

---

## 2. ticker生成仕様

`live-stream-scene.js`:

- `_eqTickerItem(eq)` → `【地震】`
- `_rainTickerItem(rain)` → `【大雨】`
- `_railTickerItem(rail)` → `【鉄道】`
- `_tideTickerItem(tide)` → `【潮位】`
- `buildTickerItems(scene)` → priority降順で並べる
- `buildTickerText(items)` → `　／　` 区切りのticker本文に変換
- itemなし時は `【監視中】全国の地震・豪雨・潮位・交通影響を監視中　／　`

取得失敗カテゴリは `情報を取得できません` / `運行情報を取得できません` として扱い、「なし」と断定しない。

---

## 3. 構文チェック

```text
node --check frontend/js/live-stream/live-stream-main.js                 OK
node --check frontend/js/live-stream/live-stream-scene.js                OK
node --check frontend/js/live-stream/live-stream-ticker.js               OK
node --check frontend/js/live-stream/live-stream-panels.js               OK
node --check frontend/js/live-stream/live-stream-map.js                  OK
node --check frontend/js/live-stream/live-stream-clock.js                OK
node --check frontend/js/live-stream/live-stream-earthquake-adapter.js   OK
node --check frontend/js/live-stream/live-stream-rain-adapter.js         OK
node --check frontend/js/live-stream/live-stream-tide-adapter.js         OK
node --check frontend/js/live-stream/live-stream-railway-adapter.js      OK
node --check e2e/live-stream.spec.js                                     OK
node --check e2e/eq-mock-verify.spec.js                                  OK
node --check e2e/rain-mock-verify.spec.js                                OK
node --check e2e/tide-mock-verify.spec.js                                OK
node --check e2e/rail-mock-verify.spec.js                                OK
```

全件 OK ✅

---

## 4. Docker 状態

| サービス | 状態 |
|---|---|
| evacuation-navi-backend | Up (healthy) |
| evacuation-navi-frontend | Up |
| evacuation-navi-martin | Up (healthy) |
| evacuation-navi-osrm-walking | Up |

既存起動状態を維持 ✅

---

## 5. HTTP 確認

| URL | ステータス |
|---|---|
| `/live/stream` | 200 ✅ |
| `/live/stream?state=calm&chrome=off&demoNow=...` | 200 ✅ |
| `/live/stream?state=alert&chrome=off&demo=1&demoNow=...` | 200 ✅ |
| `/live/stream?chrome=off` | 200 ✅ |
| `/live` | 200 ✅ |
| `/` | 200 ✅ |

---

## 6. E2E 結果

### `e2e/live-stream.spec.js`

```text
Phase Stream-2-A: 8/8 PASS
Phase Stream-2-B.2 rain adapter: 6/6 PASS
Phase Stream-2-B.4 railway adapter: 6/6 PASS
Phase Stream-2-B.3 tide adapter: 6/6 PASS
Phase Stream-2-C ticker: 7/7 PASS
Phase Stream-2-B.1 earthquake adapter: 6/6 PASS
```

**39/39 PASS** ✅

### 既存 mock spec

```text
e2e/eq-mock-verify.spec.js     5/5 PASS
e2e/rain-mock-verify.spec.js   6/6 PASS
e2e/tide-mock-verify.spec.js   6/6 PASS
e2e/rail-mock-verify.spec.js   7/7 PASS
```

合計: **63/63 PASS** ✅

---

## 7. demo=1 テロップ確認

対象:

```text
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00
```

取得本文:

```text
【地震】19:21 岩手県沖 M6.1 最大震度5弱 ／ 【大雨】静岡県 中部 キキクル「危険」 ／ 【鉄道】中央線快速 三鷹〜東京 / 人身事故 ／ 【潮位】東京 満潮05:30 184cm ／
```

確認:

- `【地震】` を含む ✅
- `【大雨】` を含む ✅
- `【鉄道】` を含む ✅
- `【潮位】` を含む ✅
- 区切り文字 `／` を含む ✅
- priority順で地震が大雨より前 ✅
- `undefined` / `null` / `NaN` / `[object` なし ✅
- console/page error なし ✅

---

## 8. state=calm テロップ確認

対象:

```text
/live/stream?state=calm&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
```

取得本文:

```text
【監視中】全国の地震・豪雨・潮位・交通影響を監視中 ／
```

確認:

- `監視中` を含む ✅
- 警戒デモ文言ではない ✅
- `undefined` / `null` / `NaN` なし ✅
- console/page error なし ✅

---

## 9. 通常表示テロップ確認

対象:

```text
/live/stream?chrome=off
```

Note: デフォルトモードは64秒ループで、最初の16秒は calm。短時間では監視中テロップになる。警戒フェーズに入るまで待機して実データ由来tickerを確認した。

警戒フェーズ待機後の取得本文:

```text
【地震】20:48 福島県会津 M4.6 最大震度2 - なし ／ 【大雨】新潟県付近 豪雨キキクル「危険」 ／ 【鉄道】銀座線 16時23分頃、上野駅で車両点検のため、遅れが出ています。 ／ 【潮位】稚内 満潮01:00 11cm ／
```

確認:

- 実データ由来の地震・大雨・鉄道・潮位が反映 ✅
- 表示対象がないフェーズでは監視中文言 ✅
- `undefined` / `null` / `NaN` / `Invalid Date` / `[object Object]` なし ✅
- 取得失敗カテゴリがある場合も「なし」と断定しない生成ロジック ✅

---

## 10. 取得失敗時の扱い

✅ **PASS with notes**

静的確認:

- 地震 error: `【地震】情報を取得できません`
- 大雨 error: `【大雨】情報を取得できません`
- 鉄道 error: `【鉄道】運行情報を取得できません`
- 潮位 error: `【潮位】情報を取得できません`

既存 mock spec で各カテゴリの API 500 / 不正JSON時に画面が壊れないことは確認済み。  
Phase 2-C 専用の全カテゴリticker error mockは未追加のため notes 扱い。

---

## 11. marquee確認

- `live-stream-ticker` / `live-stream-ticker-body` は表示 ✅
- CSS marquee track は維持 ✅
- `render()` では `_lastTickerText` を比較し、本文が変わった時のみ `ticker-a` / `ticker-b` を更新 ✅
- 時計更新だけで ticker DOM を不必要に更新しない構造 ✅
- demoNow指定時は本文が安定 ✅

Note: marqueeアニメーションの厳密なフレーム検証は未実施。

---

## 12. 表示欠損確認

ticker本文に以下が含まれないことをE2Eと実表示で確認:

```text
undefined
null
NaN
Invalid Date
[object Object]
```

✅ 問題なし。

---

## 13. スクリーンショット

| ファイル | 内容 |
|---|---|
| `test-results/live-stream-phase2c-ticker-demo-1920.png` | `state=alert&demo=1` / 1920×1080 |
| `test-results/live-stream-phase2c-ticker-calm-1920.png` | `state=calm` / 1920×1080 |
| `test-results/live-stream-phase2c-ticker-live-1920.png` | `?chrome=off` / 1920×1080 |

3件保存済み ✅  
`test-results/` は `.gitignore` 対象。

---

## 14. `/live` 回帰

- HTTP 200 ✅
- `live-stream.spec.js` の `/live` regression PASS ✅
- `.ls-stage` DOM 未混入 ✅
- `live-stream.css` link 未混入 ✅
- 既存 `/live` ファイル変更なし ✅

---

## 15. `/` 回帰

- HTTP 200 ✅
- `live-stream.spec.js` の `/` regression PASS ✅
- `.ls-stage` DOM 未混入 ✅
- `live-stream.css` link 未混入 ✅
- 既存ナビ本体ファイル変更なし ✅

---

## Notes

1. ticker item は各カテゴリ最大1件。
2. priority は簡易実装。大きな地震・大雨・鉄道見合わせ・潮位警戒を上位にする。
3. `/live/stream?chrome=off` はデフォルトループの最初16秒が calm のため、即時確認では監視中表示になる。
4. Phase 2-C 専用の failure ticker mock spec は未追加。既存カテゴリ別mockと静的確認で扱いを確認。
5. marqueeリセットの厳密なパフォーマンス検証は未実施。

---

## 修正推奨事項

- ticker error用の専用mock specを追加し、各カテゴリ error item が本文へ出ることを直接検証する。
- ticker priorityを運用ルールとして文書化する。
- ticker itemをカテゴリごとに複数件出すか、最大1件のまま運用するかを次フェーズで確定する。

---

## PASS 条件照合

| 条件 | 結果 |
|---|---|
| `/live/stream` が表示できる | ✅ |
| 既存E2Eが PASS | ✅ |
| ticker用E2Eが PASS | ✅ `live-stream.spec.js` 内 7/7 |
| demo=1 で4カテゴリが出る | ✅ |
| state=calm で監視中文言 | ✅ |
| 通常表示で実データ由来または監視中文言 | ✅ |
| undefined / null / NaN が出ない | ✅ |
| 取得失敗時に「なし」と断定しない | ✅ |
| console/page error なし | ✅ |
| `/live` が壊れていない | ✅ |
| `/` が壊れていない | ✅ |

---

## 次フェーズ候補

- Phase 2-D: 中央地図の投影精度改善
- Phase 2-E: OBS配信用プリセット / 運用安定化
- Phase 3-A: 自動注目・巡回ロジック改善
