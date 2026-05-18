# 避難所マーカー画像化対応 検証レポート

- 判定: PASS with notes
- 検証日: 2026-05-19
- 確認環境:
  - macOS / zsh
  - Docker Compose
  - frontend: nginx `http://127.0.0.1:8080`
  - backend: FastAPI `http://127.0.0.1:8000`
  - Playwright Chromium headless

## 実施コマンド

```bash
find frontend e2e -name '*.js' -print0 | xargs -0 -n1 node --check
docker compose ps
curl -s http://127.0.0.1:8000/health
curl -I http://127.0.0.1:8080
npx playwright test e2e/shelter-marker-image.spec.js
npx playwright test e2e/smoke.spec.js e2e/evacuation-ui.spec.js e2e/shelter-style-tsunami-regression.spec.js
```

追加で、Docker配信中の実画面 `http://127.0.0.1:8080/` を Playwright で開き、実backend経由の避難所表示とブラウザエラー有無を確認した。

## 確認した画面URL

- `http://127.0.0.1:8787/`（E2E静的配信、APIモック）
- `http://127.0.0.1:8080/`（Docker frontend + 実backend）

## 検証項目ごとの結果

### 1. 構文・起動確認

- frontend / e2e JS の `node --check`: PASS
- Docker frontend/backend 起動: PASS
  - backend: `healthy`
  - frontend: HTTP 200
- 実backend health: PASS
  - `shelters_loaded: 10285`
  - hazard datasets loaded
- ブラウザコンソール致命エラー: PASS
  - Docker実画面確認で `errors: []`
- 避難所レイヤーON/OFF: PASS
  - E2EでOFF時に `.shelter-icon` / `.shelter-cluster-icon` が0件
  - 再ONで正常再表示

### 2. SVGアイコン表示確認

- 指定避難所: PASS
  - `.shelter-icon--es` とSVG表示を確認
- 指定緊急避難場所: PASS
  - `.shelter-icon--eee` とSVG表示を確認
- 種別入れ替わり: PASS
  - モックデータで `evacuation_shelter` と `emergency_evacuation_site` を同時確認
- 小サイズ・高解像度: PASS
  - SVGインライン描画のため拡大縮小でぼやけにくい
- 既存ポップアップ: PASS
  - 種別名、施設名、住所、ハザード、座標、ルートボタンを確認

### 3. ズーム依存サイズ確認

- zoom 16: PASS
  - アイコン設定サイズ 28px
- zoom 17以上: PASS
  - アイコン設定サイズ 34px
- zoom変更追従: PASS
  - zoom変更後の再描画でサイズ更新を確認
- iconAnchorずれ: PASS
  - クリック・ポップアップ表示に不自然なずれなし
- note:
  - 現実装では候補避難所レイヤーは zoom 10 では表示されない（`SHELTER_BROWSE_CONFIG.ZOOM_SHOW_MIN` / fallback 11 未満でクリア）。
  - 広域ブラウズON時は zoom 11〜13 で近傍候補が意図的に非表示になり、広域ブラウズレイヤーへ譲る挙動。

### 4. 選択時アニメーション確認

- 選択中クラス: PASS
  - `.shelter-icon--selected` が1件だけ付与される
- 別マーカー選択時の解除: PASS
  - 前選択が解除され、選択状態が移動
- Popup同期: PASS
  - 指定避難所 / 指定緊急避難場所のポップアップ内容を確認
- アニメーション過剰性: PASS
  - 白リング + pulse。現在地マーカーとは別クラス・別見た目

### 5. クラスタリング確認

- クラスタ表示: PASS
  - 候補避難所レイヤー単体検証では zoom 12 で `.shelter-cluster-icon` を確認
- クラスタ件数表示: PASS
  - `.shelter-cluster-count` を内包
- 高ズーム個別表示: PASS
  - zoom 17 でクラスタ0件、個別SVGマーカー表示
- レイヤーOFF時クラスタ非表示: PASS
- note:
  - 通常UIで広域ブラウズレイヤーがONの場合、zoom 11〜13 は候補避難所マーカーを隠す設計。クラスタ挙動のE2Eでは `isShelterBrowseLayerVisible=false` にして対象機能を切り出した。

### 6. 現在地近傍避難所の強調確認

- 現在地あり: PASS
  - 近傍上位5件が `.shelter-icon--near`
  - 残りが `.shelter-icon--far`
- 現在地なし: PASS
  - near/far クラス0件で通常表示
- 取得失敗相当: PASS
  - `currentLocation = null` でJSエラーなし

### 7. 既存機能の回帰確認

- smoke UI: PASS（7件）
- 避難先UI false-safe 回帰: PASS（6件）
- 津波警報連携後の避難所表示フラグ回帰: PASS（6件）
- 現在地ボタン / 避難先検索 / クリア / bottom panel 基本UI: PASS
- スマホ幅 390x844: PASS
  - 地図、下部タブ、避難所マーカー表示を確認
- ハザードロード: PASS
  - backend health で hazard datasets loaded を確認

### 8. パフォーマンス確認

- E2Eモック7件: PASS
  - zoom変更、近傍計算、ON/OFFでフリーズなし
- Docker実backend: PASS
  - 実画面で表示範囲39件を描画
  - ブラウザエラーなし
- note:
  - 数千件規模の広域表示は広域ブラウズレイヤーとクラスタリング設計に依存。今回の自動確認では大量全件DOM描画までは行っていない。

## スクリーンショット保存先

- `test-results/shelter-marker-image-desktop.png`
- `test-results/shelter-marker-image-mobile.png`
- `test-results/shelter-marker-docker-real.png`

## 発見した問題

- 仕様確認メモ: 検証指示の zoom 10 は、現実装では候補避難所レイヤー表示対象外。
- 仕様確認メモ: 広域ブラウズON時の zoom 11〜13 は、候補避難所マーカーではなく広域ブラウズレイヤーが表示を担当する。
- UI文言メモ: 凡例に旧来の色表現（例: 指定緊急避難場所の赤）が残っている。実マーカーはSVG種別形状で識別するため、凡例更新を検討するとよい。

## 修正が必要な場合の推奨対応

- zoom 10 でも候補避難所マーカーを表示したい場合は、`SHELTER_BROWSE_CONFIG.ZOOM_SHOW_MIN` と `refreshEmergencyShelters()` の低ズーム非表示仕様を見直す。
- 広域ブラウズON時も候補避難所クラスタを同時表示したい場合は、`_shouldHideEmergencyShelterCandidatesForBrowse()` の制御方針を再検討する。
- 凡例の色・文言をSVGアイコン（指定避難所=家形、指定緊急避難場所=走り人形）に合わせて更新する。

