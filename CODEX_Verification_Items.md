# OnHighGround2 大容量データアップロード対応 CODEX 検証項目

本ドキュメントは、大容量データの Drag & Drop アップロード実装における、CODEX検証および品質担保のためのチェックリストである。

## 1. 静的解析・構成確認 (CODEX 検証)

### 1.1 JS 構文確認
- **実施コマンド:**
  ```bash
  find frontend -name '*.js' -print0 | xargs -0 -n1 node --check
  ```
- **確認事項:** [ ] Syntax Error が一切ないこと。

### 1.2 Python コンパイル確認
- **実施コマンド:**
  ```bash
  PYTHONPYCACHEPREFIX=.pycache-check python3 -m py_compile \
  backend/main.py \
  backend/app/api/admin*.py \
  backend/app/services/*.py
  ```
- **確認事項:** [ ] Compile Error が一切ないこと。

### 1.3 Nginx 設定確認
- **確認事項:** 以下の設定が適切に反映されているか。
  - [ ] `client_max_body_size` (例: 12G)
  - [ ] `proxy_request_buffering off`
  - [ ] `proxy_buffering off`

---

## 2. API 検証

### 2.1 upload/start
- [ ] ステータスコード `200 OK` が返却される。
- [ ] レスポンスに `upload_id` が含まれている。
- [ ] レスポンスに `chunk_size` が含まれている。

### 2.2 chunk upload
- [ ] Chunk の append (追記) 保存が成功する。
- [ ] アップロード中、サーバーのメモリ使用率に異常な増加がないこと。
- [ ] `data_runtime/uploads/tmp/` に一時ファイルが正しく生成される。
- [ ] Chunk の順序が整合性を保って書き込まれている。

### 2.3 upload/finish
- [ ] 最終的なファイル移動 (Final file move) が正常に行われる。
- [ ] 元ファイルとサーバー保存ファイルのサイズが一致する。
- [ ] 不完全なアップロード (Partial upload) に対する完了リクエストが拒否される。

### 2.4 upload/cancel
- [ ] 一時ファイル (Temp) が削除される。
- [ ] DB 等のアップロードステータス (Upload state) がクリーンアップされる。

---

## 3. エラー・セキュリティ検証

### 3.1 Retry (再試行)
- **擬似障害:** ネットワーク切断 (Network abort) を発生させる。
- [ ] 自動的に Retry が開始される。
- [ ] Retry 回数に上限が設定されている（無限ループにならない）。

### 3.2 無効な拡張子 (Invalid extension)
- [ ] 許可されていない拡張子のファイルが Reject される。

### 3.3 Path Traversal (パス移動攻撃)
- **入力例:** `../../evil.zip`
- [ ] ファイル名が適切にサニタイズされ、意図しないディレクトリへの書き込みが防止されている。

---

## 4. UI/UX 確認

### 4.1 Drag & Drop 動作
- [ ] ドラッグ＆ドロップでファイルが選択できる。
- [ ] クリックによるファイル選択ダイアログが動作する。

### 4.2 進捗 (Progress) 表示
- [ ] 進捗率 (%) がリアルタイムに更新される。
- [ ] 転送速度 (Speed) が表示される。
- [ ] 残り時間 (Remaining time) が概算表示される。

### 4.3 キャンセル動作
- [ ] UI 上で停止ボタンが機能する。
- [ ] Backend 側のクリーンアップ処理がトリガーされる。

---

## 5. 大容量・負荷検証

### 5.1 1GB 級ファイルテスト
- [ ] ブラウザがフリーズしたり、クラッシュしたりしない。
- [ ] Backend で OOM (Out Of Memory) が発生しない。

### 5.2 複数データセット切替
- [ ] `dataset_id` が混線せず、指定したデータセットに対して正しくアップロードされる。

---

## 6. 連携・回帰テスト

### 6.1 Ingest パイプライン連携
- [ ] アップロード完了後、既存の Ingest 処理が正常に開始できる。

### 6.2 回帰確認 (Regression Test)
- **実施コマンド:**
  ```bash
  npx playwright test
  ```
- [ ] 既存の管理画面 (Admin UI) 機能が破壊されていないこと。

---

## 7. 最終判定

| 判定結果 | チェック (いずれか一つ) |
| :--- | :--- |
| **PASS** | [ ] |
| **PASS with notes** | [ ] |
| **FAIL** | [ ] |

### 問題発生時の記録事項
問題があった場合は以下を記録すること：
1. **再現手順:**
2. **ログ:**
3. **原因推定:**
4. **修正案:**

---

## CODEX 検証実施結果（2026-05-06）

### 実施環境
- 作業ディレクトリ: repository root
- Backend: `evacuation-navi-backend` (`127.0.0.1:8000`)
- Frontend: `evacuation-navi-frontend` (`127.0.0.1:8080`)
- 備考: 検証開始時点では起動中 FastAPI プロセスの OpenAPI に `/api/admin/upload/*` が未反映で `404 Not Found` だったため、`docker compose restart backend` 後に API 検証を実施した。

### 1. 静的解析・構成確認
- [x] JS 構文確認: `find frontend -name '*.js' -print0 | xargs -0 -n1 node --check` 成功。
- [x] Python コンパイル確認: `PYTHONPYCACHEPREFIX=.pycache-check python3 -m py_compile backend/main.py backend/app/api/admin*.py backend/app/services/*.py` 成功。
- [x] Nginx 設定確認: `nginx.conf` に以下を確認。
  - `client_max_body_size 12G`
  - `proxy_request_buffering off`
  - `proxy_buffering off`

### 2. API 検証
- [x] `POST /api/admin/upload/start`: `200 OK`、`upload_id`、`chunk_size=8388608` を確認。
- [x] 無効拡張子: `bad.exe` は `400 Bad Request` で拒否。
- [x] Path Traversal: `../../evil.geojson` は `200 OK` で受理され、in-process `finish` 検証で最終ファイル名が `finish-ok.geojson` にサニタイズされることを確認。
- [x] Chunk append: 42 bytes の `.geojson` chunk 送信で `{"received":true,"written":42}` を確認。
- [x] 一時ファイル生成: `/data_runtime/uploads/tmp/{upload_id}.part` が生成され、サイズ 42 bytes を確認。
- [x] Chunk 順序: `hello` + `world` を offset `0` / `5` で送信し、一時ファイル内容が `helloworld`、サイズ 10 bytes であることを確認。
- [x] Partial finish 拒否: `total_size=43`、実ファイル 42 bytes で `400 Bad Request`、`サイズ不一致 expected=43 actual=42` を確認。
- [x] `DELETE /api/admin/upload/cancel`: `200 OK`、`{"cancelled":true}` を確認。
- [x] Cancel cleanup: cancel 後 `/data_runtime/uploads/tmp` が `total 0` になることを確認。
- [x] Final file move: 実データセットの ingest 起動を避けるため、backend コンテナ内でサービスをモックして `upload_start -> upload_chunk -> upload_finish` を直接実行。`.part` が `finish-ok.geojson` に rename され、`job_id=job-test-001` が返ることを確認。
- [x] メモリ確認: 小容量 chunk 検証時の backend は `1.976GiB / 9.213GiB (21.45%)`。異常な増加は確認されず。ただし 1GB 級ファイルでは未確認。
- [x] 複数 dataset_id: `KANAGAWA-URBAN-001` と `TOKYO-URBAN-001` で個別に `upload/start` が成功し、別 upload_id が発行されることを確認。両方 cancel 済み。

### 3. エラー・セキュリティ検証
- [x] Retry 上限: `frontend/admin/upload-manager.js` の `_sendChunk(..., retries = 3)` と指数バックオフ `1s, 2s, 4s` をコード確認。
- [ ] Network abort の実ブラウザ擬似障害: 未実施。
- [x] Invalid extension: `.exe` を API で拒否確認。
- [x] Path Traversal: `Path(name).name` と `_SAFE_NAME_RE` によるサニタイズ、およびモック finish で最終ファイル名確認。

### 4. UI/UX 確認
- [x] Drag & Drop: `frontend/admin/datasets.html` の `ondrop="handleDrop(event)"` と `frontend/admin/datasets.js` の `handleDrop` を確認。
- [x] クリック選択: upload zone の `onclick` と file input `onchange="handleFileSelect(this)"` を確認。
- [x] 進捗率: `_updateChunkProgress` が `cp-percent` と `cp-bar` を更新することを確認。
- [x] 転送速度: `UploadManager` が `speed` を算出し、`_formatSpeed` で表示することを確認。
- [x] 残り時間: `UploadManager` が `etaSec` を算出し、`_formatEta` で表示することを確認。
- [x] キャンセル UI: `cancelChunkUpload()` が `UploadManager.cancel()` を呼ぶことを確認。
- [x] Backend cleanup trigger: `UploadManager._cancelSession()` が `DELETE /cancel` を呼ぶことを確認。

### 5. 大容量・負荷検証
- [ ] 1GB 級ファイルテスト: 未実施。実データセット更新や長時間負荷を伴うため、今回の検証では小容量 chunk とメモリ観測に限定。
- [x] 複数データセット切替: `upload/start` レベルで `dataset_id` ごとに別 upload_id が発行されることを確認。

### 6. 連携・回帰テスト
- [x] Ingest パイプライン連携: モック finish で `JobType.ingest_upload` の job 作成と submit 呼び出しまで確認。
- [ ] 実データセットでの ingest パイプライン正常完了: 未実施。小さな検証ファイルで実 dataset state を更新すると既存データを破壊する可能性があるため回避。
- [ ] `npx playwright test`: FAIL。363 件中 64 件目付近まで実行し、複数の 30 秒 timeout / 既存 UI 回帰失敗が出たため中断。

#### Playwright で確認した主な失敗
- `admin-datasets.spec.js:602` 初期表示コンソールエラーなし: `Failed to load resource: the server responded with a status of 404 (Not Found)` が 1 件発生。
- `admin-datasets.spec.js:749` URL取得ジョブ受付成功: 同じ 404 console error により失敗。
- `admin-datasets.spec.js:1052` ネットワークエラー時もクラッシュせずエラー通知: 失敗。
- `admin-datasets.spec.js:1235` Config 保存: `tr[data-config-key="navigation.arrival_distance_m"] button` locator 待ちで 30 秒 timeout。画面側は card layout で表示されており、テスト selector と DOM 構造が不一致の可能性。
- `admin-datasets.spec.js:1247` ログレベル select 編集: 30 秒 timeout。
- `admin-datasets.spec.js:1260` Config 範囲外値: 30 秒 timeout。
- `admin-datasets.spec.js:1327` SSE ログ行追加: 失敗。
- `admin-datasets.spec.js:1345` 最大1000行間引き: 失敗。
- `block-ahead-reroute-generated.spec.js` 複数ケース: `harness-error` で 30 秒 timeout。

### 最終判定

| 判定結果 | チェック |
| :--- | :--- |
| **PASS** | [ ] |
| **PASS with notes** | [ ] |
| **FAIL** | [x] |

### 問題発生時の記録
1. **再現手順:** `npx playwright test` を実行。
2. **ログ:** `test-results/*/error-context.md` に各失敗の Playwright context が生成済み。
3. **原因推定:** 大容量 upload API 自体は小容量・モック正常系で通過。一方、既存 Playwright 回帰で 404 console error、Config DOM selector 不一致、SSE mock/ログ表示、reroute harness timeout が発生。upload 実装とは別領域の既存回帰失敗を含む可能性が高い。
4. **修正案:** 404 リソースの特定、Config テスト selector の現行 DOM への更新、SSE mock と Logs UI のイベント処理確認、reroute harness の timeout 原因調査を実施する。
