# /live/stream Phase Stream-2-B.1 地震情報実データ接続 MVP — 検証レポート

## 判定: PASS with notes

---

## 検証日時

2026-07-02 20:40 JST

## 対象ブランチ / コミット

- branch: main (untracked 新規ファイル群)
- base commit: ba6f7bd

---

## 変更ファイル

| ファイル | 区分 | 内容 |
|---|---|---|
| `frontend/js/live-stream/live-stream-earthquake-adapter.js` | **新規** | /live APIレスポンス → stream ViewModel 変換 |
| `frontend/js/live-stream/live-stream-scene.js` | 更新 | `buildScene()` を実データ・demo・error 対応に拡張 |
| `frontend/js/live-stream/live-stream-main.js` | 更新 | `?demo=1` 対応・`_fetchEq()` ループ追加 |
| `frontend/js/live-stream/live-stream-panels.js` | 更新 | testid 追加・popup 詳細・件数・ticker 対応 |
| `frontend/live/stream.html` | 更新 | adapter スクリプトタグ追加 |
| `e2e/live-stream.spec.js` | 更新 | `demo=1` 追加・Phase 2-B.1 テスト 6 件追加 |

既存 `/live` ファイル変更: **ゼロ**  
既存 `/` ファイル変更: **ゼロ**  
backend 変更: **ゼロ**

---

## 1. 静的確認

- `/live/stream` 専用ファイルのみ変更 ✅
- `/live` 本体への影響なし ✅
- `buildScene()` 差し替え口維持 ✅
- `EarthquakeStreamAdapter` が adapter 責務を担う ✅
- `?demo=1` パラメータで実データ取得スキップ ✅

スコープ逸脱なし。キキクル・鉄道・潮位の実データ接続は未対応（対象外）。

---

## 2. 不要な大改修確認

- backend API 追加: なし ✅
- DB 追加: なし ✅
- /live 本体リファクタ: なし ✅
- キキクル・鉄道・潮位の実データ接続: なし ✅

---

## 3. 構文チェック

```
node --check frontend/js/live-stream/live-stream-main.js   → OK
node --check frontend/js/live-stream/live-stream-scene.js  → OK
node --check frontend/js/live-stream/live-stream-earthquake-adapter.js → OK
node --check frontend/js/live-stream/live-stream-panels.js → OK
node --check frontend/js/live-stream/live-stream-map.js    → OK
node --check frontend/js/live-stream/live-stream-clock.js  → OK
node --check frontend/js/live-stream/live-stream-ticker.js → OK
node --check e2e/live-stream.spec.js → OK
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

### Phase Stream-2-A 既存テスト (8件)

```
✓ calm view shows the full broadcast layout and no active target
✓ alert view shows category panels and center pulses
✓ demoNow freezes header and center clocks
✓ clock updates when demoNow is absent
✓ tide current marker position changes with demoNow
✓ chrome=off hides development controls only
✓ /live regression has no stream CSS/DOM leakage
✓ / regression has no stream CSS/DOM leakage
```

**8/8 PASS** ✅

### Phase Stream-2-B.1 新規テスト (6件)

```
✓ demo=1 alert view shows stable earthquake demo data
✓ calm state suppresses earthquake display regardless of demo flag
✓ earthquake status testid is visible in alert demo mode
✓ earthquake history items have testid in alert demo mode
✓ earthquake popup shows active target in alert demo mode
✓ calm state shows no earthquake pulse on center map
```

**6/6 PASS** ✅

**合計 14/14 PASS** ✅

---

## 7. mock ベース詳細検証 (e2e/eq-mock-verify.spec.js)

| 検証項目 | 結果 |
|---|---|
| 0件表示: `現在 対象なし` / ct-eq=0 / パルスなし | ✅ PASS |
| 12時間フィルタ: cutoff外(06:00)が除外される | ✅ PASS |
| activeTarget 優先順位: 震度5弱 > 震度3 (M高くても) | ✅ PASS |
| API 500 → ヘッダー '-' / page error なし / JS console.error なし | ✅ PASS |
| 不正JSON → page error なし / console error なし | ✅ PASS |

**5/5 PASS** ✅

---

## 8. 実データ接続確認

### /live 地震データ取得口

`live-stream-main.js` の `_fetchEq()` が `/api/live/earthquakes/history?days=1` を直接呼ぶ。

- このエンドポイントは `backend/app/api/live_earthquakes.py` が担い、`GET /api/live/earthquakes/history` として提供
- P2P地震情報 → JMA fallback の既存ロジックをそのまま再利用
- 新規 JMA 直接アクセス・新規 API: **なし**
- 既存 `/live` の `live-layers.js` と同一エンドポイントを使用 ✅

### 実データ確認 (`/live/stream?chrome=off`)

- API fetch 実行: ✅ (Network ログで `/api/live/earthquakes/history?days=1` 呼び出し確認)
- 検証時API応答: `source=p2p`, `fallback=false`, `count=11`
- 地震あり時: 地震小窓に反映 ✅
- 中央地図パルス: 実座標由来の位置に表示 ✅
- ヘッダー件数: 実数値 ✅
- console error: なし ✅

---

## 9. demo / mock モード仕様

| パラメータ | 動作 |
|---|---|
| `?demo=1` | 実データ取得スキップ。SCENES.alert デモシーン固定。E2E 安定化用 |
| `?state=calm` | 実データに関わらず SCENES.calm 固定 |
| `?state=alert`（デフォルト） | 実データ取得を試みる。取得成功 → 実データ表示。取得失敗 → error 状態（ヘッダー '-'、デモ表示） |
| `?demoNow=ISO8601` | 時計固定 + 12時間判定の基準時刻 |

---

## 10. 0件表示確認

✅ **PASS**

- `EarthquakeStreamAdapter.build()` が空配列 → `targets: []`, `statusCount: 0`
- `render()` が `eqOn = false` → `現在 対象なし` 表示
- `ct-eq` = `0`
- 中央地図: 地震パルスなし
- console error: なし

---

## 11. 取得失敗表示確認

✅ **PASS**

- HTTP 500 時: `_eqStatus = 'error'` → `buildScene()` が `earthquake: { ...base.earthquake, status: 'error' }` を返す
- `render()` で `eq.status === 'error'` → `ct-eq` = `'-'`
- 地震小窓: `一時的に取得不可` (`live-stream-earthquake-status`)
- page error: なし
- JS console.error: なし（`console.warn` のみ使用）

**「地震なし」と断定しない** ✅

---

## 12. 12時間フィルタ確認

✅ **PASS** (mock ベース確認)

- `demoNow = 2026-06-30T19:42:00+09:00` のとき cutoff = 07:42
- A: 19:21 → 表示対象 ✅
- B: 08:00 → 表示対象 ✅
- C: 06:00 → 除外 ✅
- ct-eq = 2 ✅

---

## 13. activeTarget 優先順位確認

✅ **PASS** (mock ベース確認)

優先順位:
1. 最大震度が高い（5弱 > 3）
2. マグニチュードが大きい（同震度時）
3. 発生時刻が新しい（同M時）

検証: 震度3/M6.5 vs 震度5弱/M5.0 → 震度5弱が選択 ✅

---

## 14. 中央地図パルス確認

- `live-stream-pulse-earthquake` testid: alert時に表示 ✅
- calm時: 非表示 ✅
- 色: `var(--c-eq)` (赤系) ✅
- 位置: `EarthquakeStreamAdapter._latLonToSvg()` による簡易投影
  - 基準点: 東京 (35.7N, 139.7E) → SVG (582, 500)
  - 東北地震 (39-40N) → SVG y ≈ 360-395 (上部 = 正しい方向) ✅
  - 九州地震 (32-33N) → SVG y ≈ 605-640 (下部 = 正しい方向) ✅

---

## 15. ヘッダー地震件数確認

| 状態 | 表示 |
|---|---|
| 実データ 12h N件 | `N` |
| 実データ 0件 | `0` |
| API 500 / 不正JSON | `-` |
| demo モード (SCENES.alert) | `2`（targets 数） |

✅ 全ケース正常

---

## 16. スクリーンショット

| ファイル | 内容 |
|---|---|
| `test-results/live-stream-phase2b1-earthquake-demo-1920.png` | state=alert&demo=1 / 1920×1080 |
| `test-results/live-stream-phase2b1-earthquake-calm-1920.png` | state=calm / 1920×1080 |
| `test-results/live-stream-phase2b1-earthquake-live-1920.png` | ?chrome=off（実データ） / 1920×1080 |

3件保存済み ✅

---

## 17. /live 回帰確認

- HTTP 200 ✅
- console/page error なし ✅
- `ls-stage` DOM 未混入 ✅
- `live-stream.css` リンク未混入 ✅
- live-stream.spec.js のリグレッションテスト PASS ✅

---

## 18. / 回帰確認

- HTTP 200 ✅
- console/page error なし ✅
- `ls-stage` DOM 未混入 ✅
- `live-stream.css` リンク未混入 ✅

---

## Notes

1. **12時間フィルタは adapter 側で実装**。`/api/live/earthquakes/history?days=1` は24時間分を返し、adapter 側で demoNow 基準の12時間フィルタを適用する設計。

2. **activeTarget 選択は簡易実装**。震度 → M → 時刻の優先順で実装。複数対象の8秒巡回は Phase 2-A の枠組みを継承しているが、地震実データ時は常に最優先地震1件のみ targets に含む（現状）。

3. **中央地図の座標は概算**。`EarthquakeStreamAdapter._latLonToSvg()` は線形近似 (25px/deg, -35px/deg)。厳密な Mercator 投影は次フェーズ以降。

4. **テロップは最小対応**。実データ地震がある場合、テロップ先頭に `【地震】HH:MM 震源名 M6.1 最大震度5弱` を付加。テロップ全体の動的化は Phase 2-C 以降。

5. **mock 検証ファイルの保持**。`e2e/eq-mock-verify.spec.js` は検証用として残す。CI に含める場合は `playwright.config.js` のインクルード設定を調整すること。

6. **API 500 時の "Failed to load resource" コンソールメッセージ**はブラウザ組み込み動作。JS コードからの `console.error` 呼び出しはゼロ。

---

## 修正推奨事項

- なし（PASS with notes 範囲内）

---

## PASS 条件照合

| 条件 | 結果 |
|---|---|
| /live/stream が表示できる | ✅ |
| 既存 dedicated E2E が PASS | ✅ 8/8 |
| 地震デモ表示 E2E が PASS | ✅ 6/6 |
| 実データ取得口が既存 /live 資源を利用 | ✅ `/api/live/earthquakes/history` |
| 地震データあり時に地震小窓へ反映 | ✅ |
| 地震データあり時に中央地図パルスへ反映 | ✅ |
| 地震件数がヘッダーへ反映 | ✅ |
| 地震0件時に正常な対象なし表示 | ✅ |
| 取得失敗時に「なし」と断定しない | ✅ 「一時的に取得不可」 |
| console/page error なし | ✅ |
| /live が壊れていない | ✅ |
| / が壊れていない | ✅ |

---

## 次フェーズ候補

- Phase 2-B.2: キキクル・豪雨情報 実データ接続
- Phase 2-B.3: 中央地図の Mercator 投影精度改善
- Phase 2-C: テロップ全カテゴリ動的化
- Phase 3-A: 複数対象地震の activeTarget 巡回UI改善
