# Hazard Capability Matrix

## Phase 4 時点の対応状況

---

## ハザード種別対応マトリクス

| ハザード | 表示名 | enabled | polygon | TTI | RSA | データ形式 | 状態 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `flood` | 洪水浸水想定 | ✅ | ✅ | ❌ | ❌ | GeoJSONL | 実装済み |
| `storm_surge` | 高潮浸水想定 | ✅ | ✅ | ❌ | ❌ | GeoJSON | 実装済み |
| `tsunami` | 津波浸水想定 | ✅ | ✅ | ✅ (v1) | ✅ | GeoJSON (dir) | 実装済み |
| `inland_flood` | 内水氾濫 | ✅ | ✅ | ❌ | ❌ | GeoJSON | Phase4 |
| `landslide` | 土砂災害 | ✅ | ✅ | ❌ | ❌ | GeoJSON | Phase4 |

---

## 凡例

| 記号 | 意味 |
| --- | --- |
| ✅ | 実装済み・有効 |
| ❌ | 未実装 / 無効 |
| ✅ (v1) | v1 実装済み（近似実装、将来改善予定） |

---

## 各列の定義

| 列 | 定義 |
| --- | --- |
| **enabled** | `HazardDefinition.enabled` — ハザードが全体として有効か（backend + frontend 両方が有効な場合 True） |
| **polygon** | `capabilities["polygon_check"]` — ポリゴン内外判定が機能しているか |
| **TTI** | `capabilities["time_to_impact"]` — 到達時間計算が実装されているか |
| **RSA** | `capabilities["rsa_support"]` — 到達可能安全エリア計算に関与するか |
| **データ形式** | backend が読み込むデータ形式 |

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
- **将来拡張**: 浸水深評価（severity）、タイル化（Phase 4.1）
- **データソース（予定）**: 自治体オープンデータ（浸水深別ポリゴン）

### landslide（土砂災害）

- **状態**: `enabled=True` / `backend_enabled=True` / `frontend_enabled=True`（Phase 4）
- **データ**: `landslide_sample.geojson`（サンプル）
  - 参照順位: `data_runtime/backend/hazard/landslide/` → `data_lake/normalized/tokyo/landslide/` → `data/hazard/`
  - 設定キー: `hazard.landslide.enabled` / `hazard.landslide.path`
- **属性**: `zone_type`（警戒区域 / 特別警戒区域）— 将来の危険度レベル分岐に使用予定
- **将来拡張**: 危険度レベル分岐、タイル化（Phase 4.1）
- **データソース（予定）**: 都道府県別土砂災害警戒区域データ

---

## TTI 対応ロードマップ

| ハザード | v1（現在） | v2（将来） |
| --- | --- | --- |
| tsunami | 重心距離近似 (`distance_based_estimation`) | 津波伝播シミュレーション |
| flood | 未対応 (`not_supported`) | 浸水タイムラインデータ連携 |
| storm_surge | 未対応 (`not_supported`) | 潮位予報データ連携 |
| inland_flood | 未対応 (`not_supported`) | 浸水深評価・タイムライン連携（Phase 4.1） |
| landslide | 未対応 (`not_supported`) | 危険度レベル分岐・降雨連携（Phase 4.1） |

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

## 参照先ドキュメント

- 設計詳細: [hazard_engine_design.md](hazard_engine_design.md)
- レイヤー戦略: [layer_strategy.md](layer_strategy.md)
- データポリシー: [runtime_data_policy.md](runtime_data_policy.md)
