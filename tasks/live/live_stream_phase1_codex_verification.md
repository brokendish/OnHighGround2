# /live/stream Phase Stream-1 Codex Verification

## 判定

PASS with notes

Phase Stream-1 の `/live/stream` は Docker frontend の `http://127.0.0.1:8080/live/stream` で表示でき、1920x1080 配信用レイアウト、URL パラメータ、時計、テロップ、小窓4種、console/page error なし、通常 `/live` と `/` の基本回帰を確認した。

## 検証日時

- 2026-07-01 21:48:13 JST

## 対象

- Branch: `main`
- HEAD: `ba6f7bd`
- Target: `http://127.0.0.1:8080/live/stream`

## 静的確認

### 追加ファイル

Claude 実装として以下の新規ファイルを確認した。

- `frontend/live/stream.html`
- `frontend/css/live/live-stream.css`
- `frontend/js/live-stream/live-stream-scene.js`
- `frontend/js/live-stream/live-stream-map.js`
- `frontend/js/live-stream/live-stream-panels.js`
- `frontend/js/live-stream/live-stream-clock.js`
- `frontend/js/live-stream/live-stream-ticker.js`
- `frontend/js/live-stream/live-stream-main.js`
- `design_handoff_live_stream/README.md`
- `design_handoff_live_stream/index.html`
- `tasks/stream/Phase Stream-1: 災害監視Live配信画面 MVP 実装_CODEX.md`
- `tasks/stream/Phase Stream-1: 災害監視Live配信画面 MVP 実装_claude.md`

### 変更ファイル

- 既存ファイルの変更は `git status --short` 上では確認されなかった。
- Codex 検証成果物として本レポートを新規追加した。

### 影響範囲

- 既存ナビ本体 `frontend/index.html`, `frontend/js/navigation.js`, `frontend/js/nav-*.js`, `frontend/js/hazard-layers.js`, `frontend/js/location-info-panel.js` への変更なし。
- 通常 `/live` 用の `frontend/live.html` と既存 `frontend/js/live/` への変更なし。
- `/live/stream` は `frontend/live/stream.html` と専用 CSS/JS で分離されている。
- `buildScene(rawLiveData)` が `frontend/js/live-stream/live-stream-scene.js` にあり、将来の `/live` 正規化済みデータ差し替え口として確認済み。
- `renderMap()`, `zoomToTarget()`, `renderTide()` が独立しており、将来 Leaflet / MapLibre / 既存地図への差し替え余地がある。

Note: `docs/live/DEVELOPMENT_GUARDRAILS.md` の「触ってよい場所」には `frontend/live/` と `frontend/js/live-stream/` が明記されていない。一方、既存本体を改変せず `/live/stream` を分離する目的には合っているため、今回の検証では注意事項として扱った。

## Docker 状態

`docker compose ps` で以下を確認した。

- `evacuation-navi-backend`: Up, healthy, `8000`
- `evacuation-navi-frontend`: Up, `8080`
- `evacuation-navi-martin`: Up, healthy
- `evacuation-navi-osrm-walking`: Up, `5501`

## HTTP 確認

すべて `HTTP/1.1 200 OK`。

- `/live/stream`
- `/live/stream?state=calm`
- `/live/stream?state=alert`
- `/live/stream?chrome=off`
- `/live`
- `/`

## 構文チェック

すべて `node --check` 成功。

- `frontend/js/live-stream/live-stream-main.js`
- `frontend/js/live-stream/live-stream-scene.js`
- `frontend/js/live-stream/live-stream-clock.js`
- `frontend/js/live-stream/live-stream-ticker.js`
- `frontend/js/live-stream/live-stream-panels.js`
- `frontend/js/live-stream/live-stream-map.js`

## Playwright 実画面確認

一時検証スクリプト `/private/tmp/live_stream_phase1_verify.js` で Docker frontend `8080` を直接検証した。

### 確認URL

- `http://127.0.0.1:8080/live/stream`
- `http://127.0.0.1:8080/live/stream?state=calm`
- `http://127.0.0.1:8080/live/stream?state=alert`
- `http://127.0.0.1:8080/live/stream?state=alert&chrome=off`
- `http://127.0.0.1:8080/live/stream?state=calm&chrome=off`
- `http://127.0.0.1:8080/live/stream?state=alert&chrome=off`
- `http://127.0.0.1:8080/live`
- `http://127.0.0.1:8080/`

### 結果

- page error: なし
- console error: なし
- stage/header/center/ticker: 表示確認
- 地震/豪雨/鉄道/潮位小窓: 表示確認
- `?state=calm`: 「現在、表示対象なし」表示確認
- `?state=alert`: 地震・豪雨・鉄道・潮位の警戒情報表示確認
- `?chrome=off`: 開発UI非表示確認
- 時計: 2秒待機で `HH:MM:SS` 変化確認
- 鉄道小窓ポップアップ: 0件確認
- 通常 `/live`: 200、console/page error なし
- `/`: 200、console/page error なし

## 1920x1080 レイアウト確認

`/live/stream?state=calm&chrome=off`

- stage: `1920 x 1080`
- header: `1920 x 72`
- ticker: `1920 x 46`
- center: `900 x 930`
- 小窓: 各 `476 x 458`
- 横スクロール: なし
- 縦スクロール: なし

`/live/stream?state=alert&chrome=off`

- stage: `1920 x 1080`
- header: `1920 x 72`
- ticker: `1920 x 46`
- center: `900 x 930`
- 小窓: 各 `476 x 458`
- 横スクロール: なし
- 縦スクロール: なし

## 縮小フィット確認

`1366x768` と `1280x720` で確認した。

- stage は viewport 内に縮小フィット
- 横スクロールなし
- 縦スクロールなし
- カラム構成は維持
- 小窓の大きな重なりなし

## 色ルール確認

computed style で小窓枠線色を確認した。

- 地震: `rgb(255, 77, 61)` = `#ff4d3d`
- 豪雨: `rgb(47, 123, 255)` = `#2f7bff`
- 鉄道: `rgb(43, 213, 118)` = `#2bd576`
- 潮位: `rgb(198, 75, 224)` = `#c64be0`

中央地図のパルスもカテゴリごとの CSS 変数を使っていることを確認した。

## スクリーンショット

- `test-results/live-stream-calm-1920.png`
- `test-results/live-stream-alert-1920.png`
- `test-results/live-stream-alert-1366.png`
- `test-results/live-stream-alert-1280.png`

## E2E 追加有無

- 追加なし。

理由: 既存 Playwright 設定は `frontend/` をローカルサーバーで直接配信する前提で、今回の `/live/stream` は nginx の `try_files` ルールで `frontend/live/stream.html` を解決する構成。Phase Stream-1 の検証では Docker frontend `8080` への実ブラウザ検証を優先し、既存 E2E 設定変更や実装側への `data-testid` 追加は行わなかった。

## Notes

- 実装はデモデータベースで、実データ接続は Phase Stream-1 の必須範囲外。
- `renderTide()` の現在時刻位置は `cur = 19.42` の固定値で、Claude レポート通り Phase Stream-2 で実時刻連動にするのがよい。
- Google Fonts を外部参照している。配信安定性重視ならセルフホスト化推奨。
- 汎用クラス `.win`, `.row`, `.legend` などはあるが、CSS は `/live/stream` HTML でのみ読み込まれるため通常 `/live` と `/` への漏れは確認されなかった。

## 修正推奨事項

Phase Stream-1 の受け入れを妨げる修正必須事項はなし。

次フェーズ候補:

- `renderTide()` の固定現在時刻を実時刻に変更
- `/live` 正規化済みデータを `buildScene()` に接続
- 小窓地図を簡易 SVG から既存 Leaflet / MapLibre 基盤に置換
- テロップ文言を動的 API 連携
- フォントのセルフホスト化
- nginx 経由の `/live/stream` を対象にした dedicated E2E を追加
