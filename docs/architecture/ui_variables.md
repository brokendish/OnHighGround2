# UI 変数設計メモ

`frontend/index.html` の `<style>` 先頭で定義している CSS カスタムプロパティの設計方針。

---

## 現在定義されている変数

```css
:root {
    --ui-safe-top:    max(20px, calc(env(safe-area-inset-top)    + 8px));
    --ui-safe-bottom: max(16px, calc(env(safe-area-inset-bottom) + 8px));
}

/* iPad 補正 (768px〜1366px) */
@media (min-width: 768px) and (max-width: 1366px) {
    :root {
        --ui-safe-top:    max(28px, calc(env(safe-area-inset-top)    + 12px));
        --ui-safe-bottom: max(24px, calc(env(safe-area-inset-bottom) + 12px));
    }
}
```

---

## 変数の意図

### `--ui-safe-top`

地図オーバーレイ UI の**上端基準**。

| 端末 | env() 値の目安 | 変数の解決値 |
|------|--------------|------------|
| PC / Android | 0px | 20px (floor) |
| iPhone (ノッチあり) | ~44px | 52px |
| iPad (ステータスバーのみ) | ~20px | 28px |

- `env(safe-area-inset-top)` でノッチ・ステータスバーを回避
- `+ 8px` で視覚的な余白を確保
- `max(20px, …)` で safe-area が 0 の端末でも最低余白を保証

### `--ui-safe-bottom`

地図オーバーレイ UI の**下端基準**。

| 端末 | env() 値の目安 | 変数の解決値 |
|------|--------------|------------|
| PC / Android | 0px | 16px (floor) |
| iPhone (ホームインジケータあり) | ~34px | 42px |
| iPad (ホームインジケータあり) | ~20px | 24px |

- `env(safe-area-inset-bottom)` でホームインジケータ・ブラウザ下部バーを回避
- `+ 8px` で余白を確保
- `max(16px, …)` で最低余白を保証

---

## 使い方のルール

### 基本: 変数をそのまま使う

```css
.some-bottom-ui {
    bottom: var(--ui-safe-bottom);
}

.some-top-ui {
    top: var(--ui-safe-top);
}
```

### 相対オフセットが必要な場合: `calc()` で乗せる

```css
/* 下部コントロールの上に重なるパネル */
.panel-above-bottom {
    bottom: calc(var(--ui-safe-bottom) + 64px);
}

/* 上部バッジの下に続くコントロール群 */
.controls-below-top {
    top: calc(var(--ui-safe-top) + 32px);
}
```

### やってはいけないこと

```css
/* ❌ env() を個別に足す → 端末差がそのまま UI 差になる */
.bad {
    bottom: calc(12px + env(safe-area-inset-bottom));
}

/* ❌ 変数を使わず固定値 → iPad/iPhone で見切れる可能性 */
.also-bad {
    bottom: 8px;
}
```

---

## 現在の適用箇所

| 要素 | プロパティ | 値 | PC解決値 |
|------|-----------|-----|---------|
| `#map-brand-badge` | `top` | `var(--ui-safe-top)` | 20px |
| `#map-top-right-controls` | `top` | `calc(var(--ui-safe-top) + 32px)` | 52px |
| `#map .leaflet-top.leaflet-left` | `top` | `calc(var(--ui-safe-top) + 80px)` | 100px |
| `#map-bottom-controls` | `bottom` | `calc(var(--ui-safe-bottom) + 24px)` | 40px |
| `.nav-reroute-panel` | `bottom` | `calc(var(--ui-safe-bottom) + 64px)` | 80px |

---

## 前提条件

以下の meta viewport 指定が必須。これがないと `env(safe-area-inset-*)` が 0 になる。

```html
<meta name="viewport" content="width=device-width, initial-scale=1.0,
    maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
```

---

## body の高さ指定

```css
body {
    height: 100dvh;  /* Safari の動的ビューポート対応。100vh は iPad Safari でズレる */
}
```

`100vh` は iPad Safari でアドレスバー等を含んだ高さになる場合があり、実表示領域とズレる。
`100dvh` (dynamic viewport height) はツールバーの表示状態に追従する。Safari 15.4+ で対応。

---

## 新しい UI 要素を追加するとき

1. **上端に固定するなら** → `top: var(--ui-safe-top)` または `calc(var(--ui-safe-top) + Xpx)`
2. **下端に固定するなら** → `bottom: var(--ui-safe-bottom)` または `calc(var(--ui-safe-bottom) + Xpx)`
3. `env(safe-area-inset-*)` を直接書かない
4. 固定 px だけで配置しない
