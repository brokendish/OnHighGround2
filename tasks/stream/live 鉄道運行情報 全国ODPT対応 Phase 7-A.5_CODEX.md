# CODEX用検証指示書

## /live 鉄道運行情報 全国ODPT対応 Phase 7-A.5 検証

### 目的

Claude実装後、`/live` および `/live/stream` の鉄道運行情報が、ODPT通常公開範囲の全国対応として正しく動作しているか検証する。

特に、以下を重点確認する。

```text
- チャレンジ2026限定データを対象にしていないこと
- 全国ODPT通常公開データを扱えること
- GeoJSON bounds / fallback が正しく動くこと
- 東京西側固定ズームへ戻っていないこと
- /live と /live/stream が破綻していないこと
```

---

## 検証観点

### 1. ODPT取得対象

確認すること。

* 首都圏固定・関東固定になっていない
* ODPT通常公開APIの全国対象を扱える
* チャレンジ2026限定、期間限定、実験的データを取得対象にしていない
* 除外条件がコードまたは設定で明示されている

NG例:

```text
challenge2026
contest
limited
temporary
experimental
```

相当のデータを通常LIVEに混ぜている。

---

### 2. 正規化結果

backend APIまたは生成JSONを確認する。

期待:

```text
operator
railway
status
description
updated_at
source
lat/lng または fallback情報
matched_geojson 相当の診断情報
```

確認ポイント:

* 路線名が空にならない
* 事業者名が空にならない
* status分類が破綻しない
* ODPT本文がUIに表示可能な形で残る
* 平常運行が大量カード表示されない

---

### 3. GeoJSON一致路線

GeoJSONに存在する路線を障害状態にして検証する。

期待:

* 実路線ジオメトリからbounds取得
* 地図上で路線が強調される
* `/live/stream` 小地図で路線全体が収まる
* 代表点だけに寄らない

確認例:

```text
京王線
東武東上線
有楽町線
副都心線
```

既存テスト資産があれば流用する。

---

### 4. GeoJSON未一致路線

GeoJSONに存在しない検証用路線を混ぜる。

期待:

* 未一致路線のみ代表点fallback
* GeoJSON一致路線は実boundsのまま
* 未一致路線がbounds計算から完全に無視されない
* fallbackが東京駅固定にならない

---

### 5. 混在ケース

以下のケースを必ず確認する。

```text
GeoJSON一致路線 + GeoJSON未一致路線
```

期待:

```text
一致路線: 実路線bounds
未一致路線: 代表点
両方: 統合boundsに含まれる
```

このケースは過去に弱かったため、E2Eで直接確認すること。

---

### 6. 複数障害路線の統合bounds

東西・南北に離れた複数路線を同時障害にする。

期待:

* 全障害路線が画面内に収まる
* 1路線だけにズームしない
* 8秒巡回で地図中心が変わらない
* `setView([lat,lng], 12)` 方式に戻っていない

確認する値:

```text
fittedLineIds
bounds
center
zoom
matchedNames
fallbackNames
```

診断情報がある場合は活用する。

---

### 7. 路線名マッチング

以下のような名称差を検証する。

```text
有楽町線 → 東京メトロ有楽町線
副都心線 → 東京メトロ副都心線
東上線 → 東武東上線
```

期待:

* 完全一致だけに依存していない
* 接頭辞付き名称でもGeoJSON一致できる
* 短すぎる名称による誤一致がない

---

### 8. `/live` 回帰

確認:

```bash
curl -I http://127.0.0.1:8080/live
```

期待:

```text
200 OK
console errorなし
鉄道レイヤーON/OFF可能
既存の地震・雨雲・キキクル等に影響なし
```

---

### 9. `/live/stream` 回帰

確認:

```bash
curl -I "http://127.0.0.1:8080/live/stream?chrome=off"
```

期待:

```text
200 OK
console errorなし
鉄道小地図表示が破綻しない
障害路線boundsが正しく反映される
詳細カード巡回は許容
小地図ズーム巡回はNG
```

---

## 推奨コマンド

実際のファイル名に合わせて調整すること。

```bash
node --check frontend/js/live-stream/live-stream-railway-layer.js
node --check frontend/js/live-stream/live-stream-panels.js
```

```bash
npx playwright test e2e/live-stream-railway-bounds-verification.spec.js
```

```bash
npx playwright test \
  e2e/live-stream-railway-bounds-verification.spec.js \
  e2e/live-stream-railway-phase5b.spec.js \
  e2e/live-stream-railway-calm-map.spec.js \
  e2e/live-stream-railway-color-layer.spec.js \
  e2e/live-stream-railway-detail.spec.js \
  e2e/rail-mock-verify.spec.js
```

追加実装がある場合は、全国ODPT対応専用E2Eを追加すること。

推奨名:

```text
e2e/live-railway-odpt-national.spec.js
e2e/live-stream-railway-odpt-national.spec.js
```

---

## 追加すべきE2E

最低限、以下を追加する。

### Case 1: チャレンジ2026限定除外

```text
ODPT catalog/mock に challenge2026 相当を含める
通常公開データのみ採用されること
challenge2026 は railway list に出ないこと
```

### Case 2: 関東外ODPT路線

```text
関東外の通常ODPT路線mockを投入
/live の鉄道情報に表示されること
/live/stream でも破綻しないこと
```

### Case 3: GeoJSON一致 + 未一致混在

```text
一致路線は実bounds
未一致路線は代表点fallback
統合boundsに両方含まれること
```

### Case 4: 東京西側固定回帰防止

```text
東側・西側の障害路線を同時投入
center が常に 35.69,139.692 付近へ固定されないこと
```

---

## PASS条件

以下をすべて満たすこと。

* ODPT通常公開範囲の全国対応になっている
* チャレンジ2026限定データを対象外にしている
* `/live` が200 OK
* `/live/stream?chrome=off` が200 OK
* 鉄道関連E2EがPASS
* 全国ODPT対応専用E2EがPASS
* GeoJSON一致・未一致混在ケースがPASS
* 東京西側固定ズームの旧挙動が再発していない
* 既存ナビ本体に不要な変更がない

---

## FAIL条件

以下が1つでもあればFAIL。

* チャレンジ2026限定データを通常LIVEに混ぜている
* `setView([代表点], 12)` 巡回ズームに戻っている
* 複数障害路線のうち1路線しか表示boundsに入らない
* GeoJSON未一致路線が完全に無視される
* 東京西側または東京駅固定fallbackが復活している
* `/live` または `/live/stream` がHTTP 200でない
* 鉄道以外の既存LIVE機能に明確な回帰がある

---

## レポート作成先

```text
tasks/live/live_railway_odpt_national_codex_verification.md
```

判定は以下のいずれかで記載する。

```text
PASS
PASS with notes
FAIL
```
