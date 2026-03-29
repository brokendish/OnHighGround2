# OnHighGround — UI/UX 仕様書

対象ファイル: `frontend/index.html`
作成日: 2026-03-29
目的: 設計書・ユーザ操作マニュアル作成の基礎資料

---

## 1. 画面構成の概要

```
┌──────────────────────────────────────────┐
│  [サイドバー (350px)]  │  [地図エリア]      │
│                        │                   │
│  ├ 現在地設定          │  [左上] ブランド   │
│  ├ ハザードレイヤー    │  [右上] 操作ボタン │
│  ├ 検索条件            │                   │
│  ├ 検索結果            │  （地図本体）      │
│  ├ 目的地設定          │                   │
│  └ ナビゲーション      │  [下部] 操作パネル │
│                        │                   │
└──────────────────────────────────────────┘
```

- サイドバーはトグルボタンで折りたたみ可能
- 地図エリアは残り全幅を占有
- モバイルではサイドバーが上部に変形（高さ制限付き）

---

## 2. レイアウト構造

### 2.1 DOM 構造（主要要素）

```
body
└── .container
    ├── #sidebarWrapper (.sidebar-wrapper)
    │   ├── .sidebar-toggle (#sidebarToggle)
    │   └── .sidebar
    │       ├── .sidebar-header  ← ブランディング
    │       └── [コンテンツ各セクション]
    └── #map
        ├── [Leaflet 地図本体]
        └── #map-ui-overlay
            ├── #map-brand-badge         ← 左上バッジ
            ├── #map-top-right-controls  ← 右上ボタン群
            ├── #shelter-map-card        ← 避難所選択カード
            ├── #map-bottom-controls     ← 下部操作パネル
            ├── #navBanner               ← ナビ警告バナー
            └── #navReroutePanel         ← オフルートパネル
```

### 2.2 レスポンシブ対応

| 幅 | レイアウト変化 |
|----|-------------|
| PC (769px〜) | サイドバー左固定 350px、地図右側フレックス |
| タブレット (768px) | サイドバー上部配置に変形、最大高さ制限あり |
| スマートフォン (〜480px) | 下部パネルの幅・余白を縮小 |

---

## 3. サイドバー仕様

### 3.1 セクション構成

```
[ヘッダー]
  アイコン + "OnHighGround"
  "津波・高潮・洪水から身を守る避難経路案内"

[📍 現在地設定]
  ・現在地を取得ボタン (#getCurrentLocation)
  ・手動指定モード切替 (#manualLocationMode)
    └ ON時: ヒントテキスト表示
  ・手動更新時に自動再検索 (#autoRefreshOnManualUpdate)
  ・指定緊急避難場所の表示切替 (#showEmergencyShelters)
  ・避難所ステータス表示 (#shelterStatus)

[ハザードレイヤー] ← <details> 折りたたみ
  ・津波 (東京・神奈川・千葉)
  ・洪水 (東京)
  ・高潮 (東京)
  ・内水氾濫 (東京)
  ・土砂災害 (東京)
  ※ 各レイヤーにチェックボックスと凡例

[現在地情報] (#currentLocationInfo) ← 現在地取得後に表示
  ・緯度・経度・標高・精度

[危険度情報] (#dangerStatusPanel) ← 検索後に表示

[選択避難所情報] (#selectedShelterInfo) ← 避難所選択後に表示
  ・名称・種別・住所・距離・所要時間
  ・ナビ開始/停止/再ルートボタン
  ・経路案内 (ターンバイターン)

[⚙️ 検索条件]
  ・移動手段 (徒歩/自動車)
  ・最大距離スライダー (100〜10,000m)
  ・最低高低差スライダー (1〜100m)
  ・検索/クリアボタン

[検索結果] ← 検索後に表示
  ・おすすめ候補 (#recommendedPanel)
  ・救出安全エリア (#rsaPanel)
  ・候補一覧 (#destinationsPanel)

[🗺 目的地設定] (#destinationPanel) ← 常時表示
  ・確定目的地表示 (#destConfirmedInfo)
  ・目的地フリーワード検索
  ・検索結果リスト (#destinationSearchResults)
  ・経路案内 (#userDestRouteGuidance)

[🧭 ナビゲーション] (#navPanel) ← ナビ開始後に表示
  ・ナビステータス (#navStatus)
  ・自動再ルートトグル (#navFollowBtn)
```

---

## 4. 地図オーバーレイUI 仕様

### 4.1 左上: ブランドバッジ (#map-brand-badge)

- アプリアイコン + "OnHighGround" + サブテキスト
- `pointer-events: none`（タッチ透過）
- 常時表示

### 4.2 右上: 操作ボタン群 (#map-top-right-controls)

| ボタンID | 機能 | 初期状態 |
|---------|------|---------|
| `#layer-toggle-btn` | ハザードレイヤー選択パネルの開閉 | 閉 |
| `#shelter-toggle-btn` | 指定緊急避難場所の表示/非表示 | 表示中 (active) |
| `#map-clear-overlay-btn` | 地図上の全マーカー・経路をクリア | 有効 (danger) |
| `#legend-toggle-btn` | 凡例パネルの開閉 | 閉 |

**関連パネル:**
- `#layer-panel` — ハザードレイヤー選択 (JS: `buildLayerPanel()` で生成)
- `#legend-panel` — 凡例表示 (JS: `buildLegendPanel()` で生成)

### 4.3 下部: 操作パネル (#map-bottom-controls)

折りたたみハンドル付きのフローティングパネル。

```
┌──────────────────────────────┐
│  ─── ∧  (ハンドル)           │
│                              │
│  [現在地]  [避難先検索]       │  ← #mbc-row-normal (通常時)
│                              │
│  [ナビ開始]  [ナビ停止]       │  ← #mbc-row-nav (目的地設定後)
│                              │
│  目的地まで ● km ▲ステータス  │  ← #mbc-row-dist (ナビ中)
│  現在地ハザード: ●  標高: ●m  │  ← #mbc-row-hazard (ナビ中)
│                              │
│  最大距離 ────●──── 2000m    │
│  高低差   ────●──── 10m      │  ← #mbc-row-sliders (常時)
└──────────────────────────────┘
```

| 行ID | 表示条件 | 内容 |
|------|---------|------|
| `#mbc-row-normal` | 通常時（常時） | 現在地取得・避難先検索 |
| `#mbc-row-nav` | 目的地設定後 | ナビ開始・ナビ停止 |
| `#mbc-row-dist` | ナビ中 | 残距離・オフセット状態 |
| `#mbc-row-hazard` | ナビ中 | 現在地のハザード情報・標高 |
| `#mbc-row-sliders` | 常時 | 検索条件スライダー |

### 4.4 避難所選択カード (#shelter-map-card)

避難所マーカーをタップ時に表示されるフローティングカード。

```
┌─────────────────────┬──┐
│ [避難所名]           │ × │
│ [種別]               │   │
├─────────────────────┘   │
│ 🚶 徒歩  📏 ●km  ⏱ ●分  │
│                          │
│ [ハザード情報]  ← 候補のみ │
│ [標高・スコア]  ← 候補のみ │
│ [コメント]     ← 候補のみ │
│                          │
│ [経路案内テキスト]        │
│ ─── (リサイズハンドル) ─── │
└──────────────────────────┘
```

- 上部ヘッダーをドラッグして移動可能
- 下端のリサイズハンドルで高さ変更可能
- ×ボタンで閉じる

### 4.5 ナビ警告バナー (#navBanner)

- ナビ中に警告状態になると表示
- テキストは JS により動的に設定

### 4.6 オフルートパネル (#navReroutePanel)

```
ルートから外れた可能性があります
[目的地名]
[自動再ルート中...]  ← 自動再ルートON時のみ

[🔄 同じ避難先へ再ルート]
[🔍 新しい避難先を検索]
```

---

## 5. UI モード遷移

```
[起動]
    ↓
[通常モード]
  ・下部: 現在地 / 避難先検索 / スライダー
  ・右上: レイヤー切替 / 避難所表示 / クリア / 凡例
    ↓ 現在地取得
[現在地取得済み]
  ・サイドバーに現在地情報表示
    ↓ 避難先検索 または 目的地設定
[目的地設定済み]
  ・下部: ナビ開始/停止ボタン表示
  ・サイドバー: 選択避難所情報表示
  ・地図: 選択カード表示
    ↓ ナビ開始
[ナビ中]
  ・下部: 残距離・ハザード情報を表示
  ・下部: 通常ボタンを非表示
    ↓ ルート逸脱
[オフルート警告]
  ・オフルートパネル表示
  ・「同じ避難先へ再ルート」or「新しい避難先を検索」
    ↓ ナビ停止 or クリア
[通常モードへ戻る]
```

---

## 6. 主要操作とトリガー

| ユーザ操作 | UI要素 | 呼び出す関数 |
|-----------|--------|------------|
| 現在地取得 | `#getCurrentLocation` / `#locate-overlay-btn` | (GPS取得処理) |
| 避難先検索 | `#search-overlay-btn` | (検索処理) |
| 目的地テキスト検索 | `#destinationSearchInput` + Enter / ボタン | `searchUserDestination()` |
| 目的地クリア | `#map-clear-overlay-btn` | `clearUserDestination()` |
| ナビ開始 | `#nav-start-overlay-btn` / `#shelterNavStartBtn` | `startNavigation()` |
| ナビ停止 | `#nav-stop-overlay-btn` / `#shelterNavStopBtn` | `stopNavigation()` |
| 同一目的地へ再ルート | `#navRerouteSameBtn` / `#shelterRerouteSameBtn` | `rerouteToSameDestination()` |
| 新目的地で再ルート | `#navRerouteNewBtn` / `#shelterRerouteNewBtn` | `rerouteWithNewSearch()` |
| 自動再ルートON/OFF | `#navFollowBtn` | `toggleNavAutoReroute()` |
| 下部パネル折りたたみ | `#map-bottom-handle` | (クラス切替) |

---

## 7. 検索パラメータ

| パラメータ | UI要素 | 範囲 | デフォルト |
|-----------|--------|------|-----------|
| 移動手段 | 移動手段ドロップダウン | 徒歩 / 自動車 | 徒歩 |
| 最大移動距離 | `#distance-slider-overlay` | 100〜10,000m | 2,000m |
| 最低高低差 | `#elevation-slider-overlay` | 1〜100m | 10m |

---

## 8. ハザードレイヤー

| レイヤー名 | 対象地域 | チェックボックスID |
|-----------|---------|-----------------|
| 津波 | 東京・神奈川・千葉 | (各prefecture) |
| 洪水 | 東京 | — |
| 高潮 | 東京 | — |
| 内水氾濫 | 東京 | — |
| 土砂災害 | 東京 | — |

---

## 9. アクセシビリティ

| 要素 | 対応内容 |
|------|---------|
| `#searchMessage` | `role="status"` `aria-live="polite"` で検索状態をスクリーンリーダーに通知 |
| スライダー | `aria-label="最大移動距離"` / `aria-label="必要高低差"` |

---

## 10. CSS 変数設計

詳細は [ui_variables.md](ui_variables.md) を参照。

```css
:root {
    --ui-safe-top:    max(20px, calc(env(safe-area-inset-top)    + 8px));
    --ui-safe-bottom: max(16px, calc(env(safe-area-inset-bottom) + 8px));
}
/* iPad補正 */
@media (min-width: 768px) and (max-width: 1366px) {
    :root {
        --ui-safe-top:    max(28px, calc(env(safe-area-inset-top)    + 12px));
        --ui-safe-bottom: max(24px, calc(env(safe-area-inset-bottom) + 12px));
    }
}
```

---

## 11. 今後の拡張検討

### 11.1 音声ナビゲーション（検討中）

**背景:** フィールドテストで「画面を見ながら歩くのがきつい・危ない」と確認。
実際の避難時は画面確認の余裕がないため、音声ガイダンスの必要性が高い。

**検討ポイント:**
- 曲がり角での音声案内（「100m先を右折」）
- 危険エリア接近時の警告音声
- ナビ開始・停止・再ルートの音声フィードバック
- Web Speech API (`SpeechSynthesis`) での実装可否
- オフライン時の動作（音声合成はブラウザ内蔵のため基本的にオフライン可）

**実装候補 API:**
```javascript
// Web Speech API (SpeechSynthesis)
const utterance = new SpeechSynthesisUtterance('100メートル先を右折してください');
utterance.lang = 'ja-JP';
window.speechSynthesis.speak(utterance);
```

---

*このドキュメントは設計書・ユーザ操作マニュアル作成の基礎資料として維持する。*
*UI変更時は併せて更新すること。*
