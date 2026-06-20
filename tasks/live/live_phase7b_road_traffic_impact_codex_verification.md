# Phase 7-B 道路交通影響レイヤー MVP CODEX検証

## 判定

**PASS with notes**

Phase 7-B の API 契約、正規化、取得不可とデータなしの分離、カード、レイヤー ON/OFF、マーカー、ポップアップ、注意書き、モバイル表示を確認した。実ブラウザ確認で交通カードが固定地図の背面に隠れる問題を発見し、交通カードコンテナを地図前面へ配置して修正した。

notes:

- `ROAD_TRAFFIC_API_KEY` は検証環境に未設定。このため実データ取得は未検証で、実 HTTP は安全に `status=unavailable` を返した。
- 閾値は絶対交通量による暫定値。平常時交通量との比較は未実装。
- 全 `/live` E2E は 277 件中 268 件成功。残る9件は旧テストが追加 API をモックせず、静的E2Eサーバーの404を console error として検出する同一のテストハーネス要因。Phase 7-B 専用11件と鉄道回帰5件は全成功した。

## 検証環境

- date: 2026-06-20 08:51 JST（検証開始時）
- branch: `main`
- commit: `e2bb440`
- backend: healthy
- frontend: up
- Martin: healthy
- OSRM walking: up

## 実施コマンド

```bash
python3 -m compileall backend
node --check frontend/js/live/live-road-traffic-layer.js
node --check frontend/js/live/live-road-traffic-panel.js
venv/bin/python -m pytest -q tests/test_live_road_traffic_service.py tests/test_live_road_traffic_api.py
docker compose ps
docker compose restart backend
curl -s -i http://127.0.0.1:8000/api/live/road-traffic/summary
curl -s --get --data-urlencode 'prefecture=東京都' http://127.0.0.1:8000/api/live/road-traffic/summary
curl -s --get --data-urlencode 'prefecture=大阪府' http://127.0.0.1:8000/api/live/road-traffic/summary
npx playwright test e2e/live-road-traffic-layer.spec.js e2e/live-train-layer.spec.js
npx playwright test e2e/live-*.spec.js
```

## API確認

- 実 HTTP: 200 OK
- APIキー未設定時: `status=unavailable`, `stale=false`, `items=[]`
- 例外や backend 停止なし
- `scope.mode=all` を確認

## 実データ取得確認

APIキー未設定のため未実施。

- 取得件数: 0（unavailable）
- 観測地点数: 0
- 道路名数: 0
- 取得時間・最新観測時刻: 対象外

## 正規化確認

ユニット/API契約テスト 66件成功。

- normal: severity 0
- high / low: severity 2
- very_high / very_low: severity 3
- unavailable: `items=[]`
- 5分値優先、1時間値の5分換算フォールバックを確認
- `volume_5min=0` を欠損と誤判定する問題を修正し、very_low になる回帰テストを追加

## scope確認

- 東京都: `mode=prefecture`, `prefecture=東京都`
- 大阪府: `mode=prefecture`, `prefecture=大阪府`
- 東京駅座標: `mode=location`, `prefecture=東京都`
- bbox: 指定文字列を保持
- 各 scope とも取得不可を `ok + items=[]` に変換しないことを確認

## UIカード確認

- 「🚗 道路交通影響」を表示
- normal をランキングから除外
- unavailable とデータなしを異なる文言で表示
- very_high / low を含む状態表示を確認
- 「通行止めではありません」と明示し、通行止め・規制と断定しない
- 固定地図の背面に隠れていたカードを `#live-traffic-cards` で前面配置するよう修正

## 地図レイヤー確認

- 初期 OFF、ON/OFF 操作成功
- ON 時に状態別観測点マーカーを表示
- OFF 時に非表示
- 鉄道、雨雲、津波カードを維持

## ポップアップ確認

道路名、方向、5分交通量、1時間交通量、状態、観測時刻、出典、注意書きを確認。`undefined` / `null` の表示なし。

## キャッシュ確認

- 同一条件の2回呼び出しで取得処理が1回だけ実行されることをユニットテストで確認
- 期限切れ後の取得失敗で既存キャッシュを `stale=true` として返すことを確認
- APIキー未設定の実HTTPは外部取得を行わないため、実測時間（約4.3ms → 2.7ms）はキャッシュ性能の判定には使用しない

## モバイル確認

- 390 × 844 でカード表示
- 横スクロールなし
- レイヤー操作可能
- 交通カード領域に高さ制限と縦スクロールを設定

## 回帰確認

- Phase 7-B + 鉄道: 16/16 success
- Phase 7-B 専用: 11/11 success
- 全 `/live` E2E: 268/277 success
- 9件の失敗はすべて、新 API を未モックの旧テストで発生する `404 Failed to load resource` の console error 検出。機能アサーションの失敗はなし。

## 発見した問題

1. 交通量0を `or` でフォールバックし、欠損扱いする可能性があった。
2. 道路・鉄道カードが地図の背面にあり、DOM上は可視でも画面では見えなかった。
3. Phase 7-B E2E に Playwright 非対応の minimum count 指定と、否定注意書きを断定として検出する矛盾があった。
4. 既存E2Eの一部が新 API を共通モックしていない。

1〜3は修正済み。4は製品コード外の既存テストハーネス課題として記録する。

## 修正提案

- JARTIC本番契約・認証・レスポンス仕様を確定後、実レスポンス fixture による正規化契約テストを追加する。
- 既存 `/live` E2E の共通APIモックへ `/api/live/road-traffic/summary` の unavailable 応答を追加する。
- 将来は曜日・時間帯・観測点別の平常値比較へ閾値を更新する。

## スクリーンショット

- `tasks/live/screenshots/live_phase7b_desktop_unavailable.png`
- APIキー未設定時の実 `/live`。道路カードが前面表示され、「道路交通量情報を取得できません」と表示されることを確認。

## 最終結論

実データ未設定と既存E2Eハーネスの追随不足を notes とする。Phase 7-B MVP 自体の false-safe、正規化、UI、地図操作、モバイルおよび既存主要機能との共存は確認できたため **PASS with notes** と判定する。
