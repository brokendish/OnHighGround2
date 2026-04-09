# Martin ベクタータイル配信

OnHighGround2 のハザードレイヤーは、Martin によるベクタータイル（MVT）配信を優先する。
フロントエンドは Martin が利用不可な場合、自動的に API / GeoJSON 配信にフォールバックする。

---

## アーキテクチャ概要

```
data_lake/normalized/{region}/{hazard}/   ← GeoJSON 正規化済みデータ（パイプライン正本）
           ↓  scripts/build_tiles.py
data_lake/tiles/{region}/{hazard}/         ← MBTiles 生成物
           ↓  scripts/publish/deploy_to_runtime.sh
data_runtime/frontend/tiles/{region}/{hazard}/  ← Martin が参照する runtime
           ↓  Martin (コンテナ内 /tiles にマウント)
/tiles/{source_id}/{z}/{x}/{y}             ← ベクタータイル URL
           ↓  nginx proxy /tiles/ → martin:3000/
フロントエンド (L.vectorGrid.protobuf)      ← Leaflet でレンダリング
```

Martin はあくまで「地図配信レイヤー」であり、データパイプライン（正規化・検証・タイル生成）は
引き続き `data_lake/` とスクリプト群が担う。

---

## 現在配信中のタイルソース（東京）

| source ID | MBTiles パス | ハザード種別 |
|---|---|---|
| `tokyo_flood_max` | `data_runtime/frontend/tiles/tokyo/flood/tokyo_flood_max.mbtiles` | 洪水 |
| `tokyo_storm_surge` | `data_runtime/frontend/tiles/tokyo/storm_surge/tokyo_storm_surge.mbtiles` | 高潮 |
| `tokyo_tsunami_A40-23_13` | `data_runtime/frontend/tiles/tokyo/tsunami/tokyo_tsunami_A40-23_13.mbtiles` | 津波（東京） |
| `kanagawa_tsunami_A40-16_14` | `data_runtime/frontend/tiles/tokyo/tsunami/kanagawa_tsunami_A40-16_14.mbtiles` | 津波（神奈川）※1 |
| `kanagawa_tsunami_A40-20_14` | `data_runtime/frontend/tiles/tokyo/tsunami/kanagawa_tsunami_A40-20_14.mbtiles` | 津波（神奈川）※1 |
| `chiba_tsunami_A40-18_12` | `data_runtime/frontend/tiles/tokyo/tsunami/chiba_tsunami_A40-18_12.mbtiles` | 津波（千葉）※1 |

> ※1 **既知のレイアウト問題:** kanagawa・chiba の tsunami タイルが `tiles/tokyo/tsunami/` 配下に混在している。
> ソース ID（ファイル名ステム）は正しいため現在の配信には影響しないが、
> Kanagawa ハザード一式を追加する前に `tiles/kanagawa/tsunami/` へ移動して整理すること。
> 移動後は `deploy_to_runtime.sh --region kanagawa` を再実行し、`docker compose restart martin` で反映する。
>
> `inland_flood`・`landslide` はタイル化未実装。引き続き API 配信（`/api/hazards/{type}/tokyo`）を使用。

---

## タイル生成手順

```bash
# GeoJSON → MBTiles 変換（tippecanoe 必要）
python scripts/build_tiles.py \
    --profile drop \
    --input  data_lake/normalized/tokyo \
    --output data_lake/tiles/tokyo

# MBTiles → data_runtime へ配備
scripts/publish/deploy_to_runtime.sh --region tokyo
```

`deploy_to_runtime.sh` 実行後、以下のコマンドで Martin に新しいタイルを認識させる。

```bash
# タイルファイルの内容だけを更新する場合（config/volume に変更なし）
docker compose restart martin

# docker-compose.yml の command / volumes / config を変更した場合（コンテナ再作成が必要）
docker compose up -d --force-recreate martin
```

> **注意:** `restart` はプロセスを再起動するだけで、`command` や `volumes` の変更は反映されない。
> コンテナ定義（`config/martin.yaml`、マウント設定）を変更したときは必ず `--force-recreate` を使うこと。
> 反映されているかどうかは `docker inspect evacuation-navi-martin` の `Args` と `Mounts` で確認できる。

---

## フォールバック動作

フロントエンド (`frontend/js/hazard-layers.js`) の起動フロー:

1. `checkMartinAvailable()` — `/tiles/catalog` に fetch。失敗 → 全レイヤーを GeoJSON モードで起動。
2. `shouldUseVectorTiles(layerKey)` — `VECTOR_TILE_SOURCES[layerKey]` にエントリがある場合のみ true。
3. 個別レイヤー HEAD チェック — `/tiles/{tilesetId}` を HEAD リクエスト。
   - 成功 → ベクタータイルモードで有効化
   - 失敗 + `apiUrl` あり → `_vectorTilesUnavailable = true` を立て、API フォールバックで有効化
   - 失敗 + `apiUrl` なし → チェックボックスを disabled

この設計により「Martin が落ちている」「tiles が未配備」いずれの場合もアプリが使用不能になることはない。

---

## Martin 設定ファイル

`config/martin.yaml` で管理する。

```yaml
listen_addresses: '0.0.0.0:3000'

mbtiles:
  paths:
    - /tiles/tokyo/flood
    - /tiles/tokyo/tsunami
    - /tiles/tokyo/storm_surge
    # 将来: kanagawa を追加する場合はここに追記
    # - /tiles/kanagawa/flood
    # - /tiles/kanagawa/tsunami
```

**スキャン動作の注意点:**  
`mbtiles.paths` は **非再帰スキャン**（指定ディレクトリ直下の `.mbtiles` のみ）。  
`/tiles` だけ書いても `/tiles/tokyo/flood/` には入らない。  
各 `{region}/{hazard_type}` ディレクトリを明示的に列挙すること。

**ソース ID = ファイル名ステム**（例: `tokyo_flood_max.mbtiles` → ID `tokyo_flood_max`）。

| 操作 | コマンド |
| --- | --- |
| タイルファイルを追加・更新した（config 変更なし） | `docker compose restart martin` |
| `config/martin.yaml` の paths を追記した | `docker compose restart martin` |
| `docker-compose.yml` の volumes/command を変更した | `docker compose up -d --force-recreate martin` |

---

## 神奈川（将来）を追加する手順

```
1. GeoJSON を正規化して data_lake/normalized/kanagawa/{hazard_type}/ に配置

2. タイル生成
   python scripts/build_tiles.py \
       --input  data_lake/normalized/kanagawa \
       --output data_lake/tiles/kanagawa

3. runtime へ配備
   scripts/publish/deploy_to_runtime.sh --region kanagawa
   # → data_runtime/frontend/tiles/kanagawa/{hazard_type}/*.mbtiles が生成される

4. Martin 再起動（タイルファイルの追加のみなので restart で十分）
   docker compose restart martin
   # → /tiles/kanagawa/... が自動的に配信開始（config/martin.yaml 変更不要）

5. frontend/js/hazard-layers.js に HAZARD_LAYERS と VECTOR_TILE_SOURCES エントリを追加
   # 例: kanagawa_flood_max, kanagawa_storm_surge など

6. index.html サイドパネルと map-overlay-ui.js にチェックボックス・メニューを追加
```

`deploy_to_runtime.sh` は `--region` 引数でリージョンを切り替えられる。
`config/martin.yaml` はリージョンに関わらず変更不要。

---

## トラブルシューティング

| 症状 | 確認事項 |
|---|---|
| レイヤーが灰色・何も表示されない | `docker logs evacuation-navi-martin` でエラー確認 |
| catalog が空 | `data_runtime/frontend/tiles/` に .mbtiles が存在するか確認 |
| tiles は配信されているが色がおかしい | `VECTOR_TILE_SOURCES[layerKey].colorFn` と source-layer 名を確認 |
| チェックボックスが disabled のまま | ブラウザコンソールで `[hazard:init]` ログを確認、HEAD チェック結果を確認 |
| Martin 起動時に "path not found" | `deploy_to_runtime.sh` を実行してから `docker compose restart martin` |
| コンテナが古い command/config のまま | `docker inspect evacuation-navi-martin` で `Args` と `Mounts` を確認。変更が反映されていなければ `docker compose up -d --force-recreate martin` |
