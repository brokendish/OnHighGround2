# Phase 3-C 観察・調整 実装指示書

## 目的

`/live` の雨雲面スキャン・キキクル危険度集計が、実データ運用時に全国監視として妥当な表示になっているか観察しやすくする。

このフェーズでは新機能追加ではなく、観察・調整・記録性の強化を目的とする。

---

## 対象

- `/live`
- `/api/live/summary`
- 雨雲危険地域ランキング
- キキクル危険地域ランキング
- dangerous_areas 統合表示

---

## 実装方針

### 1. 観察ログの追加

`/api/live/summary` 生成時に、以下を INFO ログで確認できるようにする。

```text
live summary observation:
rain_areas=3
kikikuru_areas=4
dangerous_areas=5
top_area=千葉県付近
top_level=danger
```

雨雲側:

```text
live rain observation:
candidates=3
areas=3
stride=2
max_areas=5
```

キキクル側:

```text
live kikikuru observation:
landslide=2
flood=1
inundation=1
areas=4
```

---

### 2. APIレスポンスの debug/metadata 確認

既存契約を壊さない範囲で、すでに debug / metadata 的な領域がある場合のみ、観察用情報を追加する。

追加候補:

```json
{
  "observation": {
    "rain_area_count": 3,
    "kikikuru_area_count": 4,
    "dangerous_area_count": 5,
    "max_areas": 5
  }
}
```

既存API契約を壊す場合は追加しないこと。

---

### 3. dangerous_areas の重複観察

同一都道府県・同一地域名が複数種別で並んだ場合にログで確認できるようにする。

例:

```text
live duplicate area observation:
label=千葉県付近
types=rain,landslide,flood
```

このフェーズでは統合表示への変更はしない。

---

### 4. false-safe維持

以下を維持すること。

- unknown を danger にしない
- weak / low risk を danger にしない
- threshold未満を dangerous_areas に出さない
- データ取得失敗時に危険断定しない

---

### 5. UI変更は最小限

原則としてUI変更は行わない。

ただし、既存表示が壊れている場合のみ軽微な修正を許可する。

禁止:

- 新カード追加
- 新ランキングUI追加
- 表示件数変更
- スコアリング変更
- 危険度色変更

---

### 6. areas上限維持

以下を維持すること。

```python
MAX_AREAS = 5
```

このフェーズでは上限変更しない。

---

## 禁止事項

- rankingロジックの大幅変更
- score計算変更
- areas上限変更
- キキクル種別の新規追加
- 雨雲スキャン zoom / stride / threshold 変更
- UI全面改修
- `/live` 以外への影響

---

## 完了条件

- `/api/live/summary` が正常に返る
- 雨雲・キキクル・dangerous_areas の件数を観察できる
- 同一地域重複をログで把握できる
- 既存E2Eが成功する
- `/live` 表示が壊れていない
- ナビ本体に影響がない