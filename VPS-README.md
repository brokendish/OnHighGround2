# OnHighGround2 VPS 運用メモ

最終更新: 2026-03-14

---

## 目次

1. [サービス構成概要](#1-サービス構成概要)
2. [Docker 起動・停止手順](#2-docker-起動停止手順)
3. [OSRM 再構築（データ更新時）](#3-osrm-再構築データ更新時)
4. [動作確認コマンド](#4-動作確認コマンド)
5. [トラブルシュート](#5-トラブルシュート)
6. [データマウント構成](#6-データマウント構成)

---

## 1. サービス構成概要

注記:
東京版データ基盤 v1 の `data_lake/` は、現時点ではローカル開発用の取得・正規化・検証基盤です。
この運用メモにある VPS 構成には、まだ `data_lake` パイプラインの定期実行や配信同期は組み込まれていません。

### 🌐 公開ドメイン

| サービス | URL | 説明 |
|----------|-----|------|
| フロント | https://ohg.brokendish.org | WebアプリUI（Leaflet + Routing） |
| API | https://api.brokendish.org | FastAPI バックエンド |
| OSRM | https://osrm.brokendish.org | ルーティング専用サーバ |

---

### 🐳 Dockerコンテナ構成

| コンテナ名 | 役割 | 公開ポート |
|-----------|------|-----------|
| evacuation-navi-frontend | nginx 静的配信 | 8080 |
| evacuation-navi-backend | FastAPI | 8000 |
| evacuation-navi-osrm-walking | OSRM (foot.lua) | 5501 |
| evacuation-navi-osrm-driving | OSRM (car.lua) | 5500 |

---

### 🔀 リバースプロキシ（Caddy）

Caddy が HTTPS 終端およびドメイン振り分けを行う。

| ドメイン | 転送先 |
|---------|--------|
| ohg.brokendish.org | 127.0.0.1:8080 |
| api.brokendish.org | 127.0.0.1:8000 |
| osrm.brokendish.org | 127.0.0.1:5501 |

> CORS は `osrm.brokendish.org` 側で制御している。

---

## 2. Docker 起動・停止手順

作業ディレクトリ:

```bash
cd ~/Development/GitHub/OnHighGround2
```

### ▶ 起動

```bash
docker compose up -d
```

### 📋 状態・ログ確認

```bash
# 状態確認
docker compose ps

# 全ログ
docker compose logs -f

# 特定サービスのみ
docker compose logs -f osrm-walking
docker compose logs -f backend
```

### ⏹ 停止

```bash
docker compose down
```

> ボリュームは削除されない。

### 🔁 再起動

```bash
# 全コンテナ
docker compose restart

# 特定コンテナのみ
docker compose restart frontend
```

---

## 3. OSRM 再構築（データ更新時）

OSMデータを更新した場合は `.osrm` ファイルを削除して再生成する。

```bash
rm -rf ./data_lake/validated/tokyo/osm/walking/*
rm -rf ./data_lake/validated/tokyo/osm/driving/*
docker compose up -d --build
```

---

## 4. 動作確認コマンド

### API 確認

```bash
curl https://api.brokendish.org/health
```

### OSRM 確認

```bash
curl "https://osrm.brokendish.org/route/v1/walking/139.7671,35.6812;139.7600,35.6850?overview=false"
```

### フロント確認

ブラウザで以下にアクセス:

```
https://ohg.brokendish.org
```

---

## 5. トラブルシュート

### 502 Bad Gateway

1. コンテナ状態を確認する

```bash
docker compose ps
```

2. OSRM が落ちていないか確認する
3. Caddy ログを確認する

```bash
sudo journalctl -u caddy -n 50
```

---

### CORS エラー

Caddyfile の `osrm.brokendish.org` 設定を確認する。

```bash
curl -sSI -H "Origin: https://ohg.brokendish.org" \
  "https://osrm.brokendish.org/route/v1/walking/139.7671,35.6812;139.7600,35.6850?overview=false"
```

---

## 6. データマウント構成

Docker Compose では backend に `./data_lake:/data_lake:ro` をマウントし、以下を直接参照します:

- DEM: `data_lake/validated/tokyo/dem/elevation.tif`
- 避難所: `data_lake/normalized/tokyo/shelter/tokyo_shelter.geojson`
- 洪水ハザード: `data_lake/normalized/tokyo/flood/tokyo_flood_max.geojson`（起動時にメモリ展開）
- 津波ハザード: `data_lake/normalized/tokyo/tsunami/tsunami_tokyo.geojson`（起動時にメモリ展開。`hazard.tsunami.targets=tokyo` で制御）

Martin は `./data_lake/tiles:/tiles:ro` をマウントし、`/tiles/tokyo/*` 配下の MBTiles を配信します。

### バックエンド /health の確認例

```bash
curl https://api.brokendish.org/health
```

正常時のレスポンス（抜粋）:

```json
{
  "status": "ok",
  "hazard_loaded": ["flood", "tsunami"],
  "hazard_polygon_counts": { "flood": 58539, "tsunami": 33124 },
  "hazard_sources": {
    "flood": ["tokyo_flood_max"],
    "tsunami": ["tsunami_tokyo"]
  },
  "shelters_loaded": 2500
}
```

`hazard_loaded` が空配列の場合は、ハザードデータの配置パスを確認してください。
