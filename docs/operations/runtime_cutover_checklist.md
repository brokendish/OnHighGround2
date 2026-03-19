# Runtime Cutover チェックリスト

Phase 2 以降の起動時・デプロイ時に使用するチェック手順。

---

## 0. 前提: deploy_to_runtime.sh の実行

**最初に必ず実行すること。**

```bash
scripts/publish/deploy_to_runtime.sh --region tokyo
# ドライランで確認してから実行する場合:
scripts/publish/deploy_to_runtime.sh --region tokyo --dry-run
```

配備完了後 `data_runtime/manifests/latest.json` を確認:
```bash
cat data_runtime/manifests/latest.json
```

---

## 1. backend 起動ログの確認

```bash
docker logs evacuation-navi-backend 2>&1 | grep -E "loaded from|fallback"
```

**期待するログ（すべて `loaded from runtime` であること）:**

```
INFO [__main__] OnHighGround2 backend starting
INFO [__main__] DEM loaded from runtime: /data_runtime/backend/elevation/elevation.tif
INFO [__main__] Flood loaded from runtime: /data_runtime/backend/hazard/flood/tokyo_flood_check.geojsonl
INFO [__main__] StormSurge loaded from runtime: /data_runtime/backend/hazard/storm_surge/tokyo_storm_surge.geojson
INFO [__main__] Tsunami loaded from runtime: /data_runtime/backend/hazard/tsunami/tsunami_tokyo.geojson
INFO [__main__] Shelter loaded from runtime: /data_runtime/backend/shelters
INFO [__main__] 避難場所データ読み込み件数: NNNN
```

**WARNING が出た場合（fallback 発生）:**

```
WARNING [__main__] DEM fallback to data_lake: ...
```

→ `deploy_to_runtime.sh` で該当ファイルが配備されているか確認する。
→ `data_runtime/manifests/latest.json` の `missing_files` を確認する。

---

## 2. RSA 有効ログの確認

```bash
docker logs evacuation-navi-backend 2>&1 | grep "geometry_utils"
```

**期待するログ:**

```
INFO [geometry_utils] geometry_utils: shapely/pyproj available — RSA calculation enabled
```

`disabled` が出た場合:
- `docker compose build backend` でイメージを再ビルドする
- Dockerfile に `libgeos-dev` / `libproj-dev` が含まれているか確認する

---

## 3. API 疎通確認

```bash
BASE=http://localhost:8080

# ヘルスチェック
curl -s "${BASE}/api/health" | python3 -m json.tool

# ハザード判定
curl -s "${BASE}/api/hazard-check?lat=35.685&lon=139.753" | python3 -m json.tool

# 避難先検索
curl -s -X POST "${BASE}/api/evacuation" \
  -H "Content-Type: application/json" \
  -d '{"lat":35.685,"lon":139.753,"transport_mode":"walking","max_distance":2000}' \
  | python3 -m json.tool

# 避難所一覧
curl -s "${BASE}/api/emergency-shelters?lat=35.685&lon=139.753&radius_km=2" | python3 -m json.tool
```

**確認ポイント:**

| エンドポイント | 確認内容 |
|---|---|
| `/api/health` | `status: "ok"`, DEM/hazard/shelter が loaded |
| `/api/hazard-check` | `is_danger`, `hazards` が返る |
| `/api/evacuation` | `recommended` に RSA 関連フィールド (`reachable_safe_area`) が含まれること |
| `/api/emergency-shelters` | 避難所リストが返る |

**RSA 確認:** `/api/evacuation` のレスポンスで:
```json
"reachable_safe_area": {
  "enabled": true,
  "radius_m": NNNN,
  "area_m2": NNNN,
  "exists": true,
  "geometry": { ... }
}
```
`enabled: true` かつ `geometry` が null でないこと。

---

## 4. frontend /layers 参照確認

```bash
# /layers/ からGeoJSONが返るか確認
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/layers/tokyo_storm_surge.geojson
# → 200 であること

# /hazard/ は deprecated（ファイルがあれば200、なければ404）
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/hazard/tokyo_storm_surge.geojson
# → 200 (後方互換) or 404 (ファイルがなければOK)
```

**ブラウザ確認（開発者ツール → Network タブ）:**

- ハザードレイヤーを ON にしたとき、`/layers/...` へのリクエストが発生すること
- `/hazard/...` へのリクエストが発生しないこと（`LAYER_BASE_PATH = '/layers'` が効いていること）

---

## 5. Martin タイル配信確認

```bash
# カタログ確認（runtime のタイルが登録されているか）
curl -s http://localhost:8080/tiles/catalog | python3 -m json.tool

# タイルデータの疎通（flood タイルの例）
curl -s -o /dev/null -w "%{http_code}" \
  "http://localhost:8080/tiles/tokyo_flood_max/0/0/0"
```

**起動ログ確認:**

```bash
docker logs evacuation-navi-martin 2>&1 | head -30
```

`/tiles/tokyo/flood`, `/tiles/tokyo/tsunami` 等が configure されたログが出ること。

`data_runtime/frontend/tiles/` にタイルがない場合:
1. `deploy_to_runtime.sh` を実行してタイルを配備
2. `docker compose restart martin` でマーティンを再起動

---

## 6. 全サービス起動確認

```bash
docker compose ps
# すべてのサービスが "running" または "healthy" であること

docker compose logs --tail 20 backend
docker compose logs --tail 20 martin
```

---

## 7. トラブルシューティング

| 症状 | 原因 | 対処 |
|---|---|---|
| `fallback to data_lake` ログ | runtime にデータ未配備 | `deploy_to_runtime.sh` を実行 |
| RSA `disabled` ログ | shapely/pyproj ビルド失敗 | `docker compose build backend` (--no-cache) |
| `/layers/...` が 404 | `frontend/layers/` にファイルなし | `deploy_to_runtime.sh` を実行（sync 含む） |
| Martin タイルが空 | `data_runtime/frontend/tiles/` 空 | `deploy_to_runtime.sh` を実行後、martin 再起動 |
| `/api/health` で shelter=0 | 避難所データ未配備 | `deploy_to_runtime.sh` を実行 |

---

## 8. 定期確認コマンド（運用中）

```bash
# 最新の配備状態を確認
cat data_runtime/manifests/latest.json

# fallback が発生していないか確認
docker logs evacuation-navi-backend 2>&1 | grep "fallback" | tail -20

# エラーログの確認
docker logs evacuation-navi-backend 2>&1 | grep -E "ERROR|EXCEPTION" | tail -20

# タイルサーバーの死活確認
curl -sf http://localhost:8080/tiles/catalog > /dev/null && echo "Martin OK" || echo "Martin NG"
```
