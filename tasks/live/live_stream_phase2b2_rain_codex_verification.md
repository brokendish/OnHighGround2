# /live/stream Phase Stream-2-B.2 キキクル・豪雨情報実データ接続 MVP — 検証レポート

## 判定: PASS with notes

---

## 検証日時

2026-07-02 21:06 JST

## 対象ブランチ / コミット

- branch: main (untracked 新規ファイル群)
- base commit: ba6f7bd

---

## 変更ファイル

| ファイル | 区分 | 内容 |
|---|---|---|
| `frontend/js/live-stream/live-stream-rain-adapter.js` | 新規 | `/api/live/summary` レスポンス → stream 豪雨 ViewModel 変換 |
| `frontend/js/live-stream/live-stream-scene.js` | 更新 | `_buildRainSection()` 追加、`buildScene()` に `rainModel` / `useRainDemo` 対応 |
| `frontend/js/live-stream/live-stream-main.js` | 更新 | `_fetchRain()` / `_rainStatus` 追加、再描画 signature に rain 状態追加 |
| `frontend/js/live-stream/live-stream-panels.js` | 更新 | rain error 表示、`live-stream-rain-*` testid 追加 |
| `frontend/live/stream.html` | 更新 | rain adapter スクリプトタグ追加 |
| `e2e/live-stream.spec.js` | 更新 | Phase 2-B.2 rain adapter テスト 6件追加 |
| `e2e/rain-mock-verify.spec.js` | 新規 | mock 検証 6件追加 |

既存 `/live` ファイル変更: **ゼロ**  
既存 `/` ファイル変更: **ゼロ**  
backend 変更: **ゼロ**

---

## 1. 静的確認

- `/live/stream` 専用ファイル中心の変更 ✅
- `/live` 本体への影響なし ✅
- `/` 本体への影響なし ✅
- 地震 adapter / E2E は維持 ✅
- `RainStreamAdapter` が rain/kikikuru adapter 責務を担う ✅
- `?demo=1` で豪雨実データ取得をスキップ ✅
- `?state=calm` では豪雨表示なし ✅

スコープ逸脱なし。キキクルタイル完全描画、洪水/浸水/土砂の分割UI、鉄道・潮位実データ接続までは広げていない。

---

## 2. データ取得口確認

`live-stream-main.js` の `_fetchRain()` が `/api/live/summary` を直接呼ぶ。

- 既存 `backend/app/api/live_summary.py` の `GET /api/live/summary` を利用 ✅
- `summary.rain.areas[]` と `summary.kikikuru.areas[]` を `RainStreamAdapter.build()` で stream 表示用に変換 ✅
- 新規 JMA 直接アクセスなし ✅
- 新規 backend API なし ✅
- DB 追加なし ✅

検証時API応答:

```text
status=ok
rain.status=ok / rain.areas=5
kikikuru.status=ok / kikikuru.areas=1
rain.summary.strong_rain_detected=true
kikikuru.summary.watch_area_count=1
```

---

## 3. 構文チェック

```text
node --check frontend/js/live-stream/live-stream-main.js                 OK
node --check frontend/js/live-stream/live-stream-scene.js                OK
node --check frontend/js/live-stream/live-stream-rain-adapter.js         OK
node --check frontend/js/live-stream/live-stream-earthquake-adapter.js   OK
node --check frontend/js/live-stream/live-stream-panels.js               OK
node --check frontend/js/live-stream/live-stream-map.js                  OK
node --check frontend/js/live-stream/live-stream-clock.js                OK
node --check frontend/js/live-stream/live-stream-ticker.js               OK
node --check e2e/live-stream.spec.js                                     OK
node --check e2e/eq-mock-verify.spec.js                                  OK
node --check e2e/rain-mock-verify.spec.js                                OK
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
Phase Stream-2-B.1 earthquake adapter: 6/6 PASS
```

**20/20 PASS** ✅

### `e2e/eq-mock-verify.spec.js`

```text
5/5 PASS
```

地震 0件、12時間フィルタ、activeTarget、API 500、不正JSONが引き続き PASS ✅

### `e2e/rain-mock-verify.spec.js`

| 検証項目 | 結果 |
|---|---|
| 0件表示: ct-rain=0 / パルスなし / page error なし | ✅ PASS |
| キキクル danger 1件: target / pulse / popup / ct-rain=1 | ✅ PASS |
| activeTarget: danger が warning より優先 | ✅ PASS |
| API 500: ct-rain=`-` / page error なし / JS console.error なし | ✅ PASS |
| 不正JSON: page error なし / console error なし | ✅ PASS |
| watch: alerts list のみ、target/popup/pulse なし、ct-rain=0 | ✅ PASS |

**6/6 PASS** ✅

合計: **31/31 PASS** ✅

Note: 最初に `eq-mock` と `rain-mock` を並列実行した際、Playwright helper server の `127.0.0.1:8787` が競合したため `eq-mock` 側だけ `EADDRINUSE` になった。単独再実行では 5/5 PASS。

---

## 7. demo / mock モード仕様

| パラメータ | 豪雨動作 |
|---|---|
| `?demo=1` | 実データ取得スキップ。`SCENES.alert.rain` デモ固定 |
| `?state=calm` | 実データに関わらず `SCENES.calm`。豪雨 target / pulse なし |
| `?state=alert` | `/api/live/summary` を取得。成功時は rain/kikikuru 実データ表示 |
| `?demoNow=ISO8601` | 時計固定。E2E安定化用 |

---

## 8. 対象0件表示確認

✅ **PASS** (mock ベース)

- `RainStreamAdapter.build()` が空配列 → `targets: []`, `alerts: []`, `statusCount: 0`
- `ct-rain` = `0`
- 中央地図: `live-stream-pulse-rain` なし
- 豪雨小窓: `現在 対象なし`
- console/page error なし

---

## 9. 取得失敗表示確認

✅ **PASS** (mock ベース)

- HTTP 500 → `_rainStatus = 'error'`
- `buildScene()` が `rain.status='error'` を scene に反映
- `ct-rain` = `-`
- 豪雨小窓: `一時的に取得不可`
- page error なし
- JS `console.error` なし

**「豪雨なし」と断定しない** ✅

---

## 10. activeTarget 選択ルール確認

✅ **PASS with notes**

現状の選択ルール:

1. `danger`
2. `warning`
3. `watch`

ただし `watch` は targets には含めず、左パネル alerts のみに表示する。  
mock では `danger > warning` を確認済み。

Note: 同一危険度内の雨量強度・更新時刻による優先順位は未実装。Phase 2-B.2 の簡易実装として PASS with notes。

---

## 11. 8秒巡回確認

✅ **PASS**

- 複数 target があるデモ表示で `対象 1/2` 等の巡回UIが表示される
- `render()` は `Math.floor(tick / 8)` で対象を切り替える
- 再描画 signature に `_rainStatus` を含み、時計更新のみでは巡回がリセットされない

---

## 12. 中央地図パルス確認

✅ **PASS with notes**

- 対象あり: `live-stream-pulse-rain` 表示 ✅
- 対象0件: `live-stream-pulse-rain` 非表示 ✅
- 色: `var(--c-rain-2)` / 雨域セル `var(--c-rain)` 系 ✅
- 位置: `RainStreamAdapter._latLonToSvg()` による簡易線形投影 ✅

Note: 簡略SVG上の概算座標。厳密投影や実雨域ポリゴン描画は次フェーズ以降。

---

## 13. キキクル・豪雨小窓表示確認

- 地域名: 表示 ✅
- カテゴリ: `キキクル` / `土砂災害` / `豪雨` 等に変換 ✅
- 危険度: `危険` / `警戒` / `注意` 表示 ✅
- 更新時刻: 左パネル用 alert model に保持 ✅
- popup: target あり時に表示 ✅
- `undefined` / `null` / `NaN` 表示なし ✅

---

## 14. ヘッダー豪雨件数確認

| 状態 | 表示 |
|---|---|
| 対象あり | `1` 以上 ✅ |
| 対象0件 | `0` ✅ |
| API 500 / 不正JSON | `-` ✅ |
| `watch` のみ | `0`、左リストには表示 ✅ |
| demo モード | `0` / `-` ではない ✅ |

---

## 15. スクリーンショット

| ファイル | 内容 |
|---|---|
| `test-results/live-stream-phase2b2-rain-demo-1920.png` | `state=alert&demo=1` / 1920×1080 |
| `test-results/live-stream-phase2b2-rain-calm-1920.png` | `state=calm` / 1920×1080 |
| `test-results/live-stream-phase2b2-rain-live-1920.png` | `?chrome=off` 実データ / 1920×1080 |

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

1. activeTarget は危険度順の簡易実装。同一危険度時の雨量強度・更新時刻ソートは未実装。
2. 雨域表現は簡略SVG上のぼかし円。キキクルタイルや実雨域ポリゴンの完全描画は対象外。
3. `watch` レベルは target/pulse/popup には出さず、alerts list のみに表示する仕様。
4. テロップの豪雨動的化は最小対応または未対応。Phase 2-C 以降の対象。
5. Playwright テストを並列プロセスで同時起動すると helper server port 競合が起きるため、mock spec は順次実行が安全。

---

## 修正推奨事項

- 同一危険度内での優先順位を `observed_at` または雨量強度相当の指標で安定ソートする。
- `RainStreamAdapter` の簡易投影を、地震 adapter と共通 helper 化するか、次フェーズで Mercator 系に寄せる。
- 豪雨テロップを実データ由来にする。

---

## PASS 条件照合

| 条件 | 結果 |
|---|---|
| `/live/stream` が表示できる | ✅ |
| 既存 dedicated E2E が PASS | ✅ |
| 地震 E2E が PASS | ✅ |
| キキクル・豪雨デモ表示 E2E が PASS | ✅ |
| 既存 `/live` のキキクル・豪雨系データ取得口を利用 | ✅ `/api/live/summary` |
| 対象あり時に小窓へ反映 | ✅ |
| 対象あり時に中央地図パルスへ反映 | ✅ |
| 豪雨件数がヘッダーへ反映 | ✅ |
| 対象0件時に正常な対象なし表示 | ✅ |
| 取得失敗時に「なし」と断定しない | ✅ |
| console/page error なし | ✅ |
| `/live` が壊れていない | ✅ |
| `/` が壊れていない | ✅ |

---

## 次フェーズ候補

- Phase 2-B.3: 鉄道情報 実データ接続
- Phase 2-B.4: 潮位・水位情報 実データ接続
- Phase 2-C: テロップ全カテゴリ動的化
- Phase 2-D: 中央地図の投影精度改善
