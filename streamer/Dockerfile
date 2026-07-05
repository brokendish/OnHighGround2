# streamer — Stream Phase 6-B: VPS Container Streamer PoC
#
# OnHighGround2 本体 (frontend/backend/martin/osrm-walking) から隔離された、
# /live/stream の配信・録画専用コンテナ。重ければこのコンテナだけ止めればよい。
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

# Stream Phase 5-B.1: VPS/コンテナのOS timezoneは既定でUTCであることが多いため、
# コンテナ自体のtimezoneもJSTに合わせておく (ログ・date コマンド等の可読性のため)。
# 画面表示自体は frontend/js/live-stream 側でタイムゾーン非依存 (UTC+9固定計算) に
# 修正済みなので、この設定が無くても画面はJSTになるが、二重の安全策として設定する。
ENV TZ=Asia/Tokyo

# chromium: /live/stream 表示用ヘッドレスブラウザ
# xvfb:     仮想ディスプレイ (DISPLAY=:99)
# ffmpeg:   x11grab による録画/RTMPS送信
# fonts-noto-cjk / fonts-noto-color-emoji: 日本語が豆腐にならないようにする
# tzdata:   TZ=Asia/Tokyo を実際に反映させるために必要 (Debian slim には既定で無い)
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        xvfb \
        ffmpeg \
        fonts-noto-cjk \
        fonts-noto-color-emoji \
        ca-certificates \
        tzdata \
        curl \
        jq \
        tini \
        bash \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /recordings /tmp/chromium-profile

# 配信画面に Chromium 自身の翻訳提案バブル ("Japanese / English" ポップアップ) が
# 映り込まないようにする。--disable-features=Translate 等のコマンドラインフラグだけでは
# 実機検証で消えなかったため、エンタープライズポリシーで確実に無効化する。
RUN mkdir -p /etc/chromium/policies/managed \
    && printf '{\n  "TranslateEnabled": false,\n  "DefaultNotificationsSetting": 2\n}\n' \
       > /etc/chromium/policies/managed/streamer-policy.json

COPY entrypoint.sh run-record.sh run-youtube.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/run-record.sh /usr/local/bin/run-youtube.sh

# 既定値 (docker-compose.yml / .env.stream で上書きされる想定)
# Stream Phase 6-C: 1280x720/30fps を維持し、YouTube送信は STREAM_DURATION_SEC (既定300秒=5分)
# で必ず時間を区切る (無制限配信を避ける安全側デフォルト)。
ENV STREAM_URL="http://frontend/live/stream?chrome=off" \
    STREAM_WIDTH=1280 \
    STREAM_HEIGHT=720 \
    STREAM_FPS=30 \
    VIDEO_BITRATE=3500k \
    AUDIO_BITRATE=128k \
    RECORD_SECONDS=60 \
    STREAM_DURATION_SEC=300 \
    OUTPUT_FILE=/recordings/stream-test.mp4 \
    CHROMIUM_WAIT_SECONDS=8 \
    DISPLAY=:99

WORKDIR /recordings

# tini を PID 1 にして、Xvfb/Chromium/ffmpeg の子プロセスがゾンビ化しないようにする。
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["record"]
