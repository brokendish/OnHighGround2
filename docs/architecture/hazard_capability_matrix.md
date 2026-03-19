# Hazard Capability Matrix

**Phase 3 時点の対応状況**

---

## ハザード種別対応マトリクス

| ハザード | 表示名 | backend 判定 | frontend 表示 | TTI | RSA | データ形式 | 状態 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `flood` | 洪水浸水想定 | ✅ | ✅ | ❌ | ❌ | GeoJSONL | 実装済み |
| `storm_surge` | 高潮浸水想定 | ✅ | ✅ | ❌ | ❌ | GeoJSON | 実装済み |
| `tsunami` | 津波浸水想定 | ✅ | ✅ | ✅ (v1) | ✅ | GeoJSON (dir) | 実装済み |
| `inland_flood` | 内水氾濫想定 | ❌ | ❌ | ❌ | ❌ | GeoJSON | 計画中 |
| `landslide` | 土砂災害警戒区域 | ❌ | ❌ | ❌ | ❌ | GeoJSON | 計画中 |

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
| **backend 判定** | `HazardService` でポリゴン内外判定が機能しているか |
| **frontend 表示** | フロントエンドでハザードレイヤーが表示されるか |
| **TTI** | Time to Impact（到達時間）計算が実装されているか |
| **RSA** | Reachable Safe Area（到達可能安全エリア）に関与するか |
| **データ形式** | backend が読み込むデータ形式 |

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
- **TTI v1**: 現在地が入る津波ポリゴンの重心までの距離 / 津波速度で近似
  - 精度は低め。将来的に津波伝播シミュレーション結果への置き換えを検討。
- **RSA**: TTI が算出できた場合のみ RSA を計算。`supports_rsa=True`。
- **multi-region**: 複数都県ファイルを順次ロード（累積式）

### inland_flood（内水氾濫想定）

- **状態**: `backend_enabled=False` / `frontend_enabled=False`
- **整備条件**: 国土地理院または各自治体の内水氾濫想定 GeoJSON の整備
- **追加方法**: `hazard_definitions.py` の `backend_enabled=True` に変更 + main.py にロード追加

### landslide（土砂災害警戒区域）

- **状態**: `backend_enabled=False` / `frontend_enabled=False`
- **整備条件**: 都道府県別の土砂災害警戒区域データの整備
- **注意**: 評価方式が警戒区域の段階（特別警戒 / 警戒）を区別する必要があるため、
  `HazardService.assess_candidate()` の拡張が必要になる見込み

---

## TTI 対応ロードマップ

| ハザード | v1（現在） | v2（将来） |
| --- | --- | --- |
| tsunami | 重心距離近似 | 津波伝播シミュレーション |
| flood | 未対応 | 浸水タイムラインデータ連携 |
| storm_surge | 未対応 | 潮位予報データ連携 |

---

## 参照先ドキュメント

- 設計詳細: [hazard_engine_design.md](hazard_engine_design.md)
- レイヤー戦略: [layer_strategy.md](layer_strategy.md)
- データポリシー: [runtime_data_policy.md](runtime_data_policy.md)
