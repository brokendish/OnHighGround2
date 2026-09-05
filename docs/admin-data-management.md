# データ管理画面 運用ガイド

このドキュメントは、operator 向けデータ管理画面（`/admin/datasets`）の目的・アクセス方法・
用語・基本操作を説明する運用ガイドです。信頼境界（trust boundary）自体の設計は
[Operator セットアップ](operator-setup.md) を参照してください。本ガイドは日常運用の手順に
限定します。

## 1. 目的

データ管理画面は、OnHighGround2 が扱う地理データ（ハザード・避難所・DEM・OSM・鉄道等）の
**取り込み（ingest）・正規化（normalize）・検証（validate）状態を追跡・操作する**ための
operator 専用画面です。

**管理画面が担当しない範囲**: `data_runtime/current` への実際の反映（atomic publish）は
管理画面からは行いません。publish は `scripts/publish/deploy_to_runtime_atomic.sh` を
operator コンテナ内で実行する、別の CLI ワークフローです（4節参照）。この分離は意図的な
設計であり、「validated なデータを揃える」ことと「それを runtime へ反映する」ことを別の
承認・実行ステップとして扱うためです。

## 2. アクセス方法

管理画面は **public backend からは到達できません**。`docker-compose.yml` の
`--profile operator` を明示的に有効化した場合にのみ起動する `backend-operator` /
`operator-gateway` 経由でアクセスします。

```bash
docker compose --profile operator up -d
```

`operator-gateway` は loopback（`127.0.0.1`）限定の host publish のみを行います
（既定 `http://127.0.0.1:18100`）。VPS 上で外部からアクセスする場合は、SSH ポートフォワード等
loopback を経由する手段を使い、**public 側の `/admin` パスを復活させたり、operator の
host publish を `0.0.0.0` へ広げたりしないでください**（[Operator セットアップ](operator-setup.md)
参照）。

認証は `OPERATOR_AUTH_SECRET`（`.env.operator`）で保護されています。未設定・空文字の場合、
`backend-operator` は起動時検証で fail-closed し起動しません。

## 3. 用語

| 用語 | 意味 |
| --- | --- |
| dataset | 1つの地理データセット（例: 東京都の洪水浸水想定区域）。`dataset_id` で一意に識別 |
| dataset_id | registry 上の識別子（例: `TOKYO-RIVER-001`）。**配信 artifact のファイル名や Martin の tileset ID とは別概念**（後述） |
| layer_type | データセットの種別（`flood`, `storm_surge`, `tsunami`, `landslide`, `inland_flood`, `pseudo_inland_flood`, `lowland_poor_drainage`, `shelter`, `evacuation_shelter`, `emergency_shelter`, `admin_boundary` 等） |
| active / active mapping | ある `layer_type` × `region` の組み合わせに対して「現在配信すべきdataset」として指定すること。`data_lake/admin/active_mappings.json` に永続化される |
| validated | 正規化・検証を通過し、publish 可能な状態のデータ（`data_lake/validated/<region>/<type>/` 配下） |
| deployable | `DatasetState.deploy_status` の値の1つ。validated artifact が存在し、publish 可能であることを示す（**atomic publish が実際に行われたかどうかとは独立**——後述の注意事項参照） |
| runtime | `data_runtime/` 配下、backend/Martin が実際に読み込む配備先 |
| atomic publish | `data_runtime/current` を新しい version へ無停止で切り替える正式な反映手順。`deploy_to_runtime_atomic.sh` が実行する |
| current | `data_runtime/current` シンボリックリンク。今読まれるべき version を指す |
| tile | Martin が配信する vector tile（`.mbtiles`）。**`dataset_id` とは独立に、`data_lake/tiles/<region>/<type>/*.mbtiles` の実ファイル名が Martin の tileset ID になる**（5節参照） |
| registry | `data_lake/registry/dataset_definitions.json`（データセットの静的定義）と `data_lake/admin/active_mappings.json`（どれが active か）の総称 |

## 4. 初回登録

新しいデータセットを登録する場合、`data_lake/registry/dataset_definitions.json` へ
定義を追加します（現状、管理画面からの新規定義作成 UI は無く、この JSON ファイルを
直接編集します）。最低限必要なフィールド:

- `dataset_id`（一意な識別子）
- `region`、`category`、`display_name`
- `layer_type`（3節の用語表を参照。避難所系は必ず `shelter` / `evacuation_shelter` /
  `emergency_shelter` のいずれかにすること——`backend/app/services/shelter_service.
  SHELTER_LAYER_TYPES` と一致しない値を使うと atomic publish 対象から漏れる）
- `validated_storage_path`（validated 成果物の格納先ディレクトリ）
- `runtime_path`（legacy fallback 用。atomic publish が正常動作している環境では
  ほぼ参照されない）
- 取り込み方法（`accepted_input_modes`）、必要な正規化・検証の有無

登録後、管理画面（`/admin/datasets`）で該当データセットが一覧に表示されることを確認します。

## 5. active 化

「active mapping」とは、ある `layer_type:region` の組み合わせについて「今どの dataset_id を
使うか」を指定する設定です（`data_lake/admin/active_mappings.json`）。

- 管理画面の該当データセット詳細から「active に設定」操作を行うか、
  `PUT /api/admin/active-mappings/{layer_type}/{region}` を直接呼びます。
- **active mapping は atomic publish の対象選択には使われないケースがある点に注意**:
  - 避難所系（`shelter`/`evacuation_shelter`/`emergency_shelter`）は、
    `scripts/publish/resolve_shelter_sources.py` が active_mappings を参照して動的に
    publish 対象を決定します（正しく active 化すれば自動的に反映される）。
  - hazard 系の vector tile（Martin）は、active mapping・`dataset_id` とは無関係に、
    `data_lake/tiles/<region>/<type>/*.mbtiles` の実ファイルの有無だけで Martin の
    配信可否が決まります（`GET /api/hazards/<type>/<region>/meta` の `tileset_id` が
    この実体を動的に解決して返します）。active mapping を切り替えても、対応する tile
    ファイル自体を用意しない限り vector tile 配信は変わりません。
  - hazard 系の GeoJSON API（flood・storm_surge 等の fallback、pseudo_inland_flood・
    lowland_poor_drainage の tile-only 配信を除く）は active mapping を経由します
    （`HazardDatasetService`）。

## 6. データ更新

新しいデータを投入する場合の分担:

```text
取得（ingest: upload / fetch_url / fetch_official）   ← 管理画面 or scripts/download/
        ↓
正規化（normalize）                                    ← 管理画面のjob or scripts/normalize/
        ↓
検証（validate）                                        ← 管理画面のjob or scripts/validate/
        ↓
active化（該当する場合）                                ← 管理画面 or active_mappings.json編集
        ↓
─────────────────────── ここまでが管理画面の担当範囲 ───────────────────────
        ↓
atomic publish（current への反映）                      ← operator CLI（deploy_to_runtime_atomic.sh）
        ↓
runtime（backend/Martinが実際に読む状態）
```

**「validated になった」＝「runtime に反映された」ではありません。** validated な
データセットが `deployable` と表示されていても、`data_runtime/current` へ反映するには
別途 `scripts/publish/deploy_to_runtime_atomic.sh --region <region>` を operator コンテナ内で
実行する必要があります（手順は [VPS 起動/再構築チェックリスト](checklists/vps_startup_checklist.md)
の 4.5 節、または [データ準備](data-setup.md) を参照）。

## 7. 正常確認

データ更新・publish 後、以下を順に確認します（すべて read-only な GET/確認コマンドですが、
一部の GET は初回呼び出し時にのみ内部状態を再計算して保存する副作用があります——8節参照）。

1. **registry**: `data_lake/registry/dataset_definitions.json` に定義が存在するか
2. **active mapping**: `data_lake/admin/active_mappings.json` に該当 `layer_type:region` の
   エントリがあるか
3. **validated artifact**: `state.current_validated_path` またはregistryの
   `validated_storage_path` が指すファイルが実在するか
4. **current**: `readlink data_runtime/current` が正常な symlink を返すか
5. **backend API**: 該当 hazard/shelter の API が 200 を返し、期待する件数が含まれるか
6. **Martin**（tile 配信の場合）: `GET /tiles/catalog` に該当 tileset が含まれるか、
   `GET /api/hazards/<type>/<region>/meta` の `tileset_id` が Martin の実体と一致するか
7. **frontend**: 通常ナビ画面で該当レイヤーが選択可能で、fallback/disabled バッジが
   ついていないか

## 8. 注意事項

### GET が state を書き換える場合がある

`HazardDatasetService`・`ShelterRegistry` の一部読み取り経路は、
`DatasetStateService.init_from_definition()` を経由します。この関数は
`data_lake/admin/state/{dataset_id}.json` が存在しない場合、または記録された path が
ディスク上に実在しない（stale）場合、ファイルシステムをスキャンして状態を再推定し、
**その結果を state ファイルへ書き込みます**。

- 初回呼び出し時、または state ファイルが stale と判定された時のみ書き込みが発生します
  （2回目以降は既存 state をそのまま返す、idempotent な読み取りになります）。
- これは「read-only であるべき GET が実際には副作用を持つ」既知の設計上の注意点です。
  今回の一連の修正では、この挙動自体は変更していません。
- 運用上の影響: 通常の確認作業では大きな問題にはなりませんが、read-only のはずの
  確認スクリプトを複数同時に走らせる、あるいは「変更が一切発生していないこと」を
  厳密に検証したい場合（監査等）は、この副作用を踏まえて `data_lake/admin/state/*.json`
  の `mtime` を事前後で比較するなどの配慮をしてください。
- 公開 backend から到達可能な該当 route: `GET /api/hazards/{type}/{region}`
  （`landslide`/`inland_flood` を除く）、`GET /api/hazards/{type}/{region}/meta`、
  `GET /api/hazards/active`、`GET /api/emergency-shelters`（ただし shelter は atomic
  publish が正常な環境では通常この経路を通らない）。

### public backend に admin API を戻さない

トラブルシューティングのためであっても、`backend-public` へ admin 相当のルートを追加したり、
`operator-gateway` の host publish を loopback 以外へ広げたりしないでください。これは
Phase 2-B 系の公開監査で確立された trust boundary です。

## 9. 関連ドキュメント

- [Operator セットアップ](operator-setup.md) — trust boundary の設計そのもの
- [データ準備](data-setup.md) — validated データの準備と atomic publish 手順
- [VPS 起動/再構築チェックリスト](checklists/vps_startup_checklist.md) — 一連の手順を通した実行手順
