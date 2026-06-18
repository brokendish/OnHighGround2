# CODEX用検証指示書

# 総合災害ビューア全国監視 Phase 7-A.3

# 鉄道路線オーバーレイ視認性改善

## 検証目的

Phase 7-A.3 の鉄道路線オーバーレイ視認性改善を検証する。

今回の重点は以下。

* 全路線が白一色ではなく、路線ごとの公式カラーで表示されること
* 障害状態でも路線識別色が失われないこと
* 障害状態が線幅・ハロー・破線で判別できること
* 同一路線の複数線表示が過剰でないこと
* 側線・車庫線・駅構内線が目立ちすぎないこと
* 既存 `/live` の災害監視UIを壊していないこと

---

## 対象

```text
/live
```

対象レイヤー:

```text
鉄道運行影響
```

対象ファイル候補:

```text
frontend/js/live/live-train-osm-layer.js
frontend/js/live/live-train-line-colors.js
frontend/css/live/live.css
frontend/css/live/live-train.css
```

成果物:

```text
tasks/live/live_phase7a3_railway_overlay_visibility_codex_verification.md
```

---

## 1. 起動確認

```bash
python3 -m compileall backend
docker compose ps
```

期待:

* backend healthy
* frontend up
* martin healthy
* compile PASS

---

## 2. E2E実行

既存・追加テストを実行する。

```bash
npx playwright test e2e/live-train-osm-layer.spec.js
npx playwright test e2e/live-train-layer.spec.js
npx playwright test e2e/live-basic.spec.js
```

追加E2Eがある場合:

```bash
npx playwright test e2e/live-train-overlay-visibility.spec.js
```

期待:

全PASS。

---

## 3. 路線カラー確認

鉄道運行影響レイヤーをONにして、主要路線の stroke 色を確認する。

最低限確認対象:

```text
山手線
中央線
京浜東北線
総武線
京葉線
埼京線
銀座線
丸ノ内線
東西線
千代田線
京王線
小田急線
```

期待:

* 全路線が白一色ではない
* 路線ごとに識別可能な色が付いている
* 公式カラーまたは一般的なラインカラーに近い
* fallback色ばかりになっていない

---

## 4. 障害状態表現

モックで以下を投入する。

```text
delay
partial_suspension
suspended
```

確認:

### delay

期待:

* 路線公式カラーは維持
* 通常より太い
* 黄色系ハローなどで遅延が分かる

### partial_suspension

期待:

* 路線公式カラーは維持
* 太線
* 破線またはオレンジ系ハロー

### suspended

期待:

* 路線公式カラーは維持
* 太線
* 赤ハローまたは強調縁取り

重要:

```text
障害状態だからといって路線本体色を黄色/赤へ完全上書きしないこと
```

---

## 5. 通常路線の見やすさ

確認:

* 背景地図に埋もれない
* 地名を潰さない
* 災害レイヤーを邪魔しない
* opacityが強すぎない
* 主要路線が視認できる

期待:

```text
通常路線: 1.5〜2.5px程度
障害路線: 3.5〜5px程度
```

---

## 6. 複数線・側線の抑制確認

ズームインして確認する。

確認地点例:

```text
新宿付近
東京駅付近
品川付近
池袋付近
調布付近
```

期待:

* 駅構内線が大量に出すぎない
* 車庫線・側線・待避線が目立ちすぎない
* 1路線が過剰に何本も並んで見えない
* 副都心やターミナル付近でも破綻しない

完全に1本化できなくてもよいが、ユーザーが混乱するほどの白線密集は解消されていること。

---

## 7. GeoJSONサイズ・パフォーマンス

確認:

```text
/layers/railways/kanto_railways.geojson
```

確認項目:

* HTTP 200
* gzip有効
* 初回fetchのみ
* メモリキャッシュ使用
* pan/zoomで再fetchされない
* 表示範囲フィルタリングが機能する
* 操作が重くならない

期待:

* console errorなし
* request failureなし
* UIフリーズなし

---

## 8. 凡例確認

鉄道レイヤーON時に、凡例が分かりやすいこと。

期待表示:

```text
路線色: 各路線の公式カラー
太線: 遅延
破線: 一部運休
赤ハロー: 運転見合わせ
```

または同等の説明。

---

## 9. ポップアップ確認

路線クリック時に確認。

表示項目:

* 路線名
* 事業者
* 状態
* 説明
* 更新時刻
* 出典

期待:

* undefined/null 表示なし
* 状態表現とポップアップ内容が一致する
* 路線色と状態表現が矛盾しない

---

## 10. モバイル確認

スマホ幅で確認。

期待:

* 横スクロールなし
* レイヤーパネル操作可能
* 凡例が画面を塞ぎすぎない
* 交通カードが崩れない
* 鉄道路線が太すぎない
* 災害警告UIとz-index競合しない

---

## 11. 回帰確認

最低限確認:

* 地震一覧展開
* 地震項目クリックで地図フォーカス
* 津波警報UI
* 雨雲レイヤー
* キキクルレイヤー
* 高潮レイヤー
* 潮位観測点
* 日月カード
* 危険地域ランキング
* 河川情報リンク
* 鉄道カード
* 鉄道レイヤーON/OFF

---

## 12. 判定基準

### PASS

以下をすべて満たす。

* 鉄道路線が路線ごとの色で表示される
* 白一色表示ではない
* 障害状態でも路線色が維持される
* 障害状態が線幅/破線/ハローで判別できる
* 側線・車庫線・駅構内線の過剰表示が抑制されている
* パフォーマンスに問題がない
* モバイルで破綻しない
* 既存 `/live` 機能の回帰がない

### PASS with notes

以下のような軽微な課題が残る場合。

* 一部路線の公式カラー未登録
* ターミナル駅周辺で多少複数線が残る
* 凡例に改善余地あり
* 色味の微調整余地あり

### FAIL

以下のいずれか。

* 全路線が白一色のまま
* 障害状態で路線色が失われる
* 路線が太すぎて地図を潰す
* 側線・車庫線が大量表示される
* `/live` が重くなる
* モバイルで操作不能
* 既存災害レイヤーを壊す

---

## 13. レポート作成

以下に作成する。

```text
tasks/live/live_phase7a3_railway_overlay_visibility_codex_verification.md
```

記載内容:

```text
# Phase 7-A.3 鉄道路線オーバーレイ視認性改善 CODEX検証

## 判定
PASS / PASS with notes / FAIL

## 検証環境
- date
- branch
- commit
- docker compose status

## 実施コマンド
- backend compile
- pytest if any
- Playwright

## 路線カラー確認

## 障害状態表現確認

## 複数線・側線抑制確認

## パフォーマンス確認

## モバイル確認

## 回帰確認

## 発見した問題

## 修正提案

## スクリーンショット

## 最終結論
```
