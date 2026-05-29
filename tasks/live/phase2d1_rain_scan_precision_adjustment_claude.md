# Phase 2-D.1 雨雲面スキャン精度調整

## 目的

Phase 2-D 雨雲面スキャン方式において、千葉県（木更津・市原・茂原周辺）の強雨域が危険地域ランキングへ出現しない問題を改善する。

調査結果では ranking 処理ではなく candidate area 生成前に脱落していることが確認されている。

現行設定:

- zoom=6
- PIXEL_STRIDE=4
- STRONG_PIXEL_THRESHOLD=3

対象タイル:

- z6 (56,25)

調査ログ:

- stride1 → strong=15 severe=20
- stride2 → strong=3 severe=6
- stride4 → strong=0 severe=2

現行の stride4 により candidate area が生成されていない。

---

## 実装内容

### 1. PIXEL_STRIDE変更

変更前

```python
PIXEL_STRIDE = 4
```

変更後

```python
PIXEL_STRIDE = 2
```

---

### 2. threshold維持

以下は変更しないこと。

```python
STRONG_PIXEL_THRESHOLD = 3
```

理由:

false-safe契約を維持するため。

---

### 3. zoom維持

以下は変更しないこと。

```python
SCAN_ZOOM = 6
```

理由:

全国監視での処理負荷増加を避けるため。

---

### 4. area位置算出変更

現状:

candidate area の座標が tile center を使用している。

問題:

同一タイル内で強雨域が端に存在すると、
実際の位置と大きく異なる場所名が表示される可能性がある。

---

変更後:

strong/severe 判定されたピクセル群の重心を算出する。

例:

```python
centroid_x = average(pixel_x)
centroid_y = average(pixel_y)
```

重心を緯度経度へ変換し、

```python
area.lat
area.lng
```

へ使用すること。

---

### 5. prefecture判定変更

現状:

tile center座標で都道府県判定している場合は修正すること。

変更後:

重心座標から都道府県判定すること。

```python
prefecture = lookup_prefecture(
    centroid_lat,
    centroid_lng
)
```

---

### 6. areas上限維持

変更しないこと。

```python
MAX_AREAS = 5
```

---

### 7. false-safe契約維持

以下を維持すること。

- unknown を danger にしない
- weak を danger にしない
- strong/severe を優先
- threshold未満は出力しない

---

## ログ追加

デバッグ容易化のため以下を追加。

candidate生成時:

```text
rain_scan candidate:
tile=(56,25)
strong=3
severe=6
centroid=(35.xxxx,139.xxxx)
prefecture=千葉県
```

ランキング採用時:

```text
rain_scan area:
name=千葉県付近
risk=danger
score=xx
```

---

## 禁止事項

- zoom変更禁止
- threshold変更禁止
- rankingロジック変更禁止
- areas上限変更禁止
- 危険度スコア算出変更禁止

---

## 完了条件

以下を満たすこと。

- 千葉県強雨域が candidate として生成される
- 危険地域ランキングへ表示される
- 沖縄検出が維持される
- 既存API契約を変更しない
- Docker起動成功
- lint/テスト成功