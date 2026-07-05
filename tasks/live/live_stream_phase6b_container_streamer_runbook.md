# /live/stream Container Streamer Runbook (Stream Phase 6-B)

VPSから `/live/stream` をYouTube等へ配信するための streamer コンテナの運用手順。
詳しい技術的な内容 (build/オプション/トラブルシュート) は [`streamer/README.md`](../../streamer/README.md) を参照。
本ドキュメントは「実際に触る前に何を確認し、どう安全に止めるか」に絞った運用手順。

## 1. 前提

```text
streamer は OnHighGround2 本体 (frontend/backend/martin/osrm-walking) から隔離されている。
`--profile streamer` を明示しない限り `docker compose up -d` では起動しない。
restart: "no" のため、落ちても勝手に再起動しない。
```

## 2. 起動前確認

```bash
docker compose ps
curl -I http://127.0.0.1:8080/live/stream?chrome=off
cp .env.stream.example .env.stream   # 初回のみ。Stream Key等の実値を書く
git status                            # .env.stream が追跡対象になっていないか確認
```

## 3. build

```bash
docker compose --profile streamer build streamer
```

## 4. まず60秒ローカル録画 (YouTubeへは何も送らない)

```bash
docker compose --profile streamer run --rm streamer record
ls -lh test-results/streamer/
```

録画ファイル (`test-results/streamer/stream-test.mp4`) を再生し、以下を目視確認する。

```text
画面が白画面/真っ黒になっていない
日本語が文字化け(豆腐)していない
地図・小画面・ticker が表示されている
Chromiumの翻訳ポップアップ等、余計なブラウザUIが映り込んでいない
```

## 5. リソース確認

```bash
docker stats onhighground-live-streamer
```

CPU/メモリが `cpus: 1.0` / `mem_limit: 1024m` の範囲に収まっているか確認する。
VPS本体 (frontend/backend等) の応答が重くなっていないかも合わせて確認する。

## 6. 異常時の停止手順

```text
1. docker compose stop streamer
2. (反応がなければ) docker stop onhighground-live-streamer
3. (それでも反応がなければ) docker kill onhighground-live-streamer
4. docker compose ps で frontend/backend/martin/osrm-walking が Up のままであることを確認する
   (streamer を止めても本体には影響しないはずだが、必ず確認する)
```

## 7. YouTube送信 (雛形・dry-run既定)

```bash
docker compose --profile streamer run --rm streamer youtube
```

既定では実際には配信せず、実行予定のffmpegコマンド (Stream Keyはマスク済み) を表示するだけ。
実際に配信する場合のみ、YouTube側の公開範囲 (限定公開/非公開/テスト配信相当) を確認した上で:

```bash
docker compose --profile streamer run --rm -e YOUTUBE_CONFIRM=1 streamer youtube
```

```text
配信中に問題があれば、上記6の停止手順をすぐに実行する。
Stream Key をログ・チャット・スクリーンショットに映さないよう注意する。
```

## 8. 完了条件 (Claude実装側)

```text
streamer コンテナ構成が追加されている
.env.stream.example がある / .env.stream は git 管理されない
record mode / youtube mode (dry-run) が動作確認済み
リソース制限 (shm_size/cpus/mem_limit) が入っている
restart: "no" + profiles: [streamer] で勝手に起動しない
README / runbook がある
既存 OnHighGround2 本体への変更が streamer サービス追加のみ (最小限)
```

## 9. 既知のnotes

```text
- 実機検証で Chromium の翻訳提案ポップアップが画面に映り込む問題を確認し、
  enterprise policy (TranslateEnabled: false) で解消済み。
- 24時間365日の自動配信・自動起動・YouTube API連携・1080p本番配信・監視通知は
  本フェーズの対象外 (後続フェーズで扱う)。
- YouTube実配信 (RTMPS実送信) は dry-run 確認までを Claude 実装側の完了条件とし、
  実際の配信確認は運用者判断で行うこと。
```
