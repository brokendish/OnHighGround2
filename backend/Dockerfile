FROM python:3.11.14-slim@sha256:c8271b1f627d0068857dce5b53e14a9558603b527e46f1f901722f935b786a39

# public専用image（Phase 2-B.1）。
# Docker CLI/SDK、データパイプラインツール（osmium-tool, tippecanoe）、
# admin/simulation/layer_types モジュールは一切含めない
# （operator専用は backend/Dockerfile.operator）。
# 作業ディレクトリを設定
WORKDIR /app

# システムパッケージのインストール
# libgeos-dev: shapely のソースビルドに必要 (--no-build-isolation 使用時)
# libproj-dev: pyproj のソースビルドに必要 (RSA 計算で使用)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    && rm -rf /var/lib/apt/lists/*

# Pythonパッケージの依存関係をコピー
COPY requirements.txt .

# ビルド補助ツールを先に更新（pkg_resources を必要とする依存のビルド対策）
RUN pip install --no-cache-dir --upgrade pip "setuptools<81" wheel
RUN pip install --no-cache-dir "Cython<3.1" "numpy>=1.26,<2"

# 依存関係をインストール
RUN pip install --no-cache-dir --no-build-isolation -r requirements.txt

# アプリケーションコードをコピー
# backend/Dockerfile.dockerignore（このDockerfile専用のBuildKit dockerignore）が
# admin/admin_config/admin_datasets/admin_upload/simulation/layer_types_api、
# pipeline_service.py、job_manager.py、app_operator.py 等を送信build contextから
# 除外する。backend/.dockerignore（共通baseline）はこのDockerfileには適用されない
# （Dockerfile.dockerignore が存在する場合はそちらのみが使われるため）。
COPY . .

# Phase 2-B.5: 固定数値UID/GID（第4.2節）。public processをrootで実行しない。
# UID/primary GID = 10001、supplemental GID 20001（lease coordination volume用）。
# 数値のみで指定し、名前解決に依存しない（docker-compose.yml側もuser: "10001:10001"
# の数値指定で固定するため、/etc/passwdへの名前登録は必須ではないが、
# 一部ツールのUID→名前解決前提コードのために明示ユーザーも作成する）。
RUN groupadd -g 10001 ohg2public \
    && groupadd -g 20001 ohg2leases \
    && useradd -u 10001 -g 10001 -G 20001 -M -s /usr/sbin/nologin ohg2public

# ポートを公開
EXPOSE 8000

USER 10001:10001

# main.py は app_public.py の互換シム（既存の起動経路 `uvicorn main:app` を
# 変更せずに維持するため）。実体は backend/app_public.py。
#
# Phase 2-B.5: umaskはcontainer起動時に既定（Debianの022等）が使われるため、
# 固定数値identity検証（第4.2節、runtime_atomic.verify_process_identity）が
# 期待する0007をexec前に明示設定する。
CMD ["sh", "-c", "umask 0007 && exec uvicorn main:app --host 0.0.0.0 --port 8000"]
