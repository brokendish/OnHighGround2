# streamer — `/live/stream` 配信・録画コンテナ (Stream Phase 6-B/6-C PoC)

## 目的

`/live/stream?chrome=off` を YouTube 等へ配信するための実験用コンテナ。
OnHighGround2 本体 (`frontend` / `backend` / `martin` / `osrm-walking`) から完全に隔離しており、
このコンテナが重い・不安定・失敗しても本体には影響しない。まずは **60秒のローカル録画** が
最優先のゴールで、YouTube 実送信は雛形 (dry-run 既定) までとする。

## 構成

```text
streamer/
  Dockerfile        chromium + xvfb + ffmpeg + Noto CJK フォント
  entrypoint.sh      mode (record/youtube/shell) を受け取り、Xvfb→Chromium起動→各処理へ
  run-record.sh      ffmpeg で60秒ローカル録画してMP4を生成
  run-youtube.sh     YouTube RTMPS送信 (既定はdry-run。YOUTUBE_CONFIRM=1で実送信)
  README.md          このファイル
.env.stream.example  環境変数の雛形 (実値は .env.stream にコピーして使う。git管理外)
```

`docker-compose.yml` に `streamer` サービスを追加してあるが、`profiles: [streamer]` を
指定しているため、通常の `docker compose up -d` では起動しない。明示的に
`--profile streamer` を付けたときだけ対象になる。

## 起動前確認

```bash
docker compose ps                              # frontend 等が正常に動いているか
curl -I http://127.0.0.1:8080/live/stream?chrome=off   # 200 OK か
cp .env.stream.example .env.stream             # 初回のみ。実際のStream Key等を書く
```

`.env.stream` は `.gitignore` に登録済みなので、通常のコミット操作でうっかり
コミットされることはない。念のため `git status` で確認してから作業すること。

## build

```bash
docker compose --profile streamer build streamer
```

## 60秒ローカル録画

まずはこれだけ試せば十分 (YouTubeへは何も送信しない)。

```bash
docker compose --profile streamer run --rm streamer record
```

- 録画時間・解像度等の既定値は `streamer/Dockerfile` の `ENV` に持たせてある
  (`RECORD_SECONDS` / `STREAM_WIDTH` / `STREAM_HEIGHT` / `STREAM_FPS` / `VIDEO_BITRATE` /
  `AUDIO_BITRATE`)。`docker-compose.yml` 側では重複させていないため、`.env.stream` に書けば
  そのまま反映される。
- 一時的に短く試したい場合は `-e` で上書きできる (`.env.stream` より優先される)。

```bash
docker compose --profile streamer run --rm -e RECORD_SECONDS=10 streamer record
```

## 録画ファイルの確認

出力は `./test-results/streamer/` にマウントされる (`test-results/` は `.gitignore` 済み)。

```bash
ls -lh test-results/streamer/
```

中身をざっと確認したい場合 (ffprobe/ffmpegはコンテナ内にある):

```bash
docker compose --profile streamer run --rm --entrypoint bash streamer -c \
  "ffprobe -v error -show_entries format=duration,size:stream=width,height,codec_name /recordings/stream-test.mp4"
```

静止画として1枚書き出して見た目を確認する場合:

```bash
docker compose --profile streamer run --rm --entrypoint bash streamer -c \
  "ffmpeg -y -i /recordings/stream-test.mp4 -vframes 1 -update 1 -ss 3 /recordings/preview.png"
```

## shell モード (デバッグ用)

```bash
docker compose --profile streamer run --rm -it streamer shell
```

コンテナ内で `chromium --version` / `ffmpeg -version` / `curl http://frontend/live/stream` 等を
手動で確認できる。

## YouTube送信モード (Stream Phase 6-C: 限定公開5分PoC。既定はdry-run)

`YOUTUBE_RTMP_URL` / `YOUTUBE_STREAM_KEY` を `.env.stream` に設定した上で:

```bash
docker compose --profile streamer run --rm streamer youtube
```

既定 (`YOUTUBE_CONFIRM` 未設定 or `0`) では **実際には配信を開始せず**、実行される予定の
ffmpegコマンド (Stream Keyはマスク済み) を表示するだけで終了する。

実際に配信を開始する場合のみ、明示的に `YOUTUBE_CONFIRM=1` を指定する。送信時間は
`STREAM_DURATION_SEC` (既定300秒=5分) で必ず区切られる (無制限配信を避ける安全側デフォルト)。

```bash
docker compose --profile streamer run --rm \
  -e YOUTUBE_CONFIRM=1 \
  -e STREAM_DURATION_SEC=300 \
  streamer youtube
```

詳しい手順 (YouTube Studioでの限定公開ライブ枠の作り方、監視・停止手順) は
[`tasks/live/live_stream_phase6c_container_youtube_poc_runbook.md`](../tasks/live/live_stream_phase6c_container_youtube_poc_runbook.md) を参照。

**注意**:
- Stream Key は決してログに平文で出さない設計になっている (`****` にマスクされる)。
  それでも配信前には、限定公開/非公開などYouTube側の公開範囲設定を必ず確認すること。
- 24時間365日の自動配信・自動再起動は対象外。`restart: "no"` のため、コンテナが落ちても
  勝手に再起動しない。
- `STREAM_DURATION_SEC=0` にすると無制限配信になる。通常は変更しないこと。

## 緊急停止

配信・録画中に重い/おかしいと感じたら、このコンテナだけ止めれば本体には影響しない。

```bash
# compose 経由で起動している場合
docker compose stop streamer

# run --rm で起動している場合 (フォアグラウンドで動いているターミナルで Ctrl+C でも止まる)
docker ps
docker stop onhighground-live-streamer
# 反応がなければ
docker kill onhighground-live-streamer
```

## リソース確認

```bash
docker stats onhighground-live-streamer
```

`docker-compose.yml` 側で `shm_size: 512m` / `cpus: 1.0` / `mem_limit: 1024m` を設定済み。
VPS本体の保護を優先するため、まずはこの制限内で様子を見ること。

## トラブルシュート

| 症状 | 確認/対処 |
|---|---|
| `frontend not reachable` の警告が出る | `docker compose ps` で `frontend` が Up か確認。ネットワーク名 (`evacuation-navi-network`) が一致しているか確認 |
| chromium が起動直後に落ちる | `entrypoint.sh` が `/tmp/chromium.log` の内容を出力するので確認する。`shm_size` 不足の場合は `--disable-dev-shm-usage` が効いているか確認 |
| 録画が真っ黒/真っ白 | `CHROMIUM_WAIT_SECONDS` を増やしてページの読み込みを待つ (既定8秒) |
| 日本語が文字化け/豆腐になる | `fonts-noto-cjk` が正しく入っているか (Dockerfile 再build で解消するはず) |
| ffmpeg が `Thread message queue blocking` を出す | 実害なければ無視してよい (x11grabのバッファ警告)。気になる場合は `-thread_queue_size` オプションの追加を検討 |
| 画面右上に翻訳ポップアップが映り込む | `/etc/chromium/policies/managed/streamer-policy.json` (`TranslateEnabled: false`) を同梱済み。再buildで解消しない場合は `--user-data-dir` を作り直す (プロファイルの残留設定を疑う) |
| YouTube送信でStream Keyが心配 | 本ドキュメント記載のとおり dry-run で内容を確認してから `YOUTUBE_CONFIRM=1` を使う。ログに平文キーが出ていないか必ず確認する |

## 実装対象外 (Phase 6-C時点)

- 24時間365日の常時配信 / systemd・cronによる自動起動
- YouTube API による配信枠自動作成・Stream Keyのローテーション
- OBS実機制御
- 1080p本番配信 (まずは1280x720/30fps/3.5Mbpsで負荷を見る)
- 監視・通知

これらは後続フェーズで検討する。
