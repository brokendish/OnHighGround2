# Phase 7-B.2 JARTIC交通量観測点レイヤー MVP — CODEX検証レポート

## 判定

PASS

## 検証日時

2026-06-29 23:36 JST

追記: 2026-06-30 00:08 JST 頃、OnHighGround2 本体地図で実データのマーカー表示とポップアップ表示を画面確認済み。

## 検証環境

- ブランチ: `main`
- コミット: `ffe3bda`
- 作業ディレクトリ: `/Users/hideki/Documents/GitHub/OnHighGround2`
- Python: `venv/bin/python`
- E2E: Playwright Chromium

## 変更ファイル一覧

- `backend/main.py`
- `backend/app/api/jartic_traffic.py`
- `backend/app/services/jartic_traffic_service.py`
- `frontend/index.html`
- `frontend/js/map-overlay-ui.js`
- `frontend/js/jartic-traffic-layer.js`
- `tests/test_jartic_traffic_service.py`
- `e2e/jartic-traffic-layer.spec.js`

## APIキー不要対応の確認結果

- `/api/jartic/traffic` は `JARTIC_API_KEY` 未設定でも取得処理へ進む。
- `x-api-key` ヘッダは送信しない。
- APIキー未設定を理由に `unavailable` を返す分岐はない。
- 取得失敗時のみ `status: "unavailable"` を返す。
- 実APIでも APIキーなしで交通量観測点データを取得し、地図表示できることを確認済み。

補足:

- 既存 `/live` 道路交通量サービスには、過去フェーズ由来の `ROAD_TRAFFIC_API_KEY` / `x-api-key` 前提が残っている。今回の本体側 MVP とは別実装のため本修正対象外としたが、JARTIC APIキー不要方針を全体へ反映する場合は別途整理が必要。

## Backend API確認結果

- `GET /api/jartic/traffic` を追加。
- レスポンス形式は `status/source/updated_at/items/message`。
- JARTIC WFS の `cql_filter` は日本語フィールド名をクォートしない構文を使用する。
- 座標なし、観測点コードなしの Feature は除外。
- `0` は欠損扱いせず `0` として保持。
- 欠損値は `null` として保持。
- `total` は上り・下りの両方がある場合のみ算出。
- DB / PostgreSQL / 履歴保存 / 変化率算出は追加していない。

## キャッシュ確認結果

モック取得で以下を生成確認。

- `data_runtime/backend/jartic/latest_traffic.json`
- `data_runtime/backend/jartic/manifest.json`

`manifest.json` は `status/source/updated_at/saved_at/item_count/snapshot` を保持。日付別・時刻別の履歴ファイルは作成しない。

## Frontend表示確認結果

- OnHighGround2本体のレイヤーパネルに `交通量観測点` トグルを追加。
- 初期状態は OFF。
- ON で `/api/jartic/traffic?bbox=...` を呼び、マーカーを描画。
- OFF で JARTIC 観測点マーカーを消去。
- 本体地図の `map` 参照に合わせ、`window.map` ではなく global `map` も参照するよう修正。
- 実画面で水色の CircleMarker が複数表示されることを確認。

## BBOX表示確認結果

- フロントは現在の地図表示範囲から BBOX を生成し、API に `bbox` パラメータを付与する。
- バックエンドは `bbox=min_lng,min_lat,max_lng,max_lat` で `items` を絞り込む。
- E2E で BBOX パラメータ付与と空配列時のマーカー非表示を確認。

## ポップアップ確認結果

以下の表示を E2E で確認。

- `交通量観測点`
- `上り`
- `下り`
- `合計`
- `小型`
- `大型`
- `観測時刻`
- `観測点コード`
- `出典: JARTIC / 国土交通省交通量API`

時刻表示は `yyyy-mm-dd hh:mm` 形式。`0` は `0台` と表示される。欠損値は `-` 表示。

実画面で以下の表示を確認。

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

## 表示文言確認結果

JARTIC観測点レイヤーのユーザー向け表示では、交通量を渋滞・混雑・規制・通行止め・事故として断定していない。

## `/live` 影響確認結果

- `/live.html` に `jartic-traffic-toggle` が存在しないことを E2E で確認。
- 今回の本体側 JARTIC 観測点 UI は `/live` に追加していない。

## 既存機能回帰確認結果

専用 E2E 上で本体初期表示、地図初期化、レイヤーパネル表示、`/live.html` 初期表示の範囲を確認。Docker compose 全体起動・既存全E2Eは今回未実行。

## 実行したコマンド

```bash
sed -n '1,240p' docs/live/DEVELOPMENT_GUARDRAILS.md
node --check frontend/js/jartic-traffic-layer.js
python3 -m compileall backend/app/services/jartic_traffic_service.py backend/app/api/jartic_traffic.py
venv/bin/python -m pytest -q tests/test_jartic_traffic_service.py
npx playwright test e2e/jartic-traffic-layer.spec.js
env JARTIC_TRAFFIC_USE_MOCK=true venv/bin/python -c "import asyncio, sys; sys.path.insert(0, 'backend'); from app.services.jartic_traffic_service import get_traffic_observations; r=asyncio.run(get_traffic_observations()); print(r['status'], len(r['items']))"
find data_runtime/backend/jartic -maxdepth 2 -type f -print
python3 -m json.tool data_runtime/backend/jartic/manifest.json
```

## テスト結果

- `venv/bin/python -m pytest -q tests/test_jartic_traffic_service.py`: 19 passed
- `npx playwright test e2e/jartic-traffic-layer.spec.js`: 12 passed
- `node --check frontend/js/jartic-traffic-layer.js`: passed
- `python3 -m compileall backend/app/services/jartic_traffic_service.py backend/app/api/jartic_traffic.py`: passed

## スクリーンショット保存先

実画面確認:

- `/Users/hideki/Library/Mobile Documents/com~apple~CloudDocs/スクリーンショット/スクリーンショット 2026-06-30 0.08.28.png`

失敗時の Playwright artifacts は `test-results/` に一時生成。

## 発見した問題と修正

1. `manifest.json` が未作成だったため、最新スナップショット用 manifest を保存するよう修正。
2. 本体地図は global `map` であり `window.map` ではなかったため、JARTICレイヤーの地図参照を `map` / `window.map` 両対応に修正。
3. ポップアップ時刻が `MM/DD HH:mm` だったため、`yyyy-mm-dd hh:mm` 形式へ修正。
4. ポップアップ内の任意値を HTML エスケープするよう修正。
5. E2E の操作対象が非表示 checkbox に寄っていたため、レイヤー公開APIと DOM event を同期する形で安定化。
6. JARTIC WFS API の `cql_filter` で日本語フィールド名をダブルクォートすると API Gateway が JSON として誤解析し HTTP 400 になるため、`時間コード=...` / `BBOX(ジオメトリ,...)` のクォートなし構文へ修正。

## 次に確認すべきこと

- 観測点数と応答サイズを継続確認する。
- 既存 `/live` 道路交通量サービスの `ROAD_TRAFFIC_API_KEY` / `x-api-key` 前提を、別タスクで APIキー不要方針へ合わせるか判断する。
