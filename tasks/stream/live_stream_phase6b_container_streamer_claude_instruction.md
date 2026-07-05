# Claude用実装指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 6-B：VPS Container Streamer PoC MVP

## 目的

VPS本体を極力汚さず、OnHighGround2 本体コンテナ群を巻き込まない形で、YouTube配信用の streamer コンテナを追加する。

最終目標は 24時間365日の自動配信だが、本フェーズではそこまで行わない。

本フェーズの目的は、まず以下を確認できる最小PoCを作ること。

```text
1. streamer 専用コンテナを build できる
2. コンテナ内で Xvfb + Chromium + ffmpeg が起動できる
3. `/live/stream?chrome=off` を表示できる
4. 60秒のローカル録画 MP4 を生成できる
5. 重すぎる場合は streamer コンテナだけ停止できる
6. OnHighGround2 本体を壊さない
```

YouTube RTMPS への実送信は、本フェーズでは「設定とスクリプト雛形」まででよい。実送信は後続または手動確認で行う。

---

## 背景・方針

ユーザーは Mac + OBS から YouTube 配信に成功済み。

次の本丸は VPS からの自動配信だが、VPS本体に Chromium / ffmpeg / Xvfb / フォント / 音声系を直接入れると、OnHighGround2 本体に悪影響が出る可能性がある。

そのため、配信機能は streamer コンテナに隔離する。

```text
OnHighGround2本体:
  frontend / backend / martin / osrm-walking
  → 守る対象

streamer:
  Chromium / Xvfb / ffmpeg / fonts / run scripts
  → 実験対象
  → 重ければ止める
  → 壊れても本体を巻き込まない
```

重要な考え方:

```text
ヤバかったら止める
最初から高画質にしない
最初から常駐化しない
最初から本番 Stream Key を使わない
まずは60秒ローカル録画
```

---

## 絶対に守ること

### 1. VPSホストを汚さない

Dockerfile / compose / script で完結させる。

VPS本体への apt install を前提にしない。

### 2. 既存コンテナを壊さない

既存の `frontend`, `backend`, `martin`, `osrm-walking` 等のサービス設定は最小変更に留める。

streamer service 追加以外の compose 変更は必要最小限にする。

### 3. Stream Key を git 管理しない

YouTube Stream Key や RTMP URL を実ファイルに直書きしない。

`.env.stream` を使う場合は `.gitignore` に必ず追加する。

`.env.stream.example` にはダミー値のみを入れる。

### 4. 初期状態で自動再起動しない

PoC段階では以下を基本とする。

```yaml
restart: "no"
```

勝手に配信が再開される状態を作らない。

### 5. 初期品質は控えめにする

初期PoCは以下を推奨する。

```text
1280x720
30fps
3000〜3500kbps
無音AAC付き
```

1080p は後続で負荷確認後に検討する。

---

## 推奨構成

新規ディレクトリ例:

```text
streamer/
  Dockerfile
  entrypoint.sh
  run-record.sh
  run-youtube.sh
  README.md
.env.stream.example
```

compose 追加例:

```yaml
streamer:
  build:
    context: ./streamer
  container_name: onhighground-live-streamer
  depends_on:
    - frontend
  env_file:
    - .env.stream
  environment:
    STREAM_URL: "http://frontend/live/stream?chrome=off"
    STREAM_WIDTH: "1280"
    STREAM_HEIGHT: "720"
    STREAM_FPS: "30"
    VIDEO_BITRATE: "3500k"
    RECORD_SECONDS: "60"
    OUTPUT_FILE: "/recordings/stream-test.mp4"
  volumes:
    - ./test-results/streamer:/recordings
  shm_size: "512m"
  cpus: "1.0"
  mem_limit: "1024m"
  restart: "no"
  profiles:
    - streamer
```

`profiles` を使える構成なら、通常の `docker compose up -d` で streamer が勝手に起動しないようにする。

起動例:

```bash
docker compose --profile streamer build streamer
docker compose --profile streamer run --rm streamer record
```

compose の既存構成に合わせて調整してよい。

---

## Dockerfile要件

streamer コンテナに必要なもの:

```text
chromium または chromium-browser
xvfb
ffmpeg
fonts-noto-cjk
fonts-noto-color-emoji
ca-certificates
curl
jq
tini
bash
```

Debian/Ubuntu ベースでよい。

Chromium はコンテナ内では `--no-sandbox` が必要になる場合が多い。

日本語が豆腐にならないように Noto CJK を必ず入れる。

---

## entrypoint / mode設計

`entrypoint.sh` は mode を受け取れるようにする。

```bash
./entrypoint.sh record
./entrypoint.sh youtube
./entrypoint.sh shell
```

compose run から使いやすくする。

```bash
docker compose --profile streamer run --rm streamer record
docker compose --profile streamer run --rm streamer shell
docker compose --profile streamer run --rm streamer youtube
```

---

## 60秒ローカル録画モード

まず最重要。

`record` mode では、YouTubeへ送信せず、コンテナ内で `/live/stream?chrome=off` を表示し、ffmpeg で MP4 を生成する。

処理の流れ:

```text
1. Xvfb を DISPLAY=:99 で起動
2. Chromium を DISPLAY=:99 で起動
3. STREAM_URL を開く
4. 数秒待って画面ロード
5. ffmpeg で x11grab
6. anullsrc で無音音声を付ける
7. RECORD_SECONDS 秒で停止
8. /recordings/stream-test.mp4 を生成
```

ffmpeg例:

```bash
ffmpeg \
  -y \
  -f x11grab \
  -video_size "${STREAM_WIDTH}x${STREAM_HEIGHT}" \
  -framerate "${STREAM_FPS}" \
  -i "${DISPLAY}.0" \
  -f lavfi \
  -i anullsrc=channel_layout=stereo:sample_rate=44100 \
  -t "${RECORD_SECONDS}" \
  -c:v libx264 \
  -preset veryfast \
  -pix_fmt yuv420p \
  -b:v "${VIDEO_BITRATE}" \
  -maxrate "${VIDEO_BITRATE}" \
  -bufsize "7000k" \
  -c:a aac \
  -b:a 128k \
  "${OUTPUT_FILE}"
```

実装では必要に応じて調整してよい。

---

## Chromium起動要件

Chromium 起動例:

```bash
chromium \
  --no-sandbox \
  --disable-dev-shm-usage \
  --disable-gpu \
  --autoplay-policy=no-user-gesture-required \
  --window-size="${STREAM_WIDTH},${STREAM_HEIGHT}" \
  --start-fullscreen \
  "${STREAM_URL}"
```

`--disable-dev-shm-usage` は shm_size を取っていても保険として入れてよい。

ただし、描画に悪影響がある場合は調整する。

---

## YouTube送信モード

`youtube` mode は雛形として実装する。

必要な環境変数:

```text
YOUTUBE_RTMP_URL
YOUTUBE_STREAM_KEY
```

送信先URL:

```bash
${YOUTUBE_RTMP_URL}/${YOUTUBE_STREAM_KEY}
```

絶対に stream key をログに出さない。

ログに出す場合はマスクする。

```text
rtmps://a.rtmps.youtube.com/live2/****
```

ffmpeg は FLV/RTMPS 送信。

```bash
-f flv "${YOUTUBE_RTMP_URL}/${YOUTUBE_STREAM_KEY}"
```

本フェーズでは `youtube` mode の dry-run / help 表示まででも可。

ただし、後続で使える形にしておく。

---

## .env.stream.example

新規作成する。

```env
# Copy this file to .env.stream and fill in real values.
# DO NOT commit .env.stream.

YOUTUBE_RTMP_URL=rtmps://a.rtmps.youtube.com/live2
YOUTUBE_STREAM_KEY=replace-with-your-stream-key

STREAM_URL=http://frontend/live/stream?chrome=off
STREAM_WIDTH=1280
STREAM_HEIGHT=720
STREAM_FPS=30
VIDEO_BITRATE=3500k
RECORD_SECONDS=60
OUTPUT_FILE=/recordings/stream-test.mp4
```

`.env.stream` は `.gitignore` に追加。

---

## README / Runbook

`streamer/README.md` または `tasks/live/` に runbook を作成する。

最低限含めること:

```text
目的
構成
起動前確認
build方法
60秒録画方法
録画ファイル確認方法
YouTube送信モードの注意
緊急停止方法
リソース確認方法
トラブルシュート
```

緊急停止:

```bash
docker compose stop streamer
```

run container の場合:

```bash
docker ps
docker stop onhighground-live-streamer
```

または:

```bash
docker kill onhighground-live-streamer
```

---

## リソース制限

compose に以下を入れる。

```yaml
shm_size: "512m"
cpus: "1.0"
mem_limit: "1024m"
```

環境により `cpus` / `mem_limit` の扱いが異なる場合は、既存 compose 方針に合わせる。

初期PoCでは VPS本体保護を優先する。

---

## `/live/stream` URL

streamer コンテナから frontend に接続する。

優先:

```text
http://frontend/live/stream?chrome=off
```

既存 compose の service 名が異なる場合は合わせる。

外部 HTTPS URL を使うより、Docker network 内の frontend を使う方が負荷と依存が少ない。

ただし Caddy 経由でしか正しく動かない構成なら、外部URLも選択肢として残す。

---

## 実装対象外

本フェーズでは以下は対象外。

```text
24時間365日の常時配信
systemd timer / cron による自動起動
YouTube API で配信枠を自動作成
Stream Key の自動ローテーション
OBS実機制御
1080p本番配信
監視通知
```

これらは後続フェーズで扱う。

---

## 期待される成果物

```text
streamer/Dockerfile
streamer/entrypoint.sh
streamer/run-record.sh または entrypoint内record処理
streamer/run-youtube.sh または entrypoint内youtube処理
streamer/README.md
.env.stream.example
.gitignore 追記
docker-compose.yml または compose override への streamer service 追加
```

必要に応じて:

```text
tasks/live/live_stream_phase6b_container_streamer_runbook.md
```

---

## 実装後の自己確認

Claude側で最低限以下を確認する。

```bash
docker compose config
```

可能なら:

```bash
docker compose --profile streamer build streamer
```

ただし、実際の重い実行は CODEX 検証側で行ってよい。

---

## 完了条件

Claude実装としての完了条件:

```text
streamer コンテナ構成が追加されている
.env.stream.example がある
.env.stream が git 管理されない
record mode がある
youtube mode 雛形がある
リソース制限がある
restart: no または profiles で勝手に起動しない
README / runbook がある
既存 OnHighGround2 本体への変更が最小限
```

重要:

PoCなので、最初に重視するのは「安全に試せること」。
配信成功よりも、本体を壊さないこと、止められることを優先する。
