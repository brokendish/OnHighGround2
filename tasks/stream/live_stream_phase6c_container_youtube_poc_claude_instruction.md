# Claude用実装・運用準備指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 6-C：VPS Container YouTube 限定公開 5分送信 PoC

## 目的

Phase 6-B で作成・検証済みの streamer コンテナを使い、VPS上のコンテナから YouTube 限定公開ライブへ 5分だけ送信できることを確認する。

今回の目的は 24時間配信ではない。

まず以下を確認する。

```text
streamer コンテナから YouTube RTMPS へ送信できる
720p/30fps の負荷が VPS 上で許容範囲か確認できる
Stream Key がログ・Git・成果物へ漏れない
ヤバかったら streamer コンテナだけ停止できる
既存 OnHighGround2 本体を巻き込まない
```

## 前提

Phase 6-B は完了済み。

確認済みの前提:

```text
streamer service は profiles: [streamer]
restart: "no"
通常 docker compose up では起動しない
60秒ローカル録画成功
1280x720 / H.264 / AAC
/live/stream?chrome=off が録画に表示される
実Stream Keyは未露出
.env.stream は git 管理外
```

Phase 6-B の notes:

```text
720p/30fps 録画中に CPU 約110%
メモリ 約902MiB / 1GiB
PoCとしては許容だが、1080pや常用前に追加確認が必要
```

そのため Phase 6-C では **720p/30fps 固定** で進める。

## 絶対に守ること

### 1. いきなり常駐化しない

禁止:

```text
restart: unless-stopped へ変更する
systemd 化する
cron/timer 化する
24時間配信設定を入れる
```

今回の PoC は手動実行のみ。

### 2. 1080p化しない

禁止:

```text
1920x1080
60fps
高ビットレート
```

初期値は以下を維持する。

```text
1280x720
30fps
3000k〜3500k
```

### 3. Stream Key を絶対に漏らさない

禁止:

```text
Stream Key を git 管理する
Stream Key をログに出す
Stream Key を検証レポートへ書く
Stream Key を screenshots / artifacts に含める
```

`.env.stream` は git 管理外であること。

`.env.stream.example` は dummy 値のみ。

### 4. 既存サービスを止めない

streamer の起動・停止で以下を止めないこと。

```text
frontend
backend
martin
osrm-walking
```

停止は streamer のみ。

```bash
docker compose --profile streamer stop streamer
```

または run 実行中なら Ctrl+C で streamer 実行だけ止める。

## 実装・準備対象

既存 Phase 6-B の streamer 構成を確認し、不足があれば最小限修正する。

対象例:

```text
streamer/run-youtube.sh
streamer/entrypoint.sh
streamer/README.md
tasks/live/live_stream_phase6c_container_youtube_poc_runbook.md
.env.stream.example
docker-compose.yml
```

## 追加・確認すべき機能

### 1. YouTube送信は明示確認付きにする

実送信は `YOUTUBE_CONFIRM=1` のときだけ行う。

期待:

```text
YOUTUBE_CONFIRM=1 なし:
  dry-run
  実送信しない

YOUTUBE_CONFIRM=1 あり:
  YouTube RTMPS へ送信
```

### 2. 送信時間を制限できるようにする

PoCでは5分だけ送る。

推奨環境変数:

```text
STREAM_DURATION_SEC=300
```

`run-youtube.sh` は duration が指定されている場合、ffmpeg に `-t ${STREAM_DURATION_SEC}` を渡す。

未指定時の扱いは、以下のどちらかでよい。

```text
未指定なら無制限
または安全のため 300 秒
```

PoCでは安全側として 300 秒を推奨。

### 3. Stream Key マスク

ログに出すURLは必ずマスクする。

例:

```text
rtmps://a.rtmps.youtube.com/live2/****
```

ffmpeg コマンドを echo する場合もマスク済みにする。

### 4. YouTube送信用runbookを作る

以下を作成する。

```text
tasks/live/live_stream_phase6c_container_youtube_poc_runbook.md
```

内容:

```text
目的
前提
.env.stream 作成方法
YouTube Studioで限定公開ライブを作る手順
docker composeコマンド
開始手順
監視手順
停止手順
緊急停止手順
確認ポイント
失敗時の切り戻し
```

### 5. 緊急停止手順を明記する

runbook に必ず書く。

```bash
docker compose --profile streamer stop streamer
```

run 中の場合:

```bash
Ctrl+C
```

それでも止まらない場合:

```bash
docker ps --filter name=streamer
docker kill <streamer-container-name>
```

### 6. 負荷確認コマンドを明記する

runbook に以下を入れる。

```bash
docker stats
```

推奨観察対象:

```text
streamer CPU
streamer MEM
backend CPU/MEM
frontend CPU/MEM
martin CPU/MEM
VPS load average
```

## .env.stream の例

`.env.stream.example` は dummy 値のみ。

例:

```dotenv
YOUTUBE_RTMP_URL=rtmps://a.rtmps.youtube.com/live2
YOUTUBE_STREAM_KEY=replace-with-your-stream-key
YOUTUBE_CONFIRM=0
STREAM_URL=http://frontend/live/stream?chrome=off
STREAM_WIDTH=1280
STREAM_HEIGHT=720
STREAM_FPS=30
VIDEO_BITRATE=3500k
AUDIO_BITRATE=128k
STREAM_DURATION_SEC=300
```

実運用の `.env.stream` はユーザーが手動で作る。

## 推奨 docker compose 実行

dry-run:

```bash
docker compose --profile streamer run --rm streamer youtube
```

実送信:

```bash
docker compose --profile streamer run --rm \
  -e YOUTUBE_CONFIRM=1 \
  -e STREAM_DURATION_SEC=300 \
  streamer youtube
```

既存の entrypoint / command 設計に合わせて読み替えてよい。

## YouTube側の前提

ユーザーが YouTube Studio で以下を準備する。

```text
限定公開ライブ枠
RTMPS URL
Stream Key
```

Stream Keyは `.env.stream` にのみ記載する。

配信タイトル例:

```text
OnHighGround LIVE VPS streamer PoC
```

公開範囲:

```text
限定公開
```

いきなり公開にしない。

## 品質設定

Phase 6-C では以下に固定。

```text
解像度: 1280x720
FPS: 30
Video bitrate: 3000k〜3500k
Audio: AAC 128k 無音音声
Duration: 300秒
```

1080pは今回対象外。

## 成功条件

```text
streamer コンテナから YouTube 限定公開へ5分送信できる
YouTube Studioでプレビュー/ライブ映像が確認できる
5分後に送信が終了する、または手動停止できる
Stream Key がログに出ない
streamer停止後も既存サービスが動いている
/live/stream が 200 OK
/live が 200 OK
/ が 200 OK
CPU/MEMが危険域であれば notes として記録される
```

## FAIL条件

```text
Stream Key がログやファイルへ露出する
streamer 起動で既存サービスが落ちる
streamer 停止で既存サービスも止まる
YouTubeへ意図せず無制限配信される
YOUTUBE_CONFIRM=1 なしで実送信される
CPU/MEMが制限を超えてVPSが不安定になる
```

## 注意

このフェーズは「実配信の一歩手前」ではなく、実際に YouTube 限定公開へ送信する。

ただし目的は5分PoCであり、常用化ではない。

ヤバかったら止める。
