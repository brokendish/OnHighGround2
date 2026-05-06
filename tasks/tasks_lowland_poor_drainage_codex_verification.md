# OnHighGround2 低地・排水困難エリア Codex 検証結果

検証日時: 2026-05-06 JST

## 最終判定

**PASS with notes**

国土交通省 G08 低位地帯データを使った `低地・排水困難エリア` は、dataset definition、normalize、validate、tile build、deploy、Martin catalog、frontend UI、backend hazard 判定に導入済みであることを確認した。

注意点:

- 指示書の MBTiles 期待ファイル名は `lowland_poor_drainage.mbtiles` だが、実装は Martin source / frontend tileset ID と整合する `tokyo_lowland_poor_drainage.mbtiles` / `kanagawa_lowland_poor_drainage.mbtiles` を使用している。
- backend の `data_runtime/backend/hazard/lowland_poor_drainage/` には deploy されず、backend は `data_lake/validated/{region}/lowland_poor_drainage/lowland_poor_drainage.geojson` を fallback として読み込む実装。再起動後に `lowland_poor_drainage` は hazard 判定へロードされた。
- `data_lake/admin/active_mappings.json` には lowland の active mapping は未登録。現状 frontend は Martin tileset を静的参照し、backend hazard 判定も fallback ロードなので動作上は問題なし。

## 1. dataset definition

PASS

実行コマンド:

```bash
rg -n "LOWLAND|lowland_poor_drainage|低地|poor drainage" data_lake/registry/dataset_definitions.json backend frontend config scripts docker-compose.yml package.json
python3 scripts/registry/check_registry.py
```

結果:

- `TOKYO-LOWLAND-POOR-DRAINAGE-001` 登録あり。
- `KANAGAWA-LOWLAND-POOR-DRAINAGE-001` 登録あり。
- `display_name` は `低地・排水困難エリア（東京都）` / `低地・排水困難エリア（神奈川県）`。
- `category` は両方 `hazard`。
- `region` は `tokyo` / `kanagawa`。
- `raw_storage_path` は `data_lake/raw/{region}/lowland_poor_drainage`。実 ZIP はその配下の `G08-15_13_GML.zip` / `G08-15_14_GML.zip`。
- registry check は `Registry check passed`。

## 2. normalize 検証

PASS

実行コマンド:

```bash
python3 scripts/normalize/normalize_lowland_poor_drainage.py --region tokyo
python3 scripts/normalize/normalize_lowland_poor_drainage.py --region kanagawa
```

結果:

- 東京: `data_lake/normalized/tokyo/lowland_poor_drainage/lowland_poor_drainage.geojson`
  - 1,483 features
  - 26.49 MB
- 神奈川: `data_lake/normalized/kanagawa/lowland_poor_drainage/lowland_poor_drainage.geojson`
  - 1,978 features
  - 24.53 MB

GeoJSON 内容確認:

```bash
python3 - <<'PY'
import json, pathlib, collections
for region in ['tokyo','kanagawa']:
 p=pathlib.Path(f'data_lake/validated/{region}/lowland_poor_drainage/lowland_poor_drainage.geojson')
 d=json.load(p.open())
 geoms=collections.Counter(f.get('geometry',{}).get('type') for f in d['features'])
 risks=collections.Counter((f.get('properties',{}).get('risk'), f.get('properties',{}).get('risk_score'), f.get('properties',{}).get('region'), f.get('properties',{}).get('dataset')) for f in d['features'])
 print(region, d.get('type'), len(d['features']), dict(geoms), risks.most_common(5))
PY
```

結果:

- 東京: `FeatureCollection`, 1,483 features, `Polygon` のみ。
- 神奈川: `FeatureCollection`, 1,978 features, `Polygon` 1,976 / `MultiPolygon` 2。
- 全 feature が `risk=low`, `risk_score=1`, `dataset=lowland_poor_drainage`, `region=tokyo|kanagawa` を保持。

## 3. validate 検証

PASS

実行コマンド:

```bash
python3 scripts/validate/validate_lowland_poor_drainage.py --region tokyo --input data_lake/normalized/tokyo/lowland_poor_drainage/lowland_poor_drainage.geojson --output data_lake/validated/tokyo/lowland_poor_drainage/lowland_poor_drainage.geojson
python3 scripts/validate/validate_lowland_poor_drainage.py --region kanagawa --input data_lake/normalized/kanagawa/lowland_poor_drainage/lowland_poor_drainage.geojson --output data_lake/validated/kanagawa/lowland_poor_drainage/lowland_poor_drainage.geojson
```

結果:

- 東京: `検証 OK`, bbox `lon=[138.9861,153.9847] lat=[24.2845,35.8728]`
- 神奈川: `検証 OK`, bbox `lon=[138.9869,139.7941] lat=[35.1422,35.6383]`
- geometry エラーなし。
- `risk=low`, `risk_score=1` を確認。

## 4. tile build 検証

PASS with notes

実行コマンド:

```bash
tippecanoe -o data_lake/tiles/tokyo/lowland_poor_drainage/tokyo_lowland_poor_drainage.mbtiles -l lowland_poor_drainage -zg --drop-densest-as-needed --extend-zooms-if-still-dropping --force data_lake/validated/tokyo/lowland_poor_drainage/lowland_poor_drainage.geojson
tippecanoe -o data_lake/tiles/kanagawa/lowland_poor_drainage/kanagawa_lowland_poor_drainage.mbtiles -l lowland_poor_drainage -zg --drop-densest-as-needed --extend-zooms-if-still-dropping --force data_lake/validated/kanagawa/lowland_poor_drainage/lowland_poor_drainage.geojson
```

結果:

- 東京 MBTiles: `data_lake/tiles/tokyo/lowland_poor_drainage/tokyo_lowland_poor_drainage.mbtiles`, 2,170,880 bytes
- 神奈川 MBTiles: `data_lake/tiles/kanagawa/lowland_poor_drainage/kanagawa_lowland_poor_drainage.mbtiles`, 2,158,592 bytes
- metadata `json.vector_layers[0].id` は両方 `lowland_poor_drainage`。
- frontend の `sourceLayer: 'lowland_poor_drainage'` と一致。
- zoom range は metadata `minzoom=0`, `maxzoom=14`、tiles 実体は min/max zoom `1..14`。極端ではない。

## 5. deploy 検証

PASS

実行コマンド:

```bash
scripts/publish/deploy_to_runtime.sh --region tokyo
scripts/publish/deploy_to_runtime.sh --region kanagawa
```

結果:

- 東京 runtime: `data_runtime/frontend/tiles/tokyo/lowland_poor_drainage/tokyo_lowland_poor_drainage.mbtiles`
- 神奈川 runtime: `data_runtime/frontend/tiles/kanagawa/lowland_poor_drainage/kanagawa_lowland_poor_drainage.mbtiles`
- 既存 tiles も deploy 対象として維持された。
- rollback 手順は専用機構が見当たらないため未実施。

## 6. Martin catalog 検証

PASS

実行コマンド:

```bash
docker compose restart martin
curl -s http://127.0.0.1:8080/tiles/catalog
docker logs --tail 50 evacuation-navi-martin
docker compose ps martin
```

結果:

- catalog に `tokyo_lowland_poor_drainage` が出現。
- catalog に `kanagawa_lowland_poor_drainage` が出現。
- Martin logs:
  - `Configured source tokyo_lowland_poor_drainage`
  - `Configured source kanagawa_lowland_poor_drainage`
- `docker compose ps martin` は `healthy`。
- 実タイル確認:
  - `GET /tiles/tokyo_lowland_poor_drainage/10/909/403` -> 200, `Content-Type: application/x-protobuf`, 84,903 bytes
  - `GET /tiles/kanagawa_lowland_poor_drainage/10/908/404` -> 200, `Content-Type: application/x-protobuf`, 54,827 bytes

## 7. frontend 表示検証

PASS

実行コマンド:

```bash
node -e "/* Playwright で http://127.0.0.1:8080/ を開き、レイヤータブを開いて低地トグルを検証 */"
```

結果:

- サイドパネルに `低地・排水困難エリア` が存在。
- `showLowlandPoorDrainageTokyo` / `showLowlandPoorDrainageKanagawa` が存在。
- レイヤータブを開いた後、hazard toggle bound は `true`。
- 東京・神奈川とも availability は `vector-tiles`。
- 東京トグル ON 後:
  - `HAZARD_LAYERS.lowland_poor_drainage_tokyo.visible === true`
  - status は `低地・排水困難エリアレイヤー: ON（東京都）`
  - legend は `display: block`
- Playwright 上の JS error はなし。

## 8. style 検証

PASS

確認内容:

- fill は `#c8b4d4`、opacity は `0.25`。
- border は `#7b5ea7`, weight `0.8`, opacity `0.4`, dashArray `4,6`。
- 洪水・高潮・津波より主張が弱い。
- 凡例 note は「地形的な排水困難エリア」「補助情報」と説明しており、現在進行中の災害表示には見えにくい。
- ルート線や現在地マーカーを強く邪魔しないスタイル。

## 9. Phase3A ルート色付け・risk 判定検証

PASS

実行コマンド:

```bash
docker compose restart backend
docker exec evacuation-navi-backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).read().decode())"
docker exec evacuation-navi-backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/hazard-check?lat=35.63743961235805&lon=139.52226429878073', timeout=10).read().decode())"
```

結果:

- backend health:
  - `hazard_loaded` に `lowland_poor_drainage` が含まれる。
  - `hazard_polygon_counts.lowland_poor_drainage = 3463`
- 低地単独地点の hazard-check:
  - `hazard_assessment.lowland_poor_drainage = "inside"`
  - `is_danger = false`
  - `hazards = []`
- 洪水と重なる地点の hazard-check:
  - `hazard_assessment.lowland_poor_drainage = "inside"`
  - `hazard_assessment.flood = "inside"`
  - `is_danger = true`
  - `hazards = ["flood"]`
- `backend/hazard_service.py` で `SUPPLEMENTARY_HAZARD_TYPES = ["lowland_poor_drainage"]` を確認。単独では強い危険判定にしない設計。

期待値:

- `hazard_type = lowland_poor_drainage`: 満たす。
- `risk_score = 1`: GeoJSON / MBTiles metadata で満たす。
- `severity = low`: normalized property は `risk=low`。backend assessment は補助 hazard として文字列 `inside/outside` を返すため、severity field は持たない。

## 10. 回帰確認

PASS with notes

実行コマンド:

```bash
docker compose ps
docker exec evacuation-navi-backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).read().decode())"
curl -s 'http://127.0.0.1:5501/route/v1/walking/139.7905,35.6415;139.8000,35.6500?overview=false'
docker exec evacuation-navi-backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/emergency-shelters?limit=5', timeout=10).read().decode()[:1200])"
docker exec evacuation-navi-backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/hazards/active', timeout=10).read().decode())"
```

結果:

- backend 起動 OK。`healthy`。
- frontend 起動 OK。`docker ps` で `0.0.0.0:8080->80/tcp`。
- Martin 起動 OK。`healthy`。
- route 検索 OK。OSRM walking route は `code=Ok`, distance `2030.8m`。
- shelter 表示用 API OK。`/api/emergency-shelters?limit=5` が `count=5`, `total_count=6939`。
- flood / tsunami / storm_surge / inland_flood / landslide は backend health と `/api/hazards/active` で既存 active dataset を確認。
- pseudo_inland_flood は `/api/hazards/active` に存在し、frontend tile deploy も維持。
- navigation 開始は Playwright で完全操作までは未実施。ただし route 取得、frontend 起動、主要 JS ロード、OSRM 応答は確認済み。

## 修正内容

コード修正は実施していない。

検証のために以下を実行した:

- normalize 再生成
- validate 再生成
- MBTiles 再生成
- runtime deploy
- Martin restart
- backend restart

## 残課題

- 指示書の MBTiles ファイル名と実装上のファイル名が異なる。現実装は frontend/Martin と整合しており表示は PASS。
- backend は lowland を `data_lake/validated` fallback から読む。runtime backend 配備を必須にするなら `deploy_to_runtime.sh` に backend hazard copy を追加する余地がある。
- `active_mappings.json` には lowland が未登録。管理 API から active hazard として扱う要件があるなら、`HazardDatasetService.HAZARD_LAYER_TYPES` と active mapping/runtime path 設計を合わせて追加する必要がある。

**PASS with notes**
