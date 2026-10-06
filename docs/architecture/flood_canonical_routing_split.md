# 洪水データ: canonical / routing artifact 分離（正式契約）

状態: 実装済み・未 publish（2026-10-05）。local candidate の生成と検証まで完了。
runtime publish / production 反映は OWNER 承認後に初回 migration で行う（§6）。

## 1. 背景

| 問題 | 実測 |
|---|---|
| 旧 normalizer が穴あき Polygon（`gml:OrientableCurve` 経由）を捨てていた | 2024/2025 とも A31a 3,361 件・A31b 14,560 件が欠落 |
| production（A31a-24 + A31b-24, 925,958 件）の strict PIP 被覆 | 東京都本土陸域の 7.5%（穴復元後の真値は 28.3%） |
| production + HazardEngine（外環 bbox + 0.000225° バッファ） | 真値浸水域の **40.4% が OUT（false negative）** |
| 穴を復元した canonical をそのまま bbox 判定 | 最大 bbox 535 km²、都陸域の 67% が IN |

HazardEngine の flood 判定は bbox 専用（`load_geojson_streaming(..., bbox_only=True)`、穴無視）のため、
公式形状を保持するデータと判定用データを分離する。

## 2. 入力データ（Tokyo flood 最小構成）

| ファイル | 内容 |
|---|---|
| `A31a-25_13_10_GML.zip` / `A31a-25_13_20_GML.zip` | 河川単位・東京都管理河川（river_name/river_number あり） |
| `A31b-25_10_5339_GML.zip` / `A31b-25_20_5339_GML.zip` | 1次メッシュ 5339・全管理者統合。**国管理河川（荒川・多摩川・江戸川等）を含む唯一の入力** |

取得元: https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A31b-2025.html（2026年5月公開）。
メッシュ 5338 の都内部分は上記で 100% カバー済みのため不要。

## 3. データ契約

| 成果物 | パス | 用途 |
|---|---|---|
| canonical | `data_lake/validated/{region}/flood/{dataset}.geojson` | 表示（tile build）・検証・将来の strict PIP。穴保持 |
| routing artifact | `data_lake/derived/{region}/flood/{dataset}.routing.geojson` | HazardEngine 判定専用（矩形 Polygon のみ） |
| routing meta | `data_lake/derived/{region}/flood/{dataset}.routing.meta.json` | provenance |
| runtime | `backend/hazard/flood/{region}/{dataset}.routing.geojson` | **flood は routing のみ。canonical は置かない** |

routing / meta パスは canonical パスから一意に導く（最後の `validated` 要素 → `derived`）。
契約の実装: `backend/app/services/flood_routing_contract.py`。

### routing meta（必須項目）

`contract`(=`flood_routing/v1`), `dataset_id`, `source_canonical_path`, `source_canonical_sha256`,
`routing_artifact_sha256`, `builder_name`, `builder_version`, `tau`, `min_split_size`, `feature_count`(>0),
`generated_at`。ほか `source_feature_count`, `tile_size`, `output_bytes`, `clip_fallbacks`, `build_seconds`。

publish 可否は state のフラグではなく毎回ファイル実体で判定する:
routing / meta が存在し、`sha256(canonical) == source_canonical_sha256` かつ
`sha256(routing) == routing_artifact_sha256` であること（`verify_routing_for_canonical`）。

## 4. 生成（`scripts/derive/build_flood_routing_artifact.py`、builder 1.1.0）

既定値: `tau=0.85`, `min_split_size=0.0002°`（≈20m）, `tile_size=0.02°`。

1. pass1: canonical を 1 feature ずつ読み、tile ごとに clip した断片を一時 JSONL バケットへ（全件をメモリに載せない）。
   同時に canonical の sha256 を計算する。
2. pass2: tile を座標の数値順に処理し、断片を union → 「面積/bbox 面積 ≥ tau」または「長辺 ≤ min_split_size」
   まで長辺方向に二分割。
3. 断片の bbox を矩形として出力。flood_rank は断片に交差する canonical の最大値（安全側に上振れしうる）。

false negative を作らない仕組み:

- clip は厳密 overlay（`shapely.intersection`）。`shapely.clip_by_rect` は使わない
  （dirty clip で、実データで小ポリゴン 21 件〈東京〉/7 件〈神奈川〉を落とした。routing validation で検出）。
- clip が失敗、または分割前後で面積が保存されない場合は分割せず元断片の bbox を出力（安全側）。
- build 前後で canonical の sha256 が変わったら失敗。

書き込み: 作業 dir と一時出力は出力先と同じ dir に作り、成功・失敗を問わず削除。routing → meta の順に
`os.replace`。失敗時は既存 derived artifact を変更しない。同じ入力・設定から同一バイト列を生成（決定的）。

## 5. pipeline（`backend/app/services/pipeline_service.py`）

```
ingest → normalize → validate（canonical）
       → derive_routing（build_flood_routing_artifact.py）
       → validate_routing（validate_flood_routing_artifact.py）   ← flood のみ
       → deployable
反映（run_deploy）: routing 契約を検証 → routing artifact を runtime_path へコピー → tile build（canonical から）
atomic publish（deploy_to_runtime_atomic.sh）: resolver が flood は routing を解決 → staging 検証 → activate
```

- derive / routing validation 失敗 → job failed（`ROUTING_DERIVE_FAILED` / `ROUTING_VALIDATION_FAILED`）、
  deployable にしない。
- 反映時に routing が無い・canonical と不一致 → `DEPLOY_BLOCKED_ROUTING_CONTRACT` で中止（runtime 無変更）。
- routing validation: 契約（sha256）、構造（閉じた軸平行矩形・flood_rank 1-5・件数 = meta）、
  被覆（canonical 全 Polygon の内部点がいずれかの bbox に含まれる = FN 実地検査）。

## 6. runtime publish 契約と初回 migration

resolver（`scripts/publish/resolve_hazard_sources.py`）: flood は validated canonical ではなく、
契約検証済みの routing artifact を返す。不成立は fail-closed。他 hazard type は変更なし。

HazardEngine（`backend/app_public.py`）: `discover_flood_routing_files()` で `*.routing.geojson` のみロード。
canonical / legacy は ERROR ログを出してロードしない。

staging 検証（`runtime_dataset_validate.py`）:

- `backend/hazard/flood/<region>/` には `*.routing.geojson` のみ許可。canonical `*.geojson`・
  legacy `*_flood_check.geojsonl`・flood 直下 file・空 region・routing 0 件・件数 floor（100）未満は reject。
- 件数 guard（50% 未満への減少、rel path 消失）は routing にもそのまま適用。

初回 migration（legacy `…/tokyo-river-001.geojson` → `…/tokyo-river-001.routing.geojson`）:

```
scripts/publish/deploy_to_runtime_atomic.sh --region tokyo --region kanagawa \
    --allow-flood-routing-migration "<OWNER 承認の参照>"
```

- 承認参照（文字列）必須。`activate_version.py --allow-flood-routing-migration --owner-approval-ref` に渡り、
  manifest の `migrations` に記録される。
- 例外にできるのは「前 version に存在した legacy flood rel の消失」だけで、同じ region に routing artifact が
  ある場合に限る。他 dataset の消失・件数減少 guard は変わらない。
- 前 version に legacy flood が無い（移行済み）・前 version が無い・rollback では flag 自体を拒否 → 一度きり。
- 移行後に移行前 version へ rollback すると、HazardEngine は canonical を読まないため flood 判定が無効になる
  （ERROR ログ）。rollback する場合は flood 判定が外れることを前提に判断すること。

## 6.1 管理画面「反映」と atomic publish（2026-10-06）

管理画面の反映（`pipeline_service.run_deploy`）は、以下の layer_type について正式 atomic publish
（`deploy_to_runtime_atomic.sh`）を起動する。data_runtime の flat path へは書かない。

| 区分 | layer_type | 管理画面反映 |
|---|---|---|
| A. atomic publish | flood / storm_surge / pseudo_inland_flood | wrapper（resolver が registry から当該 dataset を解決） |
| B. 従来経路（後続課題） | tsunami / inland_flood / landslide / lowland_poor_drainage | wrapper が registry ではなく固定 path から publish（lowland は publish 処理なし）のため対象外 |
| B. 従来経路 | OSM / tide / shelter / DEM / railway 等 | 変更なし |

- publish 対象 region は active mapping の全 region（staging は current を種に region を積み上げるため）。
- 成功条件: wrapper exit 0（4 = tile mirror 警告も可）＋ current が新 version を指す＋ manifest 存在
  ＋（migration 時）manifest.migrations に承認参照＋ 新 version に当該 artifact（flood は derived routing と sha256 一致）。
  ここまで deployed にしない。`current_runtime_path` は `data_runtime/versions/<id>/backend/hazard/...` の実 artifact。
- 失敗時: deploy_status=failed、job は具体的エラーコード（`ATOMIC_PUBLISH_FAILED` / `..._DURABILITY_UNKNOWN` /
  `..._NOT_ACTIVATED` / `..._MIGRATION_NOT_RECORDED` / `..._ARTIFACT_MISSING` 等）。current は wrapper が変更しない。
- atomic 対象の「戻す」は無効（`ROLLBACK_ATOMIC_PUBLISH_MANAGED`）。version の rollback は operator CLI。
- state: atomic 対象は current version の artifact で deploy 状態を判定。旧 flat copy の deployed は stale として再推定
  （backend-public から読めない flat path を stat しない）。
- `deploy_to_runtime.sh` は flood の routing を置く前に、staging 内の当該 region の旧 flood
  （`flood/<region>/`、flood 直下の `<region>_*` / `<region>-*`）を除去する（`purge_flood_runtime_for_region`）。

API:

- `GET /api/admin/datasets/{id}/publish-status` → `publish_mode`, `current_version`,
  `flood_routing_migration_required`, `migration_allowed_for_dataset`, `legacy_flood_files`
- `POST /api/admin/datasets/{id}/deploy` body（任意）:
  `{"allow_flood_routing_migration": true, "owner_approval_ref": "<3〜200文字>"}`。
  旧 flood が残る間の通常反映（flood 以外の atomic 対象も）は `FLOOD_ROUTING_MIGRATION_REQUIRED`、
  承認参照なしは `FLOOD_ROUTING_MIGRATION_APPROVAL_REQUIRED`、移行済み・flood 以外での指定は
  `FLOOD_ROUTING_MIGRATION_NOT_APPLICABLE`。通常反映では flag を付与しない。

UI: 反映モーダルが publish-status を取得し、移行が必要な flood では警告・旧形式一覧・承認参照入力・確認チェックと
「初回移行として反映」ボタン（通常の「反映する」は非表示）を出す。

## 7. 判定仕様（近傍バッファ）

HazardEngine は bbox に 0.000225°（≈25m）の近傍バッファを加えて判定する（既存仕様、変更なし）。
したがって canonical の浸水想定区域から約 25m 以内の地点は IN になりうる。
例: 八王子駅は canonical から 22m のため IN（strict PIP では区域外）。これはバッファ契約による仕様どおりの挙動。

## 8. local candidate 検証結果（2026-10-05）

canonical 2025（A31a-25 + A31b-25_5339）: 947,590 features、未解決 0、validator PASS。

| 方式（東京都本土陸域 709,952 点・50m grid、基準 = canonical strict PIP、真値 IN 28.3%） | IN 率 | FN | FP | FP 50m 超 | bbox | サイズ | ロード |
|---|---|---|---|---|---|---|---|
| production + bbox | 37.3% | 40.44% | 28.50% | 13.46% | 925,958 | 524MB | 13.2s |
| **routing（τ=0.85, builder 1.1.0）+ bbox** | 49.4% | **0** | 29.40% | **11.97%** | 822,693 | 254MB | 3.9s |

- routing validation（全 Polygon 内部点の被覆検査）: 東京 FN 0、神奈川 FN 0。
- build: 東京 約 5.8 分 / peak RSS 約 320MB、神奈川 約 2.6 分 / 約 67MB。routing validation: 33s / 391MB。
- 決定性: 東京を 2 回 build して routing はバイト一致。

## 9. 既知の制約・後続課題

- 神奈川（KANAGAWA-RIVER-001）の canonical は旧 normalizer 出力（穴あき欠落あり）。routing は現行
  canonical から生成しており現行と同等の被覆。神奈川の再正規化（A31a-25_14 + 該当 A31b メッシュ）は別タスク。
- routing の flood_rank は矩形内最大値で上振れする（例: 和泉多摩川駅 真値 2 → 4）。判定は二値のため影響なし。
- staging 検証は既存仕様どおり GeoJSON を `json.load` で全量読む（routing 254MB は現行 canonical 524MB より軽い）。
- legacy: `scripts/normalize/filter_flood_hazard.py` と `*_flood_check.geojsonl` はコードから未使用。
  docs（VPS-README.md, DATA_REQUIREMENTS.md, docs/data-setup.md, scripts/README.md, backend/app.properties の
  コメント）が手順として参照しているため、docs 更新と同時に削除する（今回は残置）。
