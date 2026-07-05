# live stream Phase 6-B container streamer verification

検証日: 2026-07-05  
対象: `/live/stream` VPS Container Streamer PoC MVP  
判定: **PASS with notes**

## Result

**PASS with notes**

streamer service は `profiles: [streamer]` と `restart: "no"` で追加され、通常の `docker compose up` 対象には入りません。Docker build、60秒ローカル録画、MP4の映像/音声トラック確認、既存 `/live/stream` 回帰、streamer停止確認はいずれも通過しました。

notes は、録画中のstreamerがCPU約100%前後、メモリ約900MiB/1GiBまで上がる点です。PoCのリソース制限内ではありますが、VPS常用前には軽量化または720p前提の運用確認が必要です。

## Summary

- 既存 frontend/backend/martin/osrm-walking の設定変更は、`docker-compose.yml` へのstreamer service追加のみ。
- `.env.stream` は `.gitignore` に追加されており、実Stream Keyは追跡対象外。
- `.env.stream.example` はダミーキーのみ。
- `docker compose config --services` ではstreamerは出ず、`--profile streamer` 指定時のみ出る。
- `docker compose --profile streamer build streamer` は成功。
- `docker compose --profile streamer run --rm streamer record` で60秒MP4生成成功。
- 録画は `/live/stream?chrome=off` を表示し、日本語・地図・パネル・tickerが確認できた。
- 検証中に録画へマウスカーソルが映り込むのを見つけたため、streamer専用スクリプトに `ffmpeg -draw_mouse 0` を追加した。
- YouTube dry-runはdummy keyを `****` にマスクし、実送信しないことを確認。
- 既存 `/live/stream` scoped E2E は167件通過。

## Checked files

- `.gitignore`
- `docker-compose.yml`
- `.env.stream.example`
- `streamer/Dockerfile`
- `streamer/entrypoint.sh`
- `streamer/run-record.sh`
- `streamer/run-youtube.sh`
- `streamer/README.md`
- `tasks/live/live_stream_phase6b_container_streamer_runbook.md`

## Environment

Docker services after build/record/stop:

```text
evacuation-navi-backend        Up / healthy
evacuation-navi-frontend       Up
evacuation-navi-martin         Up / healthy
evacuation-navi-osrm-walking   Up
```

HTTP checks:

```text
http://127.0.0.1:8080/live/stream             200 OK
http://127.0.0.1:8080/live/stream?chrome=off  200 OK
http://127.0.0.1:8080/live                    200 OK
http://127.0.0.1:8080/                        200 OK
```

## Commands

Static/config checks:

```bash
docker compose config --services
docker compose --profile streamer config --services
docker compose --profile streamer config
bash -n streamer/entrypoint.sh
bash -n streamer/run-record.sh
bash -n streamer/run-youtube.sh
rg -n "YOUTUBE_STREAM_KEY|live2/" . --glob '!.git/**' --glob '!.env.stream' --glob '!*.log'
```

Build/record/probe:

```bash
docker compose --profile streamer build streamer
docker compose --profile streamer run --rm streamer record
docker stats --no-stream
docker compose --profile streamer run --rm --entrypoint bash streamer -c \
  'ffprobe -v error -show_entries format=duration,size:stream=index,codec_type,codec_name,width,height,sample_rate,channels -of json /recordings/stream-test.mp4'
docker compose --profile streamer run --rm --entrypoint bash streamer -c \
  'ffmpeg -y -ss 30 -i /recordings/stream-test.mp4 -vframes 1 -update 1 /recordings/stream-test-preview-30s.png'
docker compose --profile streamer stop streamer
```

Regression:

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

## Docker build

`docker compose --profile streamer build streamer` succeeded.

Dockerfile includes the expected PoC runtime pieces:

- `chromium`
- `xvfb`
- `ffmpeg`
- `fonts-noto-cjk`
- `fonts-noto-color-emoji`
- `ca-certificates`
- `curl`
- `jq`
- `tini`

`tini` is configured as PID 1.

## Local recording result

Generated:

```text
test-results/streamer/stream-test.mp4
test-results/streamer/stream-test-preview.png
test-results/streamer/stream-test-preview-30s.png
```

Final `ffprobe`:

```json
{
  "streams": [
    {
      "index": 0,
      "codec_name": "h264",
      "codec_type": "video",
      "width": 1280,
      "height": 720
    },
    {
      "index": 1,
      "codec_name": "aac",
      "codec_type": "audio",
      "sample_rate": "44100",
      "channels": 2
    }
  ],
  "format": {
    "duration": "60.000000",
    "size": "9776378"
  }
}
```

Visual check from `stream-test-preview-30s.png`:

- `/live/stream?chrome=off` is visible.
- Japanese text is readable; no tofu text observed.
- Map, side panels, mini maps, and ticker are visible.
- No blank/black-only recording.
- No Chromium translation popup observed.
- Mouse cursor is no longer visible after adding `-draw_mouse 0`.

## Resource observations

During final 60s recording:

```text
streamer CPU: 109.64%
streamer memory: 901.5MiB / 1GiB (88.04%)
backend CPU: 0.16%
frontend CPU: 0.00%
martin CPU: 0.16%
osrm CPU: 0.00%
```

The streamer is close to its memory limit and consumes about one CPU under 720p/30fps recording. Existing services stayed responsive and low-CPU. This is acceptable for PoC but should remain a **PASS with notes** item.

## Stop behavior

- `docker compose --profile streamer run --rm streamer record` exited cleanly after 60 seconds.
- `docker ps --format '{{.Names}}'` after record showed only existing services:

```text
evacuation-navi-backend
evacuation-navi-osrm-walking
evacuation-navi-frontend
evacuation-navi-martin
```

- `docker compose --profile streamer stop streamer` did not stop backend/frontend/martin/osrm.
- `/live/stream?chrome=off` remained `200 OK` after stop.

## Secret handling

- `.gitignore` includes `.env.stream`.
- `git ls-files .env.stream` returned no tracked file.
- `.env.stream.example` uses `YOUTUBE_STREAM_KEY=replace-with-your-stream-key`.
- Search found no real YouTube Stream Key in tracked/working files inspected.
- YouTube dummy dry-run output masked the key as `****` and did not start streaming.

Dry-run output included:

```text
[run-youtube] target: rtmps://a.rtmps.youtube.com/live2/****
[run-youtube] dry-run mode (YOUTUBE_CONFIRM is not "1"). No stream will be started.
-f flv rtmps://a.rtmps.youtube.com/live2/****
```

Unset-credential runtime test was not executed with Docker because the safety reviewer rejected running a mode that could consume a local `.env.stream` if present. Static script review confirms `run-youtube.sh` requires `YOUTUBE_RTMP_URL` and `YOUTUBE_STREAM_KEY` before constructing the destination, and actual streaming additionally requires `YOUTUBE_CONFIRM=1`.

## Existing app regression

Scoped `/live/stream` E2E:

```text
167 passed
```

HTTP checks after streamer build/record/stop stayed green:

```text
/live/stream             200
/live/stream?chrome=off  200
/live                    200
/                        200
```

## Findings

1. **Fixed during verification: mouse cursor was recorded**

   Initial preview frame showed a mouse cursor in the center of the recording. I added `-draw_mouse 0` to both `streamer/run-record.sh` and `streamer/run-youtube.sh`, rebuilt the image, reran the 60s recording, and confirmed the final preview no longer shows the cursor.

2. **Resource usage is high but bounded**

   The streamer used roughly one CPU and about 900MiB of its 1GiB memory limit while recording 1280x720/30fps. Existing services remained healthy. This is acceptable for PoC, but 1080p should not be assumed safe yet.

## Notes

- YouTube real RTMPS send was not performed.
- 1080p was not tested.
- The Docker build command initially failed inside the sandbox because buildx needed to write under `~/.docker`; rerunning with approved Docker permissions succeeded.
- `docker compose --profile streamer build streamer` output mentioned backend as a build target in compose progress, but the produced image was `onhighground2-streamer:latest` and the backend container remained unchanged/running.

## Final judgement

**PASS with notes**

The streamer PoC is safe enough to try locally: it does not start by default, does not auto-restart, does not expose a real Stream Key, can build, can record a valid 60s local MP4, can stop without affecting existing services, and existing `/live/stream` regression tests pass. The remaining caution is resource headroom: keep initial VPS use at 720p and monitor CPU/memory closely.
