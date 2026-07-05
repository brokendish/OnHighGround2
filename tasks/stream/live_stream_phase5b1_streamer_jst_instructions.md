# /live/stream Stream Phase 5-B.1 指示書
## Streamer JST時刻固定・配信表示微調整

# Claude用実装指示書

## 目的
VPS上の streamer container から `/live/stream` をYouTube Liveへ送信できたが、配信プレビュー上で画面内時刻がUTC表示になっている疑いがある。Phase 5-B.1では、`/live/stream` の時計・日付・中央地図内時刻・潮位の現在時刻処理をJST固定にし、streamer container側にも `TZ=Asia/Tokyo` を設定する。

## 対象
- `/live/stream` ヘッダー時計
- `/live/stream` 日付表示
- 中央地図内の現在時刻
- 潮位グラフの現在時刻マーカー
- `demoNow` のJST解釈
- streamer container の timezone 設定
- `chrome=off` の配信表示確認

## 対象外
- 地図スライド時の白抜け抑制
- OBS soak 本体
- YouTube API連携
- ffmpeg大規模チューニング
- 新規災害カテゴリ追加
- 地図・鉄道レイヤー再設計

## 1. フロント時計をJST明示にする
`new Date()` をローカルtimezone依存で表示している箇所を確認し、`Intl.DateTimeFormat` 等で `timeZone: "Asia/Tokyo"` を明示する。

対象候補:
- `frontend/js/live-stream/live-stream-clock.js`
- `frontend/js/live-stream/live-stream-runtime.js`
- `frontend/js/live-stream/live-stream-panels.js`
- `frontend/js/live-stream/live-stream-scene.js`
- 潮位関連の live-stream JS

実装例:

```js
const JST_TIME_ZONE = "Asia/Tokyo";

const timeFormatter = new Intl.DateTimeFormat("ja-JP", {
  timeZone: JST_TIME_ZONE,
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false
});

const dateFormatter = new Intl.DateTimeFormat("ja-JP", {
  timeZone: JST_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  weekday: "short"
});
```

期待:
- ヘッダー時計がJST
- 日付がJST
- 中央地図内時刻がJST
- `JST` 表記と実時刻が一致
- コンテナがUTCでも画面はJST

## 2. demoNow のJST扱い
以下のような `+09:00` 付き `demoNow` をJSTとして正しく扱う。

```text
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00
```

期待:
- ヘッダー時計が `19:42:00`
- 日付が `2026.06.30`
- 中央地図内時刻も `19:42`
- 潮位現在時刻マーカーも19:42相当
- UTC変換されて `10:42` にならない
- `Invalid Date` を出さない

## 3. 潮位グラフとの整合
timezone修正で潮位グラフが9時間ずれないことを確認する。

確認URL例:
```text
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T06:00:00%2B09:00
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T12:00:00%2B09:00
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T18:00:00%2B09:00
```

期待:
- 06:00 / 12:00 / 18:00 がそのまま表示される
- 潮位マーカー位置が大きく破綻しない

## 4. streamer container に TZ を設定
streamer service に `TZ=Asia/Tokyo` を追加する。

候補:
- `docker-compose.yml`
- `docker-compose.streamer.yml`
- `docker-compose.override.yml`
- `.env.stream`
- `streamer/Dockerfile`

例:

```yaml
environment:
  - TZ=Asia/Tokyo
```

または Dockerfile 側:

```Dockerfile
ENV TZ=Asia/Tokyo
```

重要:
- stream key をログに出さない
- `.env.stream` をgit管理に入れない
- dummy dry-run時の key mask を維持する
- `profiles: [streamer]` を維持する
- `restart: "no"` を維持する
- 通常composeでstreamerが勝手に起動しない

## 5. 配信表示の軽微確認
大きな負荷改善はしない。以下だけ確認する。
- `chrome=off` で不要UIが出ない
- 時計がJSTで進む
- テロップが動く
- 小画面が崩れない
- YouTube StudioプレビューでJST表示になる
- 既存サービスが稼働継続する

## 6. 今回やらないこと
- 地図スライド時の白抜け抑制
- Leaflet tile loading mask
- OBS soak 30〜60分検証本体
- YouTube API連携
- 自動配信開始/停止
- ffmpeg大規模チューニング
- 画質設定の大幅変更
- 新規Docker構成の大改修

## 7. 受け入れ条件
- `/live/stream` のヘッダー時計がJST
- `/live/stream?chrome=off` でもJST
- streamer container経由の録画/YouTubeプレビューでもJST
- 日付がJST基準
- `JST` 表記と表示時刻が一致
- `demoNow=...+09:00` が指定時刻のまま表示される
- 潮位グラフの現在時刻マーカーが9時間ずれない
- streamer containerに `TZ=Asia/Tokyo` が設定される
- stream key秘匿が維持される
- 通常composeでstreamerが勝手に起動しない
- 既存E2EがPASS
- `/live` と `/` が壊れない
- console/page error がない

## 8. 実装後の報告
- 変更ファイル
- JST明示化した箇所
- `demoNow` の扱い
- streamer container の `TZ=Asia/Tokyo` 設定箇所
- 録画/YouTube配信プレビューでの確認結果
- 既存E2E結果
- 未対応項目
- 次フェーズ候補

---

# CODEX用検証指示書

## 目的
Claude実装後、`/live/stream` と streamer container のJST時刻固定・配信表示微調整を検証する。

レポート保存先:

```text
tasks/live/live_stream_phase5b1_streamer_jst_codex_verification.md
```

## 1. 静的確認

```bash
git status --short
git diff --stat
```

確認:
- `/live/stream` 時計処理の修正がある
- `timeZone: "Asia/Tokyo"` 相当の明示がある
- streamer service に `TZ=Asia/Tokyo` がある
- stream keyを露出する変更がない
- `.env.stream` をgit管理していない
- `profiles: [streamer]` / `restart: "no"` が維持されている

## 2. 構文チェック

```bash
node --check frontend/js/live-stream/live-stream-clock.js
node --check frontend/js/live-stream/live-stream-runtime.js
node --check frontend/js/live-stream/live-stream-main.js
node --check frontend/js/live-stream/live-stream-panels.js
node --check frontend/js/live-stream/live-stream-ticker.js
```

変更ファイルに応じて追加する。

JST用E2Eがある場合:

```bash
node --check e2e/live-stream-jst-clock.spec.js
```

## 3. compose / timezone確認

```bash
docker compose config | grep -A30 -n "streamer"
```

確認:
- `TZ=Asia/Tokyo`
- `profiles: [streamer]`
- `restart: "no"` または同等
- stream keyが表示されていない

`.env.stream` の確認:

```bash
git status --short .env.stream
git ls-files .env.stream
```

期待:
- `.env.stream` は追跡されていない

## 4. HTTP確認

```bash
curl -I http://127.0.0.1:8080/live/stream
curl -I "http://127.0.0.1:8080/live/stream?chrome=off"
curl -I "http://127.0.0.1:8080/live/stream?state=calm&chrome=off"
curl -I "http://127.0.0.1:8080/live/stream?demo=1&chrome=off"
curl -I "http://127.0.0.1:8080/live"
curl -I "http://127.0.0.1:8080/"
```

すべて200であること。

## 5. JST時計表示確認

対象URL:

```text
/live/stream?chrome=off
```

確認:
- ヘッダー時計が現在JSTと一致
- 日付がJST基準
- `JST` 表記あり
- 中央地図内時刻もJST
- UTC時刻ではない
- 9時間ずれていない

画面時計と以下の値を比較する。

```js
new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false
}).format(new Date())
```

許容:
- 数秒程度の差

FAIL:
- UTC表示
- JST表記なのにUTC時刻
- 日付がUTC基準で前日/翌日

## 6. demoNow JST固定確認

対象URL:

```text
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00
```

期待:
- ヘッダー時計が `19:42:00`
- 日付が `2026.06.30` 相当
- `JST` 表記あり
- 中央地図内時刻も `19:42`
- UTC変換されて `10:42` にならない

追加確認:

```text
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T06:00:00%2B09:00
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T12:00:00%2B09:00
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T18:00:00%2B09:00
```

## 7. streamer container timezone確認

streamer containerで確認する。

```bash
docker compose --profile streamer run --rm streamer sh -lc 'echo $TZ; date'
```

期待:
- `Asia/Tokyo`
- JST相当の時刻

注意:
- 本番stream keyを不用意に使わない

## 8. streamer録画またはdry-run確認

可能であれば録画で確認する。

```bash
docker compose --profile streamer run --rm streamer record
```

既存手順が異なる場合はそれに合わせる。

確認:
- 録画画面の時計がJST
- `chrome=off` 表示が崩れない
- 日本語表示が崩れない
- 地図・小画面・テロップが表示される
- streamer終了後も既存サービスが稼働継続
- stream keyがログに出ない

## 9. YouTubeプレビュー確認

可能であればYouTube Studioプレビューで確認する。

確認:
- 配信プレビューに `/live/stream` が表示される
- 画面内時計がJST
- UTC表示ではない
- ストリーム状態が正常または「非常に良い」
- 既存サービスが稼働継続
- stream keyがログに出ない

`docker stats --no-stream` を記録する。

## 10. 既存E2E回帰

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

JST用E2Eがある場合:

```bash
npx playwright test e2e/live-stream-jst-clock.spec.js
```

期待:
- 全テストPASS

## 11. 表示欠損確認

以下が出ていないこと。

```text
undefined
null
NaN
Invalid Date
[object Object]
```

特に:
- ヘッダー時計
- 日付
- 中央地図内時刻
- 潮位グラフ
- 下部テロップ

## 12. `/live` 回帰確認

通常 `/live` を開く。

確認:
- HTTP 200
- console/page errorなし
- 地図・地震・豪雨・潮位・鉄道表示が壊れていない

## 13. `/` 回帰確認

ナビ本体 `/` を開く。

確認:
- HTTP 200
- console/page errorなし
- 基本地図表示が壊れていない
- `/live/stream` CSS/JS が漏れていない

## 14. スクリーンショット保存

```text
test-results/live-stream-phase5b1-jst-normal-1920.png
test-results/live-stream-phase5b1-jst-demo-1942-1920.png
test-results/live-stream-phase5b1-jst-calm-1920.png
test-results/live-stream-phase5b1-youtube-preview.png
```

YouTube preview は可能な場合のみ。

## 15. レポートに含める内容

- 判定: PASS / PASS with notes / FAIL
- 検証日時
- 対象ブランチ/コミット
- 変更ファイル
- 構文チェック結果
- compose / streamer timezone 設定確認
- HTTP確認結果
- JST時計表示確認
- `demoNow` JST固定確認
- 潮位現在時刻マーカー確認
- streamer container timezone確認
- 録画/dry-run確認
- YouTube配信プレビュー確認
- `docker stats` 結果
- 既存E2E結果
- 表示欠損確認
- `/live` 回帰
- `/` 回帰
- スクリーンショット保存先
- Notes
- 修正推奨事項
- 次フェーズ候補

## PASS条件

- `/live/stream?chrome=off` の時計がJST
- 日付がJST基準
- `JST` 表記と表示時刻が一致
- `demoNow=...+09:00` が指定時刻のまま表示
- UTC表示へ9時間ずれない
- 潮位現在時刻マーカーが大きくずれない
- streamer container に `TZ=Asia/Tokyo`
- stream keyが露出しない
- 通常composeでstreamerが勝手に起動しない
- 既存E2EがPASS
- `/live` と `/` が壊れない
- console/page errorなし

## PASS with notes条件

- YouTube実配信プレビューは未実施だが録画でJST確認済み
- streamer containerのOS timezoneはUTCだがフロント表示はJST固定
- 潮位マーカー確認が代表時刻のみ
- docker stats は短時間確認のみ
- 軽微な console warning がある

## FAIL条件

- YouTubeプレビューまたは録画で時計がUTC表示
- `JST` 表記なのにUTC時刻
- `demoNow=19:42+09:00` が `10:42` などにずれる
- `Invalid Date` が表示される
- stream keyが露出する
- streamer が通常 compose で勝手に起動する
- 既存E2Eが壊れる
- `/live` または `/` が壊れる
- 重大な console/page error

## 最終コメント例

```text
判定: PASS

/live/stream Phase 5-B.1 Streamer JST時刻固定・配信表示微調整を検証しました。
/live/stream?chrome=off、demoNow指定、streamer container経由の録画/配信プレビューで、画面内時計・日付・中央地図内時刻がJST表示になることを確認しました。
streamer container には TZ=Asia/Tokyo が設定され、stream key の秘匿、profiles: [streamer] による通常起動抑制も維持されています。
既存E2E、通常 /live、/ への回帰影響はありません。
次フェーズでは Stream Phase 5-C 地図スライド時の白抜け抑制へ進めます。
```
