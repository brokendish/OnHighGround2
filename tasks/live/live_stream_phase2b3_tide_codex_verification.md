# /live/stream Phase Stream-2-B.3 潮位・水位情報実データ接続 MVP — 検証レポート

## 判定: PASS with notes

---

## 検証日時

2026-07-02 21:47 JST

## 対象ブランチ / コミット

- branch: main (untracked 新規ファイル群)
- base commit: ba6f7bd

---

## 変更ファイル

| ファイル | 区分 | 内容 |
|---|---|---|
| `frontend/js/live-stream/live-stream-tide-adapter.js` | 新規 | `/api/live/tide/stations` と detail レスポンス → stream 潮位 ViewModel 変換 |
| `frontend/js/live-stream/live-stream-main.js` | 更新 | `_fetchTide()` / `_tideStatus` 追加、30分間隔の潮位更新追加 |
| `frontend/js/live-stream/live-stream-scene.js` | 更新 | `_buildTideSection()` 追加、`buildScene()` に `tideModel` / `useTideDemo` 対応 |
| `frontend/js/live-stream/live-stream-panels.js` | 更新 | 実潮位表示、0件/error表示、潮位 testid 追加 |
| `frontend/js/live-stream/live-stream-map.js` | 更新 | `renderTideFromRecords()` 追加、実データ点列から潮位カーブ描画 |
| `frontend/live/stream.html` | 更新 | tide adapter スクリプトタグ追加 |
| `e2e/live-stream.spec.js` | 更新 | Phase 2-B.3 tide adapter テスト 6件追加 |
| `e2e/tide-mock-verify.spec.js` | 新規 | 潮位 mock 検証 6件追加 |

既存 `/live` ファイル変更: **ゼロ**  
既存 `/` ファイル変更: **ゼロ**  
backend 変更: **ゼロ**

---

## 1. 静的確認

- `/live/stream` 専用ファイル中心の変更 ✅
- 通常 `/live` への影響なし ✅
- 通常 `/` への影響なし ✅
- 地震・豪雨 adapter / E2E は維持 ✅
- `TideStreamAdapter` が tide adapter 責務を担う ✅
- `?demo=1` で潮位実データ取得をスキップ ✅
- 2地点同時表示と8秒巡回の描画構造を維持 ✅

スコープ逸脱なし。DB追加、潮位データ生成処理の再実装、河川水位取得、鉄道実データ接続、JARTIC交通量表示までは広げていない。

---

## 2. データ取得口確認

`live-stream-main.js` の `_fetchTide()` が既存 `/live` の潮位取得口を利用する。

- 観測点一覧: `/api/live/tide/stations` ✅
- 観測点詳細: `/api/live/tide/stations/{id}` ✅
- 既存 `/live` の `frontend/js/live/live-tide-layer.js` と同じ API 系統 ✅
- フロントから `data_runtime` 等の内部ファイルへ直接依存なし ✅
- 潮位データ生成処理の重複実装なし ✅
- 新規 backend API なし ✅

検証時API応答:

```text
/api/live/tide/stations
count=50
has_data=true の観測点あり

/api/live/tide/stations/WN
name=稚内
current_tide_cm=19
records に 2026-07-02 の時間別 tide_cm あり
next_high_tide / next_low_tide あり
```

---

## 3. 構文チェック

```text
node --check frontend/js/live-stream/live-stream-main.js                 OK
node --check frontend/js/live-stream/live-stream-scene.js                OK
node --check frontend/js/live-stream/live-stream-tide-adapter.js         OK
node --check frontend/js/live-stream/live-stream-rain-adapter.js         OK
node --check frontend/js/live-stream/live-stream-earthquake-adapter.js   OK
node --check frontend/js/live-stream/live-stream-panels.js               OK
node --check frontend/js/live-stream/live-stream-map.js                  OK
node --check frontend/js/live-stream/live-stream-clock.js                OK
node --check frontend/js/live-stream/live-stream-ticker.js               OK
node --check e2e/live-stream.spec.js                                     OK
node --check e2e/eq-mock-verify.spec.js                                  OK
node --check e2e/rain-mock-verify.spec.js                                OK
node --check e2e/tide-mock-verify.spec.js                                OK
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
Phase Stream-2-B.3 tide adapter: 6/6 PASS
Phase Stream-2-B.1 earthquake adapter: 6/6 PASS
```

**26/26 PASS** ✅

### `e2e/eq-mock-verify.spec.js`

```text
5/5 PASS
```

地震 0件、12時間フィルタ、activeTarget、API 500、不正JSONが引き続き PASS ✅

### `e2e/rain-mock-verify.spec.js`

```text
6/6 PASS
```

豪雨 0件、danger target、優先順位、API 500、不正JSON、watch 表示が引き続き PASS ✅

### `e2e/tide-mock-verify.spec.js`

| 検証項目 | 結果 |
|---|---|
| 0地点: ct-tide=0 / panel表示 / page error なし | ✅ PASS |
| 2地点実データ: station名 / high / low / source / current / curve表示 | ✅ PASS |
| stations API 500: ct-tide=`-` / page error なし / JS console.error なし | ✅ PASS |
| detail API 500: graceful fallback / ct-tide=0 / no crash | ✅ PASS |
| 不正JSON: page error なし / console error なし | ✅ PASS |
| recordsなし: 地点名表示 / データなしSVG / no crash | ✅ PASS |

**6/6 PASS** ✅

合計: **43/43 PASS** ✅

---

## 7. demo / mock モード仕様

| パラメータ | 潮位動作 |
|---|---|
| `?demo=1` | 実データ取得スキップ。`SCENES.alert.tide` デモ固定 |
| `?state=calm` | `SCENES.calm`。潮位地点は表示しつつ警戒 pulse なし |
| `?state=alert` | `/api/live/tide/stations` と detail を取得。成功時は実潮位表示 |
| `?demoNow=ISO8601` | 時計固定。潮位カーブの現在時刻マーカーにも反映 |

---

## 8. 実データ接続確認

✅ **PASS**

- `/live/stream?chrome=off` で tide API fetch が実行される
- `has_data=true` の観測点から最大4地点を選択
- 各地点 detail を取得
- 右下パネルに2地点ずつ表示
- 現在潮位、満潮/干潮、潮位カーブ、現在時刻マーカーを表示
- 実データ地点には `気象庁潮位表` source 表示あり

Note: `_TIDE_SELECT = 4` のため、初期MVPでは最大4地点を巡回対象にする。

---

## 9. 潮位カーブ確認

✅ **PASS**

- 実データ時は `renderTideFromRecords()` が `records:[{h, cm}]` からカーブを生成
- `live-stream-tide-curve` が表示される
- `live-stream-tide-current-marker` が表示される
- `LiveStreamClock.getCurrentHourFloat()` を使い、demoNow / 実時刻の時刻位置にマーカーを描画
- records が空の場合は `データなし` SVGを表示し、画面は壊れない

既存 Phase 2-A テストで `demoNow=06:00` と `demoNow=18:00` の current marker 位置変化も継続 PASS。

---

## 10. 複数地点巡回確認

✅ **PASS**

- `render()` 側で `pairStart = (Math.floor(tick / 8) * 2) % N`
- 2地点ずつ表示
- N > 2 の場合は `拠点 1・2/N` 形式と `8s巡回` を表示
- 時計更新だけでは巡回状態をリセットしない
- 実データは最大4地点を対象にするため、2地点ペア巡回が可能

---

## 11. 取得成功0件表示確認

✅ **PASS** (mock ベース)

- stations API が `stations: []` を返す
- `_liveTideModel = { status:'ok', stations:[], alertCount:0 }`
- `ct-tide` = `0`
- 潮位小窓: `現在、表示対象なし`
- 取得失敗扱いにはならない
- console/page error なし

---

## 12. 取得失敗表示確認

✅ **PASS** (mock ベース)

- stations API 500 → `_tideStatus='error'`
- `ct-tide` = `-`
- 潮位小窓: `一時的に取得不可`
- page error なし
- JS `console.error` なし

Note: detail API が全件失敗した場合は、リスト取得自体は成功しているため `ok + 0地点` として扱う設計。

---

## 13. ヘッダー潮位件数確認

| 状態 | 表示 |
|---|---|
| 警戒対象あり | `1` 以上 |
| 警戒対象なし | `0` ✅ |
| stations API 500 / 不正JSON | `-` ✅ |
| detail 全失敗 | `0` ✅ |
| demo モード | デモ警戒地点数 ✅ |

重要仕様: `潮位 0` は地点データ0件ではなく、警戒対象0件の意味でよい。  
今回MVPでは高潮警戒判定が未実装のため、実データ時の `alertCount` は `0` 固定。

---

## 14. 表示欠損確認

- `undefined` / `null` / `NaN` / `Invalid Date` が出ないよう mock E2E で確認 ✅
- 満潮/干潮欠損時は `--:-- --cm`
- 現在潮位の補間不可時は `--cm`
- records なし時は `データなし` SVG

---

## 15. スクリーンショット

| ファイル | 内容 |
|---|---|
| `test-results/live-stream-phase2b3-tide-demo-1920.png` | `state=alert&demo=1` / 1920×1080 |
| `test-results/live-stream-phase2b3-tide-calm-1920.png` | `state=calm` / 1920×1080 |
| `test-results/live-stream-phase2b3-tide-live-1920.png` | `?chrome=off` 実データ / 1920×1080 |

3件保存済み ✅  
`test-results/` は `.gitignore` 対象。

---

## 16. `/live` 回帰

- HTTP 200 ✅
- `live-stream.spec.js` の `/live` regression PASS ✅
- `.ls-stage` DOM 未混入 ✅
- `live-stream.css` link 未混入 ✅
- 既存 `/live` ファイル変更なし ✅

---

## 17. `/` 回帰

- HTTP 200 ✅
- `live-stream.spec.js` の `/` regression PASS ✅
- `.ls-stage` DOM 未混入 ✅
- `live-stream.css` link 未混入 ✅
- 既存ナビ本体ファイル変更なし ✅

---

## Notes

1. 河川水位は未接続。今回対象は右下パネルの潮位実データ接続。
2. 高潮/警戒判定は未実装で、実データ時 `alertCount=0` 固定。
3. 中央地図の潮位 pulse は `station.alert` が true の地点のみ表示。実データでは警戒判定未実装のため通常は出ない。
4. 実潮位対象は初期MVPとして最大4地点。
5. 実データ records の日付フィルタは実行日のJST日付基準。
6. テロップ動的化は最小対応または未対応。Phase 2-C 以降の対象。

---

## 修正推奨事項

- 高潮警戒判定ロジックを追加し、`alertCount` と中央地図 pulse を実データ由来にする。
- 観測点選択を固定先頭4件ではなく、地域代表性や警戒度で選ぶ。
- `TideStreamAdapter` の日付基準を必要に応じて `LiveStreamClock` / `demoNow` と揃える。
- 河川水位を扱う場合は別 adapter として境界を保つ。

---

## PASS 条件照合

| 条件 | 結果 |
|---|---|
| `/live/stream` が表示できる | ✅ |
| 既存 dedicated E2E が PASS | ✅ |
| 地震 E2E が PASS | ✅ |
| 豪雨 E2E が PASS | ✅ |
| 潮位デモ表示 E2E が PASS | ✅ |
| 既存 `/live` の潮位データ取得口を利用 | ✅ `/api/live/tide/*` |
| 潮位データあり時に小窓へ反映 | ✅ |
| 2地点表示が維持される | ✅ |
| 潮位カーブが実データ由来になる | ✅ |
| 現在時刻マーカーが demoNow / 実時刻に連動 | ✅ |
| ヘッダー潮位件数が仕様通り表示 | ✅ |
| 取得失敗時に平常と断定しない | ✅ |
| console/page error なし | ✅ |
| `/live` が壊れていない | ✅ |
| `/` が壊れていない | ✅ |

---

## 次フェーズ候補

- Phase 2-B.4: 鉄道情報 実データ接続
- Phase 2-B.5: 潮位警戒判定 / 中央地図 pulse 実データ化
- Phase 2-C: テロップ全カテゴリ動的化
- Phase 2-D: 中央地図の投影精度改善
