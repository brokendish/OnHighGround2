FROM python:3.11-slim

# 作業ディレクトリを設定
WORKDIR /app

# システムパッケージのインストール
# libgeos-dev: shapely のソースビルドに必要 (--no-build-isolation 使用時)
# libproj-dev: pyproj のソースビルドに必要 (RSA 計算で使用)
RUN apt-get update && apt-get install -y \
    build-essential \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    tippecanoe \
    && rm -rf /var/lib/apt/lists/*

# Pythonパッケージの依存関係をコピー
COPY requirements.txt .

# ビルド補助ツールを先に更新（pkg_resources を必要とする依存のビルド対策）
RUN pip install --no-cache-dir --upgrade pip "setuptools<81" wheel
RUN pip install --no-cache-dir "Cython<3.1" "numpy>=1.26,<2"

# 依存関係をインストール
RUN pip install --no-cache-dir --no-build-isolation -r requirements.txt

# アプリケーションコードをコピー
COPY . .

# ポートを公開
EXPOSE 8000

# アプリケーションを実行
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
