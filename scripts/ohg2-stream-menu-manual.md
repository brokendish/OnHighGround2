# OnHighGround2 /live/stream whiptail操作シェル 簡易マニュアル

## 1. ファイル配置

VPS上で以下のように配置します。

```bash
cd ~/Development/GitHub/OnHighGround2
mkdir -p scripts
vi scripts/ohg2-stream-menu.sh
chmod +x scripts/ohg2-stream-menu.sh
```

`vi` に貼り付ける内容は `ohg2-stream-menu.sh` を使ってください。

## 2. whiptail が無い場合

Debian / Ubuntu 系なら以下で入れます。

```bash
sudo apt update
sudo apt install -y whiptail
```

## 3. .env.stream の例

`~/Development/GitHub/OnHighGround2/.env.stream`

```env
# YouTube RTMP設定
YOUTUBE_RTMP_URL=rtmp://a.rtmp.youtube.com/live2
YOUTUBE_STREAM_KEY=自分のストリームキー

# Stream表示設定
STREAM_URL=http://frontend/live/stream?chrome=off
STREAM_WIDTH=1280
STREAM_HEIGHT=720
STREAM_FPS=30
VIDEO_BITRATE=3500k
AUDIO_BITRATE=128k

# デフォルト配信時間
# 300=5分, 1800=30分, 3600=1時間, 18000=5時間
STREAM_DURATION_SEC=300
```

`.env.stream` は絶対にgit管理しないでください。

確認:

```bash
git status --short .env.stream
git ls-files .env.stream
```

`git ls-files .env.stream` で何も出なければOKです。

## 4. 起動

```bash
cd ~/Development/GitHub/OnHighGround2
./scripts/ohg2-stream-menu.sh
```

メニューから以下を選びます。

1. `Validate .env.stream`
2. `Start YouTube Stream`
3. 配信時間を選択

配信時間は以下から選べます。

- `.env.stream` の `STREAM_DURATION_SEC` を使う
- 5分
- 15分
- 30分
- 1時間
- 3時間
- 5時間
- 分単位で手入力
- 時間単位で手入力
- 秒単位で手入力

選択した時間は、その起動時だけ `STREAM_DURATION_SEC` として上書きされます。`.env.stream` は書き換えません。

## 5. Macを閉じても大丈夫か

このシェルは streamer を以下のように detached 起動します。

```bash
docker compose --profile streamer run -d --rm \
  --name ohg2-streamer \
  -e YOUTUBE_CONFIRM=1 \
  streamer youtube
```

そのため、SSHが切れてもVPS側でコンテナは動き続けます。

## 6. 状態確認

メニューから以下を確認できます。

- `Status`
- `Show Logs tail`
- `Docker Stats`

別ターミナルで見る場合:

```bash
docker logs -f ohg2-streamer
watch -n 2 'docker stats --no-stream'
docker ps --filter "name=ohg2-streamer"
```

## 7. 停止

通常停止:

```bash
docker stop ohg2-streamer
```

メニューなら:

```text
Stop Stream
```

緊急停止:

```bash
docker rm -f ohg2-streamer
```

メニューなら:

```text
Emergency Stop rm -f
```

## 8. 終了後確認

`STREAM_DURATION_SEC` に達すると自動終了する想定です。

終了後に確認:

```bash
docker ps --filter "name=ohg2-streamer"
```

何も出なければ終了しています。

残っている場合:

```bash
docker stop ohg2-streamer
```

## 9. 注意点

- YouTube stream key は絶対にログやgitに出さない
- `.env.stream` はgit管理しない
- 既に `ohg2-streamer` が起動中の場合は二重起動しない
- YouTube Studioで「非常に良い」または「良好」を確認する
- 配信中は `docker stats --no-stream` で既存サービスへの影響を見る
- 音声ビットレート警告が出る場合は、後で無音AAC 128kbps追加を検討
