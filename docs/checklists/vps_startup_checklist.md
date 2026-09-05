# VPS 起動 / 再構築チェックリスト

新規 VPS へのセットアップ時、コンテナを完全に削除した後、または**正常稼働している既存 VPS の
in-place 再構築**時に使用する。手順は記載の順番で実行すること。

動作確認済み環境：Debian 12、Docker 26+、RAM 2 GB の VPS。

## 使い方（3通りのシナリオ）

| シナリオ | 実施範囲 |
| --- | --- |
| A. 新規 VPS へのゼロからの構築 | 0 → 1 → 2 → 3 → 4 → 4.5 → 5 → 6 → 7（0.5 は不要） |
| B. **既存 VPS の in-place 再構築**（正常稼働中の環境をバックアップした上で、アプリケーション・runtime 環境を再構築する。`data_lake` 等の既存データは可能な限り保持・再利用し、問題発生時に旧環境へ戻せることを最優先とする） | 0 → **0.5（必須）** → 1 → 2 → 3 → 4 → 4.5 → 5 → 6 → 7 |
| C. コードのみ更新（`data_runtime` 等は変更しない） | 0.5 のうち Git SHA 記録・backup のみ実施し、4.5（atomic publish）以降は状況に応じて判断 |

**B（in-place 再構築）の場合、0.5 のバックアップを飛ばしてはならない。** 本チェックリストの
どの手順も VPS 上のデータを不可逆に破壊する設計ではないが、`docker compose down -v` 等の
誤操作や、想定外の設定差分による runtime 再生成の失敗に備え、必ず「元の状態に戻せる」ことを
先に確保する。

---

## 0. 前提条件

- [ ] Docker および Docker Compose プラグインがインストール済み（`docker compose version` で確認）
- [ ] Git がインストール済みでリポジトリがクローン済み
- [ ] ファイアウォールでポート 8080 が開放済み（リバースプロキシを使う場合は 80/443）
- [ ] （B の場合）今回 commit/push する修正一式が、実際にレビュー・commit・push 済みであること
      （`git status --short` が clean、`git log` に該当 commit が含まれる）。**未 commit のまま
      VPS 側で `git pull` しても、ローカルで確認済みの修正は一切反映されない。**

---

## 0.5 バックアップ（既存 VPS の in-place 再構築の場合は必須）

### 記録

- [ ] `git rev-parse HEAD` と `git branch --show-current` を記録する（再構築前の正確な版）
- [ ] `docker compose ps -a` の出力を保存する（再構築前の稼働状態）
- [ ] `docker compose config` の出力を保存する（実際に解決された設定値の記録。`.env` 系の値は
      漏洩に注意して取り扱う）

### バックアップ取得

- [ ] `data_lake/`（`registry/`、`admin/state/`、`admin/active_mappings.json` を含む）を
      別ディスク・別ホストへコピーする
- [ ] `data_runtime/`（`current` symlink、`versions/`、`manifests/` を含む）をコピーする
      （host bind mount のため、compose 停止中にファイルシステムレベルでコピー可能）
- [ ] `.env`・`.env.operator`・`.env.stream`（存在する場合）をコピーする
- [ ] `config/runtime-config.local.js`・`docker-compose.override.yml`（存在する場合）をコピーする
- [ ] VPS provider のスナップショット機能があれば、作業前にスナップショットを取得する
      （最も確実な全体ロールバック手段）

### ロールバック手段の確認

- [ ] 上記バックアップから復元する具体的な手順（コピー先パス、復元コマンド）を作業開始前に
      書き出しておく
- [ ] `scripts/publish/activate_version.py --rollback <version-id>` による atomic runtime
      単体のロールバック手段があることを確認する（`data_runtime/versions/` 配下に複数版が
      残っていれば、`current` だけを直前の版へ戻せる。ただし今回の一連の修正でディレクトリ
      レイアウトが変わった箇所——避難所の dataset_id サブディレクトリ化——があるため、
      **修正前の版と修正後の版を跨いだ rollback は避け、必要なら該当版を再 publish し直す**）
- [ ] 上記いずれの手段も無い状態で本番へ変更を加えないこと

### サービス停止

- [ ] `docker compose ps` で現在の稼働状態を確認する
- [ ] `docker compose down`（named volume・bind mount のデータは削除されない。**`-v` を
      付けないこと**——named volume を使う設定の場合、`-v` は `docker-compose.override.yml` の
      named volume を削除してしまう）

---

## 1. ディレクトリ構造

コンテナ起動前に以下のディレクトリが存在する必要がある。
これらは **gitignore 対象**のため、新規サーバーでは手動作成が必要。
（B: 既存 VPS の in-place 再構築で `data_lake`/`data_runtime` を保持する場合、既存ディレクトリを
削除せず、不足しているサブディレクトリのみ `mkdir -p` で補うこと。）

```bash
mkdir -p data_lake/registry
mkdir -p data_lake/raw
mkdir -p data_lake/normalized
mkdir -p data_lake/validated
mkdir -p data_lake/tiles
mkdir -p data_runtime/backend/elevation
mkdir -p data_runtime/frontend/tiles
```

---

## 2. ハザード・避難所データ

バックエンドがハザードチェック・避難所情報を返すには、事前にデータを investment し、
**atomic publish**（4.5 節）で `data_runtime/current` へ反映する必要がある。データの取得・
正規化・検証（normalize/validate）は管理画面（`/admin/datasets`、`--profile operator` でのみ
到達可能）またはパイプラインスクリプト（`scripts/download/`・`scripts/normalize/`・
`scripts/validate/`）で行う。**publish（`current` への反映）自体は管理画面ではなく、
`scripts/publish/deploy_to_runtime_atomic.sh` を operator コンテナ内で実行することで行う。**
管理画面の操作手順は [データ管理画面運用ガイド](../admin-data-management.md) を参照。

東京・神奈川カバレッジに最低限必要なデータセット：

| データセット | 備考 |
|---|---|
| 東京 tsunami | 約 45 MB GeoJSON |
| 神奈川 tsunami | 約 45 MB GeoJSON |
| 東京 storm_surge | 約 60 MB GeoJSON |
| 神奈川 storm_surge | 約 60 MB GeoJSON |
| 東京 landslide | 約 100 MB GeoJSON |
| 神奈川 landslide | 約 100 MB GeoJSON |
| 東京 flood | 約 80 MB GeoJSON |
| 神奈川 flood | vector tile 成果物は未生成環境あり。GeoJSON API fallback は正常動作する |
| 東京避難所（`TOKYO-SHELTER-001`, `TOKYO-EVAC-001`） | active_mappings.json に登録必須 |
| 神奈川避難所（`KANAGAWA-SHELTER-001`, `KANAGAWA-EVAC-001`） | 同上。4 dataset すべてが揃わないと片方のカテゴリ（指定避難所 or 指定緊急避難場所）が 0 件になる |

千葉の tsunami はメモリ制約のある VPS ではデフォルトで除外されている。
`backend/app.properties` の `hazard.tsunami.targets` を参照。

RAM 要件の詳細は [メモリチューニング](../operations/vps_memory_tuning.md) を参照。

---

## 3. OSRM 徒歩データ

OSRM の徒歩インデックスは、コンテナ初回起動時に PBF ファイルからビルドされる。
`osrm-walking` を起動する前に PBF ファイルを配置すること。

配置先パス：

```text
data_lake/validated/tokyo/osm/walking/tokyo-kanagawa/tokyo-kanagawa-260214.osm.pbf
```

このファイルが存在しない場合、コンテナは即座に終了する（`test -f` が失敗）。

**初回ビルド時間**：2 GB VPS で 30〜60 分。
**ビルド中はコンテナを停止しないこと。**

ビルド進捗の確認：

```bash
docker compose logs -f osrm-walking
```

正常なログ出力の流れ：

```text
OSRM index not found — building from PBF...
[osrm-extract] ...
[osrm-partition] ...
[osrm-customize] ...
[info] Listening on: 0.0.0.0:5001
[info] running and waiting for requests
```

インデックスの再ビルド（PBF 更新後など）：

```bash
rm data_lake/validated/tokyo/osm/walking/tokyo-kanagawa/tokyo-kanagawa-260214.osrm*
docker compose restart osrm-walking
```

（B: in-place 再構築で既存の `.osrm*` 成果物を保持する場合、この節は再ビルド不要。ただし
OSRM イメージの version を変更した場合は `scripts/rebuild_osrm_artifacts.sh` で明示的に
再生成すること——[データ準備](../data-setup.md) 参照。）

---

## 4. サービスの起動

依存関係の問題を避けるため、以下の順番で起動する。**サービス名は `backend-public`
（Phase 2-B.2 以降、public/operator の trust boundary 分離のため `backend` から改名済み。
`frontend`/`nginx.conf` からは既存の network alias `backend` で到達できるが、`docker compose`
の service 指定には実際の service 名 `backend-public` を使うこと）:**

```bash
# まずバックエンドとインフラを起動
docker compose up -d backend-public martin

# バックエンドの起動完了を待つ（約 30 秒）
docker compose ps

# フロントエンド（nginx）を起動 — depends_on: backend-public, osrm-walking
# osrm-walking は依存関係として自動的に起動される
docker compose up -d frontend
```

一括起動も可能（docker compose が depends_on を処理する）：

```bash
docker compose up -d
```

`runtime-init`（root, one-shot）は `backend-public`/`backend-operator` の起動前提として
自動的に実行される（`depends_on: runtime-init: condition: service_completed_successfully`）。

注意：`osrm-driving` はデフォルトでは**起動しない**（プロファイルで制御）。

---

## 4.5 Runtime publish（atomic）

**この節は container が healthy になっただけでは完了しない。** `data_runtime/current` が
実際に解決でき、hazard/shelter データが読み込まれるまでを確認する。

### runtime-init の確認

```bash
docker compose logs runtime-init
```

`[init_lease_volume] OK` で正常終了していること。

**既知の問題（B: in-place 再構築で特に注意）**: `runtime-init` は既存 artifact の
owner/mode 不一致を `chmod -R`/`chown -R` で自動修復しない設計（fail-closed）。もし旧環境の
`data_runtime/versions` が今回の修正前の owner/group で作成されていた場合
（`operator_uid:operator_gid` = 修正前の値）、修正後の `init_lease_volume.py`
（`operator_uid:leases_gid` を期待）と一致せず、かつ `versions/` が空でない場合、
`runtime-init` は以下のようなメッセージで fail する:

```text
[init_lease_volume] FAIL: /data_runtime/versions のowner/mode不一致（自動修復しない、非emptyのため）:
  expected=10002:20001/0o2750 actual=10002:10002/0o2750
```

この場合、**recursive な chown/chmod は行わず**、`versions` ディレクトリ自体（非再帰、1 inode）
のみ手動で是正してから `runtime-init` を再実行する:

```bash
# versions/ 自体の group のみ変更（配下のversion directoryやfileには触れない）
sudo chgrp 20001 data_runtime/versions
docker compose up runtime-init
```

（named volume を使うローカル環境固有の `versions/<id>/` 個々の owner/mode は
`deploy_to_runtime_atomic.sh` が publish のたびに正しく設定し直すため、`versions` 自体の
group だけを直せば以降の publish は正常に進む。）

### operator プロファイルで publish を実行

```bash
docker compose --profile operator run --rm --no-deps --entrypoint bash backend-operator -c \
  "scripts/publish/deploy_to_runtime_atomic.sh --region tokyo --region kanagawa"
```

初回 publish（`current` 未設定）では、`--region` を対象地域すべて分まとめて 1 回で指定する
こと（理由は [データ準備](../data-setup.md) の「publish と検証」節を参照——tsunami consumer
設定が全 target の同時存在を要求するため）。

### 確認

```bash
readlink data_runtime/current   # versions/<version-id> を指すこと
ls data_runtime/.staging/       # 空であること（publish成功後は残らない）
```

publish の標準出力に `publish succeeded: current -> versions/<version-id>` が出ること。
末尾に `current/frontend/layers -> frontend/layers 同期に失敗` という warning が出る場合が
あるが、これは atomic publish 自体の成功後に行う別の同期ステップ（nginx 直配信用の軽量
GeoJSON フォールバック更新）の失敗であり、`current` 自体には影響しない（許容される既知の
warning。詳細は [データ準備](../data-setup.md)）。

### Martin へ反映

publish 完了後、Martin は `data_runtime/frontend/tiles`（flat mirror、`current` とは別に
publish のたびに同期される）を起動時に一度だけ scan する。tile を追加・更新した場合は
再起動が必要:

```bash
docker compose restart martin
curl -s http://localhost:8080/tiles/catalog | python3 -m json.tool
```

---

## 5. ヘルスチェック

**「container が healthy」「runtime が実際に機能している」「必要なデータが揃っている」を
分けて確認すること。** container health だけを見て完了と判断しないこと。

### 5-1. Container health

```bash
# 全コンテナが Running 状態（Restarting になっていないこと）
docker compose ps

# バックエンド API
curl -s http://localhost:8000/health

# OSRM 徒歩（Round 12D-B以降、host publishなし。osrm/osrm-backend image に
# curl/wget/python等のHTTPクライアントが一切無いため、コンテナ内部からの
# 直接確認はできない。frontend経由のproxy確認（下記）で代替する）
docker compose ps osrm-walking  # State が running であることのみ確認
```

### 5-2. Runtime readiness

```bash
docker exec evacuation-navi-backend curl -s http://localhost:8000/health
# {"status":"ok"} であること（"degraded"の場合はtsunami coverage欠落等の可能性、
# backend起動ログの "Tsunami coverage OK" 行を確認する）
```

### 5-3. Data readiness

```bash
# nginx プロキシ経由（エンドツーエンド、OSRM 徒歩の実質的な健全性確認はここで行う）
curl -s "http://localhost:8080/api/health"
curl -s "http://localhost:8080/osrm/walking/route/v1/walking/139.69,35.68;139.70,35.69" | head -c 50

# hazard API（土砂・内水は atomic publish 経由の専用route。500の場合はLeaseErrorの可能性）
curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:8080/api/hazards/landslide/tokyo"
curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:8080/api/hazards/inland_flood/tokyo"

# 避難所（region×categoryを必ず確認する。totalが非0でも片方のcategoryが0件のことがある）
curl -s "http://localhost:8080/api/emergency-shelters?limit=15000" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(d['count'])"
```

### 5-4. Application readiness

```bash
curl -s http://localhost:8080/tiles/catalog | python3 -m json.tool
```

catalog の `tiles` が空でないこと。すべて HTTP 200 で有効な JSON が返ることを確認する。

---

## 6. 既知の問題と注意事項

### 起動時に martin が Restarting ループに入る

Martin が Restarting ループになる場合、`config/martin.yaml` にディスク上に存在しない
タイルパスが含まれている可能性がある。未ビルドのデータセットのエントリをコメントアウトまたは削除する。

```bash
docker compose logs martin
```

### バックエンドのメモリが 1.5 GB を超える

- `backend/app.properties` の `hazard.tsunami.targets` に `chiba` が含まれていないか確認
- `backend/main.py` のすべてのハザード読み込みで `bbox_only=True` が指定されているか確認
- 詳細は [メモリチューニング](../operations/vps_memory_tuning.md) を参照

### osrm-walking がヘルプテキストを表示して終了する

コンテナログに `osrm-routed <base.osrm> [<options>]:` というヘルプメッセージが表示される場合、
OSRM インデックスファイルが存在しないかパスが間違っている。

確認コマンド：

```bash
ls data_lake/validated/tokyo/osm/walking/tokyo-kanagawa/
```

`.osrm` ファイルおよびその関連ファイル（`.partition`、`.mldgr` など）がすべて存在する必要がある。

### nginx から osrm-walking にプロキシできない

`/osrm/walking/` が `InvalidUrl`（HTTP 400）を返す場合、
nginx プロキシが location プレフィックスを正しく除去できていない。
[nginx プロキシパターン](../architecture/nginx_proxy_patterns.md) を参照。

`proxy_pass` は**末尾スラッシュ付きのリテラルホスト名**を使う必要がある：

```nginx
proxy_pass http://osrm-walking:5001/;  # 正しい
```

### ShelterRegistry の CPU / メモリ使用率が高い

バックエンドのログで 30 秒ごとに避難所データが再読み込みされている場合、
`backend/app/services/shelter_service.py` を確認する：

```python
_registry_instance = ShelterRegistry(ttl_seconds=3600)  # 30 ではなく 3600 であること
```

### 避難所の特定カテゴリ（指定避難所 or 指定緊急避難場所）が 0 件になる

`GET /api/emergency-shelters` の region×category 内訳で片方が 0 件の場合、
`data_lake/admin/active_mappings.json` に4 dataset
（`TOKYO-SHELTER-001`, `TOKYO-EVAC-001`, `KANAGAWA-SHELTER-001`, `KANAGAWA-EVAC-001`）が
すべて登録され、それぞれの validated artifact が実在するか確認する
（`scripts/publish/resolve_shelter_sources.py --region <region>` を operator コンテナ内で
直接実行すると、解決結果と警告が確認できる）。

### hazard レイヤーが Martin ではなく GeoJSON fallback で表示される

`GET /api/hazards/<type>/<region>/meta` の `tileset_id` が `null` の場合、
`data_runtime/frontend/tiles/<region>/<hazard_type>/` に該当 `.mbtiles` が存在しない
（4.5 節の Martin 同期が正しく行われたか、そもそも `data_lake/tiles/` に元データがあるかを
確認する）。`tileset_id` が非 null なのに Martin から 404 が返る場合は、`docker compose
restart martin` を実行していない可能性が高い（Martin は起動時に一度だけ scan する）。

---

## 7. エンドツーエンドの確認

ブラウザで `http://<VPS の IP アドレス>:8080` を開く。

- [ ] 地図が避難所ピンと共に表示される
- [ ] 東京都内の地点でハザードチェックが結果を返す
- [ ] 避難ルート検索が完了し、徒歩ルートが表示される
- [ ] 洪水（東京）・高潮（東京・神奈川）・推定内水・低地排水困難（東京・神奈川）レイヤーが
      「GeoJSON fallback」バッジ無しで選択できる（Kanagawa 洪水のみ、tile 成果物未生成の
      場合は fallback バッジが正常）
- [ ] 土砂・内水氾濫（東京・神奈川）レイヤーが `Failed to fetch` を出さずに表示される
- [ ] 「全地域を一覧表示」で東京・神奈川双方に避難所 marker が表示される

---

## 8. 完了基準（4層に分けて判定する）

| 層 | 基準 | 満たさない場合 |
| --- | --- | --- |
| Container health | `docker compose ps` で全サービスが running/healthy | 4節・6節を再確認 |
| Runtime readiness | `current` が正常 symlink、`/health` が `ok`、staging residue なし | 4.5節を再確認 |
| Data readiness | landslide/inland_flood API 200、避難所 region×category が全て非0、Martin catalog 非空 | 2節・4.5節、6節の既知の問題を確認 |
| Application readiness | 7節のブラウザ確認が全てチェック済み | 6節の個別トラブルシューティングを確認 |

**この4層すべてを満たして初めて「再構築完了」とする。container healthy のみで完了と
判断しないこと。**
