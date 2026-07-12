# Phase 8-B.2: 遠方離島ブロック選定補正 — Claude実装記録

## 実装日

2026-07-12

## 背景

Phase 8-B.1 のCODEXレビュー（`live_phase8b1_municipality_boundary_nationwide_codex_verification.md`）で、
「小笠原支庁小笠原村は `kanto.geojson` に含まれるが、ブロック選定用bboxが本州側に絞られているため、
`_blocksForPoint()` では取得漏れの可能性がある」と指摘された。原因は Phase 8-B.1 で意図的に
`kanto` の選定用bboxを本州側実用範囲へ絞ったこと（東京都は南鳥島・小笠原諸島まで行政区域に含み、
素直にbboxを取ると九州・沖縄と丸ごと重なってしまうため）。その副作用で伊豆諸島・小笠原諸島が
選定対象から漏れていた。

## 対応方針

指示書の案A（島嶼用追加bbox）を採用。既存の8ブロック遅延ロード方式・GeoJSONファイル構成は
変更せず、`live-stream-municipality-boundary.js` のブロック選定ロジックのみ拡張。

## 実装内容

`frontend/js/live-stream/live-stream-municipality-boundary.js`:

- `BLOCK_EXTRA_BBOXES` を追加。`kanto`（伊豆諸島 + 小笠原諸島〈南鳥島含む、同一村域〉）と
  `kyushu_okinawa`（奄美群島 / 沖縄本島周辺 / 宮古・八重山 / 大東諸島）に、実データから
  算出した実際の feature bbox を元に追加候補範囲を定義
  - 座標は `frontend/layers/administrative/municipality_boundaries/{kanto,kyushu_okinawa}.geojson`
    から該当自治体の実 bbox を抽出して決定（当て推量ではない）
  - 小笠原支庁小笠原村は単一の feature bbox が既に 140.87〜153.99°E, 24.22〜27.72°N（南鳥島込み）
    をカバーしていたため、追加bboxは1つで足りた
  - 沖縄の遠方離島（宮古・八重山・大東・奄美）は実測の結果、既存の `kyushu_okinawa` 本来のbbox
    (`[122.90, 24.00, 132.10, 34.80]`) で既に技術的にはカバー済みと判明。それでも指示書通り
    明示的な追加bboxを設定し、ブロック境界付近の取りこぼしに対する保険とした
- `_blocksForBounds()` / `_blocksForPoint()` を、本来のbbox **または** 追加bboxのいずれかに
  一致すればそのブロックを選定対象に含めるよう変更（`_candidateBboxesForBlock()`で束ねてOR判定）
- 8ブロック遅延ロード方式・`loadedBlocks` diagnostics・zoom gate・ラベル選定ロジック・
  attributionはすべて維持（変更なし）

## 動作確認

Playwright実機確認（東京都小笠原村付近の地震、沖縄県宮古島地方の豪雨をmock）:

- 小笠原諸島西方沖地震: `loadedBlocks` に `kanto` を含み、`eq-mini visibleCount=1`、
  ラベル「小笠原村」表示（`test-results/live-stream-ogasawara-boundary.png`）
- 宮古島地方の豪雨: `loadedBlocks` に `kyushu_okinawa` を含み、`rain-mini visibleCount=2`、
  逆引きラベル「宮古島市」表示（`test-results/live-stream-okinawa-islands-boundary.png`）
- どちらのケースも `loadedBlocks.length < 8`（全ブロック常時ロードにはなっていない）
- console error / page error なし

## テスト

`e2e/live-stream-mini-map-municipality-boundary.spec.js` に2件追加（計9件、旧7件から拡張）:

- 小笠原諸島付近の地震で `kanto` ブロックロード + 境界線 + 「小笠原村」ラベルを確認
- 宮古島地方の豪雨で `kyushu_okinawa` ブロックロード + 境界線 + 逆引きラベル「宮古島市」を確認
- 両テストとも `loadedBlocks.length < 8` を明示的に確認（既存の全国一括ロード禁止要件の維持を担保）

回帰: `e2e/live-stream.spec.js`, `earthquake-detail`, `earthquake-detail-map-sync`,
`rain-hazard-detail`, `status-sync`, 本spec含め計100件、すべてPASS
（大阪地震・福岡豪雨のPhase 8-B.1既存テストも変更なしで通過を確認）。

## 非目標（指示書どおり据え置き）

全国全離島の完全網羅検証、行政区域データの最新版差し替え、境界データの大幅再生成、
Martin/vector tile化、ラベル表示モデルの大幅変更、複数危険自治体ラベル表示の強化。
