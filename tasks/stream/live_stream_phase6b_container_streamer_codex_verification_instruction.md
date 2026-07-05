# CODEX用検証指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 6-B：VPS Container Streamer PoC MVP 検証

## 目的

Claude実装後、VPS配信用 streamer コンテナが安全に追加されているかを検証する。

本フェーズの検証目的は YouTube本番配信ではない。

まず以下を確認する。

```text
1. 既存 OnHighGround2 本体を壊していない
2. streamer コンテナが build できる
3. 60秒ローカル録画ができる
4. streamer だけ停止できる
5. Stream Key が git 管理・ログ露出されていない
6. CPU/メモリが危険な初期設定になっていない
```

---

## 重要方針

今回の streamer は実験対象であり、OnHighGround2 本体は守る対象。

```text
frontend / backend / martin / osrm-walking:
  守る対象

streamer:
  実験対象
  重ければ止める
```

検証中に負荷が危険と判断したら、即停止する。

緊急停止:

```bash
docker compose stop streamer || true
docker ps --format '{{.Names}}' | grep -E 'streamer|onhighground-live-streamer' | xargs -r docker stop
```

さらに必要なら:

```bash
docker ps --format '{{.Names}}' | grep -E 'streamer|onhighground-live-streamer' | xargs -r docker kill
```

---

## 事前確認

まず差分を確認する。

```bash
git diff --stat
git diff
```

重点確認:

```text
既存 frontend/backend/martin/osrm の設定を大きく変えていないか
streamer service が勝手に起動しない設定か
restart: no または profiles があるか
cpus / mem_limit / shm_size があるか
.env.stream が git 管理されないか
YouTube Stream Key の実値が含まれていないか
```

---

## 静的確認

### 1. compose 構文確認

```bash
docker compose config
```

profiles を使っている場合も確認する。

```bash
docker compose --profile streamer config
```

### 2. shell script 構文確認

対象例:

```bash
bash -n streamer/entrypoint.sh
bash -n streamer/run-record.sh 2>/dev/null || true
bash -n streamer/run-youtube.sh 2>/dev/null || true
```

実際のファイル名に合わせること。

### 3. Dockerfile確認

以下が含まれているか確認。

```text
chromium または chromium-browser
xvfb
ffmpeg
fonts-noto-cjk
fonts-noto-color-emoji
ca-certificates
curl
jq または必要ツール
tini または適切なsignal handling
```

### 4. secrets確認

以下を確認。

```bash
git status --short
grep -R "YOUTUBE_STREAM_KEY\|live2/" -n . \
  --exclude-dir=.git \
  --exclude='.env.stream' \
  --exclude='*.log' || true
```

実Stream Keyらしき値が git 管理対象に入っていたら FAIL。

`.env.stream.example` のダミー値はOK。

---

## Docker build確認

```bash
docker compose --profile streamer build streamer
```

または実装に合わせる。

build が通ること。

失敗した場合は、原因をレポートに明記する。

---

## 既存サービス確認

streamer build 後も既存サービスが正常であること。

```bash
docker compose ps
curl -I http://127.0.0.1:8080/live/stream
curl -I "http://127.0.0.1:8080/live/stream?chrome=off"
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
```

期待:

```text
/live/stream 200
/live 200
/ 200
backend healthy
martin healthy
```

---

## 60秒ローカル録画検証

最重要検証。

YouTubeへ送信せず、MP4を生成する。

例:

```bash
mkdir -p test-results/streamer
docker compose --profile streamer run --rm streamer record
```

実装コマンドに合わせてよい。

期待される出力:

```text
test-results/streamer/stream-test.mp4
```

または指定された OUTPUT_FILE。

確認:

```bash
ls -lh test-results/streamer/
ffprobe -hide_banner test-results/streamer/stream-test.mp4
```

`ffprobe` がない場合は、コンテナ内または `file` コマンドで確認してよい。

```bash
file test-results/streamer/stream-test.mp4
```

期待:

```text
映像トラックあり
音声トラックあり、無音AACでよい
長さがおおむね RECORD_SECONDS
解像度が設定値と一致
```

---

## 録画内容の目視確認

可能なら生成された MP4 を取得/再生して確認。

確認ポイント:

```text
/live/stream?chrome=off が映っている
日本語文字が豆腐になっていない
白画面ではない
地図・パネル・テロップが見える
極端な崩れがない
```

自動確認だけで済ませる場合も、スクリーンショットや ffprobe 情報をレポートに残す。

---

## リソース確認

録画中に別ターミナルで確認。

```bash
docker stats --no-stream
```

または録画実行中に数回取得。

見るポイント:

```text
streamer のCPUが危険に張り付いていないか
メモリが mem_limit に張り付いていないか
既存 backend/frontend/martin が異常に重くなっていないか
```

初回PoCでは厳密なPASS基準は置かないが、以下は FAIL または STOP 推奨。

```text
VPS全体が操作不能に近い
backend/frontend が落ちる
メモリ不足でOOM
streamer停止後も負荷が残る
```

---

## 停止確認

streamer を停止できることを確認。

compose run --rm なら終了後に残らないこと。

```bash
docker ps --format '{{.Names}}'
```

起動し続ける形なら:

```bash
docker compose stop streamer
```

期待:

```text
streamer だけ止まる
frontend/backend/martin/osrm は止まらない
```

---

## YouTube送信モードの安全確認

本フェーズでは実送信しない場合でも、以下を確認。

```text
YOUTUBE_RTMP_URL / YOUTUBE_STREAM_KEY が未設定なら安全に失敗する
Stream Key をログに出さない
youtube mode が勝手に起動しない
restart: unless-stopped などで勝手に再送信しない
```

実Stream Keyを使う検証は、ユーザーが明示的に許可した場合のみ。

実送信する場合も限定公開/非公開で5分以内から開始すること。

---

## 既存 `/live/stream` E2E 回帰

可能なら scoped E2E を実行。

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

重すぎる場合は代表E2Eのみでよい。

streamer追加により `/live/stream` 本体が壊れていないことを確認する。

---

## レポート作成

以下に検証レポートを作成する。

```text
tasks/live/live_stream_phase6b_container_streamer_codex_verification.md
```

構成:

```md
# live stream Phase 6-B container streamer verification

## Result

PASS / FAIL / PASS with notes

## Summary

## Checked files

## Environment

## Commands

## Docker build

## Local recording result

## Resource observations

## Stop behavior

## Secret handling

## Existing app regression

## Findings

## Notes

## Final judgement
```

---

## PASS条件

以下を満たす場合 PASS。

```text
streamer service が追加されている
streamer が通常起動で勝手に動かない
.env.stream が git 管理されない
実Stream Key が差分に含まれていない
Docker build が通る
60秒ローカル録画 MP4 が生成される
録画に映像・音声トラックがある
録画に /live/stream が表示されている
streamer だけ停止できる
既存 /live/stream /live / が壊れていない
```

---

## PASS with notes 条件

以下は notes 付きPASS可。

```text
録画は成功したがCPU負荷が高め
720pは成功、1080pは未検証
YouTube送信モードは未実送信
一部 requestfailed はあるが録画は成立
録画開始まで数秒白画面があるが本編は表示される
```

---

## FAIL条件

以下は FAIL。

```text
既存 OnHighGround2 本体が起動しなくなる
/live/stream が壊れる
Docker build できない
record mode がない
録画ファイルが生成されない
録画が白画面のみ
日本語が豆腐になる
streamer が停止できない
Stream Key が git 管理対象に入る
streamer が通常 docker compose up -d で勝手に配信開始する
restart: unless-stopped 等でPoC段階なのに自動再起動する
```

---

## 最終判断

検証完了後、以下を明記する。

```text
PASS
PASS with notes
FAIL
```

今回の最重要判断基準は「安全に試せるコンテナになっているか」。
YouTube配信成功は後続フェーズでよい。
