# 避難場所広域ブラウズレイヤー

`frontend/js/shelter-browse-layer.js` で実装する業務表示レイヤーの設計ドキュメント。

---

## 目的と位置付け

OnHighGround2 の避難場所表示には **2 つの独立したレイヤー** がある。

| レイヤー | ファイル | 目的 | 表示方式 |
|---|---|---|---|
| **避難候補レイヤー** | `shelters.js` | 現在地周辺の避難場所を表示し、ルーティング候補として選択する | 個別 circleMarker (bbox 内のみ取得) |
| **広域ブラウズレイヤー** | `shelter-browse-layer.js` | 避難場所の分布を広域で確認する業務表示 | zoom 連動クラスタリング (全件一括取得) |

これらは **独立したレイヤー** であり、互いのロジックを変更しない。

---

## ズームモード設計

```
zoom ≤ 10   : 非表示（広域すぎて情報として意味をなさない）
zoom 11–13  : MarkerClusterGroup によるクラスター表示
zoom ≥ 14   : MarkerCluster が個別マーカーを自動展開（disableClusteringAtZoom）
```

閾値は `SHELTER_BROWSE_CONFIG` オブジェクトに集約されており、ロジックに散在しない。

```javascript
// shelter-browse-layer.js
const SHELTER_BROWSE_CONFIG = {
    ZOOM_SHOW_MIN:            11,   // これ未満は非表示
    DISABLE_CLUSTERING_ZOOM:  14,   // このズーム以上で個別マーカーに展開
    MAX_CLUSTER_RADIUS:       55,   // クラスタリング半径 (px)
    FETCH_LIMIT:           15000,   // 全件取得上限
    ...
};
```

---

## データ取得戦略

- **全件一括フェッチ（bbox なし）** を起動時に 1 回だけ実行し、結果をキャッシュする。
- パン・ズームのたびに再フェッチしない（避難候補レイヤーと異なる点）。
- 都道府県フィルター変更時はキャッシュデータを再描画するだけでフェッチしない。
- フェッチ上限: `FETCH_LIMIT = 15000`（バックエンド最大 20,000）。

```
初回ロード → /api/emergency-shelters?limit=15000
            → 全データをキャッシュ
            → shelterRegionVisible でフィルタリング
            → MarkerClusterGroup に一括追加
```

---

## アーキテクチャ

```
shelter-browse-layer.js
├── SHELTER_BROWSE_CONFIG      設定定数（閾値・色・パラメーター）
├── _initBrowseClusterGroup()  MarkerClusterGroup の初期化
├── _populateBrowseCluster()   キャッシュデータをフィルタ→マーカー一括追加
├── _applyBrowseMapVisibility() zoom に応じてレイヤーを地図に追加/削除
├── _fetchAllBrowseShelters()  API 一括フェッチ（初回のみ）
│
├── refreshShelterBrowseLayer()     公開: フェッチ+描画
├── setShelterBrowseLayerVisible()  公開: ON/OFF
└── onBrowseRegionFilterChanged()   公開: 都道府県フィルター変更時に呼ばれる
```

`map-overlay-ui.js` の region toggle バインドが `onBrowseRegionFilterChanged()` を呼び出すことで、
都道府県チェックボックスの変更が両レイヤーに反映される。

---

## UI 構成

### 右上パネル（避難場所ボタン）

```
避難場所の表示
  ── 避難候補（近傍ルーティング）──
  [✓] 🟢 指定避難所
  [✓] 🔴 指定緊急避難場所
  ────
  ── 都道府県 ──
  [✓] 東京都
  [✓] 神奈川県
  ────
  ── 広域ブラウズ（zoom≥11）──
  [✓] 全地域を一覧表示
  [ステータス]
```

### サイドバー

```
🟢 指定避難所を地図に表示する
🔴 指定緊急避難場所を地図に表示する
── 表示する都道府県 ──
東京都 / 神奈川県
── 広域ブラウズ（zoom≥11）──
🔵 全地域を一覧表示する
[ステータス]
```

---

## 将来のリージョン追加

新しい都道府県（例: 千葉・埼玉）を追加する手順：

1. `data_runtime/backend/shelters/` に `{region}_shelter.geojson` を配備する
2. `frontend/js/config.js` の `SHELTER_REGION_CONFIGS` に 1 エントリ追加する
3. 可能ならバックエンドの shelter API が `region` フィールドを返すようにする
4. **`state.js` / `index.html` / `map-overlay-ui.js` / `shelter-browse-layer.js` の追加編集は不要**

---

## 既知の制限

| 制限 | 内容 |
|---|---|
| zoom ≥ 14 での重複表示 | 広域ブラウズと避難候補の両レイヤーが同時に表示されるが、視覚スタイルが異なる（ブラウズ: 小・低 opacity / 候補: 大・高 opacity） |
| クラスター境界アーティファクト | ズームレベル変更直後に一瞬クラスターが崩れる場合がある（MarkerCluster のアニメーションによる仕様） |
| 全件フェッチの初回遅延 | 15,000 件フェッチのため初回表示までやや時間がかかる可能性がある（2 回目以降はキャッシュで即時） |
| フェッチ失敗時の再試行 | 自動再試行はしないが、ステータスの「再試行」リンクまたは OFF→ON トグルで再試行できる |

---

## トラブルシューティング

| 症状 | 確認事項 |
|---|---|
| クラスターが表示されない | ブラウザコンソールで `[shelter-browse]` ログを確認。MarkerCluster が読み込まれているか確認 |
| zoom 11 以上でも非表示 | `isShelterBrowseLayerVisible` が false になっていないか確認。チェックボックスの状態を確認 |
| クラスターアイコンのスタイルが崩れる | `index.html` の `.shelter-cluster` CSS クラスが存在するか確認 |
| ステータスが「取得失敗」 | バックエンド疎通を確認し、ステータスの「再試行」リンクまたは OFF→ON トグルで再試行 |
