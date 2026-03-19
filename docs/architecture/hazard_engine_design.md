# Hazard Engine 設計書

**Phase 3 時点の設計**

---

## 概要

Phase 3 では、ハザード種別ごとの個別実装（`if flood: ... if tsunami: ...`）から脱却し、
拡張可能なハザード抽象化構造へ移行した。

中心となるのは 3 つのコンポーネントの責務分離:

| コンポーネント | 責務 |
| --- | --- |
| `hazard_definitions.py` | ハザードの性質・対応状況の定義 |
| `hazard_engine.py` | 評価オーケストレーション (TTI / RSA 連携含む) |
| `hazard_service.py` | ポリゴン保持・点判定の低レベルサービス |

---

## コンポーネント別の責務

### hazard_definitions.py — ハザードの性質定義

各ハザード種別の「性質」をコード外の知識として一元管理する。

```python
HazardDefinition(
    name="tsunami",
    display_name="津波浸水想定",
    backend_enabled=True,
    frontend_enabled=True,
    has_polygon_check=True,
    has_time_to_impact=True,   # TTI v1 実装済み
    supports_rsa=True,         # RSA に関与
    source_type="geojson_dir",
    evaluation_mode="inside_outside",
)
```

**ここに追加するだけで新ハザードに対応できる情報:**
- `has_polygon_check`: backend の inside/outside 判定が実装されているか
- `has_time_to_impact`: TTI（到達時間）計算が実装されているか
- `supports_rsa`: RSA（到達可能安全エリア）計算に関与するか
- `frontend_enabled`: frontend レイヤー表示が実装されているか

### hazard_engine.py — 評価オーケストレーション

HazardService をラップし、higher-level な評価インターフェースを提供する。

**主要メソッド:**

| メソッド | 用途 |
| --- | --- |
| `evaluate_point(lat, lon)` | 現在地のハザード判定（`/api/hazard-check` 向け） |
| `evaluate_destination(lat, lon)` | 候補地の安全性評価（`/api/evacuation` 向け） |
| `get_time_to_impact(lat, lon)` | TTI 計算（現在は tsunami のみ） |
| `build_assessment_summary(lat, lon, tti)` | 内部共通評価形式でサマリーを生成 |
| `get_rsa_supporting_hazards()` | RSA に関与するハザード名リスト |
| `get_tti_supporting_hazards()` | TTI 対応ハザード名リスト |

### hazard_service.py — 低レベルサービス

ポリゴンデータの保持と点判定のみを担う。Phase 3 では変更なし。

- `load()`, `load_geojsonl()`, `load_dir()`: データロード
- `check_point()`, `assess_candidate()`: 点判定
- `get_tsunami_centroid_distance_m()`: TTI 計算入力（距離）

### main.py — オーケストレーター

Phase 3 以降、main.py からハザード固有知識を排除する方向で整理している。

**Phase 3 で main.py から除去したもの:**
- `_calc_tti_minutes()` 関数 → `hazard_engine.get_time_to_impact()` に移管

**main.py に残っているもの（Phase 3 時点）:**
- ハザードデータのロード処理（`resolve_existing_path` を使うため、config 依存）
- `ENABLE_TIME_MARGIN`, `TSUNAMI_SPEED_KMH` などの設定値
- HazardEngine の初期化

---

## 評価フロー

### /api/hazard-check

```
リクエスト (lat, lon)
  → hazard_engine.evaluate_point(lat, lon)
    → hazard_service.check_hazards()    # is_danger, hazards
    → hazard_service.assess_candidate() # {"flood": "inside", ...}
  → レスポンス: {is_danger, hazards, hazard_assessment}
```

### /api/evacuation

```
リクエスト (lat, lon, ...)
  → hazard_engine.evaluate_point(lat, lon)    # 現在地判定
  → hazard_engine.get_time_to_impact(lat, lon) # TTI (tsunami)
  → search_shelter_destinations(...)
    → hazard_service.assess_candidate()         # 各候補地の判定
    → derive_hazard_safe()                      # hazard_safe 決定
  → _calc_rsa() (TTI あり時)
    → hazard_engine.get_polygon_store()         # RSA 計算用ポリゴン
  → レスポンス: {hazard_status, recommended, reachable_safe_area, ...}
```

---

## TTI / RSA / assessment の関係

```
TTI (time_to_impact_minutes)
  ├── 計算対象: tsunami のみ (v1)
  ├── 計算方法: 現在地が入る津波ポリゴンの重心までの距離 / 津波速度
  └── RSA の入力: TTI から到達可能半径を計算 (radius_m = speed_mps × tti_min × 60)

RSA (reachable_safe_area)
  ├── 前提条件: TTI が算出できること (tsunami ポリゴン内 + ENABLE_TIME_MARGIN=True)
  ├── 計算: 到達可能円 - ハザードポリゴン = 安全に到達できるエリア
  └── status: "computed" | "skipped" | "disabled"

hazard_assessment
  ├── 各ハザード種別ごとに "inside" | "outside" | "unknown" を返す
  ├── derive_hazard_safe() で hazard_safe (bool | None) に集約
  └── API レスポンス: {"flood": "outside", "tsunami": "inside", ...}
```

---

## 将来のハザード追加方針

### 新ハザード追加の手順

1. **`hazard_definitions.py`** に `HazardDefinition` を追加する
2. **`main.py`** のデータロード処理に読み込みコードを追加する
3. **TTI が必要なら** `hazard_engine.get_time_to_impact()` を拡張する
4. **RSA が必要なら** `supports_rsa=True` に設定する（自動的に RSA 計算に含まれる）
5. **frontend 表示** は `frontend/js/config.js` の `HAZARD_LAYERS` / `VECTOR_TILE_SOURCES` に追加する

### inland_flood（内水氾濫）の場合

```python
HazardDefinition(
    name="inland_flood",
    has_polygon_check=True,       # ← True に変更
    has_time_to_impact=False,     # 当面 TTI なし
    supports_rsa=False,
    source_type="geojson",
    evaluation_mode="inside_outside",
)
```

その後、main.py のロード処理に `hazard_service.load("inland_flood", path)` を追加する。
評価ロジックは `HazardEngine` および `HazardService` の変更なしで自動的に対応する。

### landslide（土砂災害）の場合

evaluation_mode が異なる可能性（警戒区域の段階評価など）。
その場合は `HazardService.assess_candidate()` の拡張が必要になる見込み。

---

## ファイル構成

```
backend/
├── hazard_definitions.py  # [Phase 3 新規] ハザード種別定義
├── hazard_engine.py       # [Phase 3 新規] 評価エンジン
├── hazard_service.py      # [既存] 低レベルポリゴン判定
├── geometry_utils.py      # [既存] RSA 計算 (shapely/pyproj)
└── main.py                # [Phase 3 更新] オーケストレーター
```
