# /live/stream Phase Stream-2-B.4 鉄道情報実データ接続 MVP — 検証レポート

## 判定: PASS with notes

---

## 検証日時

2026-07-02 22:15 JST

## 対象ブランチ / コミット

- branch: main (untracked 新規ファイル群)
- base commit: ba6f7bd

---

## 変更ファイル

| ファイル | 区分 | 内容 |
|---|---|---|
| `frontend/js/live-stream/live-stream-railway-adapter.js` | 新規 | `/api/live/trains/summary` レスポンス → stream 鉄道 ViewModel 変換 |
| `frontend/js/live-stream/live-stream-main.js` | 更新 | `_fetchRail()` / `_railStatus` 追加、2分間隔の鉄道更新追加 |
| `frontend/js/live-stream/live-stream-scene.js` | 更新 | `_buildRailSection()` 追加、`buildScene()` に `railModel` / `useRailDemo` 対応 |
| `frontend/js/live-stream/live-stream-panels.js` | 更新 | 影響あり/なし/error表示、鉄道 testid 追加 |
| `frontend/live/stream.html` | 更新 | railway adapter スクリプトタグ追加 |
| `e2e/live-stream.spec.js` | 更新 | Phase 2-B.4 railway adapter テスト 6件追加 |
| `e2e/rail-mock-verify.spec.js` | 新規 | 鉄道 mock 検証 7件追加 |

既存 `/live` ファイル変更: **ゼロ**  
既存 `/` ファイル変更: **ゼロ**  
backend 変更: **ゼロ**

---

## 1. 静的確認

- `/live/stream` 専用ファイル中心の変更 ✅
- 通常 `/live` への影響なし ✅
- 通常 `/` への影響なし ✅
- 地震・豪雨・潮位 adapter / E2E は維持 ✅
- `RailwayStreamAdapter` が railway adapter 責務を担う ✅
- `?demo=1` で鉄道実データ取得をスキップ ✅
- 鉄道小窓はカード表示に集約し、地図上ポップアップなし ✅

スコープ逸脱なし。全国鉄道網完全対応、ODPT非対応路線の推定表示、駅名大量表示、DB追加、JARTIC連携、テロップ全面動的化までは広げていない。

---

## 2. データ取得口確認

`live-stream-main.js` の `_fetchRail()` が既存 `/live` の鉄道取得口を利用する。

- 取得口: `/api/live/trains/summary` ✅
- 既存 `/live` の `frontend/js/live/live-train-panel.js` と同じ API 系統 ✅
- `/live/stream` から ODPT へ直接アクセスなし ✅
- ODPT由来の正規化済み `items[]` を `RailwayStreamAdapter.build()` で stream 表示用に変換 ✅
- 新規 backend API なし ✅

検証時API応答:

```text
status=ok
stale=false
scope.mode=all
items=1
source=ODPT
railway_name=銀座線
status=delay / status_label=遅延 / severity=2
description=16時23分頃、上野駅で車両点検のため、遅れが出ています。
```

---

## 3. 構文チェック

```text
node --check frontend/js/live-stream/live-stream-main.js                 OK
node --check frontend/js/live-stream/live-stream-scene.js                OK
node --check frontend/js/live-stream/live-stream-railway-adapter.js      OK
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
Phase Stream-2-B.1 earthquake adapter: 6/6 PASS
```

**32/32 PASS** ✅

### `e2e/eq-mock-verify.spec.js`

```text
5/5 PASS
```

### `e2e/rain-mock-verify.spec.js`

```text
6/6 PASS
```

### `e2e/tide-mock-verify.spec.js`

```text
6/6 PASS
```

### `e2e/rail-mock-verify.spec.js`

| 検証項目 | 結果 |
|---|---|
| 影響0件: ct-rail=0 / empty表示 / page error なし | ✅ PASS |
| 遅延1件: list / line name / status / ct-rail=1 | ✅ PASS |
| 優先順位: suspended が delay より先頭 | ✅ PASS |
| API 500: ct-rail=`-` / unavailable表示 / JS console.error なし | ✅ PASS |
| `status: unavailable`: ct-rail=`-` / unavailable表示 | ✅ PASS |
| 不正JSON: page error なし / console error なし | ✅ PASS |
| normal item除外: severity=0を表示せず delay のみ表示 | ✅ PASS |

**7/7 PASS** ✅

合計: **56/56 PASS** ✅

---

## 7. demo / mock モード仕様

| パラメータ | 鉄道動作 |
|---|---|
| `?demo=1` | 実データ取得スキップ。`SCENES.alert.rail` デモ固定 |
| `?state=calm` | `SCENES.calm`。影響路線なし / 平常運転 |
| `?state=alert` | `/api/live/trains/summary` を取得。成功時はODPT由来の影響路線を表示 |
| `?demoNow=ISO8601` | 時計固定。E2E安定化用 |

---

## 8. 実データ接続確認

✅ **PASS**

- `/live/stream?chrome=off` で train summary API fetch が実行される
- 実データ応答は `status=ok`, `source=ODPT`
- 検証時点で銀座線の遅延1件が取得された
- `severity > 0` の項目だけを影響路線として表示
- ヘッダー `ct-rail` は影響路線数
- 影響なし時は `影響路線なし / 平常運転`
- 取得失敗時は `一時的に取得不可`

---

## 9. 影響あり表示確認

✅ **PASS**

- 鉄道小窓に影響路線カード表示
- 路線名表示: `live-stream-rail-line-name`
- 状態表示: `live-stream-rail-status`
- 区間/理由表示: `live-stream-rail-section`
- 更新時刻表示: `updatedAt` がある場合に `HH:MM`
- 路線色バー表示
- 簡略路線図では `RAIL_LINES_BASE` に map できる路線のみ強調
- `undefined` / `null` / `NaN` / `Invalid Date` / `[object Object]` 表示なし

Note: ODPT路線名が `RAIL_LINES_BASE` に対応しない場合でもカード側には表示され、簡略路線図は控えめ表示に留まる。

---

## 10. 影響なし表示確認

✅ **PASS** (mock ベース)

- API成功 + `items: []`
- `ct-rail` = `0`
- 鉄道小窓: `影響路線なし / 平常運転`
- 右側簡略路線図は控えめ表示
- 取得失敗扱いにならない
- console/page error なし

---

## 11. 取得失敗表示確認

✅ **PASS** (mock ベース)

- HTTP 500 → `_railStatus='error'`
- `status: unavailable` → adapter が `status='error'`
- `ct-rail` = `-`
- 鉄道小窓: `一時的に取得不可`
- page error なし
- JS `console.error` なし
- `平常運転` / `影響路線なし` と断定しない

---

## 12. 地図上ポップアップ非表示確認

✅ **PASS**

- `live-stream-panels.js` の鉄道小窓は `renderMap(..., { rail })` のみ
- ポップアップDOMを生成しない
- 駅名や路線名ラベルの大量表示なし
- 情報は左側カードに集約

---

## 13. ヘッダー鉄道件数確認

| 状態 | 表示 |
|---|---|
| 影響あり | `1` 以上 ✅ |
| 影響なし | `0` ✅ |
| API 500 / 不正JSON / unavailable | `-` ✅ |
| normal / severity=0 のみ | `0` ✅ |
| demo モード | デモ影響路線数 ✅ |

件数はODPT対応範囲内の `severity > 0` の影響路線数。

---

## 14. 中央地図パルス確認

✅ **PASS with notes**

- 影響あり時は `live-stream-pulse-rail` が表示される
- calm / 影響なし時は鉄道パルスなし
- 地震・豪雨・潮位の既存パルスはE2E継続PASS

Note: Phase 2-B.4 では鉄道パルスは必須ではない。現状はデモ/影響あり時に簡易位置のパルスを出すが、地図上ポップアップは出さない。

---

## 15. スクリーンショット

| ファイル | 内容 |
|---|---|
| `test-results/live-stream-phase2b4-rail-demo-1920.png` | `state=alert&demo=1` / 1920×1080 |
| `test-results/live-stream-phase2b4-rail-calm-1920.png` | `state=calm` / 1920×1080 |
| `test-results/live-stream-phase2b4-rail-live-1920.png` | `?chrome=off` 実データ / 1920×1080 |

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

1. ODPT対応範囲は限定的。APIに入る範囲の影響路線のみ表示する。
2. 路線ジオメトリは配信用の簡略SVG。ODPT全路線の地理形状表示は対象外。
3. `RAIL_LINES_BASE` に対応しない路線はカード表示が主で、簡略路線図の強調は限定的。
4. 鉄道パルスは簡易位置表示。地図上ポップアップは表示しない。
5. テロップ動的化は最小対応または未対応。Phase 2-C 以降の対象。

---

## 修正推奨事項

- ODPT路線名から `RAIL_LINES_BASE` への対応表を段階的に拡張する。
- 実データ由来の鉄道テロップを追加する。
- `updatedAt` や operator 名の表示ルールを必要に応じて整理する。

---

## PASS 条件照合

| 条件 | 結果 |
|---|---|
| `/live/stream` が表示できる | ✅ |
| 既存 dedicated E2E が PASS | ✅ |
| 地震 E2E が PASS | ✅ |
| 豪雨 E2E が PASS | ✅ |
| 潮位 E2E が PASS | ✅ |
| 鉄道デモ表示 E2E が PASS | ✅ |
| 既存 `/live` の鉄道データ取得口を利用 | ✅ `/api/live/trains/summary` |
| 影響あり時に鉄道小窓へ反映 | ✅ |
| 影響なし時に平常表示 | ✅ |
| ヘッダー鉄道件数が仕様通り表示 | ✅ |
| 地図上ポップアップが表示されない | ✅ |
| 取得失敗時に平常と断定しない | ✅ |
| console/page error なし | ✅ |
| `/live` が壊れていない | ✅ |
| `/` が壊れていない | ✅ |

---

## 次フェーズ候補

- Phase 2-C: テロップ全カテゴリ動的化
- Phase 2-D: 中央地図の投影精度改善
- Phase 2-E: 配信用表示プリセット / OBS 運用調整
