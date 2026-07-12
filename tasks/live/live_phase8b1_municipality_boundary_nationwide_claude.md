# Phase 8-B.1: 全国市区町村境界データ対応 — Claude実装記録

## 実装日

2026-07-12

## 背景

Phase 8-B の初回実装は東京都・神奈川県のみの境界データに依存しており、CODEXレビューでも
「境界線データの実カバレッジは東京都・神奈川県のみ。全国対応ではない」「gitignoreにより
未追跡」の2点が `PASS with notes` の主因として指摘された
（`tasks/live/live_phase8b_municipality_boundary_and_labels_codex_verification.md`）。
`/live/stream` は全国監視画面のため、この2点を解消する追加修正。

## データソース

**スマートニュース メディア研究所 japan-topography**
（https://github.com/smartnews-smri/japan-topography、加工元は国土交通省 国土数値情報
「行政区域」データ）の都道府県別分割済みGeoJSON（1%簡略化, `data/municipality/geojson/s0010/`）
を採用。

選定理由:
- 既存の東京都・神奈川県データと同じ国土数値情報が一次ソース（provenance一貫）
- 都道府県ごとに1市区町村=1feature（旧ローカルデータのような数百断片への分割が無い）
- 既に1%簡略化済みで軽量（47都道府県合計 約7.5MB）
- ライセンス: 商用・非商用問わず無償利用可、スマートニュースへのクレジット表記は不要。
  ただし国土数値情報側の指定クレジットは必要 → 地図のattributionに
  「国土交通省 国土数値情報（行政区域データ）を加工して作成」を追加して対応

## データパイプライン

1. `scripts/download/download_municipality_boundaries_nationwide.py`（新規）
   - 47都道府県分を`data_lake/raw/nationwide/boundary/`にダウンロード・キャッシュ
   - 既存ファイルはスキップ（再実行はネットワーク不要、`--force`で強制再取得）
2. `scripts/derive/simplify_municipality_boundaries.py`（拡張・入力元を全国データに変更）
   - 都道府県コードを8地方ブロック（北海道/東北/関東/中部/近畿/中国/四国/九州・沖縄）に割当
   - 同一市区町村コード断片のunion（新ソースは基本1feature/muniだが、将来別ソース対応の保険として維持）
   - ラベル用代表点（representative_point）・bbox を事前計算
   - **重要な修正**: 標準N03スキーマでは政令指定都市の区は `N03_003`(市)+`N03_004`(区) の組み合わせ
     （例: 横浜市+中区）。旧スクリプトは非標準の`N03_004`+`N03_005`を前提にしており、
     新データソースでは「中区」のように市名が欠落するバグがあった → `_muni_name()`を標準スキーマに修正
   - 出力: `frontend/layers/administrative/municipality_boundaries/{block}.geojson`（8ファイル、
     計1902市区町村、圧縮前4.2MB、最大ブロックでもgzip後 約250KB）

## フロントエンド（ブロック単位の遅延ロード + キャッシュ）

`frontend/js/live-stream/live-stream-municipality-boundary.js` を全面書き換え:

- `BLOCK_BBOXES`: 8ブロックのおおまかな範囲（「どのブロックを取得するか」判定専用。実際の
  境界線描画・逆引きは各featureの正確なbbox/geometryで行う）
  - 東京都は南鳥島・小笠原諸島など遠方の離島まで行政区域に含むため、素直に全features
    からbboxを算出すると kanto ブロックの範囲が九州・沖縄まで拡大してしまう問題があった
    → kanto ブロックのみ本州側の実用範囲に手動で絞り込み（離島自体の境界データは
    kanto.geojson内に変わらず含まれている。取得ブロック選定からわずかに外れるだけ）
- `_loadBlock(block)` / `_blockPromises`: モジュール全体で共有するブロック単位キャッシュ
  （eq-mini・rain-miniの2小地図間でも同じブロックを再フェッチしない）
- `_blocksForBounds()` / `_blocksForPoint()`: 現在の表示範囲・逆引き対象点と交差するブロックのみ
  選定してロード（全国一括ロードはしない — 受け入れ条件を直接満たす設計）
- `MIN_ZOOM_TO_DRAW=7` は維持（全国俯瞰時に大量ブロック・大量polygonを毎回描画しない）
- ラベル選定ロジック（震度優先度・逆引き・件数上限・衝突回避）は変更なし

## Git管理

- `.gitignore` に `frontend/layers/administrative/` および
  `frontend/layers/administrative/municipality_boundaries/*.geojson` の例外を追加
  （railways/roadsと同じ「deploy artifactだが明示的に追跡する」パターン）
- 8ブロックのGeoJSON成果物自体をコミット対象にする（**選択肢1**: 成果物をgit管理）。
  生成スクリプト（download + derive）も同時にコミットするため、他環境での再生成も可能
  （ただしdownloadはネットワークアクセスが必要 — 成果物をコミットすることでVPS/CI側は
  再生成不要にしている）
- 旧 `frontend/layers/administrative/kanto_municipality_boundary_simplified.geojson`
  （Phase 8-B時点の中間成果物）は `municipality_boundaries/kanto.geojson` に置き換わったため削除

## 動作確認

実データ形式のモックで関東外イベントを確認（Playwright実機）:

- 大阪府北部地震（大阪市北区・豊中市・尼崎市）: `eq-mini visibleCount=158`、
  ラベル「尼崎市」表示。近畿ブロックのみロード（`loadedBlocks: [kinki, chugoku, ...]`）
  （`test-results/live-stream-osaka-boundary.png`）
- 福岡県筑後の豪雨: `rain-mini visibleCount=165`、代表点から逆引きした
  「久留米市」ラベル表示（`test-results/live-stream-fukuoka-boundary.png`）
- 関東イベント単体では8ブロック中1〜数ブロックのみロード（全ブロック同時ロードにならない）
- 境界GeoJSON取得失敗・全国俯瞰(calm)時の非表示は従来どおり正常動作

## テスト

`e2e/live-stream-mini-map-municipality-boundary.spec.js` を全面更新（7件、旧6件から差し替え）:

1. 地震小画面の境界線・ラベル（既存維持）
2. キキクル/豪雨小画面の逆引きラベル（既存維持、横浜市中区の命名バグ修正確認込み）
3. **新規**: 大阪地震・福岡豪雨で境界線・逆引きラベルが機能すること（Kanto以外の実証）
4. **新規**: 単一のKanto内イベントでは8ブロック全ては読み込まれないこと（遅延ロード確認）
5. 境界データ取得失敗時のフォールバック（既存維持、URLパターンをブロック単位に更新）
6. 全国俯瞰(calm)時は境界描画もブロックフェッチも発生しないこと（`loadedBlocks.length===0`を追加確認）
7. 回帰確認（既存維持）

回帰: `e2e/live-stream.spec.js`, `earthquake-detail`, `earthquake-detail-map-sync`,
`rain-hazard-detail`, `status-sync`, `railway-selected-highlight`, `railway-phase5b` 含め
計115件、すべてPASS。

## 既知の制約（Notes）

- ブロック選定用bboxは概算のため、ブロック境界付近のイベントは隣接ブロックも余分にロードすることがある
  （安全側の設計 — 取りこぼしより過剰ロードを優先。最大でも8ブロック中2〜3程度に収まる想定）
- キキクル/豪雨小画面は引き続き「1件の代表点」表示が前提のため、ラベルも実質最大1件
  （Phase 8-B時点からの既知の制約を維持）
