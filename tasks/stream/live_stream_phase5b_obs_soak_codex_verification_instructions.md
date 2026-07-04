# /live/stream Stream Phase 5-B CODEX検証指示書
## OBS soak / 長時間安定性確認

## 目的

`/live/stream` をOBS配信・長時間表示に近い条件で継続表示し、画面・地図・タイマー・フォーカス巡回・テロップ・API失敗復帰が安定していることを検証する。

Phase 5-A / 5-A.1 までで、以下は完了済み。

- メイン地図本番地図化
- 地震情報子画面の本番地図化・詳細表示同期
- 地震子画面の固定化問題修正
- キキクル・豪雨情報表示
- 潮位・水位表示
- 鉄道情報詳細化
- 鉄道小画面の平常時路線図表示
- 下部テロップ統合
- `/live/stream` scoped E2E 一式 PASS

Phase 5-B では新機能追加ではなく、長時間運用に耐えるかを確認する。

---

# 1. 検証対象

対象URL:

```text
/live/stream?chrome=off
/live/stream?state=calm&chrome=off
/live/stream?demo=1&chrome=off&focusSpeed=test&runtimeSpeed=test
```

主対象は通常運用想定の以下。

```text
/live/stream?chrome=off
```

OBSブラウザソース想定のため、基本は `chrome=off` を使用する。

---

# 2. レポート保存先

以下に検証レポートを作成する。

```text
tasks/live/live_stream_phase5b_obs_soak_codex_verification.md
```

スクリーンショット・ログ保存先候補:

```text
test-results/live-stream-phase5b-obs-soak-start-1920.png
test-results/live-stream-phase5b-obs-soak-15min-1920.png
test-results/live-stream-phase5b-obs-soak-30min-1920.png
test-results/live-stream-phase5b-obs-soak-60min-1920.png
test-results/live-stream-phase5b-obs-soak-calm-1920.png
test-results/live-stream-phase5b-obs-soak-demo-1920.png
test-results/live-stream-phase5b-diagnostics.json
test-results/live-stream-phase5b-console.log
```

---

# 3. 検証方針

今回の目的は「機能があるか」ではなく、「長時間表示しても壊れないか」。

重点観点:

- 画面が白画面にならない
- pageerror が出ない
- unhandledrejection が出ない
- console error が出ない
- Leaflet map instance が増殖しない
- marker / layer が増え続けない
- railway layer が増殖しない
- earthquake mini-map marker が増殖しない
- focus / hold が詰まらない
- ticker が止まらない
- 時計が止まらない
- API失敗後も画面全体が壊れない
- calm / demo / real の分離が維持される
- `/live` と `/` に副作用がない

---

# 4. 静的確認

まず変更状態を確認する。

```bash
git status --short
git diff --stat
```

確認観点:

- Phase 5-B は原則検証フェーズである
- 実装修正が入っている場合は、修正範囲が `/live/stream` の安定化に限定されている
- 新機能追加に広げていない
- OBS連携やYouTube APIなどへ広げていない
- DB追加や新規外部サービス追加がない

---

# 5. 構文チェック

対象JSに `node --check` を実行する。

```bash
node --check frontend/js/live-stream/live-stream-runtime.js
node --check frontend/js/live-stream/live-stream-main.js
node --check frontend/js/live-stream/live-stream-map-view.js
node --check frontend/js/live-stream/live-stream-panels.js
node --check frontend/js/live-stream/live-stream-focus-policy.js
node --check frontend/js/live-stream/live-stream-focus-controller.js
node --check frontend/js/live-stream/live-stream-earthquake-adapter.js
node --check frontend/js/live-stream/live-stream-earthquake-detail.js
node --check frontend/js/live-stream/live-stream-railway-adapter.js
node --check frontend/js/live-stream/live-stream-railway-layer.js
```

E2E側:

```bash
node --check e2e/live-stream.spec.js
node --check e2e/live-stream-main-map.spec.js
node --check e2e/live-stream-main-map-real-data.spec.js
node --check e2e/live-stream-event-sync.spec.js
node --check e2e/live-stream-status-sync.spec.js
node --check e2e/live-stream-auto-focus.spec.js
node --check e2e/live-stream-stability.spec.js
node --check e2e/live-stream-earthquake-detail.spec.js
node --check e2e/live-stream-earthquake-detail-map-sync.spec.js
node --check e2e/live-stream-railway-detail.spec.js
node --check e2e/live-stream-railway-color-layer.spec.js
node --check e2e/live-stream-railway-calm-map.spec.js
node --check e2e/eq-mock-verify.spec.js
node --check e2e/rain-mock-verify.spec.js
node --check e2e/tide-mock-verify.spec.js
node --check e2e/rail-mock-verify.spec.js
```

Phase 5-B 用E2Eを追加した場合:

```bash
node --check e2e/live-stream-obs-soak.spec.js
```

---

# 6. Docker状態確認

```bash
docker compose ps
```

確認対象:

- frontend
- backend
- martin
- osrm-walking

必要に応じて backend health も確認する。

```bash
curl -s http://127.0.0.1:8000/health || true
```

環境によりbackend URLが異なる場合は既存手順に合わせる。

---

# 7. HTTP確認

以下が 200 で返ること。

```bash
curl -I http://127.0.0.1:8080/live/stream
curl -I "http://127.0.0.1:8080/live/stream?chrome=off"
curl -I "http://127.0.0.1:8080/live/stream?state=calm&chrome=off"
curl -I "http://127.0.0.1:8080/live/stream?demo=1&chrome=off"
curl -I "http://127.0.0.1:8080/live/stream?demo=1&chrome=off&focusSpeed=test&runtimeSpeed=test"
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
```

---

# 8. 既存E2E回帰

長時間検証前に、既存の `/live/stream` scoped E2E を実行する。

```bash
npx playwright test \
  e2e/live-stream.spec.js \
  e2e/live-stream-main-map.spec.js \
  e2e/live-stream-main-map-real-data.spec.js \
  e2e/live-stream-event-sync.spec.js \
  e2e/live-stream-status-sync.spec.js \
  e2e/live-stream-auto-focus.spec.js \
  e2e/live-stream-stability.spec.js \
  e2e/live-stream-earthquake-detail.spec.js \
  e2e/live-stream-earthquake-detail-map-sync.spec.js \
  e2e/live-stream-railway-detail.spec.js \
  e2e/live-stream-railway-color-layer.spec.js \
  e2e/live-stream-railway-calm-map.spec.js \
  e2e/eq-mock-verify.spec.js \
  e2e/rain-mock-verify.spec.js \
  e2e/tide-mock-verify.spec.js \
  e2e/rail-mock-verify.spec.js
```

期待:

```text
全テスト PASS
```

Phase 5-B 用E2Eを追加した場合は、それも実行する。

```bash
npx playwright test e2e/live-stream-obs-soak.spec.js
```

---

# 9. OBS想定表示確認

対象URL:

```text
/live/stream?chrome=off
```

表示サイズ:

```text
1920 x 1080
```

確認項目:

- 16:9で表示崩れがない
- ブラウザUI前提の余白がない
- `chrome=off` で不要UIが出ない
- ヘッダー、中央地図、小画面、テロップが収まる
- 下部テロップが画面外にはみ出さない
- 文字が読める
- 地図 attribution が過剰に邪魔していない
- 画面全体が暗すぎない
- 鉄道小画面の路線図が平常時も表示される

スクリーンショット:

```text
test-results/live-stream-phase5b-obs-soak-start-1920.png
```

---

# 10. diagnostics snapshot の取得

可能であれば、Playwrightまたはブラウザコンソールから以下を定期取得する。

```js
window.__LiveStreamDiagnostics && window.__LiveStreamDiagnostics.getSnapshot()
```

最低限、以下のタイミングで取得する。

```text
開始時
5分
10分
15分
30分
可能なら60分
```

保存先:

```text
test-results/live-stream-phase5b-diagnostics.json
```

確認したい項目例:

- runtime state
- focus active id
- focus queue / candidates
- hold state
- ticker state
- map state
- center map marker count
- center map layer count
- earthquakeDetail active id
- earthquakeDetail marker count
- earthquakeDetail map frame index/count
- earthquakeDetail hold state
- railwayDetail active id
- railwayDetail hold state
- railwayLayer loaded
- railwayLayer layerCount
- railwayLayer highlightedFeatureCount
- railwayMiniMap routeCount
- railwayMiniMap affectedCount
- subscriber count
- timer count 相当の値がある場合
- lastError

厳密に全項目が存在しなくてもよい。存在する diagnostics を記録し、増え続けないか確認する。

---

# 11. 30分 soak

対象URL:

```text
/live/stream?chrome=off
```

条件:

- Playwright Chromium または通常ブラウザ
- viewport 1920 x 1080
- 30分間表示継続
- 途中で画面操作しない
- console/page error を監視
- diagnostics を5分ごとに取得

確認項目:

- 画面が白画面にならない
- 時計が進む
- テロップが流れ続ける
- focus が詰まらない
- 地震/豪雨/潮位/鉄道の小画面が破綻しない
- 地図が真っ白にならない
- パルス/マーカーが異常増殖しない
- Leaflet instance / layer / marker が増え続けない
- railway mini map が維持される
- 鉄道API失敗が起きても画面全体が落ちない
- pageerror / unhandledrejection がない

スクリーンショット:

```text
test-results/live-stream-phase5b-obs-soak-15min-1920.png
test-results/live-stream-phase5b-obs-soak-30min-1920.png
```

---

# 12. 60分 soak

可能であれば実施する。

対象URL:

```text
/live/stream?chrome=off
```

条件:

- 1920 x 1080
- 60分間表示継続
- diagnostics を10分ごとに取得
- console/page error を監視

60分が難しい場合は30分でも可。その場合は PASS with notes 候補にする。

スクリーンショット:

```text
test-results/live-stream-phase5b-obs-soak-60min-1920.png
```

確認項目:

- 30分 soak と同じ
- 30分以降も ticker / focus / hold が継続
- 長時間後に小画面が固まっていない
- 長時間後にメモリ増加が急激でない
- 長時間後に描画が極端に重くならない

---

# 13. calm soak

対象URL:

```text
/live/stream?state=calm&chrome=off
```

時間:

```text
10〜15分
```

確認項目:

- calm状態が維持される
- 監視中文言が表示される
- 警戒デモデータが混入しない
- 地図・小画面が崩れない
- 鉄道小画面に首都圏ODPT対応路線図が表示される
- テロップが監視中として維持される
- console/page error がない

スクリーンショット:

```text
test-results/live-stream-phase5b-obs-soak-calm-1920.png
```

---

# 14. demo soak

対象URL:

```text
/live/stream?demo=1&chrome=off&focusSpeed=test&runtimeSpeed=test
```

時間:

```text
10〜15分
```

確認項目:

- demo表示が維持される
- 地震・豪雨・鉄道・潮位の各デモが表示される
- focus / hold が高速でも詰まらない
- 地震詳細ミニ地図が次へ進む
- 鉄道詳細 overlay が詰まらない
- ticker が止まらない
- marker / layer が増殖しない
- console/page error がない

スクリーンショット:

```text
test-results/live-stream-phase5b-obs-soak-demo-1920.png
```

---

# 15. API失敗・復帰確認

可能であれば Playwright route で一部API失敗を作る。

対象例:

- earthquake API 500
- rain/kikikuru API 500
- tide API 500
- train summary API 500
- invalid JSON
- 一時失敗後に正常レスポンスへ復帰

確認項目:

- 画面全体が壊れない
- 取得失敗を「なし」「平常」と断定しない
- 該当小画面に取得不可表示が出る
- 他カテゴリは表示を継続する
- API復帰後に正常表示へ戻る
- pageerror / unhandledrejection がない
- demo fallback が通常表示に混入しない

API失敗・復帰 soak の時間:

```text
10〜15分
```

API失敗・復帰テストが困難な場合は Notes に記載する。

---

# 16. メモリ・パフォーマンス確認

可能な範囲で確認する。

確認方法例:

- Chrome DevTools Protocol
- Playwright metrics
- `performance.memory` が利用可能なら取得
- diagnostics に counters がある場合は記録
- 目視で描画遅延や操作不能がないか確認

確認項目:

- JS heap が急増し続けない
- layer / marker count が増え続けない
- subscriber / timer count が増え続けない
- 30分後に描画が極端に重くならない
- CPU負荷が異常に高くならない

厳密な性能測定でなくてよい。傾向確認を行う。

---

# 17. 表示欠損確認

soak中・soak後に以下が画面に出ていないこと。

```text
undefined
null
NaN
Invalid Date
[object Object]
```

特に確認する場所:

- 下部テロップ
- 地震小画面
- キキクル・豪雨小画面
- 潮位パネル
- 鉄道小画面
- 詳細 overlay
- 中央地図の注目ラベル

---

# 18. `/live` 回帰確認

soak後に通常 `/live` を開く。

確認項目:

- HTTP 200
- console/page error なし
- 地図表示が壊れていない
- 地震表示が壊れていない
- キキクル・豪雨表示が壊れていない
- 潮位表示が壊れていない
- 鉄道表示が壊れていない
- `/live/stream` のCSS/JSが漏れていない

---

# 19. `/` 回帰確認

soak後にナビ本体 `/` を開く。

確認項目:

- HTTP 200
- console/page error なし
- 基本地図表示が壊れていない
- `/live/stream` のCSS/JSが漏れていない

---

# 20. レポート作成

保存先:

```text
tasks/live/live_stream_phase5b_obs_soak_codex_verification.md
```

レポートに含める内容:

- 判定: PASS / PASS with notes / FAIL
- 検証日時
- 対象ブランチ/コミット
- 変更ファイル
- Docker状態
- HTTP確認結果
- 構文チェック結果
- 既存E2E結果
- 30分 soak 結果
- 60分 soak 結果、または未実施理由
- calm soak 結果
- demo soak 結果
- API失敗・復帰確認結果
- diagnostics snapshot 比較
- marker / layer / map instance の増殖有無
- ticker / focus / hold の継続確認
- console/page error 結果
- メモリ/パフォーマンス所見
- スクリーンショット保存先
- `/live` 回帰
- `/` 回帰
- Notes
- 修正推奨事項
- 次フェーズ候補

---

# 21. PASS条件

以下を満たせば PASS。

- 30分以上の通常 soak で画面が壊れない
- 可能なら60分 soak でも安定
- pageerror がない
- unhandledrejection がない
- 重大な console error がない
- ticker が止まらない
- focus / hold が詰まらない
- 時計が進む
- 地図が真っ白にならない
- marker / layer / Leaflet instance が増え続けない
- 鉄道小画面の平常時路線図が維持される
- API失敗時に画面全体が壊れない
- 取得失敗を「なし」「平常」と断定しない
- 既存E2EがPASS
- `/live` が壊れていない
- `/` が壊れていない

---

# 22. PASS with notes条件

以下は PASS with notes とする。

- 60分 soak は未実施だが30分 soak は安定
- OBS実機ではなくPlaywright/通常ブラウザで確認
- 軽微な console warning がある
- API失敗・復帰mockの一部が未実施
- performance.memory が取得できず目視/diagnostics中心
- メモリが微増するが、30〜60分で安定範囲
- 実データが少なく、一部カテゴリは監視中表示中心

---

# 23. FAIL条件

以下の場合は FAIL。

- 画面が白画面になる
- pageerror が発生する
- unhandledrejection が発生する
- 重大な console error が継続する
- ticker が止まる
- focus / hold が詰まって次へ進まない
- 時計が止まる
- 地図が真っ白になる
- marker / layer / Leaflet instance が増え続ける
- API失敗後に画面全体が壊れる
- 取得失敗を「なし」「平常」と断定する
- 既存E2Eが壊れる
- `/live` が壊れる
- `/` が壊れる

---

# 24. 最終コメント例

```text
判定: PASS with notes

/live/stream Phase 5-B OBS soak / 長時間安定性確認を実施しました。
通常 chrome=off 表示で30分以上のsoakを行い、時計・テロップ・focus・hold・地図・小画面表示が継続することを確認しました。
pageerror / unhandledrejection / 重大なconsole errorは確認されず、Leaflet layer / marker / railway layer の増殖もありません。
API失敗時も画面全体は壊れず、取得失敗を平常とは断定しません。
既存E2E、通常 /live、/ への回帰影響はありません。
60分soakまたはOBS実機確認は未実施のため notes 付きとします。
```
