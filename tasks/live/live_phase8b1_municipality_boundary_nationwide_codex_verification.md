# Phase 8-B.1 全国市区町村境界データ対応 検証

## 判定

PASS with notes

## 検証日時

2026-07-12 13:42 JST

## 検証観点への回答

### 市区町村境界データが東京都・神奈川県だけに限定されていないか

限定されていない。

- `frontend/layers/administrative/municipality_boundaries/*.geojson` として8地方ブロックに分割されている。
- `jq` で確認した都道府県数は47。
- feature数は合計1902。
- 近畿ブロックに `大阪市北区` / `豊中市` / `尼崎市`、九州・沖縄ブロックに `久留米市` / `那覇市` などが含まれることを確認。

### 関東外イベントで境界線が出ない仕様が、今回の目的に反していないか

関東外イベントで境界線が出る仕様へ修正されている。

- E2Eで大阪府北部地震 + 福岡県豪雨をmockし、`eq-mini` / `rain-mini` とも `visibleCount > 0` を確認。
- Playwrightプローブでは大阪地震で `eq-mini visibleCount=158`、福岡豪雨で `rain-mini visibleCount=165`。
- 福岡豪雨の代表点は逆引きで `久留米市` ラベルを表示。
- 関東外スクリーンショット:
  - `test-results/live-stream-osaka-boundary.png`
  - `test-results/live-stream-fukuoka-boundary.png`

### 東京-first の既存資源流用に引きずられていないか

主要経路は引きずられていない。

- フロントエンドは旧 `kanto_municipality_boundary_simplified.geojson` 固定参照ではなく、`/layers/administrative/municipality_boundaries/{block}.geojson` を参照。
- `BLOCK_BBOXES` と `_blocksForBounds()` / `_blocksForPoint()` により、表示範囲または代表点と交差する地方ブロックだけを遅延ロードする。
- `.gitignore` に行政区域成果物の例外が追加され、8ブロックGeoJSONは通常の `git add` 対象になっている。
- 地図attributionに `国土交通省 国土数値情報（行政区域データ）を加工して作成` が追加されることをプローブで確認。

ただし、東京-first由来の名残として注意すべき点が1つある。`kanto` ブロックの取得判定用bboxは、遠方離島でブロック選定が広がりすぎるのを避けるため本州側の実用範囲に手動で絞られている。そのため、小笠原支庁小笠原村のような遠方離島イベントでは、データ自体は `kanto.geojson` に含まれていても `_blocksForPoint()` / `_blocksForBounds()` のブロック選定から漏れる可能性がある。全国監視を厳密に全行政区域へ広げるなら、この点は追加修正候補。

## 対象差分

- `.gitignore`
  - `frontend/layers/administrative/` と `municipality_boundaries/*.geojson` をgitignore例外化。
- `frontend/js/live-stream/live-stream-municipality-boundary.js`
  - 全国8ブロックの遅延ロード・共有キャッシュへ変更。
  - `loadedBlocks` diagnostics を追加。
  - 国土数値情報 attribution をLeaflet attributionへ追加。
- `frontend/layers/administrative/municipality_boundaries/*.geojson`
  - 北海道、東北、関東、中部、近畿、中国、四国、九州・沖縄の8ファイル。
- `scripts/download/download_municipality_boundaries_nationwide.py`
  - 全国境界データ取得スクリプト。
- `scripts/derive/simplify_municipality_boundaries.py`
  - 全国データを8地方ブロックへ変換・簡略化。
- `e2e/live-stream-mini-map-municipality-boundary.spec.js`
  - 全国対応検証を含む7件へ更新。

## データ確認

```text
chubu.geojson          346 features
chugoku.geojson        117 features
hokkaido.geojson       194 features
kanto.geojson          355 features
kinki.geojson          274 features
kyushu_okinawa.geojson 290 features
shikoku.geojson         95 features
tohoku.geojson         231 features
total                 1902 features
```

ファイルサイズ:

```text
chubu          580K
chugoku        336K
hokkaido       420K
kanto          444K
kinki          524K
kyushu_okinawa 900K
shikoku        344K
tohoku         788K
total          4.2M
```

配信確認:

- `/layers/administrative/municipality_boundaries/kinki.geojson`: `200 OK`
- `/layers/administrative/municipality_boundaries/kyushu_okinawa.geojson`: `200 OK`

## 実行コマンド

```bash
git status --short --untracked-files=all
git diff --stat
for f in frontend/layers/administrative/municipality_boundaries/*.geojson; do printf '%s ' "$f"; jq -r '.features|length' "$f"; done
jq -r '.features[].properties.pref' frontend/layers/administrative/municipality_boundaries/*.geojson | sort -u | wc -l
jq -r '.features[].properties.pref' frontend/layers/administrative/municipality_boundaries/*.geojson | sort -u
jq -r '.features[].properties.name' frontend/layers/administrative/municipality_boundaries/kinki.geojson | rg '大阪市北区|尼崎市|豊中市'
jq -r '.features[].properties.name' frontend/layers/administrative/municipality_boundaries/kyushu_okinawa.geojson | rg '久留米市|福岡市|那覇市'
curl -I http://127.0.0.1:8080/layers/administrative/municipality_boundaries/kinki.geojson
curl -I http://127.0.0.1:8080/layers/administrative/municipality_boundaries/kyushu_okinawa.geojson
node --check frontend/js/live-stream/live-stream-municipality-boundary.js
node --check frontend/js/live-stream/live-stream-map-view.js
node --check frontend/js/live-stream/live-stream-panels.js
python3 -m compileall scripts/download/download_municipality_boundaries_nationwide.py scripts/derive/simplify_municipality_boundaries.py
npx playwright test e2e/live-stream-mini-map-municipality-boundary.spec.js
node /private/tmp/phase8b1_nationwide_probe.js
npx playwright test e2e/live-stream.spec.js
npx playwright test e2e/live-stream-earthquake-detail.spec.js e2e/live-stream-rain-hazard-detail.spec.js
docker stats --no-stream
```

## UI / diagnostics 確認

大阪地震 + 福岡豪雨プローブ:

```json
{
  "errors": [],
  "boundary": {
    "lastError": null,
    "instances": {
      "eq-mini": { "visibleCount": 158, "labelCount": 1, "zoom": 9 },
      "rain-mini": { "visibleCount": 165, "labelCount": 1, "zoom": 8 }
    },
    "loadedBlocks": ["chubu", "kinki", "kyushu_okinawa", "chugoku"]
  },
  "eqLabels": ["豊中市"],
  "rainLabels": ["久留米市"],
  "attributionText": true
}
```

確認結果:

- 関東外でも境界線が表示される。
- 関東外でも逆引きラベルが表示される。
- 8ブロック全ロードではなく、必要ブロックだけをロードしている。
- page error はなし。
- attribution 文字列はDOM上に存在。

## 回帰確認

- `npx playwright test e2e/live-stream-mini-map-municipality-boundary.spec.js`: 7 passed
- `npx playwright test e2e/live-stream.spec.js`: 45 passed
- `npx playwright test e2e/live-stream-earthquake-detail.spec.js e2e/live-stream-rain-hazard-detail.spec.js`: 21 passed

## パフォーマンス確認

- 低zoomの全国俯瞰では境界線描画もブロックfetchもしないE2Eが追加されている。
- 単一Kantoイベントでは `loadedBlocks.length < 8` をE2Eで確認。
- 大阪 + 福岡の同時プローブでも4/8ブロックのロードで収まった。
- `docker stats --no-stream` 実行時:
  - frontend: CPU 0.06%, memory 9.777MiB
  - backend: CPU 0.36%, memory 2.118GiB
  - martin: CPU 0.19%, memory 34.78MiB

## Notes

- 旧 `tasks/live/live_phase8b_municipality_boundary_and_labels_codex_verification.md` の「東京都・神奈川県のみ」「未追跡」指摘は、Phase 8-B.1 の追加対応で主要部分は解消された。
- ただし、`tasks/live/live_phase8b_municipality_boundary_claude.md` など旧MVP時点の記録には、東京・神奈川限定の説明が残っている。履歴としては正しいが、最新仕様として読むと混乱するため、必要なら「Phase 8-B.1で解消済み」と追記するとよい。
- 遠方離島、特に小笠原支庁小笠原村は `kanto.geojson` に含まれるが、ブロック選定用bboxが本州側に絞られているため、現行の `_blocksForPoint()` では取得漏れの可能性がある。全国監視として厳密性を上げるなら、島嶼用ブロックまたは点判定用の追加bboxを持つのがよい。
- キキクル/豪雨ラベルは現状1代表点ベースなので、複数危険自治体の同時ラベル表示は今後の表示モデル次第。

## 結論

東京・神奈川限定だった初回MVPから、全国47都道府県・8地方ブロックの遅延ロード方式へ移行しており、`/live/stream` の全国監視画面としての目的には大きく近づいている。関東外イベントで境界線が出ない仕様は解消され、大阪・福岡のmockで境界線と自治体ラベルを確認できた。東京-first資源への依存も主要経路では外れている。

一点、遠方離島のブロック選定だけは全国監視として注記が必要なため、判定は `PASS with notes` とする。
