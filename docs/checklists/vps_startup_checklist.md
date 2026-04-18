# VPS 起動チェックリスト

新規 VPS へのセットアップ時、またはコンテナを完全に削除した後に使用する。
手順は記載の順番で実行すること。

動作確認済み環境：Debian 12、Docker 26+、RAM 2 GB の VPS。

---

## 0. 前提条件

- [ ] Docker および Docker Compose プラグインがインストール済み（`docker compose version` で確認）
- [ ] Git がインストール済みでリポジトリがクローン済み
- [ ] ファイアウォールでポート 8080 が開放済み（リバースプロキシを使う場合は 80/443）

---

## 1. ディレクトリ構造

コンテナ起動前に以下のディレクトリが存在する必要がある。
これらは **gitignore 対象**のため、新規サーバーでは手動作成が必要。

```bash
mkdir -p data_lake/registry
mkdir -p data_lake/raw
mkdir -p data_lake/normalized
mkdir -p data_lake/validated
mkdir -p data_lake/tiles
mkdir -p data_runtime/backend/elevation
mkdir -p data_runtime/frontend/tiles
```

---

## 2. ハザードデータ

バックエンドがハザードチェックを返すには、事前に管理画面（`/admin/datasets`）または
パイプライン経由でハザードデータを投入する必要がある。

東京カバレッジに最低限必要なデータセット：

| データセット | 備考 |
|---|---|
| 東京 tsunami | 約 45 MB GeoJSON |
| 神奈川 tsunami | 約 45 MB GeoJSON |
| 東京 storm_surge | 約 60 MB GeoJSON |
| 神奈川 storm_surge | 約 60 MB GeoJSON |
| 東京 landslide | 約 100 MB GeoJSON |
| 神奈川 landslide | 約 100 MB GeoJSON |
| 東京 flood | 約 80 MB GeoJSON |

千葉の tsunami はメモリ制約のある VPS ではデフォルトで除外されている。
`backend/app.properties` の `hazard.tsunami.targets` を参照。

RAM 要件の詳細は [メモリチューニング](../operations/vps_memory_tuning.md) を参照。

---

## 3. OSRM 徒歩データ

OSRM の徒歩インデックスは、コンテナ初回起動時に PBF ファイルからビルドされる。
`osrm-walking` を起動する前に PBF ファイルを配置すること。

配置先パス：

```text
data_lake/validated/tokyo/osm/walking/tokyo-kanagawa/tokyo-kanagawa-260214.osm.pbf
```

このファイルが存在しない場合、コンテナは即座に終了する（`test -f` が失敗）。

**初回ビルド時間**：2 GB VPS で 30〜60 分。
**ビルド中はコンテナを停止しないこと。**

ビルド進捗の確認：

```bash
docker compose logs -f osrm-walking
```

正常なログ出力の流れ：

```text
OSRM index not found — building from PBF...
[osrm-extract] ...
[osrm-partition] ...
[osrm-customize] ...
[info] Listening on: 0.0.0.0:5001
[info] running and waiting for requests
```

インデックスの再ビルド（PBF 更新後など）：

```bash
rm data_lake/validated/tokyo/osm/walking/tokyo-kanagawa/tokyo-kanagawa-260214.osrm*
docker compose restart osrm-walking
```

---

## 4. サービスの起動

依存関係の問題を避けるため、以下の順番で起動する：

```bash
# まずバックエンドとインフラを起動
docker compose up -d backend martin

# バックエンドの起動完了を待つ（約 30 秒）
docker compose ps

# フロントエンド（nginx）を起動 — depends_on: backend, osrm-walking
# osrm-walking は依存関係として自動的に起動される
docker compose up -d frontend
```

一括起動も可能（docker compose が depends_on を処理する）：

```bash
docker compose up -d
```

注意：`osrm-driving` はデフォルトでは**起動しない**（プロファイルで制御）。

---

## 5. ヘルスチェック

```bash
# 全コンテナが Running 状態（Restarting になっていないこと）
docker compose ps

# バックエンド API
curl -s http://localhost:8000/health

# OSRM 徒歩
curl -s "http://localhost:5501/route/v1/walking/139.69,35.68;139.70,35.69" | head -c 50

# nginx プロキシ経由（エンドツーエンド）
curl -s "http://localhost:8080/api/health"
curl -s "http://localhost:8080/osrm/walking/route/v1/walking/139.69,35.68;139.70,35.69" | head -c 50
```

すべて HTTP 200 で有効な JSON が返ることを確認する。

---

## 6. 既知の問題と注意事項

### 起動時に martin が Restarting ループに入る

Martin が Restarting ループになる場合、`config/martin.yaml` にディスク上に存在しない
タイルパスが含まれている可能性がある。未ビルドのデータセットのエントリをコメントアウトまたは削除する。

```bash
docker compose logs martin
```

### バックエンドのメモリが 1.5 GB を超える

- `backend/app.properties` の `hazard.tsunami.targets` に `chiba` が含まれていないか確認
- `backend/main.py` のすべてのハザード読み込みで `bbox_only=True` が指定されているか確認
- 詳細は [メモリチューニング](../operations/vps_memory_tuning.md) を参照

### osrm-walking がヘルプテキストを表示して終了する

コンテナログに `osrm-routed <base.osrm> [<options>]:` というヘルプメッセージが表示される場合、
OSRM インデックスファイルが存在しないかパスが間違っている。

確認コマンド：

```bash
ls data_lake/validated/tokyo/osm/walking/tokyo-kanagawa/
```

`.osrm` ファイルおよびその関連ファイル（`.partition`、`.mldgr` など）がすべて存在する必要がある。

### nginx から osrm-walking にプロキシできない

`/osrm/walking/` が `InvalidUrl`（HTTP 400）を返す場合、
nginx プロキシが location プレフィックスを正しく除去できていない。
[nginx プロキシパターン](../architecture/nginx_proxy_patterns.md) を参照。

`proxy_pass` は**末尾スラッシュ付きのリテラルホスト名**を使う必要がある：

```nginx
proxy_pass http://osrm-walking:5001/;  # 正しい
```

### ShelterRegistry の CPU / メモリ使用率が高い

バックエンドのログで 30 秒ごとに避難所データが再読み込みされている場合、
`backend/app/services/shelter_service.py` を確認する：

```python
_registry_instance = ShelterRegistry(ttl_seconds=3600)  # 30 ではなく 3600 であること
```

---

## 7. エンドツーエンドの確認

ブラウザで `http://<VPS の IP アドレス>:8080` を開く。

- [ ] 地図が避難所ピンと共に表示される
- [ ] 東京都内の地点でハザードチェックが結果を返す
- [ ] 避難ルート検索が完了し、徒歩ルートが表示される
