# Hazard Capability Matrix

## Phase 5 時点の対応状況

---

## ハザード種別対応マトリクス

| layer | 表示名 | type | source | vector_tile | fallback | severity | status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `flood` | 洪水浸水想定 | polygon | `tokyo_flood_max` | ✅ | API | ✅ 浸水深ランク | active |
| `storm_surge` | 高潮浸水想定 | polygon | `tokyo_storm_surge` | ✅ | API | ✅ 浸水深ランク | active |
| `tsunami` | 津波浸水想定 | polygon | `tokyo_tsunami_A40-23_13` | ✅ | API | — | active |
| `inland_flood` | 内水氾濫 | polygon | `A51` | — | API | ✅ depth_min_m ランク | active |
| `landslide` | 土砂災害警戒区域 | polygon | `A33` | — | API | ✅ zone_type / severity_level | active |
| `lowland_poor_drainage` | 低地・排水困難エリア | polygon | DEM由来 | — | API | ✅ risk_score | active（supplementary、`is_danger`に非影響） |
| `pseudo_inland_flood` | 低地・内水リスク（推定） | polygon | DEM由来 | — | API | ✅ risk_level | **API/UI表示専用。navigation danger判定には未使用（意図的、後述）** |

---

## runtime publish 対応 hazard と navigation 判定対応 hazard は別集合

**重要（HAZARD-ENGINE-PSEUDO-INLAND-FLOOD-NOT-WIRED、2026-09 確定）**:
`data_runtime/current` へ atomic publish される hazard type の集合（現在 7 type:
`flood` / `storm_surge` / `tsunami` / `inland_flood` / `landslide` /
`lowland_poor_drainage` / `pseudo_inland_flood`）と、`HazardEngine`
（`backend/hazard_service.py`、避難経路の危険判定・`assess_candidate()`）が
navigation danger 判定に実際に使う hazard type の集合（現在 6 type:
`pseudo_inland_flood` を除く上記）は、**意図的に異なる集合**です。

これは bug でも「未対応・将来対応予定」でもありません。runtime へ publish
され API/UI から参照可能であることと、それを navigation の危険判定へ
使ってよいことは別の判断であり、後者は精度・provenance・既存 hazard との
重複を踏まえて個別に評価します（詳細は「pseudo_inland_flood」節参照）。

---

## 凡例

| 記号 | 意味 |
| --- | --- |
| ✅ | 実装済み・有効 |
| — | 未実装 / 対象外 |
| ✅ (v1) | v1 実装済み（近似実装、将来改善予定） |

---

## 各列の定義

| 列 | 定義 |
| --- | --- |
| **type** | ハザードのジオメトリ種別（polygon = ポリゴン内外判定） |
| **source** | MBTiles / GeoJSON のデータセット名（stem） |
| **vector_tile** | Martin ベクタータイル配信が有効か |
| **fallback** | タイル不在時の代替配信経路 |
| **severity** | 危険度（浸水深ランク / zone_type）の色分け表示が有効か |
| **status** | active = 本番稼働中 |

---

## Capability モデル（Phase 3.1 導入）

各ハザードは `HazardDefinition.capabilities` プロパティで能力マップを公開する。

```python
# tsunami の例
tsunami.capabilities
# → {
#     "polygon_check":  True,   # inside/outside 判定
#     "time_to_impact": True,   # TTI 計算
#     "rsa_support":    True,   # RSA 計算に関与
# }

# flood の例
flood.capabilities
# → {
#     "polygon_check":  True,
#     "time_to_impact": False,
#     "rsa_support":    False,
# }
```

capability は既存の個別フィールド（`has_polygon_check` 等）から導出されるため、
定義と実態が常に一致する。

---

## TTI 計算詳細

### TTIService（Phase 3.1 新規: `backend/services/tti_service.py`）

TTI 計算は `TTIService.compute_tti(hazard_name, lat, lon)` に統一。

返り値構造:

```json
{
  "supported": true,
  "computed": true,
  "minutes": 12.3,
  "reason": "distance_based_estimation"
}
```

### reason 一覧

| reason | 説明 |
| --- | --- |
| `distance_based_estimation` | 重心距離近似（tsunami v1）。computed=True |
| `not_in_hazard_zone` | 該当ハザードのポリゴン外またはデータなし。computed=False |
| `not_supported` | このハザードは TTI 未対応。computed=False |
| `time_margin_disabled` | `enable_time_margin=False` により無効化。computed=False |

---

## 各ハザードの補足

### flood（洪水浸水想定）

- **データ**: `tokyo_flood_check.geojsonl`（GeoJSONL 形式、数百 MB 規模）
- **backend 特記**: `bbox_only=True` モードで読み込み（メモリ削減）
- **TTI 未対応理由**: 洪水の浸水タイムラインはデータ整備が必要。Phase 3.x 以降。
- **制御**: `app.properties` の `hazard.flood.enabled` で ON/OFF 可能

### storm_surge（高潮浸水想定）

- **データ**: `tokyo_storm_surge.geojson`（東京都）
- **TTI 未対応理由**: 高潮の到達時間は潮位予報に依存し、現時点でデータなし。

### tsunami（津波浸水想定）

- **データ**: `tsunami_{region}.geojson`（tokyo / kanagawa / chiba）
- **TTI v1**: `TTIService._compute_tsunami()` が担当
  - 現在地が入る津波ポリゴンの重心までの距離 / 津波速度で近似
  - reason = `"distance_based_estimation"`
  - 精度は低め。将来的に津波伝播シミュレーション結果への置き換えを検討。
- **RSA**: `capabilities["rsa_support"] = True` → TTI computed 時に RSA 計算が走る
- **multi-region**: 複数都県ファイルを順次ロード（累積式）

### inland_flood（内水氾濫）

- **状態**: `enabled=True` / `backend_enabled=True` / `frontend_enabled=True`（Phase 4）
- **データ**: `inland_flood_sample.geojson`（サンプル）
  - 参照順位: `data_runtime/backend/hazard/inland_flood/` → `data_lake/normalized/tokyo/inland_flood/` → `data/hazard/`
  - 設定キー: `hazard.inland_flood.enabled` / `hazard.inland_flood.path`
- **Severity（危険度）表示**: 実装済み（Phase 4.1/4.2）— 浸水深ランクによる色分け・理由ブロック表示
- **タイル化**: 未実装（GeoJSON ポリゴン判定のまま）
- **データソース（予定）**: 自治体オープンデータ（浸水深別ポリゴン）

### landslide（土砂災害警戒区域）

- **状態**: `enabled=True` / `backend_enabled=True` / `frontend_enabled=True`（Phase 5）
- **データ**: 国土数値情報 A33（土砂災害警戒区域）
  - 正規化: `scripts/normalize/normalize_landslide.py`
  - 参照順位: `data_runtime/backend/hazard/landslide/`（atomic runtime lease機構による current/versioned 優先。is_available()==False 時の legacy flat basename fallback は HAZARD-LEGACY-FLAT-FALLBACK-CONTRACT 対応により廃止済み）
  - 設定キー: `hazard.landslide.enabled`
- **属性**:
  - `zone_type`: `warning`（警戒区域）/ `special_warning`（特別警戒区域）
  - `landslide_type`: `steep_slope`（急傾斜地の崩壊）/ `debris_flow`（土石流）/ `landslide`（地すべり）
  - `severity_level`: `danger`（warning）/ `critical`（special_warning）
- **API**: `GET /api/hazards/landslide/tokyo`
- **Severity（危険度）表示**: 実装済み（Phase 4.1/4.2）— zone_type / severity_level による色分け
- **タイル化**: 未実装（GeoJSON API 配信）
- **データ取得**: 国土数値情報ダウンロードサービス A33 → `data_lake/raw/tokyo/landslide/` に配置

### pseudo_inland_flood（低地・内水リスク〔推定〕）— navigation danger判定には未使用

**この hazard type は `HazardEngine`（navigation の危険判定エンジン）へ意図的に
wiring していません。「未対応」「実装漏れ」「将来対応予定」ではなく、確定した
設計判断です（HAZARD-ENGINE-PSEUDO-INLAND-FLOOD-NOT-WIRED、CLOSED /
INTENTIONALLY_NOT_WIRED）。**

- **データの性質**: `scripts/derive/generate_pseudo_inland_flood.py` が DEM
  （標高）から標高・傾斜・凹地の3要素を単純加算スコアリングして生成する
  **非公式の参考推定データ**。降雨量・排水能力・河川近接性など実際の内水
  氾濫メカニズムは一切考慮していない。
- **registry上の明示**: `data_lake/registry/dataset_definitions.json` の
  `TOKYO-PSEUDO-INLAND-FLOOD-001` に `official: false`,
  `source_type: "generated"` が明記され、`validate_pseudo_inland_flood.py`
  が `official is not False` を検証エラーとして強制する。
- **runtime/API での扱い**: `data_runtime/current`（Tokyo のみ）へ atomic
  publish され、meta/tile 経由で UI の参考表示に使われる。**public full-body
  GeoJSON response（`GET /api/hazards/pseudo_inland_flood/{region}`）は
  LARGE-HAZARD-FULL-BODY-POLICY Phase B1（2026-09-07）により提供しない
  （422、詳細は本ドキュメント末尾「Hazard Full-Body Delivery Policy」
  参照）。UI の参考表示自体（vector tile 経由）は変更しない。
- **navigation で使わない理由**:
  1. 実際の浸水挙動に基づかない地形ヒューリスティックであり、
     navigation safety 判定の根拠として不十分（false positive リスク）。
  2. `inland_flood`（公式ハザードマップ）と bbox が広範囲に重複しており、
     `HazardEngine.assess_candidate()` は hazard type ごとに独立した
     inside/outside 判定を返す設計（`derive_hazard_safe()` は「1件でも
     inside があれば危険」という OR 判定）のため、severity（risk_level）を
     反映しない単純追加は、DEM 推定で "low" 判定された区域（実測 66,565
     feature 中 77.9%）まで一律に危険扱いし、避難可能な候補地点を
     過剰に排除するリスクが高い。
- **Tokyo-only**: DEM データが Tokyo 分のみ用意されているための制約
  （Kanagawa 分の pseudo_inland_flood は存在せず、これは unsupported
  region であり error ではない）。
- **将来の再評価候補**: `lowland_poor_drainage`（`is_danger` に影響しない
  supplementary hazard として既に運用中）と同様の non-blocking signal
  として、severity（risk_level）を保持したまま将来 wiring する可能性は
  別途 `PSEUDO-INLAND-FLOOD-SUPPLEMENTARY-NAVIGATION-EVALUATION` として
  記録する（今回は未実装。実施する場合は OWNER の safety review が必須）。

### lowland_poor_drainage（低地・排水困難エリア）

- **状態**: `SUPPLEMENTARY_HAZARD_TYPES` に属する補助 hazard。
  `hazard_assessment` には現れるが `is_danger` の判定には影響しない
  （地形的リスクであり、単独では避難判断のトリガーにならない）。
- **API**: meta（`GET /api/hazards/lowland_poor_drainage/{region}/meta`）は
  引き続き利用可能。**public full-body GeoJSON response は
  LARGE-HAZARD-FULL-BODY-POLICY Phase B1（2026-09-07）により提供しない
  （422、詳細は本ドキュメント末尾「Hazard Full-Body Delivery Policy」
  参照）。

---

## TTI 対応ロードマップ

| ハザード | v1（現在） | v2（将来） |
| --- | --- | --- |
| tsunami | 重心距離近似 (`distance_based_estimation`) | 津波伝播シミュレーション |
| flood | 未対応 (`not_supported`) | 浸水タイムラインデータ連携 |
| storm_surge | 未対応 (`not_supported`) | 潮位予報データ連携 |
| inland_flood | 未対応 (`not_supported`) | 浸水深評価・タイムライン連携 |
| landslide | 未対応 (`not_supported`) | 降雨量連携・タイムライン |

---

## RSA との連携（Phase 3.1）

RSA は `TTIService.compute_tti()` の `computed=True` 時のみ実行する。

```python
tti_detail = hazard_engine.get_time_to_impact_detail(lat, lon)

if tti_detail["computed"]:
    RSA 実行 → rsa_result (status="computed")
else:
    RSA スキップ → rsa_result (status="skipped", reason=tti_detail["reason"])
```

RSA ログ:

```text
RSA generated: radius_m=NNN area_m2=NNN exists=True/False
RSA skipped: TTI not computed (reason=not_in_hazard_zone)
RSA skipped: TTI not computed (reason=time_margin_disabled)
RSA disabled: ENABLE_RSA=False
```

---

## /api/evacuation レスポンス（Phase 3.1 追加フィールド）

`time_to_impact` フィールドがトップレベルに追加された（非破壊）。

```json
{
  "hazard_status": { ... },
  "time_to_impact": {
    "supported": true,
    "computed": false,
    "minutes": null,
    "reason": "not_in_hazard_zone"
  },
  "reachable_safe_area": { ... },
  "destinations": [ ... ]
}
```

既存の `time_to_impact_minutes`（destinations 内）は後方互換のため維持。

---

## Hazard Full-Body Delivery Policy

`GET /api/hazards/{hazard_type}/{region_code}` は、hazard type によって
実装（response の生成方式）と提供可否が異なる。この乖離は type ごとの
場当たり対応の結果ではなく、LARGE-HAZARD-GEOJSON-SWAP-THRASH /
LARGE-HAZARD-FULL-BODY-POLICY（いずれも 2026-09-07）調査で確立した
capability-based（hybrid）policy に基づく意図的な contract である。

判定軸は次の4つ: frontend での必要性（primary / fallback / unused）・
vector tile 代替の有無・現行 artifact size・response 実装の安全性
（`json.load()` による全体展開か、`StreamingResponse`/`FileResponse` か）。

| hazard type | policy | HTTP status | 理由 |
| --- | --- | --- | --- |
| `flood` | **REJECT_PUBLIC** | 413 | artifact が破滅的に巨大（tokyo≈500MB / kanagawa≈310MB）。frontend は tile primary で fallback 不要 |
| `pseudo_inland_flood` | **REJECT_PUBLIC** | 422 | frontend が full-body route を一切呼ばない（`apiUrl` 未設定）。tile 完備、サイズは理由ではない |
| `lowland_poor_drainage` | **REJECT_PUBLIC** | 422 | 同上 |
| `storm_surge` | **FALLBACK_ONLY**（`ALLOW_JSON` 現状維持） | 200 | frontend は tile primary、tile/Martin 不到達時のみ実際に使われる fallback |
| `tsunami` | **FALLBACK_ONLY**（`ALLOW_JSON` 現状維持） | 200 | frontend は tile-first（`useStaticVectorTiles`）、fallback は tile 失敗時のみ |
| `inland_flood` | **ALLOW_STREAM** / frontend primary | 200（streaming） | tile は存在するが frontend が意図的に API を primary として使用（`preferApi: true`）。既に memory-safe |
| `landslide` | **ALLOW_STREAM** / frontend primary | 200（streaming） | tile infrastructure が存在しない唯一の type。既に memory-safe |

**REJECT_PUBLIC の理由は type によって異なり、HTTP status/detail も区別する**:
`flood`（413、`_HAZARD_LARGE_RESPONSE_DETAIL`）は artifact size が理由。
`pseudo_inland_flood`/`lowland_poor_drainage`（422、
`_HAZARD_POLICY_REJECTED_DETAIL`）は frontend が使わないという
delivery-policy 上の理由であり、size が理由ではない
（`lowland_poor_drainage` は約 25MB と比較的小さい）。413 の意味的な
機械流用はしていない。

いずれの REJECT_PUBLIC でも、`/meta` エンドポイントは引き続き利用可能
（`dataset_id`/`tileset_id`/`tileset_source_layer` 等を返す）。存在しない
region（例: `pseudo_inland_flood:kanagawa`）は従来通り 404 のまま
区別される。

`storm_surge`/`tsunami` の fallback path は現状 `json.load()` +
`JSONResponse` 実装のまま（LARGE-HAZARD-FULL-BODY-POLICY Phase A で
memory-unsafe と確認済み）——streaming 化は将来の hardening 候補
（`LARGE-HAZARD-FULL-BODY-POLICY` finding、OPEN のまま）であり、
今回のスコープには含まれない。

---

## 参照先ドキュメント

- 設計詳細: [hazard_engine_design.md](hazard_engine_design.md)
- レイヤー戦略: [layer_strategy.md](layer_strategy.md)
- データポリシー: [runtime_data_policy.md](runtime_data_policy.md)
