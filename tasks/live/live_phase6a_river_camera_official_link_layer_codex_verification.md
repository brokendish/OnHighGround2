# Phase 6-A 河川ライブカメラ公式リンクレイヤー MVP 検証レポート

## 実施日時

2026-06-03 11:23:34 JST

## 前提

Claude修正後の再検証。

読み込み順:

- [frontend/live.html](/Users/hideki/Documents/GitHub/OnHighGround2/frontend/live.html:100): `live-river-camera-layer.js`
- [frontend/live.html](/Users/hideki/Documents/GitHub/OnHighGround2/frontend/live.html:101): `live-main.js`

`liveRiverCameraLayer` は `live-main.js` 実行前に `window` へ登録される順序になっている。

## Docker状態

実施:

```bash
docker compose ps
```

結果:

- backend: Up / healthy
- frontend: Up
- martin: Up / healthy
- osrm-walking: Up

## 構文確認

実施:

```bash
python3 -m compileall backend/app
node --check frontend/js/live/*.js
git diff --check
```

結果:

- `compileall`: PASS
- `node --check`: PASS
- `git diff --check`: PASS

## データ確認結果

対象:

```text
frontend/data/live/river_cameras.json
```

結果:

- JSON読み込み: PASS
- 件数: 10
- `lat` / `lng` 欠損: 0
- `name` 欠損: 0
- `url` 欠損: 0
- `id` 重複: 0

## レイヤー確認結果

URL:

```text
http://127.0.0.1:8080/live
```

結果:

- `/live` 通常フローで `liveRiverCameraLayer is not defined` は発生しない
- `#live-loading` は非表示になる
- `/data/live/river_cameras.json` が通常フローで読み込まれる
- 河川カメラトグル OFF 初期状態: マーカー 0 件
- 河川カメラトグル ON: マーカー 10 件
- 河川カメラトグル OFF 復帰: マーカー 0 件

判定: PASS

## マーカー確認結果

結果:

- 河川カメラアイコン数: 10
- `title="河川ライブカメラ"` のアイコンとして表示
- ON/OFFで重複なく追加・削除される
- page errorなし

判定: PASS

## ポップアップ確認結果

確認できた表示:

```text
利根川 布川観測所
河川: 利根川
管理者: 関東地方整備局
[公式ライブカメラを開く]
```

判定: PASS

## リンク確認結果

確認できた公式リンク属性:

- `href`: `https://www.river.go.jp/`
- `target`: `_blank`
- `rel`: `noopener noreferrer`

判定: PASS

## エラー耐性確認結果

静的確認:

- `url` 欠損時はリンクを表示しない
- `lat` / `lng` 欠損時はマーカーをスキップする
- JSON取得失敗時は `catch` で `_cameras = []` にし、`false` を返す

動的確認:

- 通常フローで page error なし
- console error なし

判定: PASS

## false-safe確認結果

結果:

- 河川カメラ実装は `dangerous_areas` / `integrated_dangerous_regions` / 危険度集計処理を直接変更していない
- 回帰E2Eの false-safe 系テストが通過
  - `integrated_dangerous_regions のデータは変化しない`
  - `予測フレームを表示しても summary の集計が変わらない`
  - 既存 danger focus / rain timeline / integrated regions 系が PASS

判定: PASS

## Console確認結果

`http://127.0.0.1:8080/live`:

- console error: なし
- page error: なし
- `live river cameras loaded: count=10` を確認

`http://127.0.0.1:8080/`:

- console error: なし
- page error: なし
- `/data/live` / `/api/live` 自動呼び出し: なし

判定: PASS

## 回帰確認結果

実施:

```bash
npx playwright test e2e/live-basic.spec.js e2e/live-earthquake-layer.spec.js e2e/live-sun-moon-card.spec.js e2e/live-tide-layer.spec.js e2e/live-storm-surge.spec.js e2e/live-integrated-regions.spec.js e2e/live-rain-timeline.spec.js e2e/live-danger-focus.spec.js
```

結果:

```text
169 passed (1.4m)
```

判定: PASS

## ナビ本体影響確認

URL:

```text
http://127.0.0.1:8080/
```

結果:

- 正常表示
- console errorなし
- page errorなし
- `/data/live` / `/api/live` 自動呼び出しなし

判定: PASS

## スクリーンショット

- `/live` 再検証: `/private/tmp/live_phase6a_recheck_live.png`
- ナビ本体再検証: `/private/tmp/live_phase6a_recheck_nav.png`

## 最終判定

PASS

理由:

Claude修正により `live-river-camera-layer.js` が `live-main.js` より先に読み込まれるようになり、前回発生していた `liveRiverCameraLayer is not defined` は解消された。通常フローで河川カメラJSON読み込み、レイヤーON/OFF、マーカー10件、ポップアップ、公式リンク属性、console/page errorなしを確認した。指定回帰E2Eも169件すべてPASSした。
