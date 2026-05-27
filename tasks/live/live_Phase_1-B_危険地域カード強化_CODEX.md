# /live Phase 1-B 危険地域カード強化 受入検証指示書（CODEX向け）

## 最重要

作業前に必ず以下を読むこと。

- AGENTS.md
- CLAUDE.md
- docs/live/DEVELOPMENT_GUARDRAILS.md
- frontend/js/live/README.md
- tasks/live/live_mvp_codex_verification.md

今回の目的は `/live Phase 1-B 危険地域カード強化` の受入検証である。

最重要観点は以下。

```text
/live の強化によって、既存避難ナビ本体を壊していないこと
````

---

# 検証対象

Phase 1-B で追加・変更された `/live` 危険地域カード強化。

確認対象の想定:

* frontend/js/live/live-alert-panel.js
* frontend/js/live/live-layers.js
* frontend/js/live/live-ui.js
* frontend/js/live/live-main.js
* frontend/css/live/live.css
* e2e/live-basic.spec.js
* 必要に応じて追加された live 専用 JS

---

# 絶対確認事項

以下が改変されていないこと。

* frontend/index.html
* frontend/js/navigation.js
* frontend/js/state.js
* frontend/js/nav-*.js
* frontend/js/hazard-layers.js
* frontend/js/location-info-panel.js
* 既存 reroute 関連
* 既存 bottom panel 関連

---

# 1. 静的確認

## 1-1. 禁止依存チェック

live 実装が以下へ依存していないこと。

* navigation.js
* state.js
* nav-*.js
* location-info-panel.js
* reroute
* OSRM

確認例:

```bash
rg -n -i "navigation\.js|state\.js|location-info-panel|reroute|osrm|nav-[A-Za-z0-9_-]*\.js" frontend/js/live frontend/live.html frontend/css/live e2e/live-basic.spec.js nginx.conf
```

依存がある場合は FAIL。

コメントや README の否定記述のみであれば notes として記録する。

---

## 1-2. 差分範囲確認

```bash
git diff --name-only HEAD
git ls-files --others --exclude-standard
```

live 関連以外の差分がある場合は内容を確認する。

---

# 2. 構文チェック

```bash
node --check frontend/js/live/live-map.js
node --check frontend/js/live/live-layers.js
node --check frontend/js/live/live-alert-panel.js
node --check frontend/js/live/live-ui.js
node --check frontend/js/live/live-main.js
test -f frontend/js/live/live-danger-summary.js && node --check frontend/js/live/live-danger-summary.js || true
```

すべて PASS であること。

---

# 3. Docker / HTTP 確認

```bash
docker compose build
docker compose up -d
docker compose ps

curl -I http://127.0.0.1:8080/
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/live.html
curl -s http://127.0.0.1:8000/health
```

期待:

* `/` HTTP 200
* `/live` HTTP 200
* `/live.html` HTTP 200
* backend healthy
* frontend running
* martin healthy
* 既存サービスに異常なし

---

# 4. /live E2E

```bash
npx playwright test e2e/live-basic.spec.js
```

期待:

```text
23 passed
```

実際の件数が異なる場合は、理由を確認して記録する。

---

# 5. Phase 1-B 受入観点

## 5-1. 危険地域カード表示

確認すること。

* 「現在の状況」カードが表示される
* 津波警報なし / あり が表示される
* 地震件数 24h が表示される
* 強雨域なし / あり が表示される
* キキクル未確認 / 危険あり / 危険なし が区別される
* 更新時刻が表示される

---

## 5-2. 「危険なし」と「取得失敗」の区別

以下が区別されていること。

### 全コア API ok + 危険なし

```text
現在、大きな警戒情報はありません
```

### API offline / unknown を含む

```text
一部情報を取得できません
```

または equivalent な非断定表示。

重要:

```text
API 取得失敗時に「安全」と断定しないこと
```

---

## 5-3. 危険地域ランキング

以下を確認すること。

* 危険地域リストが表示される
* 津波エリアが優先表示される
* M5以上地震が表示される
* M6以上地震は danger 扱いになる
* danger → warning の順に並ぶ
* 最大件数が過剰にならず、画面を壊さない

---

## 5-4. 地図フォーカス

危険地域リストの lat/lng あり項目をクリックしたとき:

* map center が変わる
* zoom が適切に変わる
* page error が発生しない

lat/lng なし項目:

* クリック不可または安全に無視される
* page error が発生しない

---

## 5-5. API 失敗耐性

API 503 / 空データ / error 相当で確認。

* 画面が壊れない
* map 操作が継続する
* レイヤートグルが継続する
* status dot が offline になる
* 危険なしと誤表示しない
* console.error が出ない
* unhandled rejection / page error が出ない

ブラウザが failed resource を console に記録する場合は、アプリケーション由来かブラウザ由来かを区別して記録する。

---

# 6. 既存ナビ代表 E2E

```bash
npx playwright test e2e/info-tab-card-ui.spec.js e2e/weather-rain-radar-card.spec.js e2e/tide-sun-moon-timeline.spec.js e2e/simulation-mode.spec.js
```

期待:

```text
44 passed
```

実際の件数が異なる場合は理由を記録する。

---

# 7. 実画面スクリーンショット

以下を保存すること。

```text
tasks/live/verification_screenshots/phase1b-live-normal.png
tasks/live/verification_screenshots/phase1b-live-danger.png
tasks/live/verification_screenshots/phase1b-live-api-failure.png
tasks/live/verification_screenshots/phase1b-navigation-root.png
```

確認観点:

* `/live` 通常
* `/live` 危険地域あり
* `/live` API failure
* `/` 既存ナビ画面

---

# 8. 判定基準

## PASS

以下をすべて満たす。

* `/live` E2E が PASS
* 危険地域カードが正常表示
* 危険なし / 取得失敗を区別
* 危険地域ランキング表示
* 地図フォーカス動作
* API failure でも page error / unhandled rejection なし
* 既存ナビ代表 E2E が PASS
* 禁止ファイル未変更
* live から navigation/state/reroute/OSRM 依存なし

## PASS with notes

軽微な UI 改善余地、ブラウザ由来の failed resource console、ランキング精度の今後改善余地などはあるが、基本動作・分離・回帰なしが確認できた場合。

## FAIL

以下のいずれかがある場合。

* `/live` E2E が FAIL
* 危険なしと取得失敗を混同
* API failure で page error / unhandled rejection
* 既存ナビ代表 E2E が FAIL
* 禁止ファイル差分あり
* navigation/state/reroute/OSRM 依存追加
* nginx 既存ルーティング破壊

---

# 9. 検証レポート作成

以下へ作成または追記すること。

```text
tasks/live/live_phase1b_danger_cards_codex_verification.md
```

記載内容:

* 判定
* 実行コマンド
* 結果
* 危険地域カード確認結果
* 危険なし / 取得失敗の区別確認
* 危険地域ランキング確認
* 地図フォーカス確認
* API failure 確認
* 既存ナビへの影響有無
* スクリーンショット保存先
* notes / 改善提案

---

# 最重要メッセージ

今回の検証目的は、カードが表示されることだけではない。

最重要は以下。

```text
/live が「今どこが危ないか」を示しつつ、
OnHighGround2 の避難ナビ本体を壊していないこと
```

```
```
