# /live Phase 1-B 危険地域カード強化 受入検証レポート

検証日: 2026-05-27 (JST)  
対象: Claude 修正後の作業ツリー上 `/live Phase 1-B 危険地域カード強化`  
判定: **PASS with notes**

## 判定概要

前回 FAIL とした false-safe 表示は解消された。

- 雨雲タイル取得成功時は `雨雲: 未判定（タイル表示のみ）` と表示され、`強雨域なし` と断定しない。
- キキクルタイル取得成功時は `キキクル: 未判定（タイル表示のみ）` と表示され、`キキクル危険地域なし` と断定しない。
- 安心メッセージは `地震・津波：大きな警戒情報はありません` となり、評価できない雨雲・キキクルを含む総合安全表示ではなくなった。
- API 503 時は `一部情報を取得できません` を表示し、page error なしで map 操作を継続できる。
- `/live` E2E は **23 passed**、既存ナビ代表 E2E は **44 passed**。
- 禁止ファイル変更や live から既存 navigation/state/reroute/OSRM への依存追加は確認されなかった。

注記: Phase 1-B の現行データ契約では雨雲・キキクルはタイル表示レイヤーであり、危険度集計は未実装である。今回の合格は、それらを未判定として明示し false-safe を避ける修正を受け入れたもの。将来 `危険あり / 危険なし` を表示するには、判定可能な summary データが別途必要である。

## 必須資料確認

確認済み:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/live/DEVELOPMENT_GUARDRAILS.md`
- `frontend/js/live/README.md`
- `tasks/live/live_mvp_codex_verification.md`

## 静的確認

### 差分境界

Phase 1-B の実装差分は `frontend/live.html`, `frontend/css/live/`, `frontend/js/live/`, `e2e/live-basic.spec.js`, `tasks/live/` の許可範囲に収まる。`.gitignore` の差分は live スクリーンショット出力先の除外追加である。

以下の禁止対象に差分はない。

- `frontend/index.html`
- `frontend/js/navigation.js`
- `frontend/js/state.js`
- `frontend/js/nav-*.js`
- `frontend/js/hazard-layers.js`
- `frontend/js/location-info-panel.js`
- 既存 reroute / bottom panel 関連

### 禁止依存

実行:

```bash
rg -n -i "navigation\.js|state\.js|location-info-panel|reroute|osrm|nav-[A-Za-z0-9_-]*\.js" frontend/js/live frontend/live.html frontend/css/live e2e/live-basic.spec.js nginx.conf
```

結果: PASS。live 側のヒットは依存しない旨のコメントと README のみ。`nginx.conf` の OSRM ヒットは既存ナビ向け proxy 設定のみ。

## 実行結果

| 確認 | コマンド | 結果 |
| --- | --- | --- |
| diff whitespace | `git diff --check` | PASS |
| JS / spec 構文 | `node --check frontend/js/live/live-map.js` ほか live JS と `e2e/live-basic.spec.js` | PASS |
| コンテナ状態 | `docker compose ps` | PASS: backend healthy, frontend running, martin healthy, osrm-walking running |
| Backend health | `curl -s http://127.0.0.1:8000/health` | PASS: `"status":"healthy"` |
| HTTP `/`, `/live`, `/live.html` | `curl -I ...` | PASS: 3 URL とも HTTP 200 |
| `/live` E2E | `npx playwright test e2e/live-basic.spec.js` | PASS: **23 passed** |
| 既存ナビ代表 E2E | `npx playwright test e2e/info-tab-card-ui.spec.js e2e/weather-rain-radar-card.spec.js e2e/tide-sun-moon-timeline.spec.js e2e/simulation-mode.spec.js` | PASS: **44 passed** |
| 実配信画面 probe | `node /private/tmp/phase1b_acceptance_probe.js` | PASS: false-safe 表示なし、API failure `pageErrors: []` |

## 修正確認

通常表示の probe 結果:

```text
津波警報なし
地震なし (24h)
雨雲: 未判定（タイル表示のみ）
キキクル: 未確認
地震・津波：大きな警戒情報はありません
```

キキクルトグル ON 後:

```text
雨雲: 未判定（タイル表示のみ）
キキクル: 未判定（タイル表示のみ）
地震・津波：大きな警戒情報はありません
```

これにより、取得できたタイルレイヤーを `危険なし` と読み替える表示は解消された。

## 危険地域ランキングとフォーカス

津波 warning と M6.4 地震の mock により以下を確認した。

- `宮城県沿岸` が危険地域 1 位、`三陸沖` が 2 位に表示される。
- 津波と M6 以上地震が danger 扱いで表示される。
- 緯度経度を持つ危険地域のクリックで map center / zoom が変わることは E2E で PASS。

雨雲・キキクルは現時点では危険地域ランキングの入力データではなく、カード上も未判定として表現される。

## API Failure

API 503 mock の表示:

```text
津波情報: 取得失敗
地震情報: 取得失敗
雨雲情報: 取得失敗
キキクル: 未確認
一部情報を取得できません
```

- `地震・津波：大きな警戒情報はありません` は表示されない。
- `pageErrors: []` を確認した。
- E2E で rain OFF -> ON 後も page error なし、status dot offline、map 操作継続を確認した。

## 既存ナビへの影響

確認範囲では影響なし。

- 禁止対象ファイルの差分なし。
- live から既存 `navigation.js` / `state.js` / reroute / OSRM への依存追加なし。
- `/` は HTTP 200。
- 既存ナビ代表 E2E は 44 passed。

## スクリーンショット

修正後に再取得済み:

- `tasks/live/verification_screenshots/phase1b-live-normal.png`
- `tasks/live/verification_screenshots/phase1b-live-danger.png`
- `tasks/live/verification_screenshots/phase1b-live-api-failure.png`
- `tasks/live/verification_screenshots/phase1b-navigation-root.png`

## Notes

- `e2e/live-basic.spec.js` は画面の存在、ランキング、フォーカス、API failure をカバーしているが、今回の修正文言である `未判定（タイル表示のみ）` と `地震・津波：` の完全一致 assertion は未追加である。今回は実配信画面 probe で確認した。
- 雨雲・キキクルの危険あり/なし判定を将来提供する場合は、タイル配信成功とは別の集計契約と E2E を追加する必要がある。
