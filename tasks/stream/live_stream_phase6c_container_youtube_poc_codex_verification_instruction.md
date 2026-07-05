# CODEX用検証指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 6-C：VPS Container YouTube 限定公開 5分送信 PoC 検証

## 目的

Claude実装後、streamer コンテナから YouTube 限定公開ライブへ 5分送信できることを検証する。

最重要観点は以下。

```text
Stream Key を漏らさない
YOUTUBE_CONFIRM=1 のときだけ実送信する
5分PoCに留める
streamerだけを起動/停止する
既存 OnHighGround2 本体を巻き込まない
VPSリソースが危険域に入らないか確認する
```

## 前提

Phase 6-B は PASS with notes。

確認済み:

```text
streamer build成功
60秒ローカル録画成功
1280x720 / H.264 / AAC
profiles: [streamer]
restart: "no"
.env.stream は git 管理外
```

Phase 6-B notes:

```text
720p/30fpsでCPU約110%
メモリ約902MiB/1GiB
```

そのため、Phase 6-C は 720p/30fps/5分限定で行う。

## 検証前の重要注意

実Stream Keyを扱うため、以下を絶対に守る。

```text
Stream Keyをレポートに書かない
Stream Keyをログに貼らない
Stream Keyをスクショに含めない
Stream Keyをgit diffに含めない
.env.streamをgit管理しない
```

検証レポートでは必ずマスクする。

```text
rtmps://a.rtmps.youtube.com/live2/****
```

## 事前確認

### 1. 差分確認

```bash
git diff --stat
git diff
```

確認:

```text
streamer関連以外を大きく変更していない
restart: "no" が維持されている
profiles: [streamer] が維持されている
.env.stream が git に入っていない
```

### 2. secret確認

```bash
git ls-files .env.stream
rg -n "YOUTUBE_STREAM_KEY|live2/|rtmps://" . \
  --glob '!.git/**' \
  --glob '!.env.stream' \
  --glob '!*.log' \
  --glob '!test-results/**'
```

期待:

```text
.env.stream は tracked ではない
実Stream Keyが出ない
.env.stream.example は dummy のみ
runbookやREADMEに実Stream Keyがない
```

### 3. compose確認

```bash
docker compose config --services
docker compose --profile streamer config --services
docker compose --profile streamer config
```

期待:

```text
通常 config --services に streamer が出ない
--profile streamer 指定時のみ streamer が出る
restart: "no"
```

## 静的確認

```bash
bash -n streamer/entrypoint.sh
bash -n streamer/run-record.sh
bash -n streamer/run-youtube.sh
```

必要に応じて README/runbook も確認する。

## build確認

```bash
docker compose --profile streamer build streamer
```

期待:

```text
build成功
既存サービスを停止しない
```

## dry-run確認

実送信前に必ず dry-run を確認する。

```bash
docker compose --profile streamer run --rm streamer youtube
```

または既存設計に合わせた dry-run コマンド。

期待:

```text
YOUTUBE_CONFIRM=1 なしでは実送信しない
出力URLは **** でマスクされる
Stream Key が表示されない
```

FAIL:

```text
YOUTUBE_CONFIRM=1 なしで実送信しようとする
Stream Keyが表示される
```

## YouTube限定公開 5分送信確認

### 1. ユーザー準備

ユーザーが YouTube Studio で限定公開ライブ枠を作成し、`.env.stream` に実Stream Keyを設定していることを確認する。

`.env.stream` の中身は表示しない。

必要項目:

```text
YOUTUBE_RTMP_URL
YOUTUBE_STREAM_KEY
STREAM_DURATION_SEC=300
STREAM_WIDTH=1280
STREAM_HEIGHT=720
STREAM_FPS=30
VIDEO_BITRATE=3000k or 3500k
AUDIO_BITRATE=128k
```

### 2. 実送信コマンド

```bash
docker compose --profile streamer run --rm \
  -e YOUTUBE_CONFIRM=1 \
  -e STREAM_DURATION_SEC=300 \
  streamer youtube
```

既存 entrypoint に合わせて読み替える。

### 3. YouTube側確認

確認項目:

```text
YouTube Studioに映像が来る
限定公開ライブである
映像が /live/stream?chrome=off である
日本語が文字化けしない
地図/パネル/tickerが表示される
音声トラックあり、または無音AACとして送信されている
5分間大きく止まらない
```

可能ならユーザーがYouTube Studio側で確認する。

## 負荷確認

実送信中、別ターミナルで確認。

```bash
docker stats --no-stream
```

または連続観察:

```bash
docker stats
```

記録対象:

```text
streamer CPU%
streamer MEM usage / limit
frontend CPU/MEM
backend CPU/MEM
martin CPU/MEM
osrm CPU/MEM
```

目安:

```text
streamer CPUが1CPU程度: notes
streamer MEMが900MiB前後: notes
1GiB超過/OOM/既存サービス不安定: FAIL
既存サービスのCPU/MEMが異常増加: FAIL or notes
```

## 停止確認

5分終了後、または手動停止後に確認。

```bash
docker ps --format '{{.Names}}'
docker compose ps
```

期待:

```text
streamer が残り続けない
backend/frontend/martin/osrm は継続
```

必要なら:

```bash
docker compose --profile streamer stop streamer
```

緊急時:

```bash
docker kill <streamer-container-name>
```

## HTTP回帰確認

送信後に確認。

```bash
curl -I http://127.0.0.1:8080/live/stream
curl -I "http://127.0.0.1:8080/live/stream?chrome=off"
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
```

期待:

```text
すべて 200 OK
```

## E2E回帰

最低限 scoped live-stream E2E を実行。

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
  e2e/live-stream-railway-calm-map.spec.js
```

重すぎる場合は、HTTP確認と主要streamer確認を優先し、E2E未実施を notes に記録する。

## 検証レポート作成

以下に作成する。

```text
tasks/live/live_stream_phase6c_container_youtube_poc_codex_verification.md
```

構成:

```md
# live stream Phase 6-C container YouTube PoC verification

## Result
PASS / FAIL / PASS with notes

## Summary

## Checked files

## Environment

## Commands

## Secret handling

## Dry-run result

## YouTube 5min send result

## Resource observations

## Stop behavior

## HTTP regression

## E2E regression

## Findings

## Notes

## Final judgement
```

## PASS条件

```text
streamerは通常composeで起動しない
restart: "no" 維持
Stream Keyが漏れていない
YOUTUBE_CONFIRM=1なしでは実送信しない
YouTube限定公開へ5分送信できる
YouTube側で映像が確認できる
送信中に既存サービスが落ちない
停止後も既存サービスが動作している
/live/stream, /live, / が 200 OK
```

## PASS with notes条件

```text
送信は成功したがCPU/MEMが高い
5分は成功したが30分以上は未検証
YouTube側で軽微な警告が出たが映像は継続
E2Eを全件は実施していないが主要確認は通過
```

## FAIL条件

```text
Stream Keyがログ/ファイル/レポートに露出
YOUTUBE_CONFIRM=1なしで実送信される
streamer起動で既存サービスが落ちる
streamer停止で既存サービスも止まる
5分送信中にVPSが不安定化
YouTube側に映像が来ない
ffmpegが即終了して原因不明
/live/stream が壊れる
```

## 注意

この検証は実際にYouTubeへ送信する。

必ず限定公開で行うこと。

配信キーを絶対に貼らないこと。

ヤバかったら streamer だけ止めること。
