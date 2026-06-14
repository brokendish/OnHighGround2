# Phase 7-A 鉄道運行影響レイヤー MVP CODEX検証

## 判定

PASS with notes

## 検証環境

- date: 2026-06-14
- branch: main
- commit: 75a005c
- docker compose status:
  - backend: Up / healthy
  - frontend: Up
  - martin: Up / healthy
  - osrm-walking: Up

## 確認項目

- backend compile: PASS
- docker health: PASS
- API確認: PASS
- 正規化確認: PASS
- UI確認: PASS
- 地図レイヤー確認: PASS with notes
- 都道府県選択確認: PASS
- モバイル確認: PASS
- 既存回帰確認: PASS

## 結果詳細

### バックエンド

- `python3 -m compileall backend`: PASS
- `venv/bin/python -m pytest tests/test_live_train_service.py tests/test_live_train_api.py`: 62 passed
- `/health`: HTTP 200, backend healthy
- `/api/live/trains/summary`: HTTP 200
- APIキー未設定時は `status: unavailable`, `items: []` を返す。
- `lat/lng` 指定時も `scope: { mode: "location", prefecture: "東京都" }` を保持することを確認。
- `prefecture=東京都`, `大阪府`, `福岡県` で HTTP 200 と scope 維持を確認。

### 正規化

- 遅延: `status=delay`, `severity=2`
- 一部運休: `status=partial_suspension`, `severity=3`
- 運転見合わせ: `status=suspended`, `severity=4`
- 平常: `normalize_odpt_item()` でカード対象外
- 取得失敗/APIキー未設定: `status=unavailable`, `items=[]`
- stale cache: 取得失敗時に既存 cache があれば `stale=true`

### フロントエンド

- `e2e/live-train-layer.spec.js`: 5 passed
- `e2e/live-basic.spec.js`: 73 passed
- 交通影響カード表示、障害あり路線のみ表示、severity 順表示を確認。
- 障害なし文言と取得失敗文言が分離されていることを確認。
- 都道府県選択で `/api/live/trains/summary?prefecture=...` が再取得されることを確認。
- 鉄道運行影響レイヤー ON/OFF とポップアップ表示を確認。
- モバイル幅で横スクロールが発生しないことを確認。

## 発見した問題と対応

- `live-main.js` が `liveTrainPanel.refresh()` を呼ぶ前に `live-train-panel.js` が読み込まれておらず、初期表示で ReferenceError になり得る依存順だった。
  - `frontend/live.html` の script 順を修正。
- APIキー未設定など取得不可時に、位置/都道府県指定の `scope` が空になっていた。
  - `unavailable` レスポンスにも `_apply_scope()` を適用。
- 地図レイヤーが API item に座標がない場合に何も描画しない状態だった。
  - 事業者の対応都道府県代表点から MVP 用代表座標を付与。
- Leaflet map が `preferCanvas: true` のため、状態別 class/style の検証が難しかった。
  - 鉄道レイヤーのみ SVG renderer を明示し、`train-line-*` class を付与。
- ポップアップが出典・更新時刻を表示しておらず、値欠落時に `undefined` が出る余地があった。
  - HTMLエスケープと fallback 表示を追加。
- 既存 `live-basic.spec.js` が新 API をモックしておらず 404 console error が発生した。
  - 鉄道 API の標準モックを追加。

## 修正提案

- MVPでは路線形状ではなく代表地点 CircleMarker 表示。将来フェーズでは ODPT railway shape または軽量タイル化済み鉄道路線データで線形状に置き換える余地あり。
- ODPT_API_KEY が設定された環境で、実データ取得と stale cache の実通信系確認を追加するとさらに確度が上がる。

## スクリーンショット

- 自動スクリーンショットは未添付。Playwright DOM 検証で代替。

## 最終結論

Phase 7-A MVP は、災害時の行動判断支援レイヤーとして成立している。取得不可と障害なしは区別され、首都圏固定ではなく都道府県 scope を保持し、既存 `/live` 基本機能にも回帰は見られない。
