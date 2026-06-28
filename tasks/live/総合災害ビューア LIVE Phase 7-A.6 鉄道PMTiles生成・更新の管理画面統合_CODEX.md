# CODEX 検証指示書

## 総合災害ビューア LIVE Phase 7-A.6

## 鉄道PMTiles生成・更新の管理画面統合

# 検証目的

管理画面から

```text
OSM取得
↓
PMTiles生成
↓
検証
↓
反映
```

が安全に実行できることを確認する。

---

# 1. 構文・起動確認

確認:

```bash
python compile
node --check
bash -n
```

Docker起動:

```bash
docker compose ps
```

確認:

```text
backend healthy
frontend up
martin healthy（利用時）
```

---

# 2. 管理画面確認

データ管理画面を開く。

確認:

```text
全国鉄道路線PMTiles項目表示
状態表示
更新ボタン
ログ表示
```

---

# 3. ジョブ実行

更新ボタン押下。

確認:

```text
ジョブ開始
進捗更新
完了表示
```

---

# 4. ダウンロード確認

確認項目:

```text
japan-latest.osm.pbf取得
サイズ正常
更新日時更新
```

ダウンロード失敗時は

```text
エラー表示
```

となること。

---

# 5. PMTiles生成確認

確認:

```text
railways_japan.pmtiles.tmp生成
```

生成完了後:

```text
railways_japan.pmtiles
```

が存在すること。

---

# 6. atomic rename確認

重要確認。

生成途中で

```text
既存PMTiles
```

が消えないこと。

失敗時も

```text
旧PMTiles
```

が残ること。

---

# 7. 失敗試験

以下を実施可能なら実施。

---

## OSM URL無効

期待:

```text
ジョブ失敗
旧PMTiles維持
```

---

## tippecanoe未存在

期待:

```text
ジョブ失敗
旧PMTiles維持
```

---

## ディスク不足想定

期待:

```text
ジョブ失敗
旧PMTiles維持
```

---

# 8. LIVE反映確認

生成後

```text
/ live
```

を表示。

確認地点:

```text
東京
大阪
仙台
札幌
福岡
```

鉄道路線表示を確認。

---

# 9. 回帰確認

最低限確認。

```text
地震履歴
市区町村震度
雨雲
キキクル
津波UI
鉄道運行障害
道路レイヤー
```

---

# 10. ログ確認

管理画面ログに以下が残ること。

```text
開始
ダウンロード
生成
検証
反映
終了
```

エラー時は原因が分かること。

---

# 判定基準

PASS

```text
ワンボタン更新成功
PMTiles生成成功
LIVE表示成功
旧ファイル保護成功
回帰なし
```

PASS with notes

```text
生成成功
表示成功
一部ログ改善余地あり
```

FAIL

```text
本番PMTiles消失
生成失敗でLIVE破損
管理画面から更新不可
回帰発生
```

---

# レポート

作成先:

```text
tasks/live/live_phase7a6_pmtiles_management_codex_verification.md
```

記載内容:

```text
判定
確認環境
生成時間
PBFサイズ
PMTilesサイズ
ログ確認結果
LIVE表示確認
回帰結果
スクリーンショット
既知制約
改善提案
```
