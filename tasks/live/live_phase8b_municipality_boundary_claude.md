# Phase 8-B: 小画面 市区町村境界線・自治体名表示改善 — Claude実装記録

## 実装日

2026-07-12

## 対象

`/live/stream` の地震小画面 (`#eq-map`) とキキクル/豪雨小画面 (`#rain-map`、両カテゴリで共有する1つの小地図)。
`/live` 本体側は対象外（指示書どおり `/live/stream` のみ）。

## データ方針とスコープ制約（重要）

市区町村境界データは、このプロジェクトが現在保有している **東京都・神奈川県のみ**
（`frontend/layers/administrative/{tokyo,kanagawa}_boundary.geojson`、CLAUDE.md記載の
Tokyo-first方針どおり）。全国境界データは未保有のため、今回のMVPは関東2都県のみ実データで
境界線・逆引きラベルが機能し、それ以外の地域では「境界線・キキクル/豪雨の逆引きラベルが出ない」
だけで、エラーにはしない（missing coverage は crash させない方針。地震のラベル自体は既存の
全国市区町村座標辞書 `frontend/data/municipality_coords.json` を使うため関東以外でも表示される — 
境界線カバレッジとは独立した情報源）。

## データ前処理

`scripts/derive/simplify_municipality_boundaries.py`（新規）:

- 既存の N03 由来境界データ（1市区町村が最大483断片に分割されている生データ）を
  `shapely.unary_union` で市区町村コード単位に統合
- `simplify(tolerance=0.0015, preserve_topology=True)` で簡略化
- ラベル用代表点 (`representative_point()`) と bbox を事前計算して properties に埋め込み
  （クライアント側で毎回 centroid 計算しない）
- 出力: `frontend/layers/administrative/kanto_municipality_boundary_simplified.geojson`
  （121市区町村、1947KB→234KB、gzip転送時 約57KB）

実行: `venv/bin/python scripts/derive/simplify_municipality_boundaries.py`

## 実装内容

### `frontend/js/live-stream/live-stream-municipality-boundary.js`（新規）

`LiveStreamRailwayLayer` と同じ「複数小地図インスタンスをkeyで束ねる」パターン。

- `init(map, opts.key)`: 境界線レイヤー・ラベルレイヤーを登録し、`moveend` で自動再描画
- 境界線は zoom 7 未満（全国俯瞰時）は描画しない（データが関東のみのため、全国俯瞰時に
  「関東だけ変な模様が浮く」ことを防ぐ）。bbox 事前計算済みの高速フィルタで現在の地図範囲内のみ描画
- 境界線は**Canvas renderer のまま**描画（`renderer:L.svg()` を強制しない）— CSSアニメーション
  不要な静的表示のため、多数のpolygonをSVG DOM化するより軽い（選択路線ハイライトとは異なる判断）
- ラベル: `setLabels(key, candidates, opts)` — 優先度順ソート + 画面座標での衝突回避
  （24px未満で重なる候補は間引く）+ maxCount上限
  - **重要な修正点**: 小地図の移動は `fitTo`/`focusOn` の flyTo/setView アニメーションを伴い
    非同期に完了する。`setLabels()` 呼び出し時点ではまだ最終 view になっておらず、投影がズレて
    全ラベルがほぼ同じ1点に重なり間引かれてしまう不具合があった。`moveend`（アニメーション完了後
    に発火）のたびに直近の候補リストで再配置する設計に修正し解消
- `findMunicipalityAt(lat, lng)`: ray casting による point-in-polygon。キキクル/豪雨データは
  市区町村名を持たない（JMA予報区単位）ため、代表点から逆引きする
- `getDiagnostics()`: インスタンスごとの `visibleCount`/`labelCount`/`zoom` を公開
  （E2E検証用。preferCanvas環境では境界線がDOM `<path>` にならないため、DOM件数では検証できない）

### `frontend/js/live-stream/live-stream-map-view.js`

`mode === 'eq-mini' || 'rain-mini'` の場合に `LiveStreamMunicipalityBoundary.init()` を呼ぶ処理を追加。

### `frontend/js/live-stream/live-stream-panels.js`

- `selectEarthquakeMunicipalityLabels(frameGroup)`: 表示中の震度マーカー（`frameGroup`）を
  そのままラベル候補にする（「震度表示対象自治体のみ表示」を、既存の表示中マーカー集合をそのまま
  使うことで自然に満たす。優先度=震度ランク）。`_renderEqMiniMapLeaflet` から呼び出し、maxCount:6
- `_syncRainMunicipalityLabel(lat, lng)`: キキクル/豪雨の代表点から `findMunicipalityAt` で
  逆引きし、該当があればラベル表示（maxCount:5、実質1件）。対象IDが変わった時のみ呼ぶ
  （token方式で問い合わせ中の切り替わりを無効化）
- 各カテゴリの「対象なし」分岐・詳細クリア処理に `clearLabels` を追加し、ゴースト表示を防止

### `frontend/css/live/live-stream.css`

- `.live-muni-label`: 白文字+黒4方向text-shadow縁取り（YouTube縮小表示での可読性を優先）
- `.rain-card`系とは独立、既存 `.stream-eq-intensity-marker` 系スタイルの隣に配置

### `frontend/live/stream.html`

`live-stream-municipality-boundary.js` の `<script>` を railway-layer.js の直後、
map-view.js の前に追加。

## 非目標（指示書どおり据え置き）

全自治体名常時表示、都道府県境と同等強度表示、地図全面ラベル化、ラベル検索UI、
境界クリックポップアップ、`/live` 本体側対応。

## 動作確認

Playwright での実機確認（東京湾震源・6区市town、横浜市中区の豪雨エリアをモック）:

- 地震小画面: 境界線 96 features 描画、ラベル4件（千代田区・渋谷区・大田区・世田谷区、
  最高震度の千代田区は必ず含まれる）。震度マーカー・境界線とも視認性良好
  （`test-results/live-stream-earthquake-mini-map-boundary.png`）
- キキクル/豪雨小画面: 境界線 113 features 描画、代表点から逆引きした「横浜市中区」ラベル表示
  （`test-results/live-stream-rain-mini-map-boundary.png`）
- 関東カバレッジ外（大阪・福岡）: 境界線 0件・キキクル/豪雨ラベル0件（グレースフルに非表示）、
  地震ポップアップ・豪雨ポップアップとも正常表示、console error なし
- 境界GeoJSON取得失敗（404モック）: 主機能（地震ポップアップ等）は無傷、`lastError` に記録、
  境界線なしにフォールバック
- 全国俯瞰（calm、低zoom）: 境界線が「関東だけ浮く」ことなく非表示

## テスト

- 新規 E2E: `e2e/live-stream-mini-map-municipality-boundary.spec.js`（6件 PASS）
- 既存回帰: `e2e/live-stream.spec.js`, `e2e/live-stream-earthquake-detail.spec.js`,
  `e2e/live-stream-earthquake-detail-map-sync.spec.js`, `e2e/live-stream-rain-hazard-detail.spec.js`,
  `e2e/live-stream-status-sync.spec.js` 含め計97件、すべて PASS

## 既知の制約（Notes）

- 境界線・キキクル/豪雨の逆引きラベルは東京都・神奈川県のみ（データ未保有のため全国対応は今後の課題）
- キキクル/豪雨小画面は現状「1件の代表点」のみ表示する設計のため、ラベルも実質最大1件
  （指示書の「最大3〜5件」は上限としては満たすが、複数候補からの優先度選定が活きる場面が少ない。
  複数地点ランキング表示が導入されればラベルも自然に複数化する）
