# キキクル Phase 4-A / 4-B Codex 検証レポート

実施日: 2026-05-23

## 判定

PASS（Phase 4-A / 4-B および関連キキクル回帰）

既存実装を検証したところ、前方警告の表示範囲、判定不可表示、Simulation Mode 連携に不足があったため補修した。前方警告はナビ中だけ表示され、状況理解カードは取得不可・判定不可を安全扱いせず、Simulation Mode から Phase 4 の代表ケースを再現できる。

## 実施した補修

- 前方危険警告を `navigation_active` / `navigation_warning` / `navigation_paused` 中だけ表示するようにし、ルートプレビュー中には表示しない。
- ナビ開始時と GPS 更新時に前方警告を再描画し、前方距離表示が移動に追従するようにした。
- キキクル `unknown` を前方警告・状況理解カードで `判定不可（安全を意味しません）` と表示し、danger / safe 扱いしないようにした。
- 状況理解カードの行動バッジを `早めの移動検討` に統一した。
- `/admin/simulation` にナビ中警告プレビューと状況理解プレビューを追加した。
- Simulation Mode に `現在地危険 / 目的地注意`、`現在地注意 / 目的地危険`、`20分後改善`、`強雨継続` のシナリオを追加した。

## 確認結果

Phase 4-A:

- 前方警告、前方距離、固定ハザード + キキクル重複説明を確認。
- `unavailable` / `unknown` は中立表示で、安全・危険を断定しない。
- 警告 UI は reroute 操作を持たず、ナビ制御への接続を追加していない。
- mobile 幅で横 overflow が発生しない。

Phase 4-B:

- 現在地 / 目的地 / ルート / 降水と時間変化を表示できる。
- `待機検討` と `早めの移動検討` を理由付きで再現できる。
- 命令口調や安全断定を追加していない。
- mobile 幅で横 overflow が発生しない。

Simulation Mode:

- 洪水危険 + 固定ハザード重複、取得不可、判定不可を再現できる。
- 現在地危険 / 目的地危険、20分後改善、強雨継続を再現できる。
- 通常画面に simulation UI や mock 状態を持ち込まない。

## 実行した検証

PASS:

```bash
npx playwright test e2e/kikikuru-layer.spec.js e2e/info-tab-card-ui.spec.js e2e/simulation-mode.spec.js e2e/nav-forward-warning.spec.js e2e/situation-card.spec.js --project=chromium
# 99 passed

python3 -m compileall backend/app backend/main.py
find frontend/js -name '*.js' -exec node --check '{}' \;
git diff --check
```

## 全体回帰の残課題

`npx playwright test --project=chromium` も開始したが、Phase 4 と無関係な既存領域で失敗したため PASS 判定には含めていない。

- `block-ahead-reroute-generated.spec.js` / `block-ahead-reroute-replay.spec.js`: `map` または `blockAheadAndReroute` の初期化待ちで 30 秒タイムアウト。
- `block-ahead-reroute.spec.js`: safe crossing 無効時の fetch 件数期待差分。
- `earthquake-intensity-points.spec.js`: 地図表示件数期待差分。
- `magnitude-polling.spec.js`: ポーリング件数・並行数・失敗状態表示の期待差分。

これらは今回変更した Phase 4 ファイルおよび関連テストの実行経路外で再現した。
