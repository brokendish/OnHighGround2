# OnHighGround2 VPS デプロイ手順書

最終更新: 2026-03-21

---

## 目次

1. [構成概要](#1-構成概要)
2. [前提条件](#2-前提条件)
3. [初回セットアップ](#3-初回セットアップ)
4. [データ転送（ローカル → VPS）](#4-データ転送ローカル--vps)
5. [本番設定の変更](#5-本番設定の変更)
6. [Docker 起動](#6-docker-起動)
7. [Caddy HTTPS 設定](#7-caddy-https-設定)
8. [動作確認](#8-動作確認)
9. [コード更新時の手順](#9-コード更新時の手順)
10. [データ更新時の手順](#10-データ更新時の手順)
11. [トラブルシュート](#11-トラブルシュート)

---

## 1. 構成概要

### サービス一覧

| コンテナ | 役割 | 内部ポート |
| --- | --- | --- |
| `evacuation-navi-frontend` | nginx（静的配信 + API プロキシ） | 8080 |
| `evacuation-navi-backend` | FastAPI（ハザード判定・避難ルート） | 8000 |
| `evacuation-navi-martin` | Martin（MBTiles ベクタータイル配信） | 3000（内部のみ） |
| `evacuation-navi-osrm-driving` | OSRM 車ルーティング | 5000（内部のみ、host publishなし） |
| `evacuation-navi-osrm-walking` | OSRM 徒歩ルーティング | 5001（内部のみ、host publishなし。frontendの`/osrm/walking/`経由で到達） |

### リクエストの流れ

```
ブラウザ
  ↓ HTTPS
Caddy（HTTPS 終端・ドメイン振り分け）
  ↓ HTTP
nginx コンテナ（:8080）
  ├── /api/       → backend:8000
  ├── /tiles/     → martin:3000
  ├── /osrm/driving/ → osrm-driving:5000
  ├── /osrm/walking/ → osrm-walking:5001
  ├── /layers/    → frontend/layers/ （静的 GeoJSON）
  └── /admin/     → frontend/admin/ （管理画面）
```

### 公開ドメイン（現在）

| URL | 説明 |
| --- | --- |
| `https://ohg.brokendish.org` | Web アプリ UI |
| `https://api.brokendish.org` | FastAPI（直接アクセス用、Caddy 経由） |

---

## 2. 前提条件

### VPS 要件

| 項目 | 最低 | 推奨 |
| --- | --- | --- |
| CPU | 2コア | 4コア |
| RAM | 4GB | 8GB以上（洪水ハザード全件ロード時に必要） |
| ディスク | 30GB | 60GB以上 |
| OS | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |

### インストール済みツール

```bash
# Docker + Docker Compose
docker --version       # 24.x 以上
docker compose version # 2.x 以上

# Caddy（HTTPS 終端）
caddy version

# rsync（データ転送用）
rsync --version
```

---

## 3. 初回セットアップ

### 3-1. リポジトリのクローン

```bash
cd ~/Development/GitHub
git clone https://github.com/YOUR_USER/OnHighGround2.git
cd OnHighGround2
```

### 3-2. data_runtime ディレクトリの作成

`data_runtime/` はgitignore 対象のため、ディレクトリ構造だけ作成する。

```bash
mkdir -p data_runtime/backend/elevation
mkdir -p data_runtime/backend/hazard/flood
mkdir -p data_runtime/backend/hazard/storm_surge
mkdir -p data_runtime/backend/hazard/tsunami
mkdir -p data_runtime/backend/hazard/inland_flood
mkdir -p data_runtime/backend/hazard/landslide
mkdir -p data_runtime/backend/shelters
mkdir -p data_runtime/frontend/layers
mkdir -p data_runtime/frontend/tiles/tokyo/flood
mkdir -p data_runtime/frontend/tiles/tokyo/storm_surge
mkdir -p data_runtime/frontend/tiles/tokyo/tsunami
mkdir -p data_runtime/manifests
```

### 3-3. OSRM インデックス用ディレクトリ

```bash
mkdir -p data_lake/raw/tokyo/osm
mkdir -p data_lake/validated/tokyo/osm/driving
mkdir -p data_lake/validated/tokyo/osm/walking
```

---

## 4. データ転送（ローカル → VPS）

### 転送が必要なファイル一覧

以下はすべて gitignore 対象のため、rsync で手動転送する。

| カテゴリ | ローカルパス | サイズ | 備考 |
| --- | --- | --- | --- |
| DEM（標高） | `data_runtime/backend/elevation/elevation.tif` | ~426MB | 必須 |
| 洪水判定 | `data_runtime/backend/hazard/flood/tokyo_flood_check.geojsonl` | ~476MB | 必須 |
| 高潮 | `data_runtime/backend/hazard/storm_surge/tokyo_storm_surge.geojson` | ~48MB | 必須 |
| 津波（東京） | `data_runtime/backend/hazard/tsunami/tsunami_tokyo.geojson` | ~16MB | 必須 |
| 津波（神奈川） | `data_runtime/backend/hazard/tsunami/tsunami_kanagawa.geojson` | ~100MB | 任意 |
| 津波（千葉） | `data_runtime/backend/hazard/tsunami/tsunami_chiba.geojson` | ~138MB | 任意 |
| 内水氾濫 | `data_runtime/backend/hazard/inland_flood/tokyo_inland_flood_A51.geojson` | ~184KB | 必須 |
| 土砂災害 | `data_runtime/backend/hazard/landslide/tokyo_landslide_A33.geojson` | ~29MB | 必須 |
| 避難所 | admin registry経由（`active_mappings.json`→atomic publish current）で配備。flat直下の`tokyo_shelter.geojson`は正規系譜外のlegacy artifactで現在は読まれない | — | — |
| 洪水タイル | `data_runtime/frontend/tiles/tokyo/flood/tokyo_flood_max.mbtiles` | ~167MB | 必須（Martin 配信） |
| 高潮タイル | `data_runtime/frontend/tiles/tokyo/storm_surge/tokyo_storm_surge.mbtiles` | ~19MB | 必須（Martin 配信） |
| 津波タイル | `data_runtime/frontend/tiles/tokyo/tsunami/*.mbtiles` | ~67MB合計 | 必須（Martin 配信） |
| GeoJSON layers | `data_runtime/frontend/layers/*.geojson` | ~200MB合計 | 必須（タイル不在時の fallback） |
| OSM データ | `data_lake/raw/tokyo/osm/kanto-260214.osm.pbf` | ~436MB | OSRM 未構築の場合のみ |

> **タイルについて**: MBTiles（`data_runtime/frontend/tiles/`）は Martin コンテナが配信する。タイルがなくても地図は表示されるが、各ハザードレイヤーが GeoJSON 直接取得（API fallback）に切り替わり、ズーム・パン時の描画が重くなる。
>
> **OSRM について**: VPS 上で `.osrm` インデックスが未生成の場合、初回 `docker compose up` 時に自動生成される（数十分かかる）。すでに `data_lake/validated/tokyo/osm/` にインデックスがあればスキップされる。

### rsync コマンド

> **注意: このセクションのコマンドはすべてローカルマシンで実行する。**
> `deploy_to_runtime.sh` は `data_lake/normalized/` がないと何もデプロイできないため、VPS 上では実行しないこと。

タイルを含む `data_runtime/` 全体を一括転送する（合計 **約1.5GB**）。

```bash
VPS=user@your-vps-ip
REMOTE=~/Development/GitHub/OnHighGround2

# ── ローカルで実行 ──────────────────────────────────────────
# 転送前に data_runtime/ を最新状態にする（初回は必須）
bash scripts/publish/deploy_to_runtime.sh --region tokyo

# data_runtime を一括転送（タイル・ハザードデータ・避難所・DEM すべて含む）
# ※ MBTiles（data_runtime/frontend/tiles/）もここで転送される。Martin に必要。
rsync -avz --progress \
  data_runtime/ \
  ${VPS}:${REMOTE}/data_runtime/

# ── パターン A: OSRM インデックス構築済みの場合（推奨・VPS での再ビルド不要）
rsync -avz --progress \
  data_lake/validated/tokyo/osm/driving/ \
  ${VPS}:${REMOTE}/data_lake/validated/tokyo/osm/driving/
rsync -avz --progress \
  data_lake/validated/tokyo/osm/walking/ \
  ${VPS}:${REMOTE}/data_lake/validated/tokyo/osm/walking/

# ── パターン B: OSRM インデックス未構築の場合（VPS 起動時に自動ビルド・数十分かかる）
rsync -avz --progress \
  data_lake/raw/tokyo/osm/kanto-260214.osm.pbf \
  ${VPS}:${REMOTE}/data_lake/raw/tokyo/osm/

# ── tile を転送
rsync -avz --progress \
  data_lake/tiles/ \
  ${VPS}:${REMOTE}/data_lake/tiles/

# ── 避難所 を転送
rsync -avz --progress \
  data_lake/validated/tokyo/shelter/ \
  ${VPS}:${REMOTE}/data_lake/validated/tokyo/shelter/
```

> **転送後の権限確認**: `rsync -a` はローカルの gid・mode を VPS へ持ち込みます。`data_runtime/frontend/tiles/`
> の `.mbtiles` は、backend-public（uid 10001、supplemental gid 20001）が読める `10002:20001 / 0640`
> でないと、Martin からは配信できても `GET /api/hazards/<type>/<region>/meta` の `tileset_source_layer` が
> `null` になります。転送後に READ ONLY で確認してください:
> `docker compose --profile operator run --rm --no-deps --entrypoint bash backend-operator -c "/scripts/publish/sync_frontend_tiles_mirror.sh --check /data_runtime/frontend/tiles"`
> （通常運用の `deploy_to_runtime_atomic.sh` publish は、この契約を自動で保証します。）

転送後の内訳（参考）：

```text
data_runtime/backend/         ~1.1GB（DEM 426MB + 洪水判定 476MB + その他）
data_runtime/frontend/tiles/  ~253MB（洪水 167MB + 高潮 19MB + 津波 67MB）
data_runtime/frontend/layers/ ~200MB（GeoJSON fallback 用）
```

---

## 5. 本番設定の変更

### app.properties の変更点

**本番では `api.reload=false` にする**（uvicorn のホットリロードは開発専用）。

VPS 上で編集：

```bash
vi backend/app.properties
```

変更箇所：

```properties
# 開発用（ローカルでは true のまま）
api.reload=false   # ← false に変更

# 津波広域モードを使う場合
hazard.tsunami.targets=tokyo,kanagawa,chiba
```

> その他の設定（ハザードパス等）は `data_runtime/` を参照しているため変更不要。

---

## 6. Docker 起動

```bash
cd ~/Development/GitHub/OnHighGround2

# バックグラウンド起動
docker compose up -d

# ログ確認
docker compose logs -f backend
docker compose logs -f martin
```

### 起動順序と確認

```bash
# コンテナ状態確認
docker compose ps

# backend ヘルスチェック（ハザードロード状況を確認）
curl http://localhost:8000/health | python3 -m json.tool
```

正常時のレスポンス例：

```json
{
  "status": "ok",
  "hazard_loaded": ["flood", "tsunami", "storm_surge", "inland_flood", "landslide"],
  "hazard_polygon_counts": {
    "flood": 666000,
    "tsunami": 33124,
    "storm_surge": 12000,
    "inland_flood": 194,
    "landslide": 29943
  },
  "shelters_loaded": 2500
}
```

`hazard_loaded` に `inland_flood` と `landslide` が含まれていることを確認する。

---

## 7. Caddy HTTPS 設定

Caddyfile（`/etc/caddy/Caddyfile`）の設定例：

```caddyfile
ohg.brokendish.org {
    reverse_proxy localhost:8080
}

api.brokendish.org {
    reverse_proxy localhost:8000
}
```

```bash
# Caddy 再起動
sudo systemctl reload caddy

# 証明書取得確認
sudo journalctl -u caddy -n 30
```

---

## 8. 動作確認

### API

```bash
# ヘルスチェック
curl https://api.brokendish.org/health

# 内水氾濫データ（件数確認）
curl https://ohg.brokendish.org/api/hazards/inland_flood/tokyo | python3 -c "import sys,json; d=json.load(sys.stdin); print('features:', len(d['features']))"

# 土砂災害データ（件数確認）
curl https://ohg.brokendish.org/api/hazards/landslide/tokyo | python3 -c "import sys,json; d=json.load(sys.stdin); print('features:', len(d['features']))"
```

### ベクタータイル

Round 12D-B1以降、Martinはhost publishされていない（3000は内部のみ、
docker-compose.dev.ymlを明示指定したローカル開発時のみ127.0.0.1限定で
opt-in可能）。VPS上でのカタログ確認はfrontend/nginx経由、または
コンテナ内部からの確認を使う。

```bash
# nginx 経由（VPS上での確認方法。frontendが/tiles/をmartinへproxyする）
curl https://ohg.brokendish.org/tiles/catalog | python3 -m json.tool

# コンテナ内部からの確認（host publishなしでもmartin自体の疎通を直接確認する場合）
docker compose exec martin wget -qO- http://localhost:3000/catalog | python3 -m json.tool
```

### 管理 UI

```
https://ohg.brokendish.org/admin/hazards
```

- 全レイヤーが `active` になっていることを確認
- `inland_flood_tokyo` と `landslide_tokyo` のステータスが `api_only / active` であることを確認

### 地図表示

```
https://ohg.brokendish.org
```

チェックボックスを ON にして各レイヤーが表示されることを確認：

| レイヤー | 表示エリア | 色 |
| --- | --- | --- |
| 津波浸水想定 | 東京湾岸エリア | 青系 |
| 洪水浸水想定 | 多摩川・隅田川流域 | 黄〜赤系 |
| 高潮浸水想定 | 湾岸低地 | 水色〜紫系 |
| 内水氾濫 | 福生市周辺（西東京） | 水色〜赤系 |
| 土砂災害警戒区域 | 多摩丘陵・奥多摩方面 | オレンジ〜濃赤 |

---

## 9. コード更新時の手順

```bash
cd ~/Development/GitHub/OnHighGround2

# コードを pull
git pull

# backend を再ビルド・再起動
docker compose build backend
docker compose up -d backend

# frontend（nginx）は静的ファイルのため再起動のみ
docker compose restart frontend
```

> `app.properties` を変更した場合は backend の再起動が必要。

---

## 10. データ更新時の手順

### ハザードデータを追加・更新した場合

ローカルで実施：

```bash
# 1. 正規化
python scripts/normalize/normalize_inland_flood.py  # 内水氾濫
python scripts/normalize/normalize_landslide.py     # 土砂災害

# 2. data_runtime へデプロイ
bash scripts/publish/deploy_to_runtime.sh

# 3. VPS に転送
rsync -avz --progress data_runtime/ user@your-vps-ip:~/Development/GitHub/OnHighGround2/data_runtime/

# 4. VPS 上で backend 再起動（ハザードデータはメモリロードのため）
ssh user@your-vps-ip "cd ~/Development/GitHub/OnHighGround2 && docker compose restart backend"
```

> **注意**: `inland_flood` と `landslide` は API エンドポイントがリクエスト毎にファイルを読むため、backend 再起動は**ポリゴン判定（hazard_service への反映）**に必要。フロントエンド表示だけなら再起動不要。

### OSRM データを更新した場合

```bash
# インデックスを削除（VPS 上）
rm -rf data_lake/validated/tokyo/osm/driving/*
rm -rf data_lake/validated/tokyo/osm/walking/*

# OSM データを転送（ローカルから）
rsync -avz data_lake/raw/tokyo/osm/kanto-260214.osm.pbf \
  user@your-vps-ip:~/Development/GitHub/OnHighGround2/data_lake/raw/tokyo/osm/

# コンテナ再起動（インデックス自動生成、数十分かかる）
docker compose up -d osrm-driving osrm-walking
docker compose logs -f osrm-walking  # 完了を確認
```

---

## 11. トラブルシュート

### backend が起動しない / hazard_loaded が空

```bash
docker compose logs backend | tail -50
```

よくある原因：

| 症状 | 確認箇所 |
| --- | --- |
| `elevation.tif not found` | `data_runtime/backend/elevation/elevation.tif` の存在確認 |
| `inland_flood` がロードされない | `data_runtime/backend/hazard/inland_flood/` にファイルがあるか確認 |
| `landslide` がロードされない | `data_runtime/backend/hazard/landslide/` にファイルがあるか確認 |
| OOM Killer に殺される | RAM 不足。`hazard.flood.enabled=false` にしてメモリを削減 |

### Martin が `Unrecognizable connection strings` エラーで起動しない

```text
ERROR martin: Unrecognizable connection strings: ["/tiles/tokyo/flood", ...]
```

`.mbtiles` ファイルが VPS に届いていない場合に発生する。

**原因**: `deploy_to_runtime.sh` を VPS 上で実行しても `data_lake/` がないため何もデプロイされない。タイルは**ローカルから rsync で転送**する必要がある。

**対処（ローカルで実行）**:

```bash
VPS=user@your-vps-ip
REMOTE=~/Development/GitHub/OnHighGround2

rsync -avz --progress \
  data_runtime/frontend/tiles/ \
  ${VPS}:${REMOTE}/data_runtime/frontend/tiles/
```

転送後、VPS で再起動：

```bash
git pull   # docker-compose.yml も最新化する
docker compose restart martin
docker compose logs --tail=20 martin
# → INFO: Discovered X sources が出れば正常
```

### Martin がカタログを返さない

```bash
docker compose logs martin
```

`/tiles/tokyo/flood` など、コンテナ起動コマンドのパスにファイルがあるか確認：

```bash
ls data_runtime/frontend/tiles/tokyo/flood/
ls data_runtime/frontend/tiles/tokyo/tsunami/
ls data_runtime/frontend/tiles/tokyo/storm_surge/
```

### 502 Bad Gateway

```bash
# コンテナ全体の状態確認
docker compose ps

# Caddy ログ
sudo journalctl -u caddy -n 50
```

### 地図上にレイヤーが表示されない

1. ブラウザの開発者ツール（F12）→ Network タブで API レスポンスを確認
2. `https://ohg.brokendish.org/api/hazards/landslide/tokyo` が 200 を返しているか確認
3. 管理 UI `https://ohg.brokendish.org/admin/hazards` でレイヤーステータスを確認

### 土砂災害・内水氾濫が表示されるエリアが狭い

データカバレッジの問題。現在の収録範囲：

| ハザード | データソース | カバレッジ |
| --- | --- | --- |
| 内水氾濫 | A51-24（国土数値情報） | 福生市のみ（13218） |
| 土砂災害 | A33-24（国土数値情報） | 東京都全域（29,943件） |

内水氾濫を広げるには、他市区町村の A51 データを `data_lake/raw/tokyo/inland_flood/` に追加して再正規化する。

---

## Appendix: data_runtime ディレクトリ構造

```text
data_runtime/
├── backend/
│   ├── elevation/
│   │   └── elevation.tif              # DEM（~426MB）
│   ├── hazard/
│   │   ├── flood/
│   │   │   └── tokyo_flood_check.geojsonl    # 洪水判定用（~476MB）
│   │   ├── storm_surge/
│   │   │   └── tokyo_storm_surge.geojson     # 高潮（~48MB）
│   │   ├── tsunami/
│   │   │   ├── tsunami_tokyo.geojson          # 東京（~16MB）
│   │   │   ├── tsunami_kanagawa.geojson       # 神奈川（~100MB）任意
│   │   │   └── tsunami_chiba.geojson          # 千葉（~138MB）任意
│   │   ├── inland_flood/
│   │   │   └── tokyo_inland_flood_A51.geojson # 内水氾濫（~184KB）
│   │   └── landslide/
│   │       └── tokyo_landslide_A33.geojson    # 土砂災害（~29MB）
│   └── shelters/
│       ├── {DATASET_ID}/{basename}.geojson    # 正規: admin registry管理
│       └── tokyo_shelter.geojson              # legacy（現在は読まれない）
├── frontend/
│   ├── layers/                                # API fallback 用 GeoJSON
│   │   ├── tsunami_tokyo.geojson
│   │   ├── tokyo_storm_surge.geojson
│   │   ├── inland_flood_tokyo.geojson
│   │   └── landslide_tokyo.geojson
│   └── tiles/
│       └── tokyo/
│           ├── flood/
│           │   └── tokyo_flood_max.mbtiles    # 洪水タイル（~167MB）
│           ├── storm_surge/
│           │   └── tokyo_storm_surge.mbtiles  # 高潮タイル（~19MB）
│           └── tsunami/
│               ├── tokyo_tsunami_A40-23_13.mbtiles
│               ├── kanagawa_tsunami_A40-16_14.mbtiles
│               ├── kanagawa_tsunami_A40-20_14.mbtiles
│               └── chiba_tsunami_A40-18_12.mbtiles
└── manifests/
    └── latest.json                            # 最終デプロイ記録
```
