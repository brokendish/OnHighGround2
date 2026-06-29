# Phase 7-B.2 JARTIC交通量観測点レイヤー MVP — 実装レポート

## 最終確認結果

判定: PASS

2026-06-30 00:08 JST 頃、OnHighGround2 本体地図上で実データの交通量観測点マーカー表示を画面確認済み。

確認スクリーンショット:

- `/Users/hideki/Library/Mobile Documents/com~apple~CloudDocs/スクリーンショット/スクリーンショット 2026-06-30 0.08.28.png`

画面上で確認できた内容:

- 地図上に水色の CircleMarker が複数表示される
- マーカークリックで「交通量観測点」ポップアップが表示される
- 上り・下り・合計・小型・大型・観測時刻・観測点コード・集計単位・データ種別・出典が正常表示される
- 交通量を渋滞・混雑・規制・通行止め・事故として断定する文言は表示されない

実表示例:

```text
交通量観測点
上り: 46台
下り: 37台
合計: 83台
小型: 55台
大型: 13台
観測時刻: 2026-06-29 23:40
観測点コード: 3110610
集計単位: 5分値
データ種別: 一般国道
出典: JARTIC / 国土交通省交通量API
```

### 実API疎通時の重要メモ

JARTIC WFS API の `cql_filter` では、日本語フィールド名をダブルクォートで囲まない。

NG:

```text
"時間コード"=YYYYMMDDHHMI AND BBOX("ジオメトリ",...)
```

OK:

```text
時間コード=YYYYMMDDHHMI AND BBOX(ジオメトリ,...,'EPSG:4326')
```

ダブルクォート付きの CQL は API Gateway 側で JSON として誤解析され、HTTP 400 になることがある。現在の実装はクォートなし構文を使用している。

## 変更ファイル一覧

| ファイル | 種別 |
|---|---|
| `backend/app/services/jartic_traffic_service.py` | 新規作成 |
| `backend/app/api/jartic_traffic.py` | 新規作成 |
| `backend/main.py` | 追記（import + include_router） |
| `frontend/js/jartic-traffic-layer.js` | 新規作成 |
| `frontend/js/map-overlay-ui.js` | 追記（交通量観測点セクション） |
| `frontend/index.html` | 追記（script タグ） |
| `tests/test_jartic_traffic_service.py` | 新規作成 |
| `e2e/jartic-traffic-layer.spec.js` | 新規作成 |

---

## Backend 実装内容

### `jartic_traffic_service.py`

- JARTIC WFS 2.0.0 API (`t_travospublic_measure_5m`) から交通量観測点データを取得
- **APIキー不要**: `x-api-key` ヘッダーなしでリクエスト送信
  - 取得成功 → `status: "ok"`
  - 通信失敗・パースエラー時のみ → `status: "unavailable"`
- データ正規化: Feature 1件 → 観測点 1件（上り・下りを統合）
  - `up` = 上り(小型+大型+判別不能)
  - `down` = 下り(小型+大型+判別不能)
  - `total` = up + down（片方欠損時は null）
  - `small` = 上り小型+下り小型
  - `large` = 上り大型+下り大型
  - 欠測フラグ "1" の方向は null
  - 0台は有効値として保持
- メモリキャッシュ: TTL 300秒（5分）
- ファイルキャッシュ: `data_runtime/backend/jartic/latest_traffic.json`（最新スナップショットのみ、履歴なし）
- マニフェスト: `data_runtime/backend/jartic/manifest.json`
- テスト用モック: `JARTIC_TRAFFIC_USE_MOCK=true` で即時返却

### `jartic_traffic.py`

- エンドポイント: `GET /api/jartic/traffic`
- クエリパラメータ: `bbox=min_lng,min_lat,max_lng,max_lat`（省略時は全件）
- 取得失敗時も HTTP 200 で `status: "unavailable"` を返す

### `backend/main.py`

- `jartic_traffic_router` を import して `app.include_router()` に追加

---

## APIキー不要対応の内容

### 変更前（既存の live_road_traffic_service.py の問題）

```python
if not api_key:
    raise ValueError("ROAD_TRAFFIC_API_KEY not set")
```

APIキー未設定で即 unavailable になっていた。

### 今回の jartic_traffic_service.py の実装

```python
# APIキー不要 — リクエストヘッダーに x-api-key を含めない
headers = {"User-Agent": "OnHighGround2/jartic-traffic-observation-layer"}
req = Request(url, headers=headers)
```

- `JARTIC_API_KEY` 環境変数の確認ロジックをそもそも持たない
- 取得を試み、失敗したときのみ unavailable

---

## キャッシュ仕様

| 項目 | 仕様 |
|---|---|
| 方式 | メモリキャッシュ（プロセス内変数） |
| TTL | 300秒（5分） |
| スナップショット | `data_runtime/backend/jartic/latest_traffic.json` |
| マニフェスト | `data_runtime/backend/jartic/manifest.json` |
| 履歴 | なし（上書きのみ） |
| DB | なし |
| ファイル増加 | なし（`latest_traffic.json` / `manifest.json` のみ） |

---

## Frontend 実装内容

### `jartic-traffic-layer.js`

- `L.layerGroup()` + `L.circleMarker()` で観測点を描画
- 地図の現在表示範囲 BBOX を `map.getBounds()` から生成し `?bbox=` として送信
- 地図移動・ズーム時（`moveend`/`zoomend`）に自動リフレッシュ
- 初期状態は非表示（`_jtVisible = false`）
- 公開 API:
  - `showJarticTrafficLayer()` / `hideJarticTrafficLayer()`
  - `isJarticTrafficLayerVisible()` / `refreshJarticTrafficLayer()`

### マーカーデザイン

- 水色 CircleMarker（`#42a5f5`）、輪郭色 `#1565c0`
- 赤・オレンジなどの危険色を使用しない
- 「渋滞」「混雑」「規制」等の文言は一切含まない

### `map-overlay-ui.js`

- レイヤーパネルの末尾に「交通情報（補助）」セクションを追加
- チェックボックス（`id="jartic-traffic-toggle"`）ON/OFF で表示切替

### `index.html`

- `<script src="js/jartic-traffic-layer.js"></script>` を末尾に追加

---

## ポップアップ表示内容

```
交通量観測点

上り:    320台
下り:    280台
合計:    600台

小型:    520台
大型:     80台
観測時刻: 2026-06-29 09:55
観測点コード: T001

出典: JARTIC / 国土交通省交通量API
```

- 欠損値は `-` と表示
- 0台は `0台` と表示（欠損扱いにしない）
- `unit` / `type` が取得できた場合のみ「集計単位」「データ種別」行を追加

---

## 今回やっていないこと

- 道路名推定・OSM道路との最近傍マッチング
- 交通量履歴の保存
- 通常比 / 変化率の算出
- 交通量ランキング
- `/live` 側での本格表示
- 通行止め・渋滞・規制・事故情報としての表示
- 道路ネットワーク形状の取得・描画
- PostgreSQL 等 DB の利用

---

## テスト結果

### pytest（ユニットテスト）

```
tests/test_jartic_traffic_service.py — 19件 PASS（0 failed）

- test_normalize_feature_basic
- test_normalize_feature_zero_is_valid
- test_normalize_feature_no_coords_returns_none
- test_normalize_feature_no_code_returns_none
- test_normalize_feature_missing_direction_is_none
- test_normalize_feature_both_missing_up_down_null
- test_filter_bbox_inside / outside / none_returns_all
- test_get_observations_ok_with_mock
- test_get_observations_no_api_key_still_tries
- test_get_observations_fetch_failure_returns_unavailable
- test_get_observations_bbox_filters
- test_mock_zero_traffic_preserved
- test_snapshot_file_created
- test_no_history_files_accumulated
- test_build_wfs_url_no_api_key
- test_build_wfs_url_has_time_code
- test_source_in_response
```

### E2E（Playwright）

`e2e/jartic-traffic-layer.spec.js` — 12件 PASS（0 failed）

- 交通量観測点トグルがレイヤーパネルに存在する
- 初期状態は OFF
- トグル ON で `/api/jartic/traffic` が呼ばれる
- bbox パラメータ付きリクエストが送られる
- トグル OFF でマーカーが消える
- ポップアップに「交通量観測点」が含まれる
- unavailable のとき マーカーは 0 件
- items=[] のとき マーカーは 0 件
- `/live` 側にトグルが存在しない
- 0台の観測点もマーカーとして描画される
- ポップアップに禁止文言（渋滞等）が含まれない

---

## 既知の制約

- JARTIC 交通量 API は公開型オープンデータとして APIキーなしで疎通確認済み
- 観測から約20-25分のラグがある（APIの仕様）
- backend 側の WFS リクエストでも BBOX 条件を使用する
- `/live` への本格表示は今回のスコープ外

---

## 次に確認すべきこと

1. 取得できる観測点数と応答サイズの継続確認
2. 観測点の座標精度・実地確認
3. `/live` への本格組み込みを行う場合は、既存の `live_road_traffic_service.py` の APIキー必須判定も同様に修正する
