# DEM 標高の整合性監査（2026-10-12）

対象: `elevation.tif`（TOKYO-DEM-001、sha256 `fdd8e3b37b53cec7587e863ee37c4f7bf4aeaf41a4f1c279cead88356226a77f`）。
Local の validated と VPS の flat runtime（`/data_runtime/backend/elevation/`）は同一 file。
この監査では runtime の DEM・backend・PSEUDO を変更していない。

## 結論

- **DEM の値は正しい。** 地理院の DEM5A 標高タイル（z15）と 300 点で比べると、正しい読み方での差は
  中央値 0.09 m・p95 1.95 m・最大 5.65 m。平地（傾斜 2° 未満）では最大 0.25 m。
- **backend の読み取り位置が誤っている。** 現在の backend（`ElevationService`）は 3 次メッシュの中で別の画素を読む。
  差は中央値 4.40 m・p95 169 m・最大 459 m（平地でも p95 14.8 m・最大 174 m）。
- 判定: **D. UNSAFE_FOR_ELEVATION_DECISION**（現在の backend の読み方では避難判断に使うべきでない）。
  DEM の画素値そのものは A 相当だが、利用経路が誤っている。

## 原因（座標軸の契約）

`data_processing/convert_dem.py` は基盤地図情報 DEM の 3 次メッシュ GML を 1 file ずつ GeoTIFF にしてから
`rasterio.merge` で 1 次メッシュ 5339 に結合している。

1. tile 内の配列は正しい: `gml:high` = `224 149`（経度 225 × 緯度 150 格子）、`sequenceRule +x-y` のとおり
   行 = 北→南（緯度）、列 = 西→東（経度）で `reshape(height, width)` している。
2. tile の transform が誤っている: `gml:lowerCorner` / `upperCorner` は「緯度 経度」の順なのに、
   そのまま `west, south, east, north` として `from_bounds` に渡している（66–67 行、175 行）。
   その結果、各 tile は「x = 緯度（画素 3.7037e-5°）、y = 経度（画素 8.3333e-5°）」と宣言される。
3. `rasterio.merge` は宣言どおりに tile を並べるため、**tile の配置だけが転置**される。

| | 実際の意味 |
|---|---|
| mosaic の列 block（225 列ごと） | 緯度方向の tile index（南→北） |
| mosaic の行 block（150 行ごと） | 経度方向の tile index（行 0 が経度最大の東端） |
| tile 内の行 | 緯度（北→南） |
| tile 内の列 | 経度（西→東） |

正しい画素（`scripts/validate/audit_dem_elevation.py` の `fgd_mosaic_rowcol`）:

```
tc = floor((lat - 35°20′) / 30″)        tl = floor((lon - 139°) / 45″)
row_in = floor((30″ - (lat - 35°20′ - tc·30″)) / 0.2″)
col_in = floor((lon - 139° - tl·45″) / 0.2″)
row = (79 - tl)·150 + row_in            col = tc·225 + col_in
```

backend は geotransform のまま（x = 緯度、y = 経度）読むため、正しい tile を引くが、tile 内では
「緯度の割合を列、経度の割合を行」に使う。tile 1 枚（約 0.9 km × 1.1 km）の中で別の画素を読む。
平地で差が小さく山地で大きく、ときどき一致する（tile の対角線付近）のはこのため。

この原因は `tests/test_dem_elevation_integrity.py` が実際の `convert_dem.py` と `ElevationService` を
合成 GML で動かして再現している（参照タイルに依存しない）。

## 比較（参照: 地理院 DEM5A 標高タイル z15、補助基準）

標本 342 点（メッシュ 5339 を 16 × 20 に分けた格子内の乱数点 320 + 既知地点 22）。DEM5A の値がある 300 点で比較。
DEM5B は 5 tile のみ・DEM10B は z15 が無いため、参照はすべて DEM5A になった。参照タイルは Web メルカトルへ
再標本化した値なので、正解ではなく補助基準として扱う。

| 読み方 | n | bias | median | RMSE | p90 | p95 | max |
|---|---|---|---|---|---|---|---|
| backend（現行、双線形） | 298 | -0.34 | 4.40 | 68.86 | 104.71 | 169.31 | 459.25 |
| 正しい読み方（最近傍） | 299 | +0.03 | 0.09 | 0.89 | 1.44 | 1.95 | 5.65 |

地形別（正しい読み方 / backend の median・max）:

| 傾斜 | n | 正しい読み方 | backend |
|---|---|---|---|
| 2° 未満 | 140 | 0.03 / 0.25 | 1.29 / 174.08 |
| 2–8° | 46 | 0.12 / 0.76 | 4.41 / 212.92 |
| 8–20° | 22 | 0.47 / 2.22 | 14.25 / 109.60 |
| 20° 以上 | 85 | 1.00 / 5.65 | 56.94 / 459.25 |

系統的な変換の探索: 全体の行反転・列反転・tile 内転置・±1 cell のずれは、どれも正しい読み方より悪い
（±1 cell のずれでも median 0.16–0.22 m・max 8–71 m）。cell の原点は北西角（floor）で確定。
backend の読み取り位置の近傍探索では、±10 画素以内に参照と 0.5 m 以内で一致する画素が 162 / 300 点にあり、
値の誤りではなく位置の誤りであることと整合する。

## 既知地点（抜粋）

| 地点 | DEM5A | 正しい読み方 | backend（現行） |
|---|---|---|---|
| 新宿駅 | 37.38 | 37.38 | 30.69（-6.69） |
| 板橋区役所 | 28.99 | 28.99 | 19.01（-9.98） |
| 高尾山山頂 | 598.03 | 598.02 | 423.95（-174.08） |
| 奥多摩駅 | 339.37 | 339.41 | 552.29（+212.92） |
| 雲取山付近 | 1067.41 | 1067.80 | 800.31（-267.10） |
| 東京駅 | 3.60 | 3.60 | 3.66 |

全 20 地点は `tests/test_dem_elevation_integrity.py`（KNOWN）に固定した。

## 避難判断への影響

標高を使う判定:

- 候補の除外: `elevation_gain < min_elevation_gain`（既定 10 m）なら候補にしない（`app_public.py` 1151 行）
- score: `elevation_score = min(gain / 30 × 50, 50)`
- grid fallback: `current_elevation + min_elevation_gain` 以上の地点だけ
- `/api/elevation`・`/api/elevation/profile` の表示値

現在地 14 点（東京 12・横浜・川崎）から 2 km 以内の避難所 896 件で、10 m 判定を backend と正しい読み方で比べた:

- **false include 25 件**（backend は「10 m 以上高い」とするが実際は違う = false-safe）
- false exclude 30 件（実際は高いのに候補から外れる）
- 標高で最上位の候補が変わる地点 4 / 14
- 例: 板橋区役所は現在地の標高を 9.98 m 低く読むため、backend が「10 m 以上高い」とする 7 件がすべて誤り

## PSEUDO への影響

`scripts/derive/generate_pseudo_inland_flood.py` も geotransform（x = 緯度）を前提に配列全体を転置するため、
backend と同じ誤りを継承する。推定内水リスクの polygon は、3 次メッシュの中で誤った位置の標高・傾斜から
作られている（tile 内で最大約 1 km の位置ずれ）。この phase では再生成していない。

## nodata / 重複の扱い

- 原本 tile の無い 3 次メッシュ（531 / 6400 tile）は、`merge` が nodata 未設定のため **0.0 で埋まっている**。
  標本では全て海域だったが、backend は None ではなく 0 m を返す。
- `-9999`（void）は 5,722,850 cell、NaN（tupleList の解析失敗）は 1,437,754 cell。backend はどちらも None。
- 同じ 3 次メッシュの XML が複数あると先に結合した方が残る。入力は `Path.glob('*.xml')` の順なので、
  DEM5A と DEM5B が重なると結果が file system の順序に依存する（再現性のリスク）。

## 修正方針（次 phase、要承認）

backend の再起動と PSEUDO の再生成が必要なため、この phase では実施しない。

1. **推奨: DEM を正しい配置に並べ替えた artifact を作る。** 画素値は変えず、tile の配置だけを戻した
   通常の north-up・lon/lat の GeoTIFF（画素 1/18000°、nodata = -9999、原本の無い tile は nodata）を
   build node で作り、正式 pipeline で publish する。`ElevationService` は通常の GeoTIFF をそのまま読める。
   PSEUDO generator の「軸入れ替わり補正」は新しい artifact では発動しないことを確認したうえで PSEUDO・tile を再生成する。
2. 代替: `ElevationService` に convert_dem 配置の読み方（`fgd_mosaic_rowcol`）を実装する。artifact は変えずに済むが、
   双線形補間で tile 境界をまたぐ扱いが必要で、PSEUDO generator にも同じ修正が要る。
3. `convert_dem.py` 自体も修正する（lowerCorner / upperCorner を緯度経度として解釈し、nodata を設定し、
   入力の結合順を固定する）。

修正までの安全側の扱い（案）: `/api/evacuation` の候補判定で標高差が判定に効く場合に warning を返す、
または DEM 由来の標高判定を degraded として表示する。いずれも backend の再起動が必要なので、
修正 phase と同時に入れるのが現実的。

## 公式原本 zip の要否

この監査の結論（値は DEM5A と一致し、誤りは読み取り位置）には公式原本 zip は不要。
source provenance を確定する目的では引き続き必要（基盤地図情報 数値標高モデル 5m・1 次メッシュ 5339 の
全 3 次メッシュ、DEM5A を優先し欠ける tile は DEM5B / 5C。取得後 convert_dem 修正版で再変換して比較する）。
