# /live Phase 2-A 雨雲危険度集計 MVP 受入検証レポート

検証日: 2026-05-28 (JST)  
対象: `afba6d7` 上の `/live Phase 2-A 雨雲危険度集計 MVP`  
判定: **PASS with notes**

## 判定概要

- `/api/live/summary.rain` は判定済みの場合のみ `strong_rain_detected` を boolean で返し、判定不能または取得失敗を `false` にしない契約を満たす。
- 実 API は `status=ok`, `evaluated=true`, `reason=sampled_nowcast`, `strong_rain_detected=false`, `sample_count=11`, `unknown_count=0` を返した。
- mock warning で `/live` が `強雨域あり` と rain 由来の危険地域を表示し、mock offline では `雨雲情報: 取得失敗` を表示した。
- backend pytest は指定どおり **24 passed** と **21 passed**、`/live` E2E は **38 passed**、既存ナビ代表 E2E は **44 passed**。
- 禁止ファイル差分および live から navigation/state/reroute/OSRM への依存追加は確認されなかった。

## 必須資料確認

確認済み:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/live/DEVELOPMENT_GUARDRAILS.md`
- `frontend/js/live/README.md`
- `tasks/live/live_mvp_codex_verification.md`
- `tasks/live/live_phase1b_danger_cards_codex_verification.md`
- `tests/test_live_summary_api.py`
- `tests/test_live_rain_summary_service.py`

## 境界確認

作業開始時点の未コミット差分は `.gitignore` と本検証指示書のみであり、Phase 2-A 実装は HEAD に含まれていた。

以下の禁止対象に未コミット差分はない。

- `frontend/index.html`
- `frontend/js/navigation.js`
- `frontend/js/state.js`
- `frontend/js/nav-*.js`
- `frontend/js/hazard-layers.js`
- `frontend/js/location-info-panel.js`
- 既存 reroute / bottom panel 関連

禁止依存検索結果は PASS。`frontend/js/live/` の一致は依存しない旨のコメントのみ、`nginx.conf` の OSRM 一致は既存ナビ向け proxy 設定のみであった。

## 実行結果

| 確認 | コマンド | 結果 |
| --- | --- | --- |
| whitespace | `git diff --check` | PASS |
| live JS 構文 | `node --check frontend/js/live/live-map.js` ほか live JS 6 本 | PASS |
| 雨雲集計 unit test | `venv/bin/pytest tests/test_live_rain_summary_service.py` | PASS: **24 passed** |
| summary API test | `venv/bin/pytest tests/test_live_summary_api.py` | PASS: **21 passed** |
| Docker build | `docker compose build` | PASS |
| Docker 起動 | `docker compose up -d` | PASS |
| コンテナ状態 | `docker compose ps` | PASS: backend healthy, frontend running, martin healthy, osrm-walking running |
| Backend health | `curl -s http://127.0.0.1:8000/health` | PASS: `"status":"healthy"` |
| HTTP 配信 | `curl -I http://127.0.0.1:8080/`, `/live`, `/live.html` | PASS: 3 URL とも HTTP 200 |
| summary 実 API | `curl -i http://127.0.0.1:8000/api/live/summary` | PASS: HTTP 200、rain 契約確認済み |
| `/live` E2E | `npx playwright test e2e/live-basic.spec.js` | PASS: **38 passed** |
| 既存ナビ代表 E2E | `npx playwright test e2e/info-tab-card-ui.spec.js e2e/weather-rain-radar-card.spec.js e2e/tide-sun-moon-timeline.spec.js e2e/simulation-mode.spec.js` | PASS: **44 passed** |
| 実画面 probe | `node /private/tmp/phase2a_acceptance_probe.js` | PASS: normal / warning / offline 表示、offline `pageErrors: []` |

補足: 指示書の `pytest` は PATH 上に存在しなかったため、プロジェクト仮想環境の `venv/bin/pytest` で実行した。

## Summary API 契約

実 API の rain レスポンス:

```json
{
  "status": "ok",
  "evaluated": true,
  "reason": "sampled_nowcast",
  "summary": {
    "strong_rain_detected": false,
    "warning_area_count": 0,
    "danger_area_count": 0,
    "sample_count": 11,
    "unknown_count": 0
  },
  "areas": []
}
```

確認結果:

- `evaluated` は boolean。
- `evaluated=true` のため `strong_rain_detected=false` は契約上妥当。
- `sample_count=11 > 0` かつ `unknown_count / sample_count = 0 < 0.5`。
- 実天候では rain warning / danger は検出されなかったため、危険あり表示は E2E と画面 mock で確認した。

## False-Safe 確認

テストと画面確認により以下を確認した。

- unknown が 50% 以上の場合は `evaluated=false`, `reason=too_many_unknown_samples`, `strong_rain_detected=null`。
- source failure / 空サンプルでは `status=offline`, `evaluated=false`, `strong_rain_detected=null`。
- frontend は `rain evaluated=false` で `強雨域なし` を表示しない。
- frontend は `rain offline` で `雨雲情報: 取得失敗` を表示する。
- offline 表示中にも application page error は発生しない。

## 集計ロジック確認

[live_rain_summary_service.py](/Users/hideki/Documents/GitHub/OnHighGround2/backend/app/services/live_rain_summary_service.py:1) を確認した。

- 全国 11 地点: 札幌、仙台、東京、新潟、名古屋、大阪、広島、高知、福岡、鹿児島、那覇。
- キャッシュ TTL: `120.0` 秒。
- 既存 `services.jma_rain_tile_service.get_precip_intensity_at` を再利用し、frontend ラスタ解析を追加していない。
- `strong` は rain area の `warning`、`severe` は `danger` として生成される。
- warning / danger の rain areas は `live_summary_service._merge_dangerous_areas()` により `dangerous_areas` へ統合される。
- unknown 率 `>= 0.5` は評価不能とし、false-safe を避ける。

## 実画面確認

実 API の通常表示:

```text
地震 9件 (24h)
強雨域なし
キキクル: 未確認
地震・津波：大きな警戒情報はありません
```

rain warning mock:

```text
強雨域あり
危険地域
1 福岡県付近 / 雨雲
```

rain offline mock:

```text
雨雲情報: 取得失敗
```

offline mock では `pageErrors: []` を確認した。地震・津波の限定メッセージは表示されるが、雨雲について安全を断定する表示ではない。

## 既存ナビへの影響

確認範囲では影響なし。

- 禁止ファイルへの未コミット差分なし。
- live summary 実装に navigation/state/reroute/OSRM 依存追加なし。
- 既存 `/` HTTP 200。
- 既存ナビ代表 E2E **44 passed**。

## スクリーンショット

保存済み:

- `tasks/live/verification_screenshots/phase2a-live-normal.png`
- `tasks/live/verification_screenshots/phase2a-live-rain-warning.png`
- `tasks/live/verification_screenshots/phase2a-live-rain-offline.png`
- `tasks/live/verification_screenshots/phase2a-navigation-root.png`

## Notes

- 実配信確認時は強雨なしであり、rain warning / danger 表示は mock による確認である。
- 11 地点サンプリングは MVP として軽量だが、地点間の狭い強雨域を取り逃す可能性がある。
- 実装は `_INTENSITY_TO_LEVEL` に `moderate: "watch"` を定義している一方、公開 `areas` は強雨相当の `warning` / `danger` のみを返す。`watch` 地点を rain セクションの参考表示として公開する必要が生じた場合は、`dangerous_areas` へ混ぜずに別途契約を拡張する余地がある。
