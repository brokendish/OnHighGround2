# live stream Phase 6-C container YouTube PoC verification

検証日: 2026-07-05  
対象: `/live/stream` container YouTube 限定公開5分送信 PoC  
判定: **FAIL (YouTube 5min send not verified)**

## Result

**FAIL**

streamerの安全機構、dry-run、build、HTTP回帰、E2E回帰は通過しました。ただし、Phase 6-CのPASS条件である「YouTube限定公開へ5分送信できる」「YouTube側で映像が確認できる」は、実Stream KeyとYouTube限定公開枠の明示確認・実送信許可がないため未実施です。

このため、実装の安全性は概ね確認できていますが、Phase 6-Cの主目的は未達としてFAILにします。

## Summary

- `profiles: [streamer]` と `restart: "no"` は維持。
- 通常 `docker compose config --services` にstreamerは出ない。
- `--profile streamer` 指定時のみstreamerが出る。
- `.env.stream` はgit追跡外。
- 実Stream Keyらしき値は検索範囲内に出ていない。
- `run-youtube.sh` は `YOUTUBE_CONFIRM=1` なしではdry-runで終了する。
- dry-run出力は `rtmps://a.rtmps.youtube.com/live2/****` にマスクされる。
- dry-run出力に `-t 300` が含まれ、5分制限が確認できた。
- Docker build成功。
- dry-run後にstreamerは残らず、既存サービスは継続。
- `/live/stream`, `/live`, `/` は200 OK。
- scoped `/live/stream` E2Eは167件通過。

## Checked files

- `.gitignore`
- `docker-compose.yml`
- `.env.stream.example`
- `streamer/Dockerfile`
- `streamer/entrypoint.sh`
- `streamer/run-record.sh`
- `streamer/run-youtube.sh`
- `streamer/README.md`
- `tasks/live/live_stream_phase6c_container_youtube_poc_runbook.md`

## Environment

`docker compose ps`:

```text
evacuation-navi-backend        Up / healthy
evacuation-navi-frontend       Up
evacuation-navi-martin         Up / healthy
evacuation-navi-osrm-walking   Up
```

## Commands

Static/config:

```bash
git diff --stat
git diff -- .gitignore docker-compose.yml
git ls-files .env.stream
rg -n "YOUTUBE_STREAM_KEY|live2/|rtmps://" . \
  --glob '!.git/**' \
  --glob '!.env.stream' \
  --glob '!*.log' \
  --glob '!test-results/**'
docker compose config --services
docker compose --profile streamer config --services
docker compose --profile streamer config
bash -n streamer/entrypoint.sh
bash -n streamer/run-record.sh
bash -n streamer/run-youtube.sh
```

Build/dry-run:

```bash
docker compose --profile streamer build streamer
docker compose --profile streamer run --rm \
  -e YOUTUBE_RTMP_URL=rtmps://a.rtmps.youtube.com/live2 \
  -e YOUTUBE_STREAM_KEY=dummy-test-key \
  streamer youtube
docker ps --format '{{.Names}}'
docker compose ps
```

HTTP:

```bash
curl -I http://127.0.0.1:8080/live/stream
curl -I "http://127.0.0.1:8080/live/stream?chrome=off"
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
```

E2E:

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

Result: **167 passed**

## Secret handling

`git ls-files .env.stream` returned no tracked file.

Search results contained only variable names, dummy/masked values, and documentation references. No real Stream Key was found in the inspected files. `.env.stream.example` contains:

```text
YOUTUBE_STREAM_KEY=replace-with-your-stream-key
```

Dry-run was executed with an explicit dummy key override, so any local `.env.stream` value, if present, was not used in the output.

## Dry-run result

Dry-run command exited successfully and did not start streaming.

Relevant output:

```text
[run-youtube] target: rtmps://a.rtmps.youtube.com/live2/****
[run-youtube] video: 1280x720@30fps bitrate=3500k audio=128k duration=300s
[run-youtube] dry-run mode (YOUTUBE_CONFIRM is not "1"). No stream will be started.
-t 300
-f flv rtmps://a.rtmps.youtube.com/live2/****
```

確認できたこと:

- `YOUTUBE_CONFIRM=1` なしでは実送信しない。
- Stream Keyは表示されない。
- 送信予定URLは `****` でマスクされる。
- 既定の送信時間は300秒。
- x11grabに `-draw_mouse 0` が入っており、Phase 6-Bで見つけたカーソル映り込み対策が維持されている。

## YouTube 5min send result

**Not executed.**

理由:

- この検証では実Stream Keyを表示・確認しない方針。
- YouTube Studio側の限定公開ライブ枠作成と、実送信許可がこのセッション内で明示確認できていない。
- 実送信は外部サービスへの副作用を伴うため、dummy dry-runまでに留めた。

未確認のPASS条件:

- YouTube限定公開へ5分送信できること。
- YouTube側で `/live/stream?chrome=off` の映像が確認できること。
- 5分間の実送信中リソース。
- YouTube側の警告有無。

## Resource observations

実送信は未実施のため、Phase 6-Cの送信中リソースは未観測です。

参考として、Phase 6-Bのローカル録画では720p/30fpsで以下でした。

```text
streamer CPU: 約110%
streamer memory: 約902MiB / 1GiB
```

Phase 6-Cも同じ720p/30fps設定ですが、RTMPS送信時の実負荷は別途確認が必要です。

## Stop behavior

dry-run後:

```text
evacuation-navi-backend
evacuation-navi-osrm-walking
evacuation-navi-frontend
evacuation-navi-martin
```

streamerコンテナは残りませんでした。既存4サービスは継続しています。

## HTTP regression

All passed:

```text
http://127.0.0.1:8080/live/stream             200 OK
http://127.0.0.1:8080/live/stream?chrome=off  200 OK
http://127.0.0.1:8080/live                    200 OK
http://127.0.0.1:8080/                        200 OK
```

## E2E regression

Scoped live-stream E2E:

```text
167 passed
```

## Findings

1. **Phase 6-C PASS condition is not satisfied because actual YouTube send was not run**

   Safety/static/dry-run checks are good, but the core acceptance criterion is real 5-minute limited YouTube send. That remains unverified.

2. **Safety defaults look appropriate**

   `profiles: [streamer]`, `restart: "no"`, `STREAM_DURATION_SEC=300`, `YOUTUBE_CONFIRM=1` gate, masked URL logging, and `.env.stream` git-ignore are all present.

## Notes

- Docker build initially failed inside sandbox due buildx writing under `~/.docker`; approved Docker build succeeded.
- The build output still mentions backend in the compose build progress, but existing backend/frontend/martin/osrm containers remained running.
- No code changes were made during this Phase 6-C verification.

## Final judgement

**FAIL**

The implementation appears safe for a controlled YouTube PoC, and dry-run/build/regression checks passed. However, the required 5-minute YouTube limited/unlisted send was not executed or verified, so Phase 6-C cannot be marked PASS.
