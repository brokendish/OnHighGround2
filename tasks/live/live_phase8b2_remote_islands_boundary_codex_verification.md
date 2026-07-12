# Phase 8-B.2 遠方離島ブロック選定補正 検証

## 判定

PASS with notes

## 検証日時

2026-07-12 14:00 JST

## 対象差分

- `frontend/js/live-stream/live-stream-municipality-boundary.js`
  - `BLOCK_EXTRA_BBOXES` を追加。
  - `kanto` に伊豆諸島・小笠原諸島（南鳥島含む）向け追加bboxを追加。
  - `kyushu_okinawa` に奄美群島・沖縄本島周辺・宮古/八重山・大東諸島向け追加bboxを追加。
  - `_candidateBboxesForBlock()` を追加し、通常bbox + 追加bboxをOR判定する構成に変更。
  - `_blocksForBounds()` / `_blocksForPoint()` が追加bboxも見るようになっている。
- `e2e/live-stream-mini-map-municipality-boundary.spec.js`
  - 小笠原諸島付近の地震mockを追加。
  - 宮古島地方の豪雨mockを追加。
  - どちらも必要ブロック、境界線、自治体ラベル、全8ブロック常時ロードでないことを検証。
- `tasks/live/live_phase8b2_remote_islands_boundary_claude.md`
  - Claude実装記録。

## データ確認

小笠原・伊豆諸島:

```text
大島支庁大島町
大島支庁利島村
大島支庁新島村
大島支庁神津島村
三宅支庁三宅村
三宅支庁御蔵島村
八丈支庁八丈町
八丈支庁青ヶ島村
小笠原支庁小笠原村
```

沖縄遠方離島:

```text
石垣市
宮古島市
島尻郡南大東村
島尻郡北大東村
八重山郡竹富町
八重山郡与那国町
```

境界GeoJSON:

```text
chubu.geojson          579K
chugoku.geojson        334K
hokkaido.geojson       419K
kanto.geojson          440K
kinki.geojson          523K
kyushu_okinawa.geojson 898K
shikoku.geojson        341K
tohoku.geojson         786K
```

## UI / diagnostics 確認

小笠原イベント:

```json
{
  "errors": [],
  "instances": {
    "eq-mini": { "visibleCount": 1, "labelCount": 1, "zoom": 8 },
    "rain-mini": { "visibleCount": 0, "labelCount": 0, "zoom": 3 }
  },
  "loadedBlocks": ["chubu", "kanto"],
  "labels": ["小笠原村"]
}
```

- `kanto` ブロックがロードされた。
- `eq-mini visibleCount=1` で境界線が表示された。
- `小笠原村` ラベルが表示された。
- page error はなし。
- スクリーンショット: `test-results/live-stream-ogasawara-boundary.png`

沖縄遠方離島イベント:

```json
{
  "errors": [],
  "instances": {
    "eq-mini": { "visibleCount": 0, "labelCount": 0, "zoom": 3 },
    "rain-mini": { "visibleCount": 2, "labelCount": 1, "zoom": 8 }
  },
  "loadedBlocks": ["chubu", "kyushu_okinawa"],
  "labels": ["宮古島市"]
}
```

- `kyushu_okinawa` ブロックがロードされた。
- `rain-mini visibleCount=2` で境界線が表示された。
- 逆引きラベル `宮古島市` が表示された。
- page error はなし。
- スクリーンショット: `test-results/live-stream-okinawa-islands-boundary.png`

本土回帰イベント:

- 大阪地震・福岡豪雨は既存E2E内で引き続きPASS。
- 関東イベントも既存E2E内で引き続きPASS。

## 実行コマンド

```bash
git diff --stat
node --check frontend/js/live-stream/live-stream-municipality-boundary.js
node --check frontend/js/live-stream/live-stream-map-view.js
node --check frontend/js/live-stream/live-stream-panels.js
ls -lh frontend/layers/administrative/municipality_boundaries/
jq -r '.features[].properties.name' frontend/layers/administrative/municipality_boundaries/kanto.geojson | rg '小笠原|八丈|三宅|大島'
jq -r '.features[].properties.name' frontend/layers/administrative/municipality_boundaries/kyushu_okinawa.geojson | rg '宮古島|石垣|竹富|与那国|南大東|北大東'
npx playwright test e2e/live-stream-mini-map-municipality-boundary.spec.js
node /private/tmp/phase8b2_islands_probe.js
npx playwright test e2e/live-stream.spec.js
npx playwright test e2e/live-stream-earthquake-detail.spec.js e2e/live-stream-rain-hazard-detail.spec.js
docker stats --no-stream
```

補足: `live-stream.spec.js` と地震/雨詳細回帰を並列起動した最初の試行では、Playwrightの一時サーバ `127.0.0.1:8787` が競合して片方が `EADDRINUSE` になった。単独再実行ではPASS。

## E2E結果

- `npx playwright test e2e/live-stream-mini-map-municipality-boundary.spec.js`: 9 passed

追加された遠方離島観点:

- 小笠原諸島付近の地震で `kanto` ロード、境界線表示、`小笠原村` ラベル表示。
- 宮古島地方の豪雨で `kyushu_okinawa` ロード、境界線表示、`宮古島市` ラベル表示。
- どちらも `loadedBlocks.length < 8` を確認。

## 回帰確認

- `npx playwright test e2e/live-stream.spec.js`: 45 passed
- `npx playwright test e2e/live-stream-earthquake-detail.spec.js e2e/live-stream-rain-hazard-detail.spec.js`: 21 passed

## パフォーマンス確認

- 遠方離島イベントでも全8ブロック常時ロードにはなっていない。
- 小笠原プローブ: `loadedBlocks=["chubu","kanto"]`
- 宮古島プローブ: `loadedBlocks=["chubu","kyushu_okinawa"]`
- 低zoom全国俯瞰では境界データをfetchしない既存E2Eも継続PASS。
- `docker stats --no-stream` 実行時:
  - frontend: CPU 0.00%, memory 9.746MiB
  - backend: CPU 5.99%, memory 2.118GiB
  - martin: CPU 0.12%, memory 34.78MiB

## Notes

- 小笠原・宮古島プローブでは目的ブロックに加えて `chubu` もロードされた。全8ブロック常時ロードではなく、地図移動中または表示boundsの広がりによる余分読みと見られるため、今回の受け入れ条件上は許容範囲と判断した。
- 南鳥島・硫黄島・石垣・大東諸島などはデータと追加bbox上はカバーされるが、今回のUIプローブは小笠原村と宮古島市に絞った。全国全離島の完全網羅検証は非目標。
- 小笠原スクリーンショットでは境界線が小さく薄い。小画面で主情報を邪魔しない点では良いが、配信で島の輪郭を強く見せたい場合は離島時だけ線幅/ズームに微調整余地がある。

## 結論

Phase 8-B.2 の目的である遠方離島のブロック選定漏れは補正されている。小笠原村付近では `kanto` ブロックがロードされ、境界線と `小笠原村` ラベルが表示された。宮古島地方では `kyushu_okinawa` ブロックがロードされ、境界線と `宮古島市` ラベルが表示された。本土イベント、低zoom、既存 `/live/stream` 回帰も壊れていない。

一部の余分ブロックロードと、全離島の網羅検証が未実施である点をNotesに残し、判定は `PASS with notes` とする。
