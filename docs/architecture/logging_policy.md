# ログポリシー — OnHighGround2 Backend

---

## 基本方針

- **ログ出力先は stdout / stderr のみ**
- アプリ側でファイルログは実装しない
- ローテーションは Docker 側で実施する
- 新しいライブラリは追加しない（標準 `logging` モジュールのみ）

---

## フォーマット

```
%(asctime)s %(levelname)s [%(name)s] %(message)s
```

出力例:

```
2026-03-19 10:23:45,123 INFO [__main__] OnHighGround2 backend starting
2026-03-19 10:23:45,130 INFO [__main__] LOG_LEVEL=INFO  config=/app/app.properties
2026-03-19 10:23:45,135 INFO [__main__] runtime path=/data_runtime
2026-03-19 10:23:45,136 INFO [__main__] fallback path=/data_lake  (data_lake)
2026-03-19 10:23:45,140 WARNING [__main__] DEM fallback to data_lake: /data_lake/validated/tokyo/dem/elevation.tif
2026-03-19 10:23:46,200 INFO [__main__] Shelter data sources: ['/data_lake/validated/tokyo/shelter']
2026-03-19 10:23:46,500 INFO [__main__] 避難場所データ読み込み件数: 1234
```

---

## ログレベルの使い分け

| レベル | 用途 |
|---|---|
| `INFO` | 正常動作の記録。起動情報、データロード成功、APIリクエスト/レスポンス |
| `WARNING` | 想定内の問題。**fallback 使用時は必ず WARNING**。設定値が見つからない場合など |
| `ERROR` / `EXCEPTION` | 予期しないエラー。スタックトレースを必ず出す（`logger.exception` を使用） |
| `DEBUG` | 開発時のみ。本番ではデフォルト無効 |

---

## runtime / fallback ルール

**data_runtime を使った場合 → INFO**

```
INFO [__main__] DEM loaded from runtime: /data_runtime/backend/elevation/elevation.tif
INFO [__main__] Tsunami loaded from runtime: /data_runtime/backend/hazard/tsunami/tsunami_tokyo.geojson
```

**data_lake へフォールバックした場合 → WARNING**

```
WARNING [__main__] DEM fallback to data_lake: /data_lake/validated/tokyo/dem/elevation.tif
WARNING [__main__] Tsunami fallback to data_lake: /data_lake/normalized/tokyo/tsunami/tsunami_tokyo.geojson
WARNING [__main__] StormSurge fallback to data_lake: /data_lake/normalized/tokyo/storm_surge/tokyo_storm_surge.geojson
```

**fallback が WARNING であること**は設計上の意図であり、
`data_runtime` にデータが未配備である状態を明示するためである。
`deploy_to_runtime.sh` を実行することで WARNING は消え、INFO に変わる。

---

## 起動時に確認できるログ

```
INFO  OnHighGround2 backend starting
INFO  LOG_LEVEL=INFO  config=/app/app.properties
INFO  runtime path=/data_runtime
INFO  fallback path=/data_lake  (data_lake)
INFO/WARNING  DEM loaded from runtime|fallback ...
INFO  Shelter data sources: [...]
INFO  避難場所データ読み込み件数: N
WARNING/INFO  Flood / StormSurge / Tsunami loaded from ...
```

---

## API リクエストログ

`/api/hazard-check`:
```
INFO [__main__] hazard-check: lat=35.68504 lon=139.75275
```

`/api/evacuation`:
```
INFO [__main__] evacuation request: lat=35.68504 lon=139.75275 mode=walking max_distance=2000
INFO [__main__] evacuation result: candidates=5 selected=1 tier=safe
```

---

## エラーログ

すべての例外は `logger.exception` を使用し、スタックトレースを出力する。

```python
# 正しい書き方
logger.exception("避難目的地検索エラー")

# 誤り（スタックトレースが出ない）
logger.error(f"エラー: {e}")
```

---

## Docker ログローテーション

`docker-compose.yml` の backend サービスに設定済み:

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "5"
```

- 1ファイル最大 10 MB
- 最大 5 世代保持（合計最大 50 MB）
- ローテーションは Docker daemon が自動で実施

---

## ログ確認コマンド

```bash
# リアルタイムで確認
docker logs -f evacuation-navi-backend

# 最新 100 行
docker logs --tail 100 evacuation-navi-backend

# タイムスタンプ付き
docker logs --timestamps evacuation-navi-backend

# 特定の単語でフィルタ（grep と組み合わせ）
docker logs evacuation-navi-backend 2>&1 | grep WARNING
docker logs evacuation-navi-backend 2>&1 | grep "fallback"
docker logs evacuation-navi-backend 2>&1 | grep "evacuation result"
```

---

## ログレベルの変更

`backend/app.properties` で変更可能:

```properties
log.level=DEBUG   # 詳細ログ（開発時）
log.level=INFO    # 通常運用（デフォルト）
log.level=WARNING # 警告以上のみ
```

`api.log_level` は uvicorn のアクセスログレベル（別設定）。

---

## 今後の改善候補

| 項目 | 概要 | 優先度 |
|---|---|---|
| JSON ログ | `python-json-logger` 等で構造化ログ化 → 外部ツールとの連携が容易 | 中 |
| リクエスト ID | `X-Request-ID` ヘッダーを伝搬し、リクエスト単位でログを追跡 | 中 |
| 外部ログ基盤 | Loki / CloudWatch Logs 等への転送（Docker log driver 変更で対応可能） | 低 |
| アクセスログ分離 | uvicorn アクセスログを別ロガーに分離 | 低 |
