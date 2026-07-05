# /live/stream YouTube 限定公開 5分送信 PoC Runbook (Stream Phase 6-C)

## 目的

Phase 6-B で検証済みの streamer コンテナから、VPS上で実際に YouTube 限定公開ライブへ
**5分だけ** 送信できることを確認する。24時間配信・常用化はこのフェーズの対象外。
技術的な詳細 (build/オプション一覧/トラブルシュート) は [`streamer/README.md`](../../streamer/README.md) を参照。

## 前提

```text
Phase 6-B 完了済み: 60秒ローカル録画成功、/live/stream?chrome=off が録画に表示される、
                    実Stream Keyは未露出、.env.stream は git 管理外。
Phase 6-B notes:    720p/30fps 録画中に CPU 約110% / メモリ 約902MiB (1GiB制限中)。
                    → Phase 6-C も 720p/30fps 固定で進める (1080p化しない)。
```

## 絶対に守ること (再掲)

```text
restart: unless-stopped へ変更しない / systemd化・cron化しない (手動実行のみ)
1280x720 / 30fps / 3000〜3500kbps を維持する (1080p・60fps・高ビットレート禁止)
Stream Key を git / ログ / 検証レポート / スクリーンショットに絶対に出さない
streamer の起動・停止で frontend/backend/martin/osrm-walking を止めない
```

## 1. .env.stream の作成

```bash
cp .env.stream.example .env.stream
# .env.stream を編集し、YOUTUBE_RTMP_URL / YOUTUBE_STREAM_KEY を実際の値にする
git status   # .env.stream が Untracked のまま (=追跡されない) ことを確認
```

`STREAM_DURATION_SEC` は既定 `300` (5分)。変更しない限りこの値が使われる。

## 2. YouTube Studio で限定公開ライブ枠を作る

```text
1. YouTube Studio → 作成 → ライブ配信を開始
2. カスタム配信 (エンコーダ配信) を選択
3. タイトル例: "OnHighGround LIVE VPS streamer PoC"
4. 公開範囲: 限定公開 (絶対に「公開」にしない)
5. RTMPS URL と Stream Key をコピーし、.env.stream に転記する
6. 配信を「作成」した状態で待機 (まだ配信開始しない)
```

## 3. build (未buildの場合のみ)

```bash
docker compose --profile streamer build streamer
```

## 4. dry-run で内容を確認 (必ず先に実施)

```bash
docker compose --profile streamer run --rm streamer youtube
```

以下を確認する。

```text
[run-youtube] target: rtmps://.../****  ← Stream Keyがマスクされている
video: 1280x720@30fps bitrate=3500k audio=128k duration=300s
実際には配信が開始されていない (dry-run mode と表示される)
```

## 5. 実送信開始 (5分間)

dry-runの内容に問題がなければ、実際に送信する。

```bash
docker compose --profile streamer run --rm \
  -e YOUTUBE_CONFIRM=1 \
  -e STREAM_DURATION_SEC=300 \
  streamer youtube
```

## 6. 監視手順

配信中、別ターミナルで以下を並行して確認する。

```bash
# コンテナ別のCPU/MEM (streamer, backend, frontend, martin を観察)
docker stats

# VPSの負荷 (load average)
uptime

# 本体サービスが生きているか
curl -I http://127.0.0.1:8080/live/stream
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
```

YouTube Studio側でもプレビュー/ライブ映像が届いているか確認する。

観察対象:

```text
streamer CPU/MEM
backend CPU/MEM
frontend CPU/MEM
martin CPU/MEM
VPS load average
```

## 7. 停止手順 (正常終了)

`STREAM_DURATION_SEC` (既定300秒) 経過後、ffmpeg は自動的に終了し配信が止まる。
YouTube Studio側で配信終了操作を行う。

## 8. 緊急停止手順

途中で止めたい場合。

```text
1. フォアグラウンドで実行中なら Ctrl+C
2. docker compose --profile streamer stop streamer
3. それでも止まらない場合:
   docker ps --filter name=streamer
   docker kill onhighground-live-streamer
```

停止後、必ず以下を確認する。

```bash
docker compose ps   # frontend/backend/martin/osrm-walking が引き続き Up であること
```

## 9. 確認ポイント (このPoCで見るべきこと)

```text
streamer コンテナから YouTube 限定公開へ5分間送信できたか
YouTube Studioでプレビュー/ライブ映像が確認できたか
5分後に自動終了した、または手動停止できたか
Stream Key がログ/ターミナル履歴/スクリーンショットに出ていないか
streamer停止後も frontend/backend/martin/osrm-walking が Up のままか
/live/stream, /live, / がいずれも 200 OK か
CPU/MEMがPhase 6-Bの目安 (CPU約110%, MEM約900MiB/1GiB) を大きく超えていないか
```

## 10. 失敗時の切り戻し

```text
配信が不安定/VPSが重い場合 → 8章の緊急停止手順を実施し、Phase 6-Cを一旦中断する。
Stream Keyが漏れた可能性がある場合 → YouTube Studio側でStream Keyを再生成する。
本体サービスに影響が出た場合 → docker compose ps で状態を確認し、
  必要な本体サービスのみ再起動する (streamerコンテナの問題を本体に波及させない)。
```

## 既知のnotes

```text
Phase 6-Bの実測: 720p/30fps録画中に CPU約110% / メモリ約902MiB (1GiB制限中)。
  PoCとしては許容範囲だが、1080p化や常用化の前には追加確認が必要。
Chromiumの翻訳提案ポップアップは Phase 6-B で enterprise policy により解消済み。
STREAM_DURATION_SEC は既定300秒。0にすると無制限になる (通常は変更しないこと)。
24時間配信・自動起動・1080p化・監視通知は本フェーズの対象外 (後続フェーズで扱う)。
```
