# キキクル Phase 3-D Codex 検証レポート

実施日: 2026-05-23

## 判定

PASS

Simulation Mode のキキクル疑似表示、周辺サマリー、route-risk 補正プレビューを確認し、検証時に見つかった座標順不整合とモバイル/結果ペインの表示不足を補修した。通常画面へのシミュレーション状態流入はなく、代表回帰も通過した。

## 実施した補修

- `現在地周辺`、`目的地周辺`、`ルート周辺` のサマリーを追加し、選択シナリオと `取得不可` / `判定不可` を同一画面で確認可能にした。
- 疑似オーバーレイ凡例を追加し、浸水・洪水・土砂および注意/危険の表現を明示した。
- route-risk プレビュー送信座標を backend 契約の `[lat, lon]` に修正した。修正前は `[lon, lat]` のため全点が無効扱いとなり、補正プレビューが `補正無効` になっていた。
- 補正プレビューを右ペイン上部へ移し、危険シナリオの結果が初期表示内で読めるようにした。
- クリア時に進行中の非同期プレビューを無効化し、解除後に古い補正結果が再表示されないようにした。
- 390px 幅で三ペインを縦積みにし、横はみ出しなくシナリオ選択、結果確認、地図確認を行えるようにした。
- 疑似オーバーレイ件数を E2E から読み取れる API を追加し、3 種描画と clear を検証可能にした。

## E2E 確認

```bash
npx playwright test e2e/simulation-mode.spec.js --project=chromium
```

- `25 passed`
- シナリオ選択、疑似オーバーレイ 3 種描画/clear、凡例、周辺サマリーを確認。
- `取得不可` / `判定不可` を安全扱いしない表示を確認。
- 洪水危険と固定ハザード重複時の `リアルタイム補正` と説明文を確認。
- route-risk の送信座標が `[lat, lon]` であることを回帰テスト化。
- JMA tile 通信および localStorage 永続化が発生しないことを確認。
- mobile `390 x 844` で横 overflow が発生しないことを確認。

代表回帰:

```bash
npx playwright test e2e/kikikuru-layer.spec.js e2e/info-tab-card-ui.spec.js --project=chromium
```

- `42 passed`
- Phase 3-C 時点で切り分けられていた情報カード文言差分は、現時点のテストでは再現しなかった。

## 静的確認

PASS:

```bash
node --check frontend/admin/simulation.js
node --check frontend/admin/simulation-map.js
node --check e2e/simulation-mode.spec.js
python3 -m compileall -q backend
git diff --check
```

## Docker 実ブラウザ確認

確認環境:

- frontend: `http://127.0.0.1:8080/admin/simulation`
- backend: health `healthy`
- frontend / backend / martin / osrm-walking: running

実 API 確認:

- `洪水 危険` を既定座標で route-risk に送ると、固定ハザードとの重複により `penalty = 16.0`、`max_level = danger`、`matched_hazards = flood, lowland_poor_drainage` を返す。
- `3種同時 危険` の画面ではオーバーレイ 3 種と `補正: -30pt` を確認した。
- `取得不可` は灰色の疑似表示と `安全を意味しません` の文言で確認した。

スクリーンショット（ローカル検証証跡、`.gitignore` 対象）:

- `tasks/screenshots/kikikuru_simulation_desktop.png`
- `tasks/screenshots/kikikuru_simulation_flood_danger.png`
- `tasks/screenshots/kikikuru_simulation_three_dangers.png`
- `tasks/screenshots/kikikuru_simulation_unavailable.png`
- `tasks/screenshots/kikikuru_simulation_mobile.png`
- `tasks/screenshots/kikikuru_simulation_legend.png`

## 非影響確認

- シミュレーション UI と状態は `/admin/simulation` 内に限定され、通常画面 `/` にパネルを生成しない。
- シミュレーション操作は JMA 実タイル取得を行わず、localStorage に状態を残さない。
- 通常画面のキキクル表示、情報タブカード、および既存 route-risk 表示の代表回帰は通過した。
