# VPS メモリチューニング — バックエンド

## 背景

バックエンドが 1.9 GiB の VPS で **約 4.7 GiB** のメモリを消費し、
OOM キルとコンテナ不安定を引き起こしていた。
このドキュメントは原因・対処内容・再設定方法を記録する。

---

## 根本原因

### 1. HazardService：座標配列をフルでメモリに展開

`hazard_service.py` がすべての GeoJSON ポリゴンを座標リングごと読み込んでいた。
Python の JSON パース結果はファイルサイズの 3〜8 倍のヒープを消費するため、
100 MB の GeoJSON が最大 500 MB のヒープを占有する。

影響を受けたデータセットと概算ファイルサイズ：

| レイヤー | ファイル数 | 生ファイルサイズ |
|---|---|---|
| tsunami（東京 + 神奈川） | 2 | 約 90 MB |
| storm_surge（東京 + 神奈川） | 2 | 約 120 MB |
| landslide（東京 + 神奈川） | 2 | 約 200 MB |

### 2. ShelterRegistry TTL = 30 秒

`shelter_service.py` の `ttl_seconds=30` が Docker ヘルスチェックの間隔と一致していた。
結果として、30 秒ごとに避難所データセット全体をディスクから再読み込みし続けるループが発生していた。

### 3. 千葉津波データがデフォルトで読み込まれていた

千葉の津波 GeoJSON（約 139 MB）がデフォルトの読み込み対象に含まれていた。
メモリ制約のある VPS では、千葉までカバーする必要がないため不要。

---

## 適用した修正

### HazardService の bbox_only モード（`backend/hazard_service.py`）

`HazardService.load()` に `bbox_only=True` オプションを追加した。
このモードでは、ポリゴン座標全体ではなく最小外接矩形（bbox）のみを保持する：

| レイヤー | bbox_only モードで保存される情報 |
|---|---|
| tsunami | `{bbox, centroid}` — 距離クエリ用にセントロイドを事前計算 |
| storm_surge | `{bbox}` — 包含チェックのみに使用 |
| landslide | `{bbox, properties}` — 詳細表示にプロパティが必要 |
| flood | `{bbox, coords}` — ポリゴン交差判定のため座標を保持 |

`backend/main.py` での起動時の呼び出し：

```python
# storm_surge
hazard_service.load("storm_surge", path, bbox_only=True)

# tsunami
hazard_service.load("tsunami", path, bbox_only=True)

# landslide
hazard_service.load("landslide", path, bbox_only=True)
```

**トレードオフ**：storm_surge と landslide は点内包判定の精度が bbox 判定に落ちる。
tsunami はセントロイド距離が保持される。
避難ルーティングという主要ユースケースでは許容範囲だが、
精度の高いハザード分析が必要になった場合は再検討すること。

### ShelterRegistry TTL（`backend/app/services/shelter_service.py`）

```python
# 修正前（30 秒ごとに常時リロードが発生していた）
_registry_instance = ShelterRegistry(ttl_seconds=30)

# 修正後
_registry_instance = ShelterRegistry(ttl_seconds=3600)
```

強制リロードが必要な場合（例：新しい避難所データをデプロイした後）：

```bash
docker compose restart backend
```

### 千葉津波の除外（`backend/app.properties`）

```properties
# chiba は VPS では除外（139 MB、メモリ上では約 1 GB；カバレッジ不要）
hazard.tsunami.targets=tokyo,kanagawa
```

千葉を再び有効にする場合（より高メモリのホストに移行する場合）：

```properties
hazard.tsunami.targets=tokyo,kanagawa,chiba
```

**注意**：千葉を無効にすると、千葉沿岸エリアのユーザーに津波警告が届かなくなる。
十分な RAM を確認した上で再有効化すること。
また無効化する場合はリリースノートに必ず記載すること。

---

## 結果

| 修正前 | 修正後 |
|---|---|
| 約 4.7 GiB | 約 2.5 GiB |

1.9 GiB VPS（ConoHa VPS 2 GB プラン）で検証済み。
OS およびその他サービス向けに約 400 MB のヘッドルームを確保した状態で安定稼働。

---

## 今後の課題

- ストリーミング GeoJSON パーサー（GeoJSONL / ijson）による起動時ピーク負荷の回避
- ハザードレイヤーをインメモリポリゴンではなく Martin タイルサーバー配信に移行
- コード変更なしに個別データセットを除外できる、リージョン単位のフィーチャーフラグ
